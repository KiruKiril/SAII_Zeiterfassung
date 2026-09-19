#!/usr/bin/env bash
# Baut das Abgabe-ZIP. Video vorher als Video_Zeiterfassung.mp4 hier ablegen.
set -euo pipefail
cd "$(dirname "$0")"

NAME="SAII_Zeiterfassung_Kiril_Rothacher"
STAGE="$(mktemp -d)/$NAME"
mkdir -p "$STAGE"

cp -R app k8s docs docker-compose.yml README.md "$STAGE/"
cp docs/Abgabe_Zeiterfassung.docx "$STAGE/"          # zusaetzlich nach oben
rm -f "$STAGE/docs/Abgabe_Zeiterfassung.docx"

# Ballast raus
rm -rf "$STAGE/app/__pycache__" "$STAGE/docs/Abgabe_Zeiterfassung.md"
find "$STAGE" -name '.DS_Store' -delete

if [ -f Video_Zeiterfassung.mp4 ]; then
  cp Video_Zeiterfassung.mp4 "$STAGE/"
  echo "Video eingepackt."
else
  echo "HINWEIS: Video_Zeiterfassung.mp4 nicht gefunden - ZIP ohne Video."
fi

rm -f "$NAME.zip"
(cd "$(dirname "$STAGE")" && zip -qr - "$NAME") > "$NAME.zip"
rm -rf "$(dirname "$STAGE")"

echo ""
echo "Fertig: $(pwd)/$NAME.zip  ($(du -h "$NAME.zip" | cut -f1))"
unzip -l "$NAME.zip" | tail -n +4 | head -30
