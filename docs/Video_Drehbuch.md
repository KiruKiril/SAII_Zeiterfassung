# Drehbuch Video (max. 2.5 Minuten)

> Die Kubernetes-Demo laeuft bereits. Falls der Port-Forward abgebrochen ist:
> `kubectl -n ze-dev port-forward svc/zeiterfassung 8080:80`
> Alternativ ohne Kubernetes: `docker compose up -d` (dann entfallen die kubectl-Teile).

Vorbereitung – in einem Terminal laufen lassen:

```bash
kubectl -n ze-dev port-forward svc/zeiterfassung 8080:80
```

---

**0:00–0:20 — Es läuft auf Kubernetes**

```bash
kubectl -n ze-dev get pods,svc,pvc
```

Sagen: „Ein Pod läuft, Service als NodePort, PVC ist Bound – der Speicher
ist also wirklich vergeben."

---

**0:20–1:10 — Durchklicken im Browser** (http://localhost:8080)

1. Login als `kiril` / `geheim123`
2. Status ist „ausgestempelt", es wird nur **Einstempeln** angeboten
   → sagen: „Der Server erlaubt nur gültige Übergänge, nicht das Frontend."
3. Notiz „Support KYZ Kunde Meyer" eintragen, **Einstempeln**
4. Status wechselt auf „arbeitet", Buttons wechseln auf Pause / Ausstempeln
5. **Pause** → **Zurück** → **Ausstempeln** durchklicken
6. Tabelle mit allen vier Stempelungen zeigen

---

**1:10–1:40 — Rollen (RBAC) und Korrigieren**

„Alle Mitarbeitenden ansehen" öffnen → Admin sieht alle Benutzer.
Bei einem Eintrag auf **Bearbeiten**, Notiz oder Zeit ändern, speichern.
In der Liste steht danach „korrigiert von kiril am …".

Sagen: „Die Korrektur überschreibt nichts – sie wird als eigener Datensatz
angehängt. Wer wann was geändert hat, bleibt im Log nachvollziehbar."
Kurz erwähnen: als `anna` (Rolle user) gibt es diesen Link nicht, und der
direkte Aufruf von `/admin` gibt 403.

---

**1:30–2:00 — Healthchecks**

```bash
curl -s localhost:8080/health; echo
curl -s localhost:8080/ready; echo
kubectl -n ze-dev describe pod -l app=zeiterfassung | grep -A1 -E "Liveness|Readiness|Startup"
```

Sagen: „`/health` prüft nur, ob der Prozess lebt. `/ready` schreibt testweise
nach /data. Getrennt, damit ein volles Volume den Pod nicht in einen
CrashLoopBackOff schickt, sondern nur aus dem Service nimmt."

---

**2:00–2:30 — Persistenz beweisen**

```bash
kubectl -n ze-dev delete pod -l app=zeiterfassung
kubectl -n ze-dev get pods          # neuer Pod-Name
```

Browser neu laden → Stempelungen sind noch da.

Sagen: „Pod gelöscht, Kubernetes hat einen neuen gestartet – anderer Name,
gleiche Daten. Das ist der PVC."
