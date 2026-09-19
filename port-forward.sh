#!/usr/bin/env bash
# Haelt den Zugang auf http://localhost:8080 offen.
#
# kubectl port-forward bricht regelmaessig ab: bei jedem Pod-Wechsel, bei
# Leerlauf und bei einer abgerissenen Verbindung ("lost connection to pod").
# Die Anwendung im Cluster laeuft dabei weiter - nur der Tunnel ist weg.
# Diese Wache startet ihn automatisch neu.
#
#   ./port-forward.sh          im Vordergrund (Ctrl-C beendet)
#   ./port-forward.sh start    im Hintergrund
#   ./port-forward.sh stop     beenden
#   ./port-forward.sh status   Zustand anzeigen
set -uo pipefail

NS=ze-dev
PORT=8080
LOG=/tmp/ze-portforward.log
PIDFILE=/tmp/ze-portforward.pid

wache() {
  echo "$$" > "$PIDFILE"
  trap 'rm -f "$PIDFILE"; exit 0' TERM INT
  local versuche=0
  while true; do
    kubectl -n "$NS" port-forward --address 127.0.0.1 svc/zeiterfassung "$PORT:80" >>"$LOG" 2>&1
    versuche=$((versuche + 1))
    echo "$(date '+%H:%M:%S') Tunnel abgerissen (#$versuche), starte neu ..." >> "$LOG"
    sleep 2
  done
}

case "${1:-fg}" in
  stop)
    if [ -f "$PIDFILE" ]; then
      kill "$(cat "$PIDFILE")" 2>/dev/null
      rm -f "$PIDFILE"
    fi
    pkill -f "port-forward --address 127.0.0.1 svc/zeiterfassung" 2>/dev/null
    echo "Port-Forward beendet."
    ;;
  status)
    if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
      echo "Wache laeuft (PID $(cat "$PIDFILE"))"
    else
      echo "Wache laeuft nicht"
    fi
    printf "http://localhost:%s -> " "$PORT"
    curl -s -o /dev/null -w "HTTP %{http_code}\n" --max-time 3 "http://localhost:$PORT/login"
    echo "Neustarts bisher: $(grep -c 'Tunnel abgerissen' "$LOG" 2>/dev/null || echo 0)"
    ;;
  start)
    "$0" stop >/dev/null 2>&1
    sleep 1
    nohup "$0" fg >>"$LOG" 2>&1 &
    sleep 4
    "$0" status
    ;;
  fg)
    "$0" stop >/dev/null 2>&1
    sleep 1
    echo "Port-Forward-Wache laeuft. http://localhost:$PORT  (Ctrl-C beendet)"
    wache
    ;;
  *)
    echo "Aufruf: $0 [start|stop|status]"; exit 1 ;;
esac
