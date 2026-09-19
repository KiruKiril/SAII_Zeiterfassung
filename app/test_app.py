import os, re, sys, tempfile, subprocess
tmp = tempfile.mkdtemp()
H = subprocess.check_output([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "hashpw.py"), "geheim123"]).decode().strip()
HA = subprocess.check_output([sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "hashpw.py"), "adminpw"]).decode().strip()
os.environ.update(DATA_DIR=tmp, SECRET_KEY="test-key-only",
                  ZE_USERS=f"kiril:{H}:user,chef:{HA}:admin")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import app as A

ok = lambda n, c: print(("  OK   " if c else "  FAIL ") + n) or (0 if c else fails.append(n))
fails = []
c = A.app.test_client()

# Health / Ready ohne Login
ok("/health ohne Login = 200", c.get("/health").status_code == 200)
ok("/ready meldet ready", c.get("/ready").get_json()["status"] == "ready")
ok("/ (geschuetzt) leitet zu Login", c.get("/").status_code == 302)

# Login
ok("falsches Passwort -> 401", c.post("/login", data={"user":"kiril","password":"x"}).status_code == 401)
r = c.post("/login", data={"user":"kiril","password":"geheim123"})
ok("richtiges Passwort -> Redirect", r.status_code == 302)

page = c.get("/").get_data(as_text=True)
token = re.search(r'name=csrf value="([^"]+)"', page).group(1)
ok("Status initial ausgestempelt", "ausgestempelt" in page)
ok("nur EIN angeboten", 'value="EIN"' in page and 'value="AUS"' not in page)

# CSRF
ok("Stempeln ohne CSRF -> 403",
   c.post("/stempeln", data={"action":"EIN"}).status_code == 403)

def stamp(a, note=""):
    return c.post("/stempeln", data={"action":a,"note":note,"csrf":token})

ok("EIN akzeptiert", stamp("EIN","Support KYZ Kunde Meyer").status_code == 302)
ok("zweites EIN -> 409 (Zustandsautomat)", stamp("EIN").status_code == 409)
ok("PAUSE akzeptiert", stamp("PAUSE").status_code == 302)
ok("ZURUECK akzeptiert", stamp("ZURUECK").status_code == 302)
ok("AUS akzeptiert", stamp("AUS").status_code == 302)
ok("unbekannte Aktion -> 400", stamp("DROP").status_code == 400)

# Persistenz
lines = open(os.path.join(tmp, "times.jsonl")).read().strip().split("\n")
ok("4 Zeilen persistiert (JSONL)", len(lines) == 4)
ok("Notiz gespeichert", "Kunde Meyer" in lines[0])
ok("Reload aus Datei -> Status AUS", A.current_status("kiril") == "AUS")

# XSS / Validierung
c.post("/stempeln", data={"action":"EIN","note":"<script>alert(1)</script>","csrf":token})
ok("Notiz HTML-escaped im Output", "&lt;script&gt;" in c.get("/").get_data(as_text=True))
ok("Notiz auf 200 Zeichen gekappt", len(A.read_entries("kiril")[0]["note"]) <= 200)

# RBAC
ok("user darf nicht auf /admin", c.get("/admin").status_code == 403)
c2 = A.app.test_client()
c2.post("/login", data={"user":"chef","password":"adminpw"})
ok("admin darf auf /admin", c2.get("/admin").status_code == 200)
ok("admin sieht fremde Eintraege", "kiril" in c2.get("/admin").get_data(as_text=True))

# Security Header
h = c.get("/health").headers
ok("X-Frame-Options gesetzt", h.get("X-Frame-Options") == "DENY")
ok("CSP gesetzt", "default-src 'self'" in h.get("Content-Security-Policy",""))

# Readiness faellt aus wenn /data weg ist
A.DATA_DIR = "/proc/kein-schreibzugriff"
ok("/ready -> 503 wenn Datenpfad kaputt", c.get("/ready").status_code == 503)
A.DATA_DIR = tmp
ok("/health bleibt 200 (Liveness unabhaengig)", c.get("/health").status_code == 200)


# --- Admin darf bearbeiten (append-only Korrekturen) ----------------------
adm = c2.get("/admin").get_data(as_text=True)
import re as _re
eid = _re.search(r'/admin/bearbeiten/([a-zA-Z0-9]+)', adm).group(1)
tok2 = _re.search(r'name=csrf value="([^"]+)"', c2.get("/").get_data(as_text=True)).group(1)

ok("admin sieht Bearbeiten-Link", "Bearbeiten" in adm)
ok("user kommt nicht ans Formular",
   c.get("/admin/bearbeiten/" + eid).status_code == 403)
