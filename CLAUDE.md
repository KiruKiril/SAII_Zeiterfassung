# Kontext für Claude Code — Projekt Zeiterfassung (SAII Tag 4/5)

Diese Datei wird beim Öffnen des Repos automatisch geladen. Sie bringt jede
neue Chat-Sitzung auf denselben Stand, damit die Arbeit ohne Rückfragen
weitergehen kann.

---

## Was das ist

Modulauftrag SAII Tag 4/5 an der HFI: eine containerisierte Zeiterfassung, die
auf Kubernetes läuft und Arbeitszeiten behält, wenn Kubernetes den Pod ersetzt.

**Klasse 26A, Gruppe 3** (Ruben F., Kiril R., Daniel E.) — der Einzelauftrag
„VibeCode the World" wurde von Kiril Rothacher umgesetzt.

Die Kursanleitung sieht den **Hermes Agent** mit lokalem Ollama-Modell vor.
Stattdessen wurde **Claude Code** verwendet. Das Lernziel bleibt identisch
(Agent plant → Review → Agent setzt um → Nachweis); nur Folie 26–30 des PDFs
(Hermes- und Ollama-Installation) entfallen. Das steht so auch im Abgabe-
Dokument — nicht verschweigen, wenn jemand fragt.

### Geforderte Abgabe
- Video, max. 2.5 Minuten, Zeiterfassung vorführen → `Video_Zeiterfassung.mp4` (2:11, **ohne Ton**)
- Dokument, max. 4 A4-Seiten: SOLL, Security-Anforderungen, Healthchecks → `docs/Abgabe_Zeiterfassung.docx`
- Mindestanforderungen: Security-Überlegungen, automatische Healthchecks, Ein-/Ausstempeln
- Freiwillig (umgesetzt): userbasiert/RBAC, Notiz pro Stempelung

Originalauftrag: `SAII_Tag4_final (1).pdf`

### Zweiter Auftrag: Kurzplanung Arbeitspakete
„GIT aufbauen + Kurzplanung Arbeitspakete" — Ablauf von der lokalen
Entwicklung bis zur Alarmierung. Abgabe: `Gruppe3_26A_SAII_AblaufProjekt.docx`,
Quelle dazu in `docs/Ablauf_Arbeitspakete.md`, Grafik `docs/Ablauf.svg`.
Der Stand je Arbeitspaket (erledigt / teilweise / offen) ist dort ehrlich
vermerkt — AP 3 lief auf lokalem minikube, nicht auf der LM.

---

## Aufbau des Repos

```
app/          app.py (die ganze Anwendung), Dockerfile, test_app.py, hashpw.py
k8s/base/     deployment.yaml, service.yaml, pvc.yaml, kustomization.yaml
k8s/overlays/ dev/ (1 Replica, NodePort 30080) und prod/ (3 Replicas, ClusterIP, NetworkPolicy)
k8s/make-secret.sh   erzeugt das Secret im Cluster — liegt bewusst nicht im Git
docs/         Abgabe-Dokument, Netzwerkplan, Video-Drehbuch, Projektverlauf
docker-compose.yml   Schnellstart ohne Kubernetes (für die Bewertung)
port-forward.sh      Zugang zum Cluster mit Selbstheilung
make-abgabe.sh       baut das Abgabe-ZIP
```

---

## Die Anwendung

Eine einzige Datei: `app/app.py` (~700 Zeilen, Flask, keine Templates-Dateien,
keine Datenbank, kein JavaScript).

- **Stempeln**: `EIN → PAUSE → ZURÜCK → AUS`, als Zustandsautomat **serverseitig**
  erzwungen (`TRANSITIONS`). Ein unerlaubter Übergang gibt 409, nicht etwa eine
  stille Doppelbuchung.
- **Persistenz**: append-only JSONL unter `/data/times.jsonl`, geschrieben mit
  `flock` + `fsync`. Defekte Zeilen werden beim Lesen übersprungen.
- **Korrekturen**: Ein Admin kann Einträge ändern, entfernen und für andere
  nachtragen. Nichts wird überschrieben — es werden Datensätze mit
  `type: correction` bzw. `type: delete` angehängt und erst beim **Lesen**
  angewendet (`effective_entries()`). Nachträge tragen `created_by`.
- **Rollen**: `user` sieht nur eigene Einträge, `admin` zusätzlich `/admin` mit
  Filtern (Datum, Benutzer, Aktion, Notiztext) und Summen je Benutzer.
- **Zeitzone**: gespeichert wird **UTC**, angezeigt und eingegeben wird
  **Ortszeit** (`ZE_TZ`, Vorgabe `Europe/Zurich`). Auch Tagesgrenze und
  Datumsfilter richten sich nach Ortszeit.
- **Healthchecks**: `/health` (Liveness, kein I/O) und `/ready` (Readiness,
  schreibt testweise nach `/data`). Getrennt, damit ein volles Volume den Pod
  nicht in einen CrashLoopBackOff schickt, sondern nur aus dem Service nimmt.

### Zugangsdaten für die Demo
| Benutzer | Passwort | Rolle |
|---|---|---|
| `kiril` | `geheim123` | admin |
| `anna` | `anna123` | user |

Passwörter stehen nirgends im Klartext, auch nicht in `docker-compose.yml` —
dort liegen nur PBKDF2-Hashes.

---

## Starten

