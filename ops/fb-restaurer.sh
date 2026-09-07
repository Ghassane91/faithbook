#!/usr/bin/env bash
# Retour arriere de la nouvelle interface FaithBook vers une sauvegarde horodatee.
#
# Usage :
#   ./fb-restaurer.sh --lister              # liste les sauvegardes disponibles
#   ./fb-restaurer.sh <horodatage>          # restaure cette sauvegarde
#   ./fb-restaurer.sh --derniere            # restaure la sauvegarde la plus recente
#   ./fb-restaurer.sh <horodatage> --caddy  # restaure aussi le Caddyfile et recharge Caddy
#   ./fb-restaurer.sh <horodatage> --dry-run
#   ./fb-restaurer.sh <horodatage> --oui    # sans demande de confirmation
#
# L'etat courant est toujours sauvegarde avant restauration : un retour arriere
# est lui-meme reversible.

set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=faithbook-env.sh
. "$HERE/faithbook-env.sh"
# shellcheck source=fb-lib.sh
. "$HERE/fb-lib.sh"

FB_DRY=0; CADDY=0; CIBLE=""; SANS_DEMANDE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --lister|-l) CIBLE="__lister__"; shift ;;
    --derniere)  CIBLE="__derniere__"; shift ;;
    --caddy)     CADDY=1; shift ;;
    --dry-run)   FB_DRY=1; shift ;;
    --oui|-y)    SANS_DEMANDE=1; shift ;;
    -h|--help)   sed -n '2,16p' "$0"; exit 0 ;;
    -*)          echo "Option inconnue : $1" >&2; exit 2 ;;
    *)           CIBLE="$1"; shift ;;
  esac
done
export FB_DRY

[ -d "$FB_DEPLOY_ROOT" ] || mort "racine des sauvegardes introuvable : $FB_DEPLOY_ROOT"
fb_sudo_init "$FB_SITE_DIR"

lister() {
  printf 'Sauvegardes disponibles dans %s :\n\n' "$FB_DEPLOY_ROOT"
  printf '  %-26s  %-22s  %s\n' "HORODATAGE" "CONTENU" "COMMIT"
  local trouve=0 d chemin contenu info
  while IFS= read -r d; do
    [ -n "$d" ] || continue
    chemin="$FB_DEPLOY_ROOT/$d"; contenu=""; info=""
    fb_test -d "$chemin/site.before" && contenu="site"
    fb_test -f "$chemin/Caddyfile.before" && contenu="${contenu:+$contenu + }Caddyfile"
    [ -z "$contenu" ] && contenu="vide"
    if fb_test -f "$chemin/manifeste.json"; then
      info="$( { cat "$chemin/manifeste.json" 2>/dev/null || ${FB_SUDO:-} cat "$chemin/manifeste.json" 2>/dev/null; } \
              | grep -o '"commit"[[:space:]]*:[[:space:]]*"[^"]*"' | cut -d'"' -f4 | cut -c1-12)"
    fi
    case "$info" in ''|non*) info="—" ;; esac
    printf '  %-26s  %-22s  %s\n' "$d" "$contenu" "$info"
    trouve=1
  done < <(find "$FB_DEPLOY_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort -r)
  [ "$trouve" -eq 1 ] || printf '  aucune\n'
  printf '\nRestauration : bash %s <horodatage>\n' "$0"
}

if [ -z "$CIBLE" ] || [ "$CIBLE" = "__lister__" ]; then
  lister
  [ -z "$CIBLE" ] && exit 2
  exit 0
fi

if [ "$CIBLE" = "__derniere__" ]; then
  CIBLE="$(find "$FB_DEPLOY_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort -r | head -1)"
  [ -n "$CIBLE" ] || mort "aucune sauvegarde disponible"
  log "sauvegarde la plus recente : $CIBLE"
fi

SRC="$FB_DEPLOY_ROOT/$CIBLE"
fb_test -d "$SRC" || { echo "Sauvegarde introuvable : $CIBLE"; echo; lister; exit 1; }
fb_test -d "$SRC/site.before" || mort "cette sauvegarde ne contient pas de site.before : $SRC"
fb_test -f "$SRC/site.before/index.html" || mort "site.before sans index.html, restauration refusee"

printf '\nRestauration FaithBook\n'
printf '  sauvegarde  : %s\n' "$SRC/site.before"
printf '  vers        : %s\n' "$FB_SITE_DIR"
printf '  fichiers    : %s\n' "$( { find "$SRC/site.before" -type f 2>/dev/null || ${FB_SUDO:-} find "$SRC/site.before" -type f 2>/dev/null; } | wc -l)"
[ "$CADDY" -eq 1 ] && printf '  Caddyfile   : oui\n'
[ "$FB_DRY" -eq 1 ] && printf '  execution   : a blanc\n'
printf '\n'

if [ "$FB_DRY" -eq 0 ] && [ "$SANS_DEMANDE" -eq 0 ] && [ -t 0 ]; then
  read -r -p "Confirmer la restauration ? (oui/non) " rep
  case "$rep" in oui|OUI|o|O|y|yes) ;; *) echo "Annule."; exit 0 ;; esac
fi

# 1. L'etat courant devient lui-meme une sauvegarde.
TS="$(date -u +%Y%m%dT%H%M%SZ)"
AVANT="$FB_DEPLOY_ROOT/${TS}-avant-restauration"
etape "1. Sauvegarde de l'etat courant"
sx mkdir -p "$AVANT/site.before"
fb_recouvrir "$FB_SITE_DIR" "$AVANT/site.before"
log "conserve dans        : $AVANT/site.before"
[ -f "$FB_CADDYFILE" ] && sx cp -a "$FB_CADDYFILE" "$AVANT/Caddyfile.before"

# 2. Restauration du site en miroir.
etape "2. Restauration du site"
fb_miroir "$SRC/site.before" "$FB_SITE_DIR"
log "site restaure depuis : $CIBLE"

# 3. Caddyfile, uniquement sur demande explicite.
if [ "$CADDY" -eq 1 ]; then
  etape "3. Restauration du Caddyfile"
  [ -f "$SRC/Caddyfile.before" ] || mort "aucun Caddyfile.before dans cette sauvegarde"
  log "utiliser plutot fb-caddy.sh --restaurer pour la configuration Caddy"
  if [ "$FB_DRY" -eq 0 ]; then
    fb_caddy_detect || mort "Caddy non detecte, restauration de la configuration impossible"
    rc=0; fb_caddy_valider "$SRC/Caddyfile.before" || rc=$?
    [ "$rc" -eq 1 ] && mort "le Caddyfile sauvegarde est invalide, remplacement annule"
    [ "$rc" -eq 2 ] && log "validation impossible, remplacement poursuivi"
    sx cp -a "$SRC/Caddyfile.before" "$FB_CADDYFILE"
    fb_caddy_recharger || mort "rechargement de Caddy en echec"
    log "Caddy recharge"
  fi
fi

# 4. Verification.
if [ "$FB_DRY" -eq 0 ] && [ -f "$HERE/fb-verifier.sh" ]; then
  etape "Verification"
  if bash "$HERE/fb-verifier.sh"; then
    log "restauration verifiee"
  else
    printf '\nLa restauration est en place mais la verification echoue.\n'
    printf 'Etat d avant restauration conserve dans : %s/site.before\n' "$AVANT"
    exit 1
  fi
fi

etape "Termine"
log "Version restauree    : $CIBLE"
log "Etat precedent       : $AVANT/site.before"