ok("admin oeffnet Formular", c2.get("/admin/bearbeiten/" + eid).status_code == 200)
ok("unbekannte ID -> 404", c2.get("/admin/bearbeiten/gibtsnicht").status_code == 404)

raw_before = len(A.read_raw())
r = c2.post("/admin/bearbeiten/" + eid,
            data={"action": "AUS", "ts": "2026-09-19T08:30", "note": "korrigiert", "csrf": tok2})
ok("Korrektur akzeptiert", r.status_code == 302)
ok("Log ist gewachsen, nichts ueberschrieben", len(A.read_raw()) == raw_before + 1)
ok("Originalzeile noch im Log",
   any(x.get("id") == eid and x.get("type", "stamp") == "stamp" for x in A.read_raw()))

upd = A.find_entry(eid)
ok("Aktion korrigiert", upd["action"] == "AUS")
ok("Notiz korrigiert", upd["note"] == "korrigiert")
ok("Zeit korrigiert (Eingabe war Ortszeit)", A.input_local(upd["ts"]) == "2026-09-19T08:30")
ok("Korrektur ist zugeordnet", upd["edited_by"] == "chef")

ok("Korrektur ohne CSRF -> 403",
   c2.post("/admin/bearbeiten/" + eid, data={"action": "EIN", "ts": "2026-09-19T08:30"}).status_code == 403)
ok("ungueltige Aktion -> 400",
   c2.post("/admin/bearbeiten/" + eid,
           data={"action": "XX", "ts": "2026-09-19T08:30", "csrf": tok2}).status_code == 400)
ok("ungueltiges Datum -> 400",
   c2.post("/admin/bearbeiten/" + eid,
           data={"action": "EIN", "ts": "kein-datum", "csrf": tok2}).status_code == 400)
ok("user darf nicht korrigieren",
   c.post("/admin/bearbeiten/" + eid,
          data={"action": "EIN", "ts": "2026-09-19T08:30", "csrf": token}).status_code == 403)

# --- Loeschen ist ebenfalls append-only -----------------------------------
before_del = len(A.read_entries())
ok("Loeschen ohne CSRF -> 403",
   c2.post("/admin/loeschen/" + eid).status_code == 403)
ok("user darf nicht loeschen",
   c.post("/admin/loeschen/" + eid, data={"csrf": token}).status_code == 403)
ok("admin loescht", c2.post("/admin/loeschen/" + eid, data={"csrf": tok2}).status_code == 302)
ok("Eintrag aus der Ansicht verschwunden", A.find_entry(eid) is None)
ok("Sichtbare Eintraege um 1 weniger", len(A.read_entries()) == before_del - 1)
ok("Datei enthaelt den Eintrag weiterhin",
   any(x.get("id") == eid for x in A.read_raw()))


# --- Admin kann Eintraege nachtragen --------------------------------------
adm2 = c2.get("/admin").get_data(as_text=True)
tok3 = _re.search(r'name=csrf value="([^"]+)"', c2.get("/").get_data(as_text=True)).group(1)

ok("Nachtragen-Button vorhanden", "Eintrag nachtragen" in adm2)
ok("user kommt nicht ans Nachtragen", c.get("/admin/nachtragen").status_code == 403)
ok("admin oeffnet Nachtragen", c2.get("/admin/nachtragen").status_code == 200)

vorher = len(A.read_entries("kiril"))
r = c2.post("/admin/nachtragen", data={
    "target_user": "kiril", "action": "EIN", "ts": "2026-09-18T07:15",
    "note": "vergessen einzustempeln", "csrf": tok3})
ok("Nachtrag akzeptiert", r.status_code == 302)
ok("Eintrag bei kiril angekommen", len(A.read_entries("kiril")) == vorher + 1)

nach = [e for e in A.read_entries("kiril") if e.get("note") == "vergessen einzustempeln"]
ok("Nachtrag ist gekennzeichnet", bool(nach) and nach[0]["created_by"] == "chef")
ok("Nachtrag traegt den gewaehlten Zeitpunkt", A.input_local(nach[0]["ts"]) == "2026-09-18T07:15")
ok("Kennzeichnung sichtbar in der Liste",
   "nachgetragen von chef" in c2.get("/admin").get_data(as_text=True))

ok("Nachtrag ohne CSRF -> 403", c2.post("/admin/nachtragen", data={
    "target_user": "kiril", "action": "EIN", "ts": "2026-09-18T07:15"}).status_code == 403)
