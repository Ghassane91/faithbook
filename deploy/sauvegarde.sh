#!/usr/bin/env bash
# Sauvegarde de FaithBook : base de donnees + preuves.
#
#   sudo /opt/faithbook/deploy/sauvegarde.sh
#
# A programmer une fois par jour (voir VPS.md, etape 8).
#
# Ce script ne supprime jamais un volume Docker et n'arrete aucun service.
# pg_dump travaille sur une base en fonctionnement.

set -euo pipefail

PROJET="${PROJET:-/opt/faithbook}"
DESTINATION="${DESTINATION:-/var/backups/faithbook}"
RETENTION_JOURS="${RETENTION_JOURS:-14}"
HORO="$(date +%Y%m%d-%H%M%S)"

mkdir -p "$DESTINATION"
cd "$PROJET"

echo "== Base de donnees =="
# --clean --if-exists : le fichier peut etre rejoue sur une base existante
# sans devoir la supprimer d'abord.
docker compose exec -T db pg_dumpall --clean --if-exists -U postgres \
  | gzip -9 > "$DESTINATION/db-$HORO.sql.gz"
echo "  $(du -h "$DESTINATION/db-$HORO.sql.gz" | cut -f1)"

echo "== Captures =="
# Les images sont volumineuses et immuables : une fois ecrite, une capture ne
# change plus. On copie donc en incrementiel plutot que de tout rearchiver
# chaque nuit, ce qui deviendrait intenable des le deuxieme mois.
VOLUME_CAPTURES="$(docker compose ps -q backend)"
if [ -n "$VOLUME_CAPTURES" ]; then
  docker cp "$VOLUME_CAPTURES:/output/." "$DESTINATION/captures/" 2>/dev/null || \
    echo "  (rien a copier, ou chemin /output absent)"
  echo "  $(du -sh "$DESTINATION/captures" 2>/dev/null | cut -f1 || echo 0)"
fi

echo "== Configuration =="
# .env contient des secrets : on le sauvegarde avec des droits restreints,
# jamais dans un depot Git, jamais dans un stockage partage sans chiffrement.
install -m 600 "$PROJET/.env" "$DESTINATION/env-$HORO.sauvegarde"

echo "== Rotation (> $RETENTION_JOURS jours) =="
find "$DESTINATION" -maxdepth 1 -name 'db-*.sql.gz' -mtime "+$RETENTION_JOURS" -print -delete
find "$DESTINATION" -maxdepth 1 -name 'env-*.sauvegarde' -mtime "+$RETENTION_JOURS" -print -delete

echo
echo "Termine : $DESTINATION"
echo
echo "RAPPEL : une sauvegarde qui n'a jamais ete restauree n'est pas une"
echo "sauvegarde. Teste la restauration au moins une fois (VPS.md, etape 8)."