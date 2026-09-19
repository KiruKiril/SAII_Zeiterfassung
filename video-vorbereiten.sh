#!/usr/bin/env bash
# Setzt die Demo auf einen sauberen Startzustand und prueft, dass alles laeuft.
set -uo pipefail
NS=ze-dev

echo "1/4  Cluster pruefen"
kubectl -n $NS get pods --no-headers 2>/dev/null || { echo "  Pod laeuft nicht. minikube start?"; exit 1; }

echo "2/4  Alte Demo-Daten entfernen"
kubectl -n $NS exec deploy/zeiterfassung -- sh -c 'rm -f /data/times.jsonl' 2>/dev/null \
  && echo "  Datenstand geleert" || echo "  konnte Daten nicht leeren"

echo "3/4  Port-Forward auf 8080"
if curl -sf -o /dev/null http://localhost:8080/login 2>/dev/null; then
  echo "  laeuft bereits"
else
  lsof -ti:8080 2>/dev/null | xargs -r kill 2>/dev/null; sleep 2
  nohup kubectl -n $NS port-forward --address 127.0.0.1 svc/zeiterfassung 8080:80 \
    > /tmp/ze-portforward.log 2>&1 &
  sleep 5
  curl -sf -o /dev/null http://localhost:8080/login && echo "  gestartet" || {
    echo "  fehlgeschlagen, siehe /tmp/ze-portforward.log"; exit 1; }
fi

echo "4/4  Healthchecks"
printf '  /health  '; curl -s http://localhost:8080/health; echo
printf '  /ready   '; curl -s http://localhost:8080/ready; echo

cat <<'HINT'

Bereit. http://localhost:8080
  kiril / geheim123  (admin)
  anna  / anna123    (user)

Vor der Aufnahme: Mitteilungen stummschalten (Kontrollzentrum > Fokus > Nicht stoeren)
und andere Fenster schliessen.
HINT
