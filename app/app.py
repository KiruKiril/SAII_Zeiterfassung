"""Zeiterfassung - minimaler, gehaerteter Stempel-Service.

Aktionen: EIN -> PAUSE -> ZURUECK -> AUS
Persistenz: append-only JSONL unter DATA_DIR (default /data), PVC-gemountet.
"""
import fcntl
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from functools import wraps

from flask import (Flask, abort, redirect, render_template_string, request,
                   session, url_for)

DATA_DIR = os.environ.get("DATA_DIR", "/data")
DATA_FILE = os.path.join(DATA_DIR, "times.jsonl")

ACTIONS = ("EIN", "PAUSE", "ZURUECK", "AUS")
# Zustandsautomat: welcher Status erlaubt welche Aktion, und wohin fuehrt sie.
TRANSITIONS = {
    "AUS": {"EIN": "EIN"},
    "EIN": {"PAUSE": "PAUSE", "AUS": "AUS"},
    "PAUSE": {"ZURUECK": "EIN", "AUS": "AUS"},
}
LABELS = {"EIN": "Einstempeln", "PAUSE": "Pause", "ZURUECK": "Zurueck",
          "AUS": "Ausstempeln"}
STATUS_TEXT = {"AUS": "ausgestempelt", "EIN": "arbeitet", "PAUSE": "in Pause"}

USER_RE = re.compile(r"^[a-z0-9_.-]{2,32}$")
NOTE_MAX = 200

app = Flask(__name__)


# --------------------------------------------------------------------------
# Konfiguration / Secrets - kommen ausschliesslich aus der Umgebung.
# --------------------------------------------------------------------------
def _load_secret_key():
    key = os.environ.get("SECRET_KEY", "")
    if key:
        return key
    if os.environ.get("ZE_ENV") == "prod":
        raise RuntimeError("SECRET_KEY ist in prod zwingend erforderlich")
    # Nur fuer lokale Entwicklung: ephemer, invalidiert Sessions bei Neustart.
    return secrets.token_hex(32)


def _parse_users(raw):
    """ZE_USERS = 'name:pbkdf2_sha256$iter$salt$hash:rolle,...'"""
    users = {}
    for entry in filter(None, (e.strip() for e in raw.split(","))):
        parts = entry.split(":")
        if len(parts) != 3:
            continue
        name, digest, role = parts
        if USER_RE.match(name) and role in ("user", "admin"):
            users[name] = {"digest": digest, "role": role}
    return users


app.secret_key = _load_secret_key()
USERS = _parse_users(os.environ.get("ZE_USERS", ""))
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=os.environ.get("ZE_ENV") == "prod",
    MAX_CONTENT_LENGTH=16 * 1024,
)


def verify_password(digest, password):
    """Konstantzeit-Pruefung gegen pbkdf2_sha256$iterations$salt$hash."""
    try:
        algo, iterations, salt, expected = digest.split("$")
        if algo != "pbkdf2_sha256":
            return False
        calc = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt), int(iterations)
        ).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(calc, expected)


