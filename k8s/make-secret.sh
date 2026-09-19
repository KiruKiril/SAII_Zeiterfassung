#!/usr/bin/env bash
# Erzeugt das Secret zur Laufzeit im Cluster. Es liegt bewusst NICHT im Git-Repo.
#   Aufruf: ./k8s/make-secret.sh <namespace> <user>:<passwort>:<rolle> [weitere...]
set -euo pipefail

NS="${1:?Namespace fehlt, z.B. ze-dev}"; shift
[ $# -gt 0 ] || { echo "Mindestens ein User noetig: name:passwort:rolle"; exit 1; }

HASHPW="$(dirname "$0")/../app/hashpw.py"
ENTRIES=""
for spec in "$@"; do
  IFS=':' read -r name pass role <<< "$spec"
  hash="$(python3 "$HASHPW" "$pass")"
  ENTRIES="${ENTRIES:+$ENTRIES,}${name}:${hash}:${role}"
done

kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NS" create secret generic zeiterfassung-secret \
  --from-literal=SECRET_KEY="$(python3 -c 'import secrets;print(secrets.token_hex(32))')" \
  --from-literal=ZE_USERS="$ENTRIES" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "Secret 'zeiterfassung-secret' in Namespace '$NS' angelegt."
