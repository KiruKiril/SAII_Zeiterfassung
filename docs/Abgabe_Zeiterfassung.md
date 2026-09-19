# Zeiterfassung – SAII Tag 4/5

**Kiril Rothacher** · Klasse 26A, Gruppe 3 · 19.09.2026
Repository: `zeiterfassung/` · Image: `zeiterfassung:1.0`

---

## 1. SOLL – was ich machen will

Ein containerisierter Zeiterfassungs-Service, der auf Kubernetes läuft und
Arbeitszeiten auch dann behält, wenn Kubernetes den Pod ersetzt.

**Funktionsumfang**

| Bereich | Umsetzung |
|---|---|
| Stempeln | `EIN → PAUSE → ZURÜCK → AUS` als Zustandsautomat im Server erzwungen |
| Notiz | Freitext pro Stempelung (z.B. „Support KYZ Kunde Meyer"), max. 200 Zeichen |
| Übersicht | Aktueller Status, heute erfasste Zeit, letzte 15 Stempelungen |
| Zeitzone | Speicherung in UTC, Anzeige und Eingabe in Ortszeit (`Europe/Zurich`) |
| Benutzer | Login mit Rollen `user` / `admin` |
| Admin-Ansicht | Filter nach Datum, Benutzer, Aktion und Notiztext; erfasste Zeit je Benutzer im Zeitraum; Einträge korrigieren, entfernen und für andere nachtragen |
| Persistenz | Append-only JSONL unter `/data/times.jsonl` auf einem PVC |
| Health | Getrennte Endpunkte `/health` (Liveness) und `/ready` (Readiness) |
| Umgebungen | Kustomize `base` + Overlays `dev` und `prod` |

**Architektur**

```
Browser ──HTTP──> Service ──> Pod: gunicorn + Flask (UID 10001, read-only rootfs)
                                    │
                                    └── volumeMount /data ──> PVC zeiterfassung-data
```

Die Anwendung ist bewusst zustandslos im Prozess: der komplette Zustand wird
aus `/data/times.jsonl` rekonstruiert. Ein neuer Pod liest die Datei und zeigt
sofort wieder den korrekten Status. Genau das macht den PVC überprüfbar.

**Dev vs. Prod** (bewusste Unterschiede, in den Overlays isoliert)

| | Dev | Prod |
|---|---|---|
| Replicas | 1 | 3 |
| Service | NodePort 30080 | ClusterIP |
| Image | lokal `zeiterfassung:1.0` | `registry.hfi.local/saii/zeiterfassung:1.0` |
| Namespace | `ze-dev` | `ze-prod` |
| Zusätzlich | – | NetworkPolicy, `imagePullPolicy: Always`, höhere Limits |

**Abgrenzung** – bewusst nicht umgesetzt: verteilte Datenbank, TLS-Terminierung
im Cluster (gehört an den Ingress), Reporting/Export, Zeitzonenlogik
(alles UTC).

---

## 2. Security-Anforderungen

Jede Anforderung mit Umsetzung und Nachweis.

### 2.1 Container und Laufzeit

| Anforderung | Umsetzung | Nachweis |
|---|---|---|
| Kein Root im Container | `useradd --uid 10001`, `USER 10001:10001`; im Pod zusätzlich `runAsNonRoot: true` | `docker exec ze-test id` → `uid=10001` |
| Kein Privilege Escalation | `allowPrivilegeEscalation: false` | Deployment-Manifest |
| Minimale Rechte | `capabilities.drop: ["ALL"]`, `seccompProfile: RuntimeDefault` | Deployment-Manifest |
| Unveränderliches Dateisystem | `readOnlyRootFilesystem: true`; Schreibpfade nur `/data` (PVC) und `/tmp` (emptyDir) | Deployment-Manifest |
| Kein Entwicklungsserver | `gunicorn` statt `flask run`; `debug` nie aktiviert | Dockerfile `CMD` |
| Kleine Angriffsfläche | Multi-Stage-Build auf `python:3.12-slim`, Build-Tools landen nicht im Runtime-Image | Dockerfile |
| Ressourcengrenzen | `requests`/`limits` für CPU und Memory → ein Pod kann den Node nicht aushungern | Deployment-Manifest |

### 2.2 Authentifizierung und Autorisierung

| Anforderung | Umsetzung |
|---|---|
| Keine Klartext-Passwörter | PBKDF2-SHA256, 240 000 Iterationen, 16 Byte Salt pro Benutzer |
| Kein Timing-Leak | Vergleich über `hmac.compare_digest` |
| Keine Benutzer-Enumeration | Login-Fehler immer identisch („Login fehlgeschlagen.") |
| Brute-Force-Bremse | Max. 5 Fehlversuche pro IP und Minute, danach HTTP 429 |
| RBAC | Rolle `admin` erforderlich für `/admin` sowie für Korrigieren, Entfernen und Nachtragen; `user` sieht ausschliesslich eigene Einträge und kann nichts Fremdes ändern |
| Session-Schutz | Cookie `HttpOnly`, `SameSite=Strict`, in Prod zusätzlich `Secure`; `SECRET_KEY` aus Secret |

### 2.3 Eingaben und Ausgaben

| Anforderung | Umsetzung |
|---|---|
| CSRF-Schutz | Session-gebundenes Token in jedem mutierenden Formular, Prüfung mit `compare_digest` → sonst 403 |
| Nur erlaubte Aktionen | Whitelist `EIN/PAUSE/ZURUECK/AUS` → sonst 400 |
| Kein unplausibler Zustand | Übergangstabelle serverseitig; z.B. zweimal `EIN` → 409 statt stiller Doppelbuchung |
| XSS | Jinja2-Autoescaping, Notiz zusätzlich auf druckbare Zeichen und 200 Zeichen begrenzt |
| Request-Grösse | `MAX_CONTENT_LENGTH = 16 KiB` |
| Filterwerte geprüft | Nur bekannte Filterfelder werden gelesen, Datum gegen `YYYY-MM-DD` und Aktion gegen die Whitelist validiert – ungültige Werte werden verworfen, nicht weitergereicht |
| Keine offene Weiterleitung | Nach dem Speichern wird das Ziel aus geprüften Einzelwerten neu gebaut, nie aus einer mitgegebenen URL |
| Sicherheitsheader | `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, CSP `default-src 'self'` |
| Kein JavaScript nötig | Die Oberfläche kommt ohne Skripte aus; die CSP bleibt streng, statt für eine Rückfrage `'unsafe-inline'` zu erlauben |
| Kein Zwischenspeichern | `Cache-Control: no-store` – nach dem Abmelden bleibt keine Seite mit Daten im Browser-Verlauf |

### 2.4 Secrets und Netzwerk

| Anforderung | Umsetzung |
|---|---|
| Keine Secrets im Image | Weder `SECRET_KEY` noch Benutzer sind im Image; beides kommt über `secretKeyRef` |
| Keine Secrets im Git | `k8s/make-secret.sh` erzeugt das Secret zur Laufzeit; im Repo liegt nur `secret.example.yaml` mit Platzhaltern |
| Kein unsicherer Default in Prod | Fehlt `SECRET_KEY` bei `ZE_ENV=prod`, startet die App gar nicht |
| Begrenzte Exposition | Prod nutzt ClusterIP statt NodePort; NetworkPolicy lässt nur den Ingress-Namespace auf Port 8080 |

### 2.5 Datenintegrität

Schreibvorgänge sind append-only und laufen über `flock` (exklusiv) plus
`fsync`. Damit kann ein `SIGKILL` mitten im Schreiben keine halbe Zeile
hinterlassen, und parallele gunicorn-Worker überschreiben sich nicht.
Defekte Zeilen werden beim Lesen übersprungen statt die App zum Absturz
zu bringen – eine kaputte Zeile darf nicht die ganze Zeiterfassung blockieren.

Auch Korrekturen durch den Admin überschreiben nichts. Eine Änderung wird als
eigener Datensatz (`type: correction`) angehängt und erst beim Lesen auf den
Originaleintrag angewendet; ein Entfernen ist ein `type: delete`-Datensatz.
Ein vom Admin nachgetragener Eintrag trägt `created_by` und wird in der Liste
als Nachtrag ausgewiesen – so bleibt unterscheidbar, was der Mitarbeitende
selbst gestempelt hat und was jemand für ihn eingetragen hat.
Damit bleibt jede Arbeitszeit-Änderung nachvollziehbar – wer sie wann gemacht
hat, steht im Log und wird in der Admin-Ansicht angezeigt. Das ist bei
Arbeitszeiten kein Detail, sondern die Voraussetzung dafür, dass die Erfassung
überhaupt belastbar ist.

---

## 3. Healthchecks

Drei Probes mit klar getrennten Aufgaben:

| Probe | Endpunkt | Prüft | Reaktion bei Fehler |
|---|---|---|---|
| `startupProbe` | `/health` | Prozess ist hochgefahren | Bis zu 30 s Anlaufzeit, erst danach wird Liveness scharf |
| `livenessProbe` | `/health` | Prozess reagiert überhaupt | Pod-Neustart nach 3 Fehlversuchen |
| `readinessProbe` | `/ready` | `/data` ist wirklich beschreibbar | Pod aus dem Service genommen, **kein** Neustart |

**Warum zwei getrennte Endpunkte?**

`/health` macht bewusst **kein** I/O und antwortet immer 200, solange der
Prozess lebt. `/ready` schreibt und löscht testweise `/data/.ready` und
liefert 503, wenn das scheitert.

Der Unterschied ist entscheidend: Wäre die Liveness-Probe an das Volume
gekoppelt, würde ein volles oder falsch berechtigtes PVC den Pod in einen
CrashLoopBackOff treiben – Kubernetes würde endlos neu starten, obwohl ein
Neustart das Speicherproblem nicht löst. So bleibt der Pod am Leben,
verschwindet aber aus dem Service, und `kubectl describe` zeigt die echte
Ursache. Genau das Fehlerbild aus der Übung
(`ERROR: Permission denied: /data/times.jsonl`) wird damit diagnostizierbar
statt zur Neustartschleife.

`startupProbe` entkoppelt die Anlaufzeit von der Überwachung: langsamer Start
führt nicht zu einem Neustart, ein späteres Hängen aber sehr wohl.

**Rollout-Strategie** – Das Deployment nutzt `strategy: Recreate`. Der PVC ist
`ReadWriteOnce`; bei einem RollingUpdate würde der neue Pod auf den Claim
warten, den der alte noch hält, und der Rollout bliebe hängen.

---

## 4. Nachweis

**Automatisierte Tests** – `python3 app/test_app.py`, 128 Tests, 0 Fehler:
Health/Ready, Login inkl. Fehlversuch, CSRF-Ablehnung, alle vier Übergänge,
unerlaubter Doppelübergang (409), unbekannte Aktion (400), JSONL-Persistenz,
XSS-Escaping, Längenbegrenzung, RBAC (user → 403, admin → 200),
Sicherheitsheader, `/ready` → 503 bei kaputtem Datenpfad bei gleichzeitig
weiterhin gesundem `/health`, Admin-Korrekturen inklusive Nachweis, dass das
Log wächst statt überschrieben zu werden, Nachträge inklusive Kennzeichnung,
sowie alle Filter einzeln und kombiniert.

Mehrere Fehler wurden durch Tests und einen Durchlauf im echten Browser
aufgedeckt und behoben. Erstens führte ein
`GET` auf eine reine `POST`-Route – etwa nach *Zurück* oder *Neu laden* im
Browser – zu einer nackten `405`-Seite ohne Rückweg; jetzt erscheint eine
Seite mit Link zurück. Zweitens verschluckte die Tagessumme Zeit, wenn zweimal
`EIN` ohne Ende dazwischen im Log stand: der laufende Startzeitpunkt wurde
überschrieben statt das offene Intervall zu schliessen. Genau das kann durch
einen Nachtrag entstehen, und die korrigierte Zeit erschien dann nicht in
„heute erfasst".

Drittens stand in der Admin-Liste eine Schaltfläche innerhalb eines Links
(`<a><button></a>`) – ungültiges HTML, das Safari beim Aufbau des DOM umbaut,
sodass „Löschen" als `GET` statt als `POST` hinausging und wirkungslos blieb.
Viertens war die Rückfrage vor dem Löschen als `onsubmit`-Attribut umgesetzt
und wurde von der eigenen Content-Security-Policy blockiert; sie erschien nie.
Beides ist ersetzt: Links sind echte Links, und die Rückfrage ist eine eigene
Seite ohne JavaScript. Fünftens wurden Seiten zwischengespeichert, sodass der
Zurück-Knopf einen veralteten Stand mit falschen Schaltflächen zeigte – ein
Klick darauf endete in einer nackten Fehlerseite. Seiten werden jetzt mit
`Cache-Control: no-store` ausgeliefert, und alle Fehlerfälle (400, 403, 404,
405, 409) erklären den Grund und bieten einen Rückweg an.

**Persistenz-Nachweis** – Container mit Volume gestartet, drei Stempelungen
erzeugt, Container mit `docker rm -f` vollständig zerstört, neuer Container auf
demselben Volume gestartet: alle drei Zeilen vorhanden, Status korrekt als
„arbeitet" rekonstruiert.

**Manifeste** – `kubectl kustomize k8s/overlays/dev` und `.../prod` rendern
fehlerfrei und unterscheiden sich in Replicas, Service-Typ, Image und
Namespace wie geplant.

---

## 5. Bekannte Grenzen

Ehrlich benannt, statt sie zu verstecken:

1. **`ReadWriteOnce` mit 3 Replicas in Prod** ist nur auf einem Single-Node-
   Cluster wie Minikube tragfähig. Sauber wäre ein `ReadWriteMany`-Volume
   oder – besser – eine echte Datenbank statt einer Datei.
2. **JSONL ist keine Datenbank.** Für den Kursumfang passend, aber ohne
   Indizes und Transaktionen; bei vielen Mitarbeitenden wird das Lesen linear teuer.
3. **Zeitzone ist fest auf `Europe/Zurich`.** Für einen Betrieb über mehrere
   Länder müsste sie pro Benutzer hinterlegt werden.
4. **Kein TLS im Cluster.** Verschlüsselung gehört an den Ingress; deshalb ist
   `SESSION_COOKIE_SECURE` in Prod aktiv und setzt HTTPS davor voraus.
5. **Login-Bremse ist prozesslokal.** Bei mehreren Replicas zählt jeder Pod
   eigene Fehlversuche; produktiv gehörte das in einen gemeinsamen Speicher.
6. **Nachträge prüfen die Reihenfolge nicht.** Ein Admin kann bewusst ein
   zweites `EIN` einfügen, ohne dass der Zustandsautomat das verhindert – sonst
   liesse sich eine kaputte Folge gar nicht erst reparieren. Der Status wird
   weiterhin aus dem jüngsten Eintrag abgeleitet, eine inhaltliche Plausibilitäts-
   prüfung über den ganzen Tag gibt es nicht.
