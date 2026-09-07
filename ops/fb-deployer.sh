#!/usr/bin/env bash
# Deploiement reproductible de la nouvelle interface FaithBook.
#
# Usage :
#   ./fb-deployer.sh                      # source git, construction puis publication
#   ./fb-deployer.sh --ref <branche|sha>  # deploie une reference precise
#   ./fb-deployer.sh --from-dir <chemin>  # publie un dossier deja construit
#   ./fb-deployer.sh --from-archive <fic> # publie une archive zip ou tar.gz deja construite
#   ./fb-deployer.sh --dry-run            # affiche les actions sans rien modifier
#   ./fb-deployer.sh --no-verify          # saute les controles HTTP finaux
#
# Principe : rien n'est supprime. L'etat courant est sauvegarde avant modification,
# les nouveaux actifs sont copies avant l'index, et l'index bascule en dernier.

set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=faithbook-env.sh
. "$HERE/faithbook-env.sh"
# shellcheck source=fb-lib.sh
. "$HERE/fb-lib.sh"

MODE="git"; SOURCE_ARG=""; FB_DRY=0; VERIFY=1
while [ $# -gt 0 ]; do
  case "$1" in
    --ref)          FB_GIT_REF="${2:?--ref attend une valeur}"; shift 2 ;;
    --from-dir)     MODE="dir";     SOURCE_ARG="${2:?--from-dir attend un chemin}"; shift 2 ;;
    --from-archive) MODE="archive"; SOURCE_ARG="${2:?--from-archive attend un chemin}"; shift 2 ;;
    --dry-run)      FB_DRY=1; shift ;;
    --no-verify)    VERIFY=0; shift ;;
    -h|--help)      sed -n '2,15p' "$0"; exit 0 ;;
    *) echo "Option inconnue : $1" >&2; exit 2 ;;
  esac
done
export FB_DRY

TS="$(date -u +%Y%m%dT%H%M%SZ)"
BAK="${FB_DEPLOY_ROOT}/${TS}"
STAGE=""
trap '[ -n "$STAGE" ] && rm -rf "$STAGE"' EXIT

# --------------------------------------------------------------- 1. Prevol
etape "1. Controles preliminaires"
for c in curl tar find; do
  command -v "$c" >/dev/null 2>&1 || mort "commande absente : $c"
done
[ -d "$FB_SITE_DIR" ] || mort "dossier servi introuvable : $FB_SITE_DIR"
fb_sudo_init "$FB_SITE_DIR"

log "dossier servi        : $FB_SITE_DIR"
log "racine sauvegardes   : $FB_DEPLOY_ROOT"
log "mode                 : $MODE"
log "horodatage           : $TS"
[ -n "${FB_SUDO:-}" ] && log "elevation            : sudo"
[ "$FB_DRY" -eq 1 ] && log "execution            : a blanc, aucune modification"

sx mkdir -p "$BAK"
if [ "$FB_DRY" -eq 0 ]; then
  if [ -n "${FB_SUDO:-}" ]; then $FB_SUDO touch "$BAK/deploiement.log" && $FB_SUDO chmod 666 "$BAK/deploiement.log" 2>/dev/null || true
  else : > "$BAK/deploiement.log"; fi
  [ -w "$BAK/deploiement.log" ] && FB_LOG="$BAK/deploiement.log"
fi

# ------------------------------------------------- 2. Obtention du build
etape "2. Obtention des fichiers a publier"
STAGE="$(mktemp -d /tmp/fb-stage.XXXXXX)"
COMMIT="non applicable"