ok("unbekannter Benutzer -> 400", c2.post("/admin/nachtragen", data={
    "target_user": "!!", "action": "EIN", "ts": "2026-09-18T07:15", "csrf": tok3}).status_code == 400)
ok("ungueltige Aktion -> 400", c2.post("/admin/nachtragen", data={
    "target_user": "kiril", "action": "XX", "ts": "2026-09-18T07:15", "csrf": tok3}).status_code == 400)
ok("ungueltiges Datum -> 400", c2.post("/admin/nachtragen", data={
    "target_user": "kiril", "action": "EIN", "ts": "morgen", "csrf": tok3}).status_code == 400)
ok("user darf nicht nachtragen", c.post("/admin/nachtragen", data={
    "target_user": "anna", "action": "EIN", "ts": "2026-09-18T07:15",
    "csrf": token}).status_code == 403)

# --- Filter ----------------------------------------------------------------
alle = len(A.read_entries())
ok("ohne Filter alle Eintraege", len(A.apply_filters(A.read_entries(), {})) == alle)
ok("Filter Benutzer", all(e["user"] == "kiril"
   for e in A.apply_filters(A.read_entries(), {"user": "kiril"})))
ok("Filter Aktion", all(e["action"] == "EIN"
   for e in A.apply_filters(A.read_entries(), {"action": "EIN"})))
ok("Filter von-Datum", all(e["ts"][:10] >= "2026-09-19"
   for e in A.apply_filters(A.read_entries(), {"von": "2026-09-19"})))
ok("Filter bis-Datum", all(e["ts"][:10] <= "2026-09-18"
   for e in A.apply_filters(A.read_entries(), {"bis": "2026-09-18"})))
ok("Filter Notiztext", all("vergessen" in e["note"].lower()
   for e in A.apply_filters(A.read_entries(), {"q": "vergessen"})))
ok("Filter kombiniert", all(e["user"] == "kiril" and e["action"] == "EIN"
   for e in A.apply_filters(A.read_entries(), {"user": "kiril", "action": "EIN"})))
ok("Filter ohne Treffer gibt leere Liste",
   A.apply_filters(A.read_entries(), {"user": "niemand"}) == [])

ok("Muellwerte werden verworfen",
   A.current_filters({"von": "kaputt", "action": "XX", "user": "kiril"}) == {"user": "kiril"})
ok("gueltige Werte bleiben",
   A.current_filters({"von": "2026-09-01", "action": "EIN"}) == {"von": "2026-09-01", "action": "EIN"})

resp = c2.get("/admin?user=kiril&action=EIN")
html = resp.get_data(as_text=True)
erwartet = len(A.apply_filters(A.read_entries(), {"user": "kiril", "action": "EIN"}))
ok("Filter ueber die URL liefert 200", resp.status_code == 200)
ok("Zaehler nennt die Trefferzahl",
   "%d von %d Eintraegen" % (erwartet, len(A.read_entries())) in html)
ok("Benutzerfilter bleibt gewaehlt", '<option value="kiril" selected>' in html)
ok("Aktionsfilter bleibt gewaehlt", '<option value="EIN" selected>' in html)
ok("gefilterte Liste zeigt nur diese Aktion", html.count("<td>PAUSE</td>") == 0)

leer = c2.get("/admin?user=niemand").get_data(as_text=True)
ok("leerer Filter zeigt Hinweis", "Keine Eintraege fuer diesen Filter" in leer)


# --- Kein Sackgassen-Fehler mehr bei GET auf POST-Routen ------------------
from datetime import datetime as _dt, timezone as _tz
for pfad in ("/stempeln", "/logout"):
    resp = c.get(pfad)
    ok("GET %s zeigt Rueckweg" % pfad,
       resp.status_code == 405 and "Zurueck zur Zeiterfassung" in resp.get_data(as_text=True))
ok("unbekannte Seite zeigt Rueckweg",
   "Zurueck zur Zeiterfassung" in c.get("/gibtsnicht").get_data(as_text=True))

# --- Ortszeit statt UTC ----------------------------------------------------
utc_iso = "2026-07-01T06:30:00+00:00"          # Sommerzeit: Zuerich = UTC+2
ok("Anzeige in Ortszeit", A.fmt_local(utc_iso) == "01.07.2026 08:30")
ok("Formularwert in Ortszeit", A.input_local(utc_iso) == "2026-07-01T08:30")
ok("Formulareingabe wird als Ortszeit gelesen",
   A.parse_form_ts("2026-07-01T08:30") == utc_iso)
ok("Hin und zurueck bleibt gleich",
   A.parse_form_ts(A.input_local(utc_iso)) == utc_iso)
