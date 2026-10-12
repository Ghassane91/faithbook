#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

PATCH=${1:?Chemin du patch frontend requis}
COMMIT=${2:?SHA GitHub requis}
[[ $COMMIT =~ ^[0-9a-f]{40}$ ]] || { echo 'SHA GitHub invalide'; exit 1; }
[[ $EUID == 0 ]] || { echo 'Exécuter avec sudo'; exit 1; }
cd /opt/integrit/src/faithbook
git apply --check "$PATCH"
[[ ! -e frontend/src/huntx-theme.css && ! -e frontend/src/views/HuntxOverview.tsx ]]
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.override.yml)
IMAGE=$(docker inspect faithbook-frontend --format '{{.Config.Image}}')
BACKUP=$(mktemp -d /opt/integrit/backups/faithbook/frontend-huntx-20261012.XXXXXXXX)
ROLLBACK="faithbook-frontend-rollback:$(basename "$BACKUP")"
tar --exclude='frontend/node_modules' --exclude='frontend/dist' -czf "$BACKUP/frontend-before.tar.gz" frontend
tar -tzf "$BACKUP/frontend-before.tar.gz" >/dev/null
docker tag "$IMAGE" "$ROLLBACK"
cp "$PATCH" "$BACKUP/"
printf '%s\n' "$COMMIT" > "$BACKUP/github-commit.txt"
printf '%s\n' "$IMAGE" > "$BACKUP/image-name.txt"
applied=0
rollback() {
  local result=$?
  trap - ERR
  set +e
  if [[ $applied == 1 ]]; then
    tar -xzf "$BACKUP/frontend-before.tar.gz" frontend/src/App.tsx frontend/src/main.tsx
    rm -f -- frontend/src/huntx-theme.css frontend/src/views/HuntxOverview.tsx
    docker tag "$ROLLBACK" "$IMAGE"
    "${COMPOSE[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 180 frontend
  fi
  printf 'Déploiement interrompu. Sauvegarde : %s\n' "$BACKUP" >&2
  exit "$result"
}
trap rollback ERR
git apply "$PATCH"
applied=1
"${COMPOSE[@]}" build frontend
"${COMPOSE[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 180 frontend
docker exec faithbook-frontend wget -qO- http://127.0.0.1/ > "$BACKUP/index-deployed.html"
docker inspect faithbook-frontend --format '{{.State.Health.Status}}' | grep -Fx healthy
printf 'COMPLETE\n' > "$BACKUP/COMPLETE"
trap - ERR
printf 'Frontend HuntX déployé. GitHub : %s\nSauvegarde : %s\n' "$COMMIT" "$BACKUP"
