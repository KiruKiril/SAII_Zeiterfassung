#!/usr/bin/env bash
# Wandelt die Bildschirmaufnahme nach mp4 und prueft die Laenge.
#   ./video-fertigstellen.sh ~/Desktop/Bildschirmaufnahme.mov
set -euo pipefail
SRC="${1:?Aufruf: ./video-fertigstellen.sh <aufnahme.mov>}"
[ -f "$SRC" ] || { echo "Datei nicht gefunden: $SRC"; exit 1; }
OUT="$(dirname "$0")/Video_Zeiterfassung.mp4"

DAUER=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$SRC" | cut -d. -f1)
echo "Laenge der Aufnahme: $((DAUER/60)) min $((DAUER%60)) s"
if [ "$DAUER" -gt 150 ]; then
  echo "ACHTUNG: laenger als 2.5 Minuten (150 s). Bitte vorher in QuickTime kuerzen (Cmd+T)."
  exit 1
fi

echo "Wandle nach mp4 ..."
ffmpeg -loglevel error -y -i "$SRC" -vcodec h264 -acodec aac -movflags +faststart "$OUT"
echo "Fertig: $OUT  ($(du -h "$OUT" | cut -f1))"
echo "Jetzt ./make-abgabe.sh ausfuehren - das Video wird dann ins ZIP gepackt."
