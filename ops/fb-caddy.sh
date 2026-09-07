#!/usr/bin/env bash
# Application securisee d'une configuration Caddy, avec retour arriere automatique.
#
# Usage :
#   ./fb-caddy.sh --montrer                 # affiche le Caddyfile actuel (secrets masques)
#   ./fb-caddy.sh --verifier                # valide la configuration en place
#   ./fb-caddy.sh --appliquer <fichier>     # sauvegarde, valide, installe, recharge, verifie
#   ./fb-caddy.sh --appliquer <f> --dry-run # ne modifie rien
#   ./fb-caddy.sh --restaurer <horodatage>  # remet un Caddyfile sauvegarde
#   ./fb-caddy.sh --lister                  # liste les Caddyfile sauvegardes
#
# En cas d'echec de la validation, du rechargement ou de la verification HTTP,
# la configuration precedente est remise en place automatiquement.

set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=faithbook-env.sh
. "$HERE/faithbook-env.sh"
# shellcheck source=fb-lib.sh
. "$HERE/fb-lib.sh"

ACTION=""; FICHIER=""; FB_DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --montrer)   ACTION="montrer"; shift ;;
    --verifier)  ACTION="verifier"; shift ;;
    --lister)    ACTION="lister"; shift ;;
    --appliquer) ACTION="appliquer"; FICHIER="${2:?--appliquer attend un fichier}"; shift 2 ;;
    --restaurer) ACTION="restaurer"; FICHIER="${2:?--restaurer attend un horodatage}"; shift 2 ;;
    --dry-run)   FB_DRY=1; shift ;;
    -h|--help)   sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Option inconnue : $1" >&2; exit 2 ;;
  esac
done
export FB_DRY
[ -n "$ACTION" ] || { sed -n '2,16p' "$0"; exit 2; }

CADDY_BAK="${FB_DEPLOY_ROOT}/caddy"
fb_sudo_init "$FB_CADDYFILE"

masquer() { fb_masquer; }

valider() {
  local f="$1"
  command -v caddy >/dev/null 2>&1 || return 2
  if caddy validate --config "$f" >/tmp/fb-caddy-valid.$$ 2>&1; then
    rm -f /tmp/fb-caddy-valid.$$; return 0
  else
    printf '\nErreurs de validation :\n'; sed 's/^/  /' /tmp/fb-caddy-valid.$$; rm -f /tmp/fb-caddy-valid.$$
    return 1
  fi
}

