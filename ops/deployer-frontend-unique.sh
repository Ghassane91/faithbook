#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
PATCH=${1:?Frontend patch required}
COMMIT=${2:?GitHub SHA required}
[[ $EUID == 0 && $COMMIT =~ ^[0-9a-f]{40}$ ]]
REPO=/opt/integrit/src/faithbook
CADDYFILE=/opt/integrit/02-infra/Caddyfile
cd "$REPO"
git apply --check "$PATCH"
CADDY_VERSION=$(docker exec caddy caddy version)
[[ $CADDY_VERSION =~ ^v2\.([0-9]+)\. ]]
(( ${BASH_REMATCH[1]} >= 11 ))
BACKUP=$(mktemp -d /opt/integrit/backups/faithbook/frontend-unique-20261012.XXXXXXXX)
tar --exclude='frontend/node_modules' --exclude='frontend/dist' -czf "$BACKUP/frontend.before.tar.gz" frontend
cp -a "$CADDYFILE" "$BACKUP/Caddyfile.before"
cp "$PATCH" "$BACKUP/"
cp "$0" "$BACKUP/deployer-frontend-unique.sh"
printf '%s\n' "$COMMIT" > "$BACKUP/github-commit.txt"
IMAGE=$(docker inspect faithbook-frontend --format '{{.Config.Image}}')
ROLLBACK="faithbook-frontend-rollback:$(basename "$BACKUP")"
docker tag "$IMAGE" "$ROLLBACK"
mkdir "$BACKUP/assets.before"
docker cp faithbook-frontend:/usr/share/nginx/html/assets/. "$BACKUP/assets.before/"
COMPOSE=(docker compose -f docker-compose.yml -f docker-compose.override.yml)
APPLIED=0
CADDY_CHANGED=0
reload_caddy() {
  docker exec caddy caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile > "$BACKUP/caddy-validation.log" 2>&1
  docker kill --signal=USR1 caddy > /dev/null
}
rollback() {
  local result=$?
  trap - ERR
  set +e
  [[ $APPLIED == 0 ]] || git apply -R "$PATCH"
  docker tag "$ROLLBACK" "$IMAGE"
  "${COMPOSE[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 180 frontend
  if [[ -f "$BACKUP/caddy-changed.txt" ]] && [[ $(cat "$BACKUP/caddy-changed.txt") == 1 ]]; then
    # Reverse only our handler, preserving unrelated configuration changes.
    python3 - "$CADDYFILE" "$BACKUP/Caddyfile.before-change" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1])
current=p.read_text()
before=Path(sys.argv[2]).read_text()
old='    handle_path /nouvelle-interface/* {\n        root * /srv/sites/faithbook-interface\n        header Cache-Control "no-cache"\n        file_server\n    }'
new='    handle_path /nouvelle-interface/* {\n        header Cache-Control "no-cache"\n        reverse_proxy faithbook-frontend:80\n    }'
assert before.count(old)==1
if current.count(new)==1:
    p.write_text(current.replace(new,old))
else:
    assert current.count(old)==1, 'Routing changed externally; review the saved Caddy configuration'
PY
    if [[ $? == 0 ]]; then reload_caddy; fi
  fi
  printf 'Deployment rolled back. Backup: %s\n' "$BACKUP" >&2
  exit "$result"
}
trap rollback ERR
git apply "$PATCH"
APPLIED=1
"${COMPOSE[@]}" build frontend
"${COMPOSE[@]}" up -d --no-deps --no-build --force-recreate --wait --wait-timeout 180 frontend
docker cp "$BACKUP/assets.before/." faithbook-frontend:/usr/share/nginx/html/assets/
cp -a "$CADDYFILE" "$BACKUP/Caddyfile.before-change"
python3 - "$CADDYFILE" "$BACKUP/caddy-changed.txt" <<'PY'
import sys
from pathlib import Path
p=Path(sys.argv[1])
s=p.read_text()
old='    handle_path /nouvelle-interface/* {\n        root * /srv/sites/faithbook-interface\n        header Cache-Control "no-cache"\n        file_server\n    }'
new='    handle_path /nouvelle-interface/* {\n        header Cache-Control "no-cache"\n        reverse_proxy faithbook-frontend:80\n    }'
if old in s:
    assert s.count(old)==1
    # The rollback marker is durable before the bound file is changed.
    Path(sys.argv[2]).write_text('1')
    p.write_text(s.replace(old,new))
else:
    assert s.count(new)==1, 'Unexpected routing configuration; no routing changes made'
    Path(sys.argv[2]).write_text('0')
PY
CADDY_CHANGED=$(cat "$BACKUP/caddy-changed.txt")
if [[ $CADDY_CHANGED == 1 ]]; then
  reload_caddy
fi
BASE=https://veille-novostok.duckdns.org
# Wait for the signal reload to take effect before asserting identical indexes.
for attempt in {1..10}; do
  curl --fail --silent --show-error --max-time 20 "$BASE/application/?v=$COMMIT" > "$BACKUP/application.http.html"
  curl --fail --silent --show-error --max-time 20 "$BASE/nouvelle-interface/?v=$COMMIT" > "$BACKUP/nouvelle-interface.http.html"
  if cmp -s "$BACKUP/application.http.html" "$BACKUP/nouvelle-interface.http.html"; then break; fi
  sleep 1
done
cmp "$BACKUP/application.http.html" "$BACKUP/nouvelle-interface.http.html"
curl --fail --silent --show-error --location --max-time 20 "$BASE/?v=$COMMIT" > "$BACKUP/root.http.html"
cmp "$BACKUP/application.http.html" "$BACKUP/root.http.html"
docker exec faithbook-frontend cat /usr/share/nginx/html/index.html > "$BACKUP/container.index.html"
cmp "$BACKUP/application.http.html" "$BACKUP/container.index.html"
python3 - "$BACKUP/application.http.html" > "$BACKUP/assets.txt" <<'PY'
import re,sys
from pathlib import Path
html=Path(sys.argv[1]).read_text()
paths=re.findall(r'(?:src|href)="(/assets/[^"<>]+\.(?:js|css))"',html)
assert len(paths)>=2
for path in paths: print(path)
PY
while IFS= read -r asset; do
  curl --fail --silent --show-error --max-time 20 "$BASE$asset" > "$BACKUP/$(basename "$asset").http"
done < "$BACKUP/assets.txt"
for route in /api/auth/me /api/huntx/archive; do
  [[ $(curl --silent --output /dev/null --write-out '%{http_code}' --max-time 20 "$BASE$route") == 401 ]]
done
[[ $(docker inspect faithbook-frontend --format '{{.State.Health.Status}}') == healthy ]]
printf 'COMPLETE\n' > "$BACKUP/COMPLETE"
trap - ERR
printf 'Same FaithBook frontend at application, nouvelle-interface and root.\nGitHub: %s\nBackup: %s\n' "$COMMIT" "$BACKUP"