# --------------------------------------------------------------------------
# Persistenz - append-only, mit Lock und fsync, damit ein Pod-Kill nichts frisst.
# --------------------------------------------------------------------------
def append_entry(entry):
    os.makedirs(DATA_DIR, exist_ok=True)
    line = json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n"
    with open(DATA_FILE, "a", encoding="utf-8") as fh:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
        finally:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def read_raw():
    """Alle Zeilen des Logs in Schreibreihenfolge - inklusive Korrekturen."""
    if not os.path.exists(DATA_FILE):
        return []
    out = []
    with open(DATA_FILE, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue  # beschaedigte Zeile ueberspringen, nie crashen
    return out


def _legacy_id(rec):
    """Eintraege aus der Zeit vor den IDs bekommen eine stabile Ersatz-ID."""
    return "L" + hashlib.sha256(
        f"{rec.get('ts')}|{rec.get('user')}".encode()).hexdigest()[:11]


def effective_entries():
    """Das Log ist append-only: Korrekturen ueberschreiben nichts, sondern
    werden beim Lesen auf den Originaleintrag angewendet. So bleibt
    nachvollziehbar, wer wann was geaendert hat."""
    base, order = {}, []
    for rec in read_raw():
        kind = rec.get("type", "stamp")
        if kind == "stamp":
            rid = rec.get("id") or _legacy_id(rec)
            base[rid] = dict(rec, id=rid)
            order.append(rid)
        elif kind in ("correction", "delete"):
            target = base.get(rec.get("target"))
            if target is None:
                continue
            if kind == "delete":
                target["deleted"] = True
            else:
                for field in ("action", "note", "ts"):
                    if field in rec:
                        target[field] = rec[field]
            target["edited_by"] = rec.get("by")
            target["edited_at"] = rec.get("at")
    live = [base[i] for i in order if not base[i].get("deleted")]
    live.sort(key=lambda r: r.get("ts", ""), reverse=True)
    return live


def read_entries(user=None, limit=None):
    out = [r for r in effective_entries() if user is None or r.get("user") == user]
    return out[:limit] if limit else out


def find_entry(entry_id):
    for rec in effective_entries():
        if rec["id"] == entry_id:
            return rec
    return None


def clean_note(raw):
    note = (raw or "").strip()[:NOTE_MAX]
    return "".join(ch for ch in note if ch.isprintable())


FILTER_KEYS = ("von", "bis", "user", "action", "q")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def current_filters(source):
    """Liest nur bekannte Filterfelder - nichts aus der URL landet ungeprueft
    in einer Weiterleitung."""
    out = {}
    for key in FILTER_KEYS:
        val = (source.get(key) or "").strip()[:64]
        if not val:
            continue
        if key in ("von", "bis") and not DATE_RE.match(val):
            continue
        if key == "action" and val not in ACTIONS:
            continue
        out[key] = val
    return out


def apply_filters(entries, f):
    von, bis = f.get("von"), f.get("bis")
    user, action = f.get("user"), f.get("action")
    needle = (f.get("q") or "").lower()
    out = []
    for e in entries:
        day = (e.get("ts") or "")[:10]
        if von and day < von:
            continue
        if bis and day > bis:
            continue
        if user and e.get("user") != user:
            continue
        if action and e.get("action") != action:
            continue
        if needle and needle not in (e.get("note") or "").lower():
            continue
        out.append(e)
    return out


def known_users(entries):
    return sorted(set(USERS) | {e.get("user") for e in entries if e.get("user")})


def parse_form_ts(raw):
    """datetime-local liefert 'YYYY-MM-DDTHH:MM'. Gibt None bei Unsinn."""
    try:
        return datetime.fromisoformat((raw or "").strip()).replace(
            tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def current_status(user):
    for rec in read_entries(user):
        action = rec.get("action")
        if action == "EIN":
            return "EIN"
        if action == "PAUSE":
            return "PAUSE"
        if action == "ZURUECK":
            return "EIN"
        if action == "AUS":
            return "AUS"
    return "AUS"


def worked_seconds_today(user):
    """Summiert EIN/ZURUECK -> PAUSE/AUS Intervalle des laufenden Tages."""
    today = datetime.now(timezone.utc).date()
    entries = list(reversed(read_entries(user)))  # chronologisch
    total, start = 0.0, None
    for rec in entries:
        try:
            ts = datetime.fromisoformat(rec["ts"])
        except (KeyError, ValueError):
            continue
        if ts.date() != today:
            continue
        action = rec.get("action")
        if action in ("EIN", "ZURUECK"):
            start = ts
        elif action in ("PAUSE", "AUS") and start is not None:
            total += (ts - start).total_seconds()
            start = None
    if start is not None:
        total += (datetime.now(timezone.utc) - start).total_seconds()
    return int(total)


# --------------------------------------------------------------------------
# Auth, CSRF, Login-Bremse
# --------------------------------------------------------------------------
_login_attempts = {}


def rate_limited(ip):
    now = time.time()
    hits = [t for t in _login_attempts.get(ip, []) if now - t < 60]
    _login_attempts[ip] = hits
    return len(hits) >= 5


def note_failure(ip):
    _login_attempts.setdefault(ip, []).append(time.time())


def csrf_token():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if session.get("user") not in USERS:
            session.clear()
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Content-Security-Policy"] = "default-src 'self'; style-src 'self' 'unsafe-inline'"
    return resp


# --------------------------------------------------------------------------
# Health / Readiness - getrennte Semantik fuer Kubernetes.
# --------------------------------------------------------------------------
@app.get("/health")
def health():
    """Liveness: Prozess reagiert. Kein I/O, damit ein volles PVC keinen Restart ausloest."""
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}, 200


@app.get("/ready")
def ready():
    """Readiness: Datenverzeichnis wirklich beschreibbar, sonst aus dem Service nehmen."""
    probe = os.path.join(DATA_DIR, ".ready")
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write(str(time.time()))
        os.remove(probe)
    except OSError as exc:
        return {"status": "unavailable", "detail": exc.__class__.__name__}, 503
    return {"status": "ready", "data_dir": DATA_DIR}, 200


# --------------------------------------------------------------------------
# Views
# --------------------------------------------------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        ip = request.remote_addr or "unknown"
        if rate_limited(ip):
            return render_template_string(
                LOGIN_HTML, error="Zu viele Versuche. Bitte kurz warten."), 429
        name = (request.form.get("user") or "").strip().lower()
        password = request.form.get("password") or ""
        record = USERS.get(name)
        if record and USER_RE.match(name) and verify_password(record["digest"], password):
            session.clear()
            session["user"] = name
            session["role"] = record["role"]
            csrf_token()
            return redirect(url_for("index"))
        note_failure(ip)
        error = "Login fehlgeschlagen."  # keine Auskunft ob User existiert
    return render_template_string(LOGIN_HTML, error=error), (401 if error else 200)


@app.post("/logout")
@login_required
def logout():
    check_csrf()
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def index():
    user = session["user"]
    role = session.get("role", "user")
    status = current_status(user)
    secs = worked_seconds_today(user)
    return render_template_string(
        INDEX_HTML,
        user=user, role=role, status=status,
        status_text=STATUS_TEXT[status],
        allowed=TRANSITIONS[status],
        labels=LABELS,
        entries=read_entries(user, limit=15),
        today=f"{secs // 3600}h {secs % 3600 // 60}min",
        csrf=csrf_token(),
    )


@app.post("/stempeln")
@login_required
def stempeln():
    check_csrf()
    user = session["user"]
    action = (request.form.get("action") or "").upper()
    if action not in ACTIONS:
        abort(400)
    status = current_status(user)
    if action not in TRANSITIONS[status]:
        abort(409)  # z.B. zweimal EIN hintereinander
    append_entry({
        "id": uuid.uuid4().hex[:12],
        "ts": datetime.now(timezone.utc).isoformat(),
        "user": user,
        "action": action,
        "note": clean_note(request.form.get("note")),
    })
    return redirect(url_for("index"))


def admin_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if session.get("role") != "admin":
            abort(403)  # RBAC: nur Rolle admin sieht und aendert fremde Daten
        return fn(*a, **kw)
    return wrapper


def check_csrf():
    if not hmac.compare_digest(request.form.get("csrf", ""), session.get("csrf", "")):
        abort(403)


@app.get("/admin")
@login_required
@admin_required
def admin():
    f = current_filters(request.args)
    alle = read_entries()
    treffer = apply_filters(alle, f)
    return render_template_string(
        ADMIN_HTML, entries=treffer[:200], gesamt=len(alle), treffer=len(treffer),
        f=f, users=known_users(alle), actions=ACTIONS, user=session["user"],
        csrf=csrf_token())


@app.get("/admin/nachtragen")
@login_required
@admin_required
def new_form():
    f = current_filters(request.args)
    vorgabe = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M")
    return render_template_string(
        NEW_HTML, users=known_users(read_entries()), actions=ACTIONS,
        csrf=csrf_token(), f=f, error=None,
        vals={"user": "", "action": "EIN", "ts": vorgabe, "note": ""})


@app.post("/admin/nachtragen")
@login_required
@admin_required
def new_apply():
    check_csrf()
    f = current_filters(request.form)
    vals = {
        "user": (request.form.get("target_user") or "").strip().lower(),
        "action": (request.form.get("action") or "").upper(),
        "ts": (request.form.get("ts") or "").strip(),
        "note": clean_note(request.form.get("note")),
    }

    def fehler(msg):
        return render_template_string(
            NEW_HTML, users=known_users(read_entries()), actions=ACTIONS,
            csrf=csrf_token(), f=f, error=msg, vals=vals), 400

    if not USER_RE.match(vals["user"]):
        return fehler("Bitte einen gueltigen Benutzer waehlen.")
    if vals["action"] not in ACTIONS:
        return fehler("Unbekannte Aktion.")
    ts = parse_form_ts(vals["ts"])
    if ts is None:
        return fehler("Ungueltiges Datum. Erwartet wird Datum und Uhrzeit.")

    # Nachtrag ist eine normale Stempelung, aber als solche gekennzeichnet -
    # damit bleibt sichtbar, dass sie nicht vom Benutzer selbst stammt.
    append_entry({
        "id": uuid.uuid4().hex[:12],
        "ts": ts,
        "user": vals["user"],
        "action": vals["action"],
        "note": vals["note"],
        "created_by": session["user"],
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    return redirect(url_for("admin", **f))


@app.get("/admin/bearbeiten/<entry_id>")
@login_required
@admin_required
def edit_form(entry_id):
    entry = find_entry(entry_id)
    if entry is None:
        abort(404)
    return render_template_string(
        EDIT_HTML, e=entry, actions=ACTIONS, csrf=csrf_token(),
        f=current_filters(request.args), error=None)


@app.post("/admin/bearbeiten/<entry_id>")
@login_required
@admin_required
def edit_apply(entry_id):
    check_csrf()
    entry = find_entry(entry_id)
    if entry is None:
        abort(404)
    f = current_filters(request.form)

    action = (request.form.get("action") or "").upper()
    if action not in ACTIONS:
        abort(400)

    ts = parse_form_ts(request.form.get("ts"))
    if ts is None:
        return render_template_string(
            EDIT_HTML, e=entry, actions=ACTIONS, csrf=csrf_token(), f=f,
            error="Ungueltiges Datum. Erwartet wird Datum und Uhrzeit."), 400

    # Append-only: die Korrektur wird angehaengt, der Originaleintrag bleibt stehen.
    append_entry({
        "type": "correction",
        "target": entry_id,
        "action": action,
        "note": clean_note(request.form.get("note")),
        "ts": ts,
        "by": session["user"],
        "at": datetime.now(timezone.utc).isoformat(),
    })
    return redirect(url_for("admin", **f))


@app.post("/admin/loeschen/<entry_id>")
@login_required
@admin_required
def delete_entry(entry_id):
    check_csrf()
    if find_entry(entry_id) is None:
        abort(404)
    # Auch das Loeschen ist ein Anhang, kein Entfernen aus der Datei.
    append_entry({
        "type": "delete",
        "target": entry_id,
        "by": session["user"],
        "at": datetime.now(timezone.utc).isoformat(),
    })
    return redirect(url_for("admin", **current_filters(request.form)))


# --------------------------------------------------------------------------
# Templates (inline, damit das Image ein einziges File bleibt)
# --------------------------------------------------------------------------
CSS = """
:root{color-scheme:light dark}
body{font-family:system-ui,-apple-system,sans-serif;max-width:46rem;margin:2rem auto;
padding:0 1rem;line-height:1.5}
h1{font-size:1.4rem;margin-bottom:.2rem}
.muted{color:#6b7280;font-size:.9rem}
.card{border:1px solid #d1d5db;border-radius:.6rem;padding:1rem;margin:1rem 0}
.status{font-size:1.1rem;font-weight:600}
button{font:inherit;padding:.55rem 1.1rem;border-radius:.4rem;border:1px solid #2563eb;
background:#2563eb;color:#fff;cursor:pointer}
button.ghost{background:transparent;color:#2563eb}
input{font:inherit;padding:.5rem;border-radius:.4rem;border:1px solid #9ca3af;width:100%;
box-sizing:border-box}
table{width:100%;border-collapse:collapse;font-size:.9rem}
td,th{text-align:left;padding:.35rem .5rem;border-bottom:1px solid #e5e7eb}
.err{color:#b91c1c}
.row{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center}
button.small{padding:.25rem .6rem;font-size:.8rem}
button.danger{border-color:#b91c1c;background:#b91c1c}
.tag{font-size:.72rem;color:#6b7280;display:block}
select{font:inherit;padding:.5rem;border-radius:.4rem;border:1px solid #9ca3af;width:100%}
.filter{display:grid;grid-template-columns:repeat(auto-fit,minmax(9rem,1fr));gap:.6rem;align-items:end}
.filter label{font-size:.8rem;color:#6b7280}
.filter input,.filter select{width:100%;margin-top:.15rem}
.count{font-size:.85rem;color:#6b7280;margin:.4rem 0}
"""

LOGIN_HTML = """<!doctype html><html lang=de><meta charset=utf-8>
<title>Zeiterfassung - Login</title><style>""" + CSS + """</style>
<h1>Zeiterfassung</h1><p class=muted>Bitte anmelden</p>
{% if error %}<p class=err>{{ error }}</p>{% endif %}
<form method=post class=card>
  <p><label>Benutzer<br><input name=user autocomplete=username autofocus></label></p>
  <p><label>Passwort<br><input name=password type=password autocomplete=current-password></label></p>
  <button type=submit>Anmelden</button>
</form></html>"""

INDEX_HTML = """<!doctype html><html lang=de><meta charset=utf-8>
<title>Zeiterfassung</title><style>""" + CSS + """</style>
<div class=row style="justify-content:space-between">
  <div><h1>Zeiterfassung</h1>
  <p class=muted>{{ user }} ({{ role }}) &middot; heute erfasst: {{ today }}</p></div>
  <form method=post action="{{ url_for('logout') }}">
    <input type=hidden name=csrf value="{{ csrf }}">
    <button class=ghost type=submit>Abmelden</button></form>
</div>
<div class=card>
  <p class=status>Status: {{ status_text }}</p>
  <form method=post action="{{ url_for('stempeln') }}">
    <input type=hidden name=csrf value="{{ csrf }}">
    <p><label>Notiz (optional)<br>
      <input name=note maxlength=200 placeholder="z.B. Support KYZ Kunde Meyer"></label></p>
    <div class=row>
      {% for action in allowed %}
        <button type=submit name=action value="{{ action }}">{{ labels[action] }}</button>
      {% endfor %}
    </div>
  </form>
</div>
<div class=card>
  <h2 style="font-size:1rem">Letzte Stempelungen</h2>
  {% if entries %}
  <table><tr><th>Zeit (UTC)</th><th>Aktion</th><th>Notiz</th></tr>
  {% for e in entries %}
    <tr><td>{{ e.ts[:19].replace('T',' ') }}</td><td>{{ e.action }}</td><td>{{ e.note }}</td></tr>
  {% endfor %}</table>
  {% else %}<p class=muted>Noch keine Eintraege.</p>{% endif %}
</div>
{% if role == 'admin' %}<p><a href="{{ url_for('admin') }}">Alle Mitarbeitenden ansehen</a></p>{% endif %}
</html>"""

ADMIN_HTML = """<!doctype html><html lang=de><meta charset=utf-8>
<title>Zeiterfassung - Admin</title><style>""" + CSS + """</style>
<h1>Alle Stempelungen</h1>
<p class=muted>Angemeldet als {{ user }} (admin) &middot; Korrekturen und Nachtraege
werden protokolliert, nicht ueberschrieben.</p>

<div class=card>
  <form method=get class=filter>
    <div><label>Von<input type=date name=von value="{{ f.von or '' }}"></label></div>
    <div><label>Bis<input type=date name=bis value="{{ f.bis or '' }}"></label></div>
    <div><label>Benutzer<select name=user>
      <option value="">alle</option>
      {% for u in users %}
      <option value="{{ u }}" {% if f.user == u %}selected{% endif %}>{{ u }}</option>
      {% endfor %}
    </select></label></div>
    <div><label>Aktion<select name=action>
      <option value="">alle</option>
      {% for a in actions %}
      <option value="{{ a }}" {% if f.action == a %}selected{% endif %}>{{ a }}</option>
      {% endfor %}
    </select></label></div>
    <div><label>Notiz enthaelt<input name=q value="{{ f.q or '' }}" maxlength=64></label></div>
    <div class=row>
      <button type=submit>Filtern</button>
      <a href="{{ url_for('admin') }}"><button class=ghost type=button>Zuruecksetzen</button></a>
    </div>
  </form>
  <p class=count>{{ treffer }} von {{ gesamt }} Eintraegen
    {%- if treffer > 200 %} (die ersten 200 werden angezeigt){% endif %}</p>
</div>

<p><a href="{{ url_for('new_form', **f) }}"><button type=button>Eintrag nachtragen</button></a></p>

<div class=card>
{% if entries %}
<table>
  <tr><th>Zeit (UTC)</th><th>Benutzer</th><th>Aktion</th><th>Notiz</th><th></th></tr>
{% for e in entries %}
  <tr>
    <td>{{ e.ts[:19].replace('T',' ') }}
      {% if e.created_by %}<span class=tag>nachgetragen von {{ e.created_by }}</span>{% endif %}
      {% if e.edited_by %}<span class=tag>korrigiert von {{ e.edited_by }}
        am {{ e.edited_at[:16].replace('T',' ') }}</span>{% endif %}</td>
    <td>{{ e.user }}</td><td>{{ e.action }}</td><td>{{ e.note }}</td>
    <td><div class=row>
      <a href="{{ url_for('edit_form', entry_id=e.id, **f) }}"><button class="ghost small"
         type=button>Bearbeiten</button></a>
      <form method=post action="{{ url_for('delete_entry', entry_id=e.id) }}"
            onsubmit="return confirm('Diesen Eintrag wirklich entfernen?')">
        <input type=hidden name=csrf value="{{ csrf }}">
        {% for k, v in f.items() %}<input type=hidden name="{{ k }}" value="{{ v }}">{% endfor %}
        <button class="danger small" type=submit>Loeschen</button></form>
    </div></td>
  </tr>
{% endfor %}</table>
{% else %}<p class=muted>Keine Eintraege fuer diesen Filter.</p>{% endif %}
</div>
<p><a href="{{ url_for('index') }}">Zurueck</a></p></html>"""

NEW_HTML = """<!doctype html><html lang=de><meta charset=utf-8>
<title>Eintrag nachtragen</title><style>""" + CSS + """</style>
<h1>Eintrag nachtragen</h1>
<p class=muted>Fuer versehentlich geloeschte oder vergessene Stempelungen.</p>
{% if error %}<p class=err>{{ error }}</p>{% endif %}
<form method=post class=card>
  <input type=hidden name=csrf value="{{ csrf }}">
  {% for k, v in f.items() %}<input type=hidden name="{{ k }}" value="{{ v }}">{% endfor %}
  <p><label>Benutzer<br>
    <select name=target_user>
      <option value="">bitte waehlen</option>
      {% for u in users %}
      <option value="{{ u }}" {% if vals.user == u %}selected{% endif %}>{{ u }}</option>
      {% endfor %}
    </select></label></p>
  <p><label>Aktion<br>
    <select name=action>
      {% for a in actions %}
      <option value="{{ a }}" {% if vals.action == a %}selected{% endif %}>{{ a }}</option>
      {% endfor %}
    </select></label></p>
  <p><label>Zeitpunkt (UTC)<br>
    <input type="datetime-local" name=ts value="{{ vals.ts }}"></label></p>
  <p><label>Notiz<br>
    <input name=note maxlength=200 value="{{ vals.note }}"></label></p>
  <div class=row>
    <button type=submit>Eintrag anlegen</button>
    <a href="{{ url_for('admin', **f) }}"><button class=ghost type=button>Abbrechen</button></a>
  </div>
</form>
<p class=muted>Der Eintrag wird als Nachtrag gekennzeichnet; in der Liste steht,
wer ihn angelegt hat.</p></html>"""

EDIT_HTML = """<!doctype html><html lang=de><meta charset=utf-8>
<title>Eintrag bearbeiten</title><style>""" + CSS + """</style>
<h1>Eintrag bearbeiten</h1>
<p class=muted>Benutzer {{ e.user }} &middot; ID {{ e.id }}</p>
{% if error %}<p class=err>{{ error }}</p>{% endif %}
<form method=post class=card>
  <input type=hidden name=csrf value="{{ csrf }}">
  {% for k, v in f.items() %}<input type=hidden name="{{ k }}" value="{{ v }}">{% endfor %}
  <p><label>Aktion<br>
    <select name=action>
      {% for a in actions %}
      <option value="{{ a }}" {% if a == e.action %}selected{% endif %}>{{ a }}</option>
      {% endfor %}
    </select></label></p>
  <p><label>Zeitpunkt (UTC)<br>
    <input type="datetime-local" name=ts value="{{ e.ts[:16] }}"></label></p>
  <p><label>Notiz<br>
    <input name=note maxlength=200 value="{{ e.note }}"></label></p>
  <div class=row>
    <button type=submit>Korrektur speichern</button>
    <a href="{{ url_for('admin', **f) }}"><button class=ghost type=button>Abbrechen</button></a>
  </div>
</form>
<p class=muted>Die Aenderung wird als Korrektur angehaengt. Der urspruengliche
Eintrag bleibt im Protokoll erhalten.</p></html>"""


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080)