**Ohne Kubernetes** (so prüft die Lehrperson):
```bash
docker compose up --build       # dann http://localhost:8080
```

**Mit Kubernetes:**
```bash
minikube start --driver=docker
docker build -t zeiterfassung:1.0 app/
minikube image load zeiterfassung:1.0
./k8s/make-secret.sh ze-dev "kiril:geheim123:admin" "anna:anna123:user"
kubectl apply -k k8s/overlays/dev
./port-forward.sh start         # dann http://localhost:8080
```

**Tests:**
```bash
python3 -m venv .venv && .venv/bin/pip install -r app/requirements.txt
.venv/bin/python app/test_app.py     # 128 Tests, müssen alle grün sein
```

---

## Entscheidungen, die nicht offensichtlich sind

Wer hier weiterarbeitet, sollte diese Gründe kennen, bevor er etwas „aufräumt":

| Entscheidung | Grund |
|---|---|
| `strategy: Recreate` statt RollingUpdate | Der PVC ist ReadWriteOnce; bei einem RollingUpdate würde der neue Pod auf den Claim warten, den der alte hält — der Rollout bliebe hängen. |
| Korrekturen als angehängte Datensätze | Das Abgabe-Dokument sagt append-only zu. Direktes Überschreiben würde diese Zusage brechen, und bei Arbeitszeiten muss nachvollziehbar bleiben, wer was geändert hat. |
| Kein JavaScript in der Oberfläche | Die CSP ist `default-src 'self'` ohne `unsafe-inline`. Inline-Handler werden blockiert. Lieber eine Bestätigungsseite als eine aufgeweichte CSP. |
| `Cache-Control: no-store` | Ohne das zeigte der Zurück-Knopf eine veraltete Seite mit falschen Schaltflächen; ein Klick darauf endete in 409. |
| Nachträge prüfen die Reihenfolge **nicht** | Sonst liesse sich eine kaputte Abfolge gar nicht erst reparieren. Bewusst so, steht in den bekannten Grenzen. |
| `port-forward.sh` statt nacktem `kubectl port-forward` | Der Tunnel bricht bei jedem Pod-Wechsel ab. Die Anwendung läuft dann weiter, aber im Browser sieht es wie ein Totalausfall aus. |

---

## Fehler, die schon einmal auftraten

Falls diese Symptome wieder erscheinen — sie sind behoben, aber die Ursachen
sind lehrreich:

| Symptom | Ursache |
|---|---|
| „Method Not Allowed" | GET auf eine reine POST-Route nach Zurück/Neuladen. Jetzt fängt ein Handler 400/403/404/405/409 ab. |
| Erfasste Zeit aktualisiert sich nicht | Zweimal `EIN` ohne Ende dazwischen überschrieb den Startzeitpunkt — die Stunden dazwischen verschwanden. |
| Zeiten passen nicht zur Uhr | Alles lief in UTC statt Ortszeit (2 h Differenz im Sommer). |
| Löschen tut nichts | `<button>` innerhalb eines `<a>` ist ungültiges HTML; Safari schickte dadurch GET statt POST. |
| Keine Rückfrage vor dem Löschen | `onsubmit` wurde von der eigenen CSP blockiert. |
| „Die ganze App läuft nicht mehr" | Fast immer nur der Port-Forward. Erst `kubectl -n ze-dev get pods` und die Logs prüfen, bevor man die App verdächtigt. |

---

## Arbeitsweise, die sich bewährt hat

- **Erst reproduzieren, dann ändern.** Jeder der oben genannten Fehler wurde
  zuerst nachgestellt — im Server-Log, im Test oder im echten Browser.
- **Nach jeder Änderung die Tests laufen lassen.** Sie haben mehrfach echte
  Defekte gefunden, nicht nur Tippfehler.
- **Im echten Browser gegenprüfen.** Zwei Fehler (ungültiges HTML, blockierte
  CSP) waren nur dort sichtbar, nicht im Test-Client.
- **Keine Behauptungen ohne Beleg.** Wenn etwas läuft, zeigt man den
  HTTP-Code, die Logzeile oder den Testlauf.

---

## Offene Punkte

- Das Video hat **keinen Ton** (Mikrofon war bei der Aufnahme nicht gewählt).
  Inhaltlich reicht es, die Begründungen stehen im Dokument.
- Der Namespace `platform` im Netzwerkplan (Monitoring, Logs, Alarmierung) ist
  **Ausbaustufe** und nicht umgesetzt — blass dargestellt und so beschriftet.
- Prod zielt auf `registry.hfi.local/saii/zeiterfassung` — ein Platzhalter.
- `ReadWriteOnce` mit 3 Replicas trägt nur auf einem Single-Node-Cluster.
- Im Repo liegt historisch eine 69 MB grosse Rohaufnahme (`.mov`). Sie ist
  inzwischen aus der Verfolgung genommen, steckt aber noch in der Historie.

---

## Wenn du als Claude hier weitermachst

Lies zusätzlich `docs/PROJEKTVERLAUF.md` und `docs/Ablauf_Arbeitspakete.md` — dort steht chronologisch, was
gemacht wurde und warum. Prüfe vor Empfehlungen, ob eine genannte Datei oder
Funktion noch existiert; dieses Dokument beschreibt den Stand vom 6.11.2026.

Antworte auf Deutsch. Commits auf Deutsch, Betreffzeile knapp, Begründung im
Rumpf.
