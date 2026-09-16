#!/usr/bin/env bash
# Envoie les sauvegardes locales vers Backblaze B2, sur le bucket deja utilise
# par FaithBook pour les captures, sous un prefixe distinct.
#
#   sudo ./envoyer-sauvegardes-b2.sh --verifier   # ne transfere rien
#   sudo ./envoyer-sauvegardes-b2.sh              # envoie les fichiers du jour
#
# Les identifiants sont lus dans le .env de FaithBook et ne sont jamais affiches.
# Aucun paquet n est installe sur l hote : l outil S3 tourne dans un conteneur
# jetable.

set -Eeuo pipefail

SOURCE="${BKP_SOURCE:-/var/backups/integrit}"
ENV_FAITHBOOK="${BKP_ENV:-/opt/integrit/src/faithbook/.env}"
PREFIXE="${BKP_PREFIX:-sauvegardes/}"
IMAGE="${BKP_IMAGE:-amazon/aws-cli:latest}"
JOURS="${BKP_JOURS:-1}"   # anciennete maximale des fichiers a envoyer

ok()   { printf '  [ OK ] %s\n' "$*"; }
ko()   { printf '  [ KO ] %s\n' "$*"; }
etape(){ printf '\n== %s\n' "$*"; }
mort() { printf '\nARRET : %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || mort "lancer avec sudo : les sauvegardes appartiennent a root."

etape "1. Controles"
command -v docker >/dev/null 2>&1 || mort "docker absent."
[ -d "$SOURCE" ] || mort "dossier de sauvegardes introuvable : $SOURCE"
[ -f "$ENV_FAITHBOOK" ] || mort "configuration introuvable : $ENV_FAITHBOOK"
ok "source : $SOURCE"

# Lecture des identifiants. Jamais affiches, jamais journalises.
lire() { grep -E "^$1=" "$ENV_FAITHBOOK" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"'' ; }
BUCKET="$(lire S3_BUCKET)"
ENDPOINT="$(lire S3_ENDPOINT_URL)"
REGION="$(lire S3_REGION)"
CLE_ID="$(lire S3_ACCESS_KEY_ID)"
CLE_SECRET="$(lire S3_SECRET_ACCESS_KEY)"

[ -n "$BUCKET" ]     || mort "S3_BUCKET absent de $ENV_FAITHBOOK"
[ -n "$ENDPOINT" ]   || mort "S3_ENDPOINT_URL absent"
[ -n "$CLE_ID" ]     || mort "S3_ACCESS_KEY_ID absent"
[ -n "$CLE_SECRET" ] || mort "S3_SECRET_ACCESS_KEY absent"
ok "bucket : $BUCKET"
ok "fournisseur : $ENDPOINT"
ok "identifiants lus (non affiches)"

etape "2. Fichiers concernes"
mapfile -t FICHIERS < <(find "$SOURCE" -maxdepth 1 -type f -name '*.gz' -mtime "-$JOURS" | sort)
if [ "${#FICHIERS[@]}" -eq 0 ]; then
  ko "aucun fichier de moins de $JOURS jour(s) dans $SOURCE"
  mort "la sauvegarde de la nuit a-t-elle bien tourne ?"
fi
total=0
for f in "${FICHIERS[@]}"; do
  taille="$(stat -c%s "$f")"; total=$((total+taille))
  printf '  %10s  %s\n' "$(numfmt --to=iec "$taille")" "$(basename "$f")"
done
ok "${#FICHIERS[@]} fichier(s), $(numfmt --to=iec "$total") au total"

if [ "${1:-}" = "--verifier" ]; then
  etape "Verification seule — rien n a ete transfere"
  printf '  Destination prevue : s3://%s/%s%s/\n' "$BUCKET" "$PREFIXE" "$(hostname)"
  exit 0
fi

etape "3. Transfert"
DESTINATION="s3://$BUCKET/$PREFIXE$(hostname)/$(date -u +%Y/%m/%d)/"
echec=0
for f in "${FICHIERS[@]}"; do
  nom="$(basename "$f")"
  if docker run --rm \
      -e AWS_ACCESS_KEY_ID="$CLE_ID" \
      -e AWS_SECRET_ACCESS_KEY="$CLE_SECRET" \
      -e AWS_DEFAULT_REGION="${REGION:-us-east-1}" \
      -v "$f":/envoi/"$nom":ro \
      "$IMAGE" s3 cp "/envoi/$nom" "$DESTINATION$nom" \
      --endpoint-url "$ENDPOINT" --only-show-errors; then
    ok "$nom"
  else
    ko "$nom"
    echec=$((echec+1))
  fi
done

etape "4. Controle a distance"
LISTE="$(docker run --rm \
   -e AWS_ACCESS_KEY_ID="$CLE_ID" \
   -e AWS_SECRET_ACCESS_KEY="$CLE_SECRET" \
   -e AWS_DEFAULT_REGION="${REGION:-us-east-1}" \
   "$IMAGE" s3 ls "$DESTINATION" --endpoint-url "$ENDPOINT" 2>&1 || true)"
if [ -n "$LISTE" ]; then
  printf '%s\n' "$LISTE" | sed 's/^/  /'
  distant="$(printf '%s\n' "$LISTE" | grep -c . || true)"
  if [ "$distant" -eq "${#FICHIERS[@]}" ] && [ "$echec" -eq 0 ]; then
    ok "les $distant fichiers sont confirmes a distance"
  else
    ko "$distant fichier(s) a distance pour ${#FICHIERS[@]} envoye(s)"
  fi
else
  ko "aucun fichier listé a distance — le transfert n est pas confirme"
  echec=$((echec+1))
fi

etape "Termine"
if [ "$echec" -eq 0 ]; then
  printf '  Sauvegardes hors du serveur : %s\n' "$DESTINATION"
  exit 0
fi
printf '  %d echec(s). Les sauvegardes locales restent intactes dans %s\n' "$echec" "$SOURCE"
exit 1
