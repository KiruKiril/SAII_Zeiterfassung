# Projektverlauf

Chronologie der Arbeit an der Zeiterfassung, 19. September 2026, in einer
Sitzung mit Claude Code. Zweck dieser Datei: nachvollziehbar machen, *warum*
der Code so aussieht, wie er aussieht — besonders die Stellen, die auf den
ersten Blick umständlich wirken.

Der Kurs sah den Hermes Agent mit lokalem Ollama-Modell vor. Verwendet wurde
Claude Code; das Vorgehen blieb dasselbe: planen, prüfen, umsetzen, nachweisen.

---

## 1. Auftrag verstehen

Das PDF `SAII_Tag4_final (1).pdf` (35 Seiten) enthält zwei Aufträge: einen
Gruppenauftrag zum Kubernetes-Troubleshooting und den Einzelauftrag
„VibeCode the World". Dieses Repo deckt den **Einzelauftrag** ab.

Mindestanforderungen laut Folie 35: Security-Überlegungen, automatische
Healthchecks, Ein- und Ausstempeln. Freiwillig: RBAC und eine Notiz pro
Stempelung — beides wurde umgesetzt.

## 2. Grundgerüst

Flask-Anwendung in einer Datei, bewusst ohne Datenbank:

- Zustandsautomat `EIN → PAUSE → ZURÜCK → AUS`, serverseitig erzwungen
- Append-only JSONL unter `/data`, mit `flock` und `fsync`
- `/health` und `/ready` von Anfang an getrennt
- Login mit PBKDF2-Hashes, CSRF-Token, Rollen `user` und `admin`
- Dockerfile: Multi-Stage, Non-Root (UID 10001), read-only Rootfs, gunicorn
- Kustomize: `base` plus Overlays `dev` und `prod`

Die erste Testrunde umfasste 26 Tests. Persistenz wurde nicht behauptet,
sondern gezeigt: Container zerstört, neuer Container auf demselben Volume,
Daten unverändert.

## 3. Auf Kubernetes gebracht

minikube installiert, Image geladen, Secret zur Laufzeit erzeugt, `dev`-Overlay
angewendet. Der entscheidende Nachweis:

```
kubectl -n ze-dev delete pod -l app=zeiterfassung
# neuer Pod …-rlhv7 statt …-jcbnh, /data/times.jsonl unverändert
```

Das `prod`-Overlay wurde serverseitig validiert (`--dry-run=server`), aber nie
wirklich deployt — es zeigt auf eine Registry, die es im Labor nicht gibt.

## 4. Abgabe-Paket

Damit die Lehrperson nichts installieren muss, kam ein `docker-compose.yml`
dazu: ein Befehl, keine Kubernetes-Kenntnisse nötig. Das Abgabe-ZIP wird von
`make-abgabe.sh` gebaut und wurde jedes Mal in einem fremden Verzeichnis
entpackt und dort gestartet — nicht nur gepackt und gehofft.

**Stolperstein:** Docker Compose interpretiert `$` in Umgebungsvariablen. Die
PBKDF2-Hashes enthalten `$`, also mussten sie als `$$` geschrieben werden.
Derselbe Fehlertyp war vorher schon in zsh aufgetreten (`$H:a` wird als
History-Modifier gelesen). Beide Male fiel es nur auf, weil der Login danach
wirklich ausprobiert wurde.

## 5. Erweiterungen

Auf Zuruf kamen dazu:

- **Korrigieren und Löschen** durch den Admin — als angehängte Datensätze,
  damit die append-only-Zusage aus dem Dokument gültig bleibt
- **Filter** in der Admin-Ansicht nach Datum, Benutzer, Aktion und Notiztext,
  mit Summen je Benutzer
- **Nachtragen** für andere Benutzer, etwa nach einer versehentlichen Löschung;
  solche Einträge sind als Nachtrag gekennzeichnet

## 6. Fehler, die beim Ausprobieren auftauchten

Dieser Abschnitt ist der nützlichste. Alle Fehler wurden zuerst reproduziert.

### Tagessumme verschluckte Stunden
Nach einer Korrektur der Startzeit änderte sich „heute erfasst" nicht. Ursache:
Stand zweimal `EIN` ohne Ende dazwischen im Log, überschrieb der zweite den
laufenden Startzeitpunkt — die Zeit dazwischen fiel weg. Genau diese Abfolge
entsteht durch einen Nachtrag. Das offene Intervall wird jetzt geschlossen,
statt den Start zu überschreiben.

### Alles lief in UTC
Die Uhr zeigte 17:00, die Anwendung 15:00. Gespeichert wird weiterhin UTC
(richtig so), angezeigt und eingegeben wird jetzt Ortszeit.

### Löschen tat nichts
Im Server-Log stand `GET /admin/loeschen/… 405`. Ursache: `<button>` innerhalb
eines `<a>` ist ungültiges HTML, Safari baut den DOM dabei um und schickte GET
statt POST. Ersetzt durch echte Links mit Schaltflächen-Optik.

### Keine Rückfrage vor dem Löschen
`onsubmit="return confirm(…)"` wurde von der eigenen CSP blockiert — im Browser
nachgemessen. Statt die CSP aufzuweichen, ist die Rückfrage jetzt eine eigene
Seite ohne JavaScript.

### Scheinbare Rauswürfe
Seiten wurden zwischengespeichert; nach dem Zurück-Knopf zeigte der Browser
einen veralteten Stand mit falschen Schaltflächen, ein Klick darauf endete in
einer nackten 409-Seite. Behoben mit `Cache-Control: no-store` und
verständlichen Fehlerseiten für 400, 403, 404, 405 und 409.

### „Die ganze Applikation läuft nicht mehr"
Das Pod-Log zeigte keinen einzigen Fehler. Abgestürzt war `kubectl port-forward`
(`lost connection to pod`). Die Anwendung lief unverändert weiter. Seitdem gibt
es `port-forward.sh` mit einer Wache, die den Tunnel nach einem Abriss in
wenigen Sekunden neu aufbaut — geprüft gegen Tunnel-Abschuss und Pod-Neustart.

**Lehre daraus:** Bei „nichts geht mehr" zuerst `kubectl get pods` und die Logs
ansehen. Dreimal war die Anwendung gesund und nur der Tunnel weg.

## 7. Stand am Ende

- **128 Tests, 0 Fehler** — auch aus dem entpackten Abgabe-ZIP heraus geprüft
- Im echten Browser durchgeklickt: als `anna` der volle Tagesablauf inklusive
  Zurück-Knopf, als `kiril` Filtern, Korrigieren, Nachtragen und Löschen
- Video 2:11, innerhalb des 2.5-Minuten-Limits, **ohne Ton**
- Abgabe-ZIP 7.3 MB mit Code, Manifesten, Dokument, Netzwerkplan und Video

## 8. Was offen blieb

- Monitoring (Namespace `platform` im Netzwerkplan) ist Konzept, nicht Code
- `ReadWriteOnce` mit 3 Replicas trägt nur auf einem Single-Node-Cluster;
  sauber wäre `ReadWriteMany` oder eine echte Datenbank
- Die Login-Bremse zählt pro Prozess, nicht clusterweit
- Kein TLS im Cluster — gehört an den Ingress