ok("Winterzeit ist UTC+1", A.fmt_local("2026-01-15T07:00:00+00:00") == "15.01.2026 08:00")
ok("Tag richtet sich nach Ortszeit",
   A.local_day("2026-07-01T23:30:00+00:00") == "2026-07-02")
ok("kaputter Zeitstempel bricht nicht ab", A.fmt_local("unsinn") == "?")

# --- Arbeitszeit: Korrektur wirkt sich aus --------------------------------
heute = _dt.now(A.TZ).date().isoformat()
c3 = A.app.test_client(); c3.post("/login", data={"user": "kiril", "password": "geheim123"})
tok4 = _re.search(r'name=csrf value="([^"]+)"', c3.get("/").get_data(as_text=True)).group(1)
c3.post("/stempeln", data={"action": "AUS", "csrf": tok4})      # sauberer Ausgangszustand
c3.post("/stempeln", data={"action": "EIN", "csrf": tok4})
vorher = A.worked_seconds_today("kiril")

neu = [e for e in A.read_entries("kiril") if e["action"] == "EIN"][0]
adm3 = c2.get("/admin").get_data(as_text=True)
tok5 = _re.search(r'name=csrf value="([^"]+)"', c2.get("/").get_data(as_text=True)).group(1)
c2.post("/admin/bearbeiten/" + neu["id"],
        data={"action": "EIN", "ts": heute + "T06:00", "note": "", "csrf": tok5})
nachher = A.worked_seconds_today("kiril")
ok("Tagessumme waechst nach Start-Korrektur", nachher > vorher + 3000)
ok("Startseite zeigt die neue Summe",
   A.hhmm(nachher) in c3.get("/").get_data(as_text=True))

# --- Admin sieht die Zeit des betroffenen Benutzers ------------------------
seite = c2.get("/admin?user=kiril").get_data(as_text=True)
ok("Admin-Ansicht nennt erfasste Zeit", "Erfasste Zeit im Zeitraum" in seite)
ok("Admin sieht kirils Summe, nicht die eigene",
   ("<b>kiril</b> " + A.hhmm(A.worked_seconds("kiril"))) in seite)
ok("ohne Benutzerfilter erscheinen alle Benutzer",
   all(("<b>%s</b>" % u) in c2.get("/admin").get_data(as_text=True)
       for u in ("kiril", "chef")))

# --- Doppelter Beginn darf keine Zeit verschlucken ------------------------
def _sek(folge):
    """Rechnet eine Aktionsfolge (Stunde, Aktion) in Sekunden um."""
    import json as _json
    pfad = os.path.join(tmp, "probe.jsonl")
    alt_file, alt_dir = A.DATA_FILE, A.DATA_DIR
    A.DATA_FILE, A.DATA_DIR = pfad, tmp
    open(pfad, "w").close()
    for stunde, aktion in folge:
        A.append_entry({"id": "p%d" % stunde, "user": "probe", "action": aktion,
                        "ts": "2026-07-01T%02d:00:00+00:00" % stunde})
    wert = A.worked_seconds("probe", "2026-07-01", "2026-07-01")
    A.DATA_FILE, A.DATA_DIR = alt_file, alt_dir
    return wert

ok("normale Folge EIN->AUS ergibt 8h", _sek([(6, "EIN"), (14, "AUS")]) == 8 * 3600)
ok("mit Pause werden Pausen abgezogen",
   _sek([(6, "EIN"), (10, "PAUSE"), (11, "ZURUECK"), (14, "AUS")]) == 7 * 3600)
ok("doppeltes EIN verschluckt die Zeit nicht",
   _sek([(6, "EIN"), (14, "EIN"), (15, "AUS")]) == 9 * 3600)
ok("Beginn ohne Ende zaehlt bis jetzt weiter",
   _sek([(6, "EIN")]) > 0)


# =========================================================================
#  Szenarien aus dem echten Gebrauch
# =========================================================================
print("\n--- Szenarien ---")

def frisch(name, passwort):
    cl = A.app.test_client()
    cl.post("/login", data={"user": name, "password": passwort})
    return cl

def tok_von(cl, pfad="/"):
    m = _re.search(r'name=csrf value="([^"]+)"', cl.get(pfad).get_data(as_text=True))
    assert m, "kein CSRF-Token auf " + pfad
    return m.group(1)

def angemeldet(cl):
    """Wurde man rausgeworfen? Dann leitet / auf den Login um."""
    return cl.get("/").status_code == 200

