# Video aufnehmen auf dem Mac

Ziel: max. 2.5 Minuten, Zeiterfassung vorführen.
Diese Datei ist nur für dich – sie wird nicht ins Abgabe-ZIP gepackt.

---

## 1. Vorbereiten

```bash
cd ~/git/hfi/SAII/SAII_Zeiterfassung
./video-vorbereiten.sh
```

Das leert die Demo-Daten, prüft Cluster und Port-Forward und zeigt die
Healthchecks. Danach:

- **Mitteilungen aus:** Kontrollzentrum (Menüleiste rechts) → Fokus → Nicht stören
- Andere Fenster und Tabs schliessen
- Zwei Fenster nebeneinander: **Browser** auf http://localhost:8080 und **Terminal**
- Einmal trocken durchgehen, bevor du aufnimmst

---

## 2. Aufnehmen

Drücke **Cmd + Shift + 5**. Unten erscheint eine Leiste.

1. **Optionen** anklicken
   - Unter *Mikrofon* dein Mikrofon auswählen – sonst hat das Video keinen Ton
   - *Sichern unter: Schreibtisch*
   - *Timer: Keiner*
2. Aufnahmemodus wählen: **Gesamten Bildschirm aufnehmen** (linkes Symbol) oder
   **Ausgewählten Bereich aufnehmen**, wenn du nur Browser + Terminal zeigen willst
3. **Aufnahme starten** klicken

**Beim ersten Mal** fragt macOS nach der Berechtigung:
Systemeinstellungen → Datenschutz & Sicherheit → Bildschirmaufnahme → Haken setzen.
Danach die Aufnahme neu starten.

**Beenden:** Stopp-Symbol in der Menüleiste oben rechts, oder **Cmd + Ctrl + Esc**.
Die Datei landet als `.mov` auf dem Schreibtisch.

---

## 3. Was du zeigst

Der genaue Ablauf mit Zeitmarken steht in `docs/Video_Drehbuch.md`.
Kurzfassung:

| Zeit | Inhalt |
|---|---|
| 0:00–0:20 | `kubectl -n ze-dev get pods,svc,pvc` – es läuft auf Kubernetes |
| 0:20–1:10 | Login, `EIN → PAUSE → ZURÜCK → AUS` mit Notiz durchklicken |
| 1:10–1:50 | Admin: filtern, Eintrag korrigieren, Eintrag nachtragen |
| 1:50–2:10 | `/health` und `/ready` zeigen, Unterschied erklären |
| 2:10–2:30 | Pod löschen, neuer Pod, Daten noch da → PVC |

---

## 4. Kürzen, falls zu lang

QuickTime Player öffnen (Doppelklick auf die `.mov`), dann **Cmd + T**.
Die gelben Griffe links und rechts ziehen, **Trimmen** klicken, **Cmd + S** sichern.

---

## 5. Umwandeln und ins ZIP packen

```bash
./video-fertigstellen.sh ~/Desktop/Bildschirmaufnahme.mov
./make-abgabe.sh
```

Das erste Skript prüft die Länge (bricht ab, wenn über 150 Sekunden), wandelt
nach `Video_Zeiterfassung.mp4` und legt es im Projektordner ab. Das zweite baut
das Abgabe-ZIP neu – diesmal mit Video.

Den echten Dateinamen der Aufnahme findest du mit:

```bash
ls -t ~/Desktop/*.mov | head -1
```
