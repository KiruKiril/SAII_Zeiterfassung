# Zeiterfassung – SAII Tag 4/5

**Kiril Rothacher** · Klasse 26A, Gruppe 3

Flask-Zeiterfassung mit `EIN / PAUSE / ZURÜCK / AUS`, Persistenz über ein
PersistentVolumeClaim, getrennten Healthchecks, Login mit Rollen und
Kustomize-Overlays für dev und prod.

---

## Für die Bewertung: in einem Befehl starten

Voraussetzung ist nur Docker. Im entpackten Ordner:

```bash
docker compose up --build
```

Dann **http://localhost:8080** im Browser öffnen.

| Benutzer | Passwort | Rolle |
|---|---|---|
| `kiril` | `geheim123` | admin (sieht alle Mitarbeitenden, kann Eintraege korrigieren) |
| `anna` | `anna123` | user (sieht nur eigene Einträge) |

Beenden mit `docker compose down`. Die Daten bleiben im benannten Volume;
mit `docker compose down -v` wird auch das gelöscht.

### Persistenz ohne Kubernetes prüfen

```bash
# Stempelung im Browser erzeugen, dann:
docker compose down          # Container komplett weg
docker compose up -d         # neuer Container, gleiches Volume
```

Die Stempelungen sind nach dem Neustart noch da.

---

## Was wo liegt

| Pfad | Inhalt |
|---|---|
| `Abgabe_Zeiterfassung.docx` | Das Abgabe-Dokument: SOLL, Security-Anforderungen, Healthchecks |
| `app/` | `app.py`, `Dockerfile`, `requirements.txt`, `hashpw.py`, `test_app.py` |
| `k8s/base/` | `deployment.yaml`, `service.yaml`, `pvc.yaml`, `kustomization.yaml` |
| `k8s/overlays/dev/` | 1 Replica, NodePort 30080, lokales Image, Namespace `ze-dev` |
| `k8s/overlays/prod/` | 3 Replicas, ClusterIP, Registry-Image, NetworkPolicy, Namespace `ze-prod` |
| `k8s/make-secret.sh` | Erzeugt das Secret im Cluster – es liegt bewusst nicht im Repo |
| `docs/Video_Drehbuch.md` | Ablauf des Demo-Videos |
| `docker-compose.yml` | Schnellstart ohne Kubernetes |

---

## Auf Kubernetes (so wurde es entwickelt und geprüft)

```bash
minikube start --driver=docker
docker build -t zeiterfassung:1.0 app/
minikube image load zeiterfassung:1.0
./k8s/make-secret.sh ze-dev "kiril:geheim123:admin" "anna:anna123:user"
kubectl apply -k k8s/overlays/dev
kubectl -n ze-dev rollout status deploy/zeiterfassung
kubectl -n ze-dev port-forward svc/zeiterfassung 8080:80
```

### Persistenz im Cluster prüfen

```bash
kubectl -n ze-dev delete pod -l app=zeiterfassung   # Pod loeschen
kubectl -n ze-dev get pods                          # neuer Pod-Name
kubectl -n ze-dev exec deploy/zeiterfassung -- cat /data/times.jsonl
```

Die Datei ist unverändert – das ist der PVC.

### Prod-Overlay prüfen

```bash
kubectl kustomize k8s/overlays/prod
kubectl create namespace ze-prod
kubectl apply -k k8s/overlays/prod --dry-run=server
```

---

## Tests

```bash
python3 -m venv .venv && .venv/bin/pip install -r app/requirements.txt
.venv/bin/python app/test_app.py
```

47 Tests: Health/Ready, Login inkl. Fehlversuch, CSRF-Ablehnung, alle vier
Zustandsübergänge, unerlaubter Doppelübergang (409), unbekannte Aktion (400),
JSONL-Persistenz, XSS-Escaping, Längenbegrenzung, RBAC (user → 403,
admin → 200), Sicherheitsheader, `/ready` → 503 bei kaputtem Datenpfad bei
gleichzeitig gesundem `/health`, Admin-Korrekturen und -Loeschungen.

## Korrigieren als Admin

Als `kiril` unter „Alle Mitarbeitenden ansehen" hat jeder Eintrag
**Bearbeiten** und **Loeschen**. Beides ueberschreibt nichts: die Aenderung
wird als Korrektur-Datensatz angehaengt und erst beim Lesen angewendet. In der
Admin-Liste steht danach, wer wann korrigiert hat. Das Log bleibt damit
vollstaendig und die Arbeitszeit-Aenderung nachvollziehbar.

---

## Healthchecks

| Endpunkt | Zweck | Verhalten |
|---|---|---|
| `/health` | Liveness | Kein I/O, 200 solange der Prozess lebt |
| `/ready` | Readiness | Schreibt testweise nach `/data`, 503 wenn das scheitert |

Getrennt, damit ein volles oder falsch berechtigtes Volume den Pod nicht in
einen CrashLoopBackOff schickt, sondern nur aus dem Service nimmt.

---

## Hinweis zu den Zugangsdaten

Passwörter stehen nirgends im Klartext – weder im Image noch in
`docker-compose.yml`, dort liegen nur PBKDF2-SHA256-Hashes. Die Werte in
`docker-compose.yml` sind Demo-Werte für die Bewertung; produktiv kommen
`SECRET_KEY` und `ZE_USERS` aus einem Kubernetes-Secret, das
`k8s/make-secret.sh` zur Laufzeit erzeugt. `k8s/secret.example.yaml` zeigt nur
die Struktur mit Platzhaltern.
