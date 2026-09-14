#!/usr/bin/env bash
# Raccordement de FaithBook a Google Drive — lot unique.
#
#   sudo ./fb-drive.sh --verifier   # ne modifie rien, dit ce qui manque
#   sudo ./fb-drive.sh --activer    # sauvegarde, configure, redemarre, TESTE un envoi reel
#   sudo ./fb-drive.sh --restaurer  # revient a la configuration precedente
#
# Rien n'est annonce comme reussi sans un envoi reellement confirme par Google.
# Le script n'affiche jamais le contenu de la cle : seulement l'adresse du
# compte de service, qui n'est pas un secret.

set -Eeuo pipefail

DOSSIER_PARENT="${FB_DRIVE_PARENT:-1ZbCQlk_aza5Bj188_jkA1P47sf2r3MEr}"
CLE_HOTE="${FB_DRIVE_KEY:-/opt/integrit/secrets/service-account.json}"
CLE_CONTENEUR="/secrets/service-account.json"
CONTENEURS=("faithbook-backend" "faithbook-worker")
SAUVEGARDES="/opt/integrit/deployments/drive"

ok()   { printf '  [ OK ] %s\n' "$*"; }
ko()   { printf '  [ KO ] %s\n' "$*"; }
info() { printf '  [ .. ] %s\n' "$*"; }
etape(){ printf '\n== %s\n' "$*"; }
mort() { printf '\nARRET : %s\n' "$*" >&2; exit 1; }

ACTION="${1:---verifier}"
[ "$(id -u)" -eq 0 ] || mort "lancer avec sudo : les fichiers de FaithBook appartiennent a root."

# ------------------------------------------------------------------ reperage
trouver_env() {
  local c
  for c in /opt/integrit/src/faithbook/.env /opt/integrit/faithbook/.env /opt/integrit/.env; do
    [ -f "$c" ] && { printf '%s' "$c"; return 0; }
  done
  # Dernier recours : le chemin declare par le conteneur.
  c="$(docker inspect faithbook-backend \
        -f '{{range .Mounts}}{{if eq .Destination "/app/.env"}}{{.Source}}{{end}}{{end}}' 2>/dev/null || true)"
  [ -n "$c" ] && [ -f "$c" ] && { printf '%s' "$c"; return 0; }
  return 1
}

etape "1. Etat des lieux"
command -v docker >/dev/null 2>&1 || mort "docker absent."
for c in "${CONTENEURS[@]}"; do
  if docker ps --format '{{.Names}}' | grep -qx "$c"; then ok "conteneur $c en marche"
  else ko "conteneur $c absent"; fi
done

FICHIER_ENV="$(trouver_env || true)"
if [ -n "$FICHIER_ENV" ]; then ok "configuration : $FICHIER_ENV"
else ko "fichier .env introuvable — renseigner FB_ENV et relancer"; fi
[ -n "${FB_ENV:-}" ] && FICHIER_ENV="$FB_ENV"

etape "2. Cle du compte de service"
if [ -f "$CLE_HOTE" ]; then
  ok "presente : $CLE_HOTE"
  if python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$CLE_HOTE" 2>/dev/null; then
    ADRESSE="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('client_email',''))" "$CLE_HOTE")"
    TYPE="$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('type',''))" "$CLE_HOTE")"
    ok "JSON valide, type=$TYPE"
    if [ "$TYPE" != "service_account" ]; then
      ko "ce n'est pas une cle de compte de service"
    fi
    printf '\n  ADRESSE A PARTAGER SUR LE DOSSIER DRIVE :\n    %s\n\n' "$ADRESSE"
    info "partagez le dossier avec cette adresse, role Editeur (Contributeur sur un Drive partage)"
  else
    ko "le fichier n'est pas un JSON valide"
  fi
  perms="$(stat -c '%a %U' "$CLE_HOTE")"
  case "$perms" in 600*|400*) ok "droits : $perms" ;; *) ko "droits trop larges : $perms — faire chmod 600" ;; esac
else
  ko "absente : $CLE_HOTE"
  info "deposez la cle JSON a cet emplacement, puis relancez"
fi

etape "3. Montage du secret dans les conteneurs"
for c in "${CONTENEURS[@]}"; do
  if docker exec "$c" test -f "$CLE_CONTENEUR" 2>/dev/null; then
    ok "$c voit $CLE_CONTENEUR"
  else
    ko "$c ne voit pas $CLE_CONTENEUR — verifier le montage dans docker-compose.yml"
  fi
done

etape "4. Configuration actuelle"
if [ -n "$FICHIER_ENV" ] && [ -f "$FICHIER_ENV" ]; then
  for v in STORAGE_BACKEND GOOGLE_SERVICE_ACCOUNT_FILE GOOGLE_DRIVE_PARENT_FOLDER_ID GOOGLE_DRIVE_SHARED_DRIVE_ID FOLDER_DATE_FORMAT; do
    val="$(grep -E "^${v}=" "$FICHIER_ENV" 2>/dev/null | tail -1 | cut -d= -f2- || true)"
    printf '  %-34s %s\n' "$v" "${val:-<absent>}"
  done
fi

if [ "$ACTION" = "--verifier" ]; then
  etape "Verification seule — rien n'a ete modifie"
  printf '  Pour activer : sudo %s --activer\n' "$0"
  exit 0
fi