case "$MODE" in
  git)
    command -v git >/dev/null 2>&1 || mort "git absent"
    command -v npm >/dev/null 2>&1 || mort "npm absent"
    command -v node >/dev/null 2>&1 || mort "node absent"
    if [ -n "${FB_NODE_MIN:-}" ]; then
      nv="$(node -v 2>/dev/null | sed 's/^v//')"
      if [ "$(printf '%s\n%s\n' "$FB_NODE_MIN" "$nv" | sort -V | head -1)" != "$FB_NODE_MIN" ]; then
        mort "Node $nv installe, $FB_NODE_MIN minimum requis (champ engines du package.json)"
      fi
      log "node                 : $nv (minimum $FB_NODE_MIN)"
    fi
    if [ -d "$FB_SRC_DIR/.git" ]; then
      log "mise a jour du depot local $FB_SRC_DIR"
      [ "$FB_DRY" -eq 1 ] || git -C "$FB_SRC_DIR" fetch --all --prune
    else
      log "clonage de $FB_GIT_URL vers $FB_SRC_DIR"
      if [ "$FB_DRY" -eq 0 ]; then
        mkdir -p "$(dirname "$FB_SRC_DIR")"
        git clone "$FB_GIT_URL" "$FB_SRC_DIR" || mort "clonage impossible. Depot prive ? Utiliser --from-archive."
      fi
    fi
    if [ "$FB_DRY" -eq 0 ]; then
      git -C "$FB_SRC_DIR" checkout --force "$FB_GIT_REF" || mort "reference introuvable : $FB_GIT_REF"
      git -C "$FB_SRC_DIR" pull --ff-only origin "$FB_GIT_REF" >/dev/null 2>&1 || true
      COMMIT="$(git -C "$FB_SRC_DIR" rev-parse HEAD)"
      log "commit               : $COMMIT"
    fi

    APP="$FB_SRC_DIR/$FB_APP_SUBDIR"
    log "construction dans $APP"
    if [ "$FB_DRY" -eq 0 ]; then
      [ -d "$APP" ] || mort "sous-dossier applicatif introuvable : $APP"
      ( cd "$APP" && eval "$FB_INSTALL_CMD" && eval "$FB_BUILD_CMD" ) \
        || mort "la construction a echoue, rien n'a ete publie"
      OUT="$FB_BUILD_OUT"
      if [ -z "$OUT" ]; then
        for cand in dist build out; do [ -d "$APP/$cand" ] && { OUT="$APP/$cand"; break; }; done
      else
        OUT="$APP/$OUT"
      fi
      [ -n "$OUT" ] && [ -d "$OUT" ] || mort "dossier de sortie introuvable (essayes : dist, build, out). Renseigner FB_BUILD_OUT."
      log "sortie de build      : $OUT"
      cp -a "$OUT/." "$STAGE/"
    else
      printf '  [a blanc] cd %s && %s && %s\n' "$APP" "$FB_INSTALL_CMD" "$FB_BUILD_CMD"
    fi
    ;;
  dir)
    [ -d "$SOURCE_ARG" ] || mort "dossier introuvable : $SOURCE_ARG"
    log "source               : $SOURCE_ARG"
    [ "$FB_DRY" -eq 1 ] || cp -a "$SOURCE_ARG/." "$STAGE/"
    ;;
  archive)
    [ -f "$SOURCE_ARG" ] || mort "archive introuvable : $SOURCE_ARG"
    log "source               : $SOURCE_ARG"
    if [ "$FB_DRY" -eq 0 ]; then
      case "$SOURCE_ARG" in
        *.zip)          command -v unzip >/dev/null 2>&1 || mort "unzip absent"; unzip -q "$SOURCE_ARG" -d "$STAGE" ;;
        *.tar.gz|*.tgz) tar -xzf "$SOURCE_ARG" -C "$STAGE" ;;
        *)              mort "format d'archive non gere : $SOURCE_ARG" ;;
      esac
      # Archive contenant un unique dossier racine : on remonte son contenu.
      if [ ! -f "$STAGE/index.html" ]; then
        seul="$(find "$STAGE" -mindepth 1 -maxdepth 1)"
        if [ "$(printf '%s\n' "$seul" | wc -l)" -eq 1 ] && [ -d "$seul" ]; then
          log "remontee du dossier racine de l'archive"
          ( shopt -s dotglob; mv "$seul"/* "$STAGE"/ ) && rmdir "$seul"
        fi
      fi
    fi
    ;;
esac

if [ "$FB_DRY" -eq 0 ]; then
  [ -f "$STAGE/index.html" ] || mort "index.html absent du resultat, rien n'a ete publie"
  NB="$(find "$STAGE" -type f | wc -l)"
  log "fichiers a publier   : $NB"
  [ "$NB" -ge 2 ] || mort "resultat suspect : $NB fichier(s) seulement, publication annulee"
fi

# -------------------------------------------------- 3. Sauvegarde de l'etat
etape "3. Sauvegarde de l'etat courant"
sx mkdir -p "$BAK/site.before"
fb_recouvrir "$FB_SITE_DIR" "$BAK/site.before"
log "site sauvegarde      : $BAK/site.before"
if [ -f "$FB_CADDYFILE" ]; then
  sx cp -a "$FB_CADDYFILE" "$BAK/Caddyfile.before"
  log "Caddyfile sauvegarde : $BAK/Caddyfile.before"
else
  log "Caddyfile introuvable a $FB_CADDYFILE, sauvegarde ignoree"
fi

# ------------------------------------------------------- 4. Publication
etape "4. Publication"
# 4a. Tout sauf index.html. Les anciens actifs a empreinte sont conserves,
#     pour les onglets deja ouverts et pour le retour arriere.
fb_recouvrir "$STAGE" "$FB_SITE_DIR" "index.html"
log "actifs copies"
# 4b. Bascule de l'index en dernier, par renommage atomique.
if [ "$FB_DRY" -eq 0 ]; then
  TMPI="${FB_SITE_DIR}/.index.html.${TS}"
  sx cp "$STAGE/index.html" "$TMPI"
  sx mv -f "$TMPI" "$FB_SITE_DIR/index.html"
  log "index bascule"
else
  printf '  [a blanc] bascule atomique de index.html\n'
fi

# ------------------------------------------------------- 5. Manifeste
etape "5. Manifeste de deploiement"
if [ "$FB_DRY" -eq 0 ]; then
  MAN="$(mktemp /tmp/fb-man.XXXXXX)"
  cat > "$MAN" <<JSON
{
  "horodatage_utc": "$TS",
  "mode": "$MODE",
  "reference": "$FB_GIT_REF",
  "commit": "$COMMIT",
  "source": "${SOURCE_ARG:-$FB_GIT_URL}",
  "dossier_servi": "$FB_SITE_DIR",
  "sauvegarde": "$BAK/site.before",
  "url": "${FB_BASE_URL%/}${FB_PATH}",
  "fichiers_publies": ${NB:-0},
  "operateur": "$(id -un)",
  "hote": "$(hostname)"
}
JSON
  sx cp "$MAN" "$BAK/manifeste.json"
  rm -f "$MAN"
  log "manifeste            : $BAK/manifeste.json"
fi

# ------------------------------------------------------- 6. Verification
if [ "$VERIFY" -eq 1 ] && [ "$FB_DRY" -eq 0 ]; then
  etape "6. Verification"
  if [ -f "$HERE/fb-verifier.sh" ]; then
    if bash "$HERE/fb-verifier.sh"; then
      log "verification         : reussie"
    else
      printf '\nLa verification a echoue. Le deploiement est en place mais degrade.\n'
      printf 'Retour arriere : bash %s/fb-restaurer.sh %s\n' "$HERE" "$TS"
      exit 1
    fi
  else
    log "fb-verifier.sh absent, verification ignoree"
  fi
else
  etape "6. Verification ignoree"
fi

# ------------------------------------------------------- 7. Purge
etape "7. Purge des anciennes sauvegardes"
if [ "$FB_DRY" -eq 0 ] && [ -d "$FB_DEPLOY_ROOT" ]; then
  ANCIENNES="$(find "$FB_DEPLOY_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null | sort -r | tail -n +"$((FB_KEEP_BACKUPS+1))")"
  if [ -z "$ANCIENNES" ]; then
    log "rien a purger (retention : $FB_KEEP_BACKUPS)"
  else
    while IFS= read -r d; do
      [ -n "$d" ] || continue
      log "purge                : $d"
      sx rm -rf "${FB_DEPLOY_ROOT:?}/${d:?}"
    done <<< "$ANCIENNES"
  fi
fi

etape "Termine"
log "URL                  : ${FB_BASE_URL%/}${FB_PATH}"
log "Sauvegarde           : $BAK"
log "Retour arriere       : bash $HERE/fb-restaurer.sh $TS"