# --- Voller Arbeitstag ohne Rauswurf --------------------------------------
u = frisch("kiril", "geheim123")
t = tok_von(u)
u.post("/stempeln", data={"action": "AUS", "csrf": t})     # sauberer Start
abfolge = [("EIN", "start"), ("PAUSE", "mittag"), ("ZURUECK", ""), ("AUS", "feierabend")]
raus = []
for aktion, notiz in abfolge:
    r = u.post("/stempeln", data={"action": aktion, "note": notiz, "csrf": t})
    if r.status_code != 302 or not angemeldet(u):
        raus.append(aktion)
ok("ganzer Tag EIN-PAUSE-ZURUECK-AUS ohne Rauswurf", raus == [])
ok("nach Feierabend weiterhin angemeldet", angemeldet(u))
ok("Status nach Feierabend ist ausgestempelt",
   "ausgestempelt" in u.get("/").get_data(as_text=True))

# --- Veraltete Seite: zweimal Feierabend ----------------------------------
r = u.post("/stempeln", data={"action": "AUS", "csrf": t})
ok("zweites Ausstempeln gibt 409", r.status_code == 409)
ok("409 erklaert den Grund statt nackter Fehlerseite",
   "Status hat sich geaendert" in r.get_data(as_text=True))
ok("409 bietet einen Rueckweg", "Zurueck zur Zeiterfassung" in r.get_data(as_text=True))
ok("nach dem 409 immer noch angemeldet", angemeldet(u))

# --- Zurueck-Knopf im Browser ---------------------------------------------
r = u.get("/stempeln")
ok("GET /stempeln erklaert den Fall", "Adresse nicht direkt aufrufbar" in r.get_data(as_text=True))
ok("nach GET /stempeln immer noch angemeldet", angemeldet(u))

# --- Keine veralteten Seiten aus dem Browser-Zwischenspeicher -------------
for pfad in ("/", "/admin", "/login"):
    cl = u if pfad != "/login" else A.app.test_client()
    ok("%s wird nicht zwischengespeichert" % pfad,
       "no-store" in cl.get(pfad).headers.get("Cache-Control", ""))

# --- Loeschen mit Rueckfrage ----------------------------------------------
adm = frisch("chef", "adminpw")
eintrag = A.read_entries()[0]
vorher = len(A.read_entries())

r = adm.get("/admin/loeschen/" + eintrag["id"])
ok("Loeschen zeigt eine Rueckfrage statt 405", r.status_code == 200)
ok("Rueckfrage nennt den Eintrag", eintrag["action"] in r.get_data(as_text=True))
ok("Rueckfrage aendert noch nichts", len(A.read_entries()) == vorher)

tok_del = _re.search(r'name=csrf value="([^"]+)"', r.get_data(as_text=True)).group(1)
r = adm.post("/admin/loeschen/" + eintrag["id"], data={"csrf": tok_del})
ok("Bestaetigung entfernt den Eintrag", r.status_code == 302)
ok("Eintrag ist aus der Liste weg", len(A.read_entries()) == vorher - 1)
ok("nach dem Loeschen immer noch angemeldet", angemeldet(adm))

ok("user kommt nicht an die Rueckfrage",
   u.get("/admin/loeschen/" + A.read_entries()[0]["id"]).status_code == 403)
ok("403 erklaert den Grund",
   "nicht mehr aktuell" in u.get("/admin/loeschen/" + A.read_entries()[0]["id"]).get_data(as_text=True))

# --- Gueltiges HTML: keine Schaltflaeche in einem Link --------------------
import re as _re2
adm2 = frisch("chef", "adminpw")
eid = A.read_entries()[0]["id"]
seiten = {
    "/": u.get("/").get_data(as_text=True),
    "/admin": adm2.get("/admin").get_data(as_text=True),
    "/admin/nachtragen": adm2.get("/admin/nachtragen").get_data(as_text=True),
    "/admin/bearbeiten": adm2.get("/admin/bearbeiten/" + eid).get_data(as_text=True),
    "/admin/loeschen": adm2.get("/admin/loeschen/" + eid).get_data(as_text=True),
    "/login": A.app.test_client().get("/login").get_data(as_text=True),
}
for pfad, html in seiten.items():
    ok("%s: kein <button> in einem <a>" % pfad,
       not _re2.search(r"<a[^>]*>\s*<button", html))
    ok("%s: keine Inline-Skripte (CSP)" % pfad,
       not _re2.search(r"\son(click|submit|change|load)\s*=", html))

r = A.app.test_client().get("/favicon.ico")
ok("Favicon wird ausgeliefert (keine 404 im Log)",
   r.status_code == 200 and r.mimetype == "image/svg+xml")

print("\n%d Fehler" % len(fails))
sys.exit(1 if fails else 0)
