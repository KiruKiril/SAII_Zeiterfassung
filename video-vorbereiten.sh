#!/usr/bin/env bash
# Setzt die Demo auf einen sauberen Startzustand und prueft, dass alles laeuft.
set -uo pipefail
NS=ze-dev

echo "1/4  Cluster pruefen"
kubectl -n $NS get pods --no-headers 2>/dev/null || { echo "  Pod laeuft nicht. minikube start?"; exit 1; }

echo "2/4  Alte Demo-Daten entfernen"
kubectl -n $NS exec deploy/zeiterfassung -- sh -c 'rm -f /data/times.jsonl' 2>/dev/null \
  && echo "  Datenstand geleert" || echo "  konnte Daten nicht leeren"

echo "3/4  Port-Forward-Wache starten"
# Nicht direkt kubectl port-forward: das bricht bei Pod-Wechsel und Leerlauf ab.
# Die Wache startet den Tunnel automatisch neu.
"$(dirname "$0")/port-forward.sh" start | sed 's/^/  /' || {
  echo "  fehlgeschlagen, siehe /tmp/ze-portforward.log"; exit 1; }

echo "4/4  Healthchecks"
printf '  /health  '; curl -s http://localhost:8080/health; echo
printf '  /ready   '; curl -s http://localhost:8080/ready; echo

cat <<'HINT'

Bereit. http://localhost:8080
  kiril / geheim123  (admin)
  anna  / anna123    (user)

Vor der Aufnahme: Mitteilungen stummschalten (Kontrollzentrum > Fokus > Nicht stoeren)
und andere Fenster schliessen.

Falls die Seite waehrend der Aufnahme doch einmal haengt: kurz warten und neu
laden - die Wache stellt den Tunnel innerhalb weniger Sekunden wieder her.
Zustand pruefen mit ./port-forward.sh status
HINT
