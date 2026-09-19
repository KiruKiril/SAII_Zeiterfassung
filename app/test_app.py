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
tok2 = _re.search(r'name=csrf value="([^"]+)"', adm).group(1)

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
ok("Zeit korrigiert", upd["ts"].startswith("2026-09-19T08:30"))
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

print("\n%d Fehler" % len(fails))
sys.exit(1 if fails else 0)
