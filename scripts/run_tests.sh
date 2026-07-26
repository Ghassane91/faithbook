#!/usr/bin/env bash
# Lance la suite de tests contre le conteneur en cours d'execution.
#   bash scripts/run_tests.sh [port-interface]
# Les tests de tests/suspendu/ (Google Drive) ne sont pas joues : voir leur README.
set -u
export MSYS_NO_PATHCONV=1

FRONT_PORT="${1:-3000}"
CONTAINER="faithbook-backend"
FAILED=0

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
    echo "Le conteneur ${CONTAINER} ne tourne pas. Lancez : docker compose up -d"
    exit 1
fi

# Le smoke test a besoin de s'authentifier. On lui passe API_KEY si elle est
# definie, sinon SMOKE_PASSWORD (mot de passe du compte admin).
echo "=== 1/2 API de bout en bout via nginx (port ${FRONT_PORT}) ==="
if [ -z "${API_KEY:-}" ] && [ -z "${SMOKE_PASSWORD:-}" ]; then
    echo "  IGNORE : definir API_KEY ou SMOKE_PASSWORD pour lancer ce test."
    echo "           ex. SMOKE_PASSWORD='...' bash scripts/run_tests.sh"
else
    python scripts/smoke_test.py "http://localhost:${FRONT_PORT}" || FAILED=1
fi

echo
echo "=== 2/2 Interface web (port ${FRONT_PORT}) ==="
if ! docker ps --format '{{.Names}}' | grep -q '^faithbook-frontend$'; then
    echo "  IGNORE : le conteneur faithbook-frontend ne tourne pas."
else
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${FRONT_PORT}/")
    [ "$code" = "200" ] && echo "  OK  page servie ($code)" || { echo "  ECHEC page ($code)"; FAILED=1; }

    code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${FRONT_PORT}/api/health")
    [ "$code" = "200" ] && echo "  OK  API relayee par nginx ($code)" || { echo "  ECHEC relais API ($code)"; FAILED=1; }

    code=$(curl -s -o /dev/null -w '%{http_code}' "http://localhost:${FRONT_PORT}/historique")
    [ "$code" = "200" ] && echo "  OK  route profonde servie ($code)" || { echo "  ECHEC route profonde ($code)"; FAILED=1; }
fi

echo
if [ "${FAILED}" -eq 0 ]; then
    echo "SUITE COMPLETE : OK"
else
    echo "SUITE COMPLETE : DES TESTS ONT ECHOUE"
fi
exit "${FAILED}"