# ------------------------------------------------------------------ activation
if [ "$ACTION" = "--restaurer" ]; then
  etape "Restauration"
  dernier="$(ls -1d "$SAUVEGARDES"/*/ 2>/dev/null | sort | tail -1 || true)"
  [ -n "$dernier" ] || mort "aucune sauvegarde dans $SAUVEGARDES"
  [ -n "$FICHIER_ENV" ] || mort "fichier .env inconnu"
  cp -a "${dernier}env.before" "$FICHIER_ENV"
  ok "configuration restauree depuis $dernier"
  docker restart "${CONTENEURS[@]}" >/dev/null && ok "conteneurs redemarres"
  exit 0
fi

[ "$ACTION" = "--activer" ] || mort "action inconnue : $ACTION"
[ -n "$FICHIER_ENV" ] && [ -f "$FICHIER_ENV" ] || mort "fichier .env introuvable, activation impossible"
[ -f "$CLE_HOTE" ] || mort "cle absente : $CLE_HOTE"
docker exec "${CONTENEURS[0]}" test -f "$CLE_CONTENEUR" || mort "le conteneur ne voit pas la cle, corriger le montage avant d'activer"

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BAK="$SAUVEGARDES/$TS"
etape "5. Sauvegarde"
mkdir -p "$BAK"
cp -a "$FICHIER_ENV" "$BAK/env.before"
ok "$BAK/env.before"

etape "6. Configuration"
regler() {
  local cle="$1" valeur="$2"
  if grep -qE "^${cle}=" "$FICHIER_ENV"; then
    sed -i "s|^${cle}=.*|${cle}=${valeur}|" "$FICHIER_ENV"
  else
    printf '%s=%s\n' "$cle" "$valeur" >> "$FICHIER_ENV"
  fi
  printf '  %-34s %s\n' "$cle" "$valeur"
}
regler STORAGE_BACKEND google_drive
regler GOOGLE_SERVICE_ACCOUNT_FILE "$CLE_CONTENEUR"
regler GOOGLE_DRIVE_PARENT_FOLDER_ID "$DOSSIER_PARENT"
regler FOLDER_DATE_FORMAT '%Y-%m-%d'
[ -n "${FB_DRIVE_SHARED_ID:-}" ] && regler GOOGLE_DRIVE_SHARED_DRIVE_ID "$FB_DRIVE_SHARED_ID"

etape "7. Redemarrage"
docker restart "${CONTENEURS[@]}" >/dev/null
ok "conteneurs redemarres"
sleep 8

etape "8. Envoi reel de controle"
# Un fichier temoin est reellement televerse. Sans confirmation de Google,
# on ne declare rien comme actif.
cat > /tmp/fb-drive-test.py <<'PY'
import sys, tempfile, datetime, pathlib
try:
    from app.services.drive import drive_client
    from app.config import settings
except Exception as e:
    print("IMPORT_KO", e); sys.exit(2)
if not drive_client.is_configured():
    print("CONFIG_KO", "is_configured() renvoie False"); sys.exit(3)
try:
    drive_client.check_parent()
except AttributeError:
    pass
except Exception as e:
    print("PARENT_KO", e); sys.exit(4)
jour = datetime.datetime.now(datetime.timezone.utc).strftime(settings.folder_date_format)
try:
    dossier = drive_client.ensure_folder(jour)
    dossier = drive_client.ensure_folder("_controle-faithbook", dossier)
    p = pathlib.Path(tempfile.gettempdir()) / "faithbook-controle.txt"
    p.write_text("Controle de raccordement FaithBook — " +
                 datetime.datetime.now(datetime.timezone.utc).isoformat() + "\n", encoding="utf-8")
    r = drive_client.upload(p, dossier, p.name)
    print("OK", jour, getattr(r, "file_id", "?"), getattr(r, "link", "") or getattr(r, "web_link", ""))
except Exception as e:
    print("UPLOAD_KO", type(e).__name__, e); sys.exit(5)
PY
docker cp /tmp/fb-drive-test.py "${CONTENEURS[0]}":/tmp/fb-drive-test.py >/dev/null
SORTIE="$(docker exec "${CONTENEURS[0]}" python /tmp/fb-drive-test.py 2>&1 || true)"
docker exec "${CONTENEURS[0]}" rm -f /tmp/fb-drive-test.py >/dev/null 2>&1 || true
rm -f /tmp/fb-drive-test.py

case "$SORTIE" in
  OK*)
    ok "envoi confirme par Google"
    printf '  %s\n' "$SORTIE"
    printf '\n  Verifiez dans Drive : un dossier date contenant _controle-faithbook/faithbook-controle.txt\n'
    printf '  Ce fichier temoin peut etre supprime.\n'
    ;;
  IMPORT_KO*) ko "le module Drive ne s importe pas"; printf '  %s\n' "$SORTIE" ;;
  CONFIG_KO*) ko "configuration incomplete vue par l application"; printf '  %s\n' "$SORTIE" ;;
  PARENT_KO*) ko "dossier parent inaccessible — le partage avec le compte de service manque ?"; printf '  %s\n' "$SORTIE" ;;
  UPLOAD_KO*) ko "l envoi a echoue"; printf '  %s\n' "$SORTIE" ;;
  *)          ko "resultat inattendu"; printf '  %s\n' "$SORTIE" ;;
esac

etape "Termine"
case "$SORTIE" in
  OK*) printf '  Drive est actif et verifie.\n' ;;
  *)   printf '  Drive N EST PAS confirme. Retour arriere : sudo %s --restaurer\n' "$0" ;;
esac
printf '  Sauvegarde : %s\n' "$BAK"