case "$ACTION" in

  montrer)
    [ -f "$FB_CADDYFILE" ] || mort "Caddyfile introuvable : $FB_CADDYFILE"
    printf 'Caddyfile : %s (secrets masques)\n\n' "$FB_CADDYFILE"
    masquer < "$FB_CADDYFILE"
    ;;

  verifier)
    [ -f "$FB_CADDYFILE" ] || mort "Caddyfile introuvable : $FB_CADDYFILE"
    rc=0; valider "$FB_CADDYFILE" || rc=$?
    case "$rc" in
      0) log "configuration en place : valide" ;;
      2) log "binaire caddy absent : validation IMPOSSIBLE, statut inconnu"; exit 3 ;;
      *) mort "la configuration EN PLACE est invalide" ;;
    esac
    ;;

  lister)
    if [ -d "$CADDY_BAK" ]; then
      printf 'Caddyfile sauvegardes dans %s :\n\n' "$CADDY_BAK"
      ls -1t "$CADDY_BAK" 2>/dev/null | sed 's/^/  /' || printf '  aucun\n'
    else
      printf 'Aucune sauvegarde Caddy dans %s\n' "$CADDY_BAK"
    fi
    printf '\nLes deploiements conservent aussi un Caddyfile.before dans chaque dossier de %s\n' "$FB_DEPLOY_ROOT"
    ;;

  appliquer)
    [ -f "$FICHIER" ] || mort "fichier introuvable : $FICHIER"
    [ -f "$FB_CADDYFILE" ] || mort "Caddyfile actuel introuvable : $FB_CADDYFILE"

    etape "1. Validation de la nouvelle configuration"
    rc=0; valider "$FICHIER" || rc=$?
    case "$rc" in
      0) log "nouvelle configuration : valide" ;;
      2) log "binaire caddy absent : la configuration N'A PAS ETE VALIDEE"
         log "le retour arriere automatique reste actif en cas d'echec du rechargement" ;;
      *) mort "la nouvelle configuration est invalide, rien n'a ete modifie" ;;
    esac

    etape "2. Differences avec la configuration en place"
    if command -v diff >/dev/null 2>&1; then
      diff -u <(masquer < "$FB_CADDYFILE") <(masquer < "$FICHIER") | sed 's/^/  /' || true
    fi

    if [ "$FB_DRY" -eq 1 ]; then
      etape "Mode a blanc"
      log "aucune modification effectuee"
      exit 0
    fi

    if [ -t 0 ]; then
      printf '\n'
      read -r -p "Appliquer cette configuration ? (oui/non) " rep
      case "$rep" in oui|OUI|o|O|y|yes) ;; *) echo "Annule."; exit 0 ;; esac
    fi

    TS="$(date -u +%Y%m%dT%H%M%SZ)"
    etape "3. Sauvegarde de la configuration en place"
    sx mkdir -p "$CADDY_BAK"
    SAUVE="$CADDY_BAK/Caddyfile.$TS"
    sx cp -a "$FB_CADDYFILE" "$SAUVE"
    log "sauvegarde           : $SAUVE"

    etape "4. Installation et rechargement"
    sx cp -a "$FICHIER" "$FB_CADDYFILE"
    if ! sx systemctl reload caddy; then
      log "RECHARGEMENT EN ECHEC, retour arriere immediat"
      sx cp -a "$SAUVE" "$FB_CADDYFILE"
      sx systemctl reload caddy || log "le rechargement de secours a aussi echoue, intervention manuelle requise"
      mort "rechargement impossible. Journal : journalctl -u caddy -n 50"
    fi
    log "Caddy recharge"
    sleep 3

    etape "5. Verification"
    if bash "$HERE/fb-verifier.sh"; then
      log "verification reussie"
      log "configuration appliquee. Retour arriere : $0 --restaurer $TS"
    else
      printf '\nVERIFICATION EN ECHEC, retour arriere automatique.\n'
      sx cp -a "$SAUVE" "$FB_CADDYFILE"
      sx systemctl reload caddy || log "le rechargement de secours a echoue, intervention manuelle requise"
      sleep 3
      if bash "$HERE/fb-verifier.sh" >/dev/null 2>&1; then
        mort "nouvelle configuration rejetee, configuration precedente remise en place et verifiee"
      else
        mort "nouvelle configuration rejetee ET la configuration precedente ne passe pas la verification. Intervention manuelle : journalctl -u caddy -n 50"
      fi
    fi
    ;;

  restaurer)
    SRC="$CADDY_BAK/Caddyfile.$FICHIER"
    [ -f "$SRC" ] || SRC="$FB_DEPLOY_ROOT/$FICHIER/Caddyfile.before"
    [ -f "$SRC" ] || mort "aucune sauvegarde pour $FICHIER (cherche dans $CADDY_BAK et $FB_DEPLOY_ROOT)"
    log "restauration depuis  : $SRC"
    rc=0; valider "$SRC" || rc=$?
    case "$rc" in
      0) log "sauvegarde valide" ;;
      2) log "binaire caddy absent : sauvegarde non validee" ;;
      *) mort "la sauvegarde est invalide, restauration annulee" ;;
    esac
    if [ "$FB_DRY" -eq 1 ]; then log "mode a blanc, rien de modifie"; exit 0; fi
    TS="$(date -u +%Y%m%dT%H%M%SZ)"
    sx mkdir -p "$CADDY_BAK"
    sx cp -a "$FB_CADDYFILE" "$CADDY_BAK/Caddyfile.$TS-avant-restauration"
    sx cp -a "$SRC" "$FB_CADDYFILE"
    sx systemctl reload caddy || mort "rechargement en echec. Journal : journalctl -u caddy -n 50"
    sleep 3
    bash "$HERE/fb-verifier.sh" || log "restauration en place mais verification en echec"
    log "restauration terminee"
    ;;
esac
