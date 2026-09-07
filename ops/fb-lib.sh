#!/usr/bin/env bash
# Fonctions communes aux scripts FaithBook. N'est pas destine a etre lance seul.

FB_LOG=""

log()   { local m; m="$(date -u +%H:%M:%S)  $*"; printf '%s\n' "$m"; _journal "$m"; }
etape() { local m; m="== $*"; printf '\n%s\n' "$m"; _journal "" ; _journal "$m"; }
mort()  { printf '\nECHEC : %s\n' "$*" >&2; _journal "ECHEC : $*"; exit 1; }
_journal() { [ -n "$FB_LOG" ] && printf '%s\n' "$1" >> "$FB_LOG" 2>/dev/null; return 0; }

# Elevation : si la cible n'est pas accessible en ecriture, ou si la racine des
# sauvegardes n'est pas lisible (sur ce serveur elle appartient a root en 0700).
fb_sudo_init() {
  FB_SUDO=""
  local cible="$1"
  local besoin=0
  if [ -e "$cible" ] && [ ! -w "$cible" ]; then besoin=1
  elif [ ! -e "$cible" ] && [ ! -w "$(dirname "$cible")" ]; then besoin=1
  fi
  if [ "$besoin" -eq 0 ] && [ -n "${FB_DEPLOY_ROOT:-}" ] && [ -d "$FB_DEPLOY_ROOT" ]; then
    local d
    d="$(find "$FB_DEPLOY_ROOT" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | head -1)"
    [ -n "$d" ] && [ ! -r "$d" ] && besoin=1
  fi
  [ "$besoin" -eq 1 ] && command -v sudo >/dev/null 2>&1 && FB_SUDO="sudo"
  return 0
}

# Teste un chemin en passant par sudo si necessaire.
fb_test() { # fb_test -d /chemin
  local op="$1" chemin="$2"
  test "$op" "$chemin" 2>/dev/null && return 0
  [ -n "${FB_SUDO:-}" ] && $FB_SUDO test "$op" "$chemin" 2>/dev/null && return 0
  return 1
}

# Execute avec elevation si necessaire, ou affiche l'action en mode a blanc.
sx() {
  if [ "${FB_DRY:-0}" -eq 1 ]; then
    printf '  [a blanc] %s%s\n' "${FB_SUDO:+$FB_SUDO }" "$*"
    return 0
  fi
  if [ -n "${FB_SUDO:-}" ]; then "$FB_SUDO" "$@"; else "$@"; fi
}

# Copie par recouvrement : ajoute et remplace, ne supprime rien.
# Utilise tar, present partout, plutot que rsync qui peut manquer.
fb_recouvrir() {
  local src="$1" dst="$2" exclu="${3:-}"
  if [ "${FB_DRY:-0}" -eq 1 ]; then
    printf '  [a blanc] copie de %s vers %s%s\n' "$src" "$dst" "${exclu:+ (sauf $exclu)}"
    return 0
  fi
  [ -d "$src" ] || mort "source de copie introuvable : $src"
  [ -d "$dst" ] || mort "destination de copie introuvable : $dst"
  # L'elevation s'applique AUX DEUX COTES : sur ce serveur le dossier servi et
  # les sauvegardes appartiennent a root, la lecture aussi demande sudo.
  local S=""; [ -n "${FB_SUDO:-}" ] && S="$FB_SUDO"
  if [ -n "$exclu" ]; then
    $S tar -C "$src" --exclude="./$exclu" -cf - . | $S tar -C "$dst" -xf -
  else
    $S tar -C "$src" -cf - . | $S tar -C "$dst" -xf -
  fi
}

# Copie miroir : la destination devient identique a la source, suppressions comprises.
# Refuse toute destination suspecte.
fb_miroir() {
  local src="$1" dst="$2"
  if [ "${FB_DRY:-0}" -eq 1 ]; then
    printf '  [a blanc] miroir de %s vers %s (suppressions comprises)\n' "$src" "$dst"
    return 0
  fi
  [ -d "$src" ] || mort "source de restauration introuvable : $src"
  case "$dst" in
    ""|"/"|"/*"|"/home"|"/opt"|"/etc"|"/var"|"/usr") mort "destination refusee : $dst" ;;
  esac
  [ "${#dst}" -ge 10 ] || mort "destination trop courte, refusee par securite : $dst"
  [ -d "$dst" ] || mort "destination de restauration introuvable : $dst"
  if command -v rsync >/dev/null 2>&1; then
    sx rsync -a --delete "$src/" "$dst/"
  else
    ( shopt -s dotglob nullglob; local elts=("$dst"/*); [ "${#elts[@]}" -gt 0 ] && sx rm -rf "${elts[@]}" ) || true
    fb_recouvrir "$src" "$dst"
  fi
}

# Masque les secrets d'un flux texte. Utilise par fb-caddy.sh et fb-inventaire.sh.
fb_masquer() {
  sed -E \
    -e 's/\$2[aby]\$[0-9]{2}\$[A-Za-z0-9.\/]+/[MASQUE-HASH]/g' \
    -e 's/(-----BEGIN [A-Z ]*PRIVATE KEY-----).*/\1 [MASQUE]/g' \
    -e 's/(basic_?auth[[:space:]]*\{?[[:space:]]*[A-Za-z0-9_.@-]*[[:space:]]+).*/\1[MASQUE]/Ig' \
    -e 's/((pass|password|passwd|secret|token|apikey|api_key|auth|hash|credential|bearer|dsn|conn(ection)?_?string)[A-Za-z0-9_-]*[[:space:]]*[:=][[:space:]]*)[^[:space:]]+/\1[MASQUE]/Ig' \
    -e 's/(Bearer|Basic)[[:space:]]+[^"'"'"'[:space:]]+/\1 [MASQUE]/Ig' \
    -e 's/\b(sk|pk|rk)[-_](live|test|proj)?[-_]?[A-Za-z0-9_-]{8,}/[MASQUE]/Ig' \
    -e 's/\b(ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{10,}/[MASQUE]/g' \
    -e 's/\bxox[baprs]-[A-Za-z0-9-]{10,}/[MASQUE]/g' \
    -e 's/\bAKIA[0-9A-Z]{16}\b/[MASQUE]/g' \
    -e 's/\b[A-Za-z0-9+]{40,}={0,2}\b/[MASQUE]/g' \
    -e 's#(://[^:/[:space:]]+):[^@[:space:]]+@#\1:[MASQUE]@#g'
}

# ---------------------------------------------------------------- Caddy
# Detecte le mode d'execution de Caddy et le chemin du Caddyfile sur l'hote.
fb_caddy_detect() {
  if [ "${FB_CADDY_MODE:-auto}" = "auto" ]; then
    if command -v docker >/dev/null 2>&1 \
       && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "${FB_CADDY_CONTAINER:-caddy}"; then
      FB_CADDY_MODE="docker"
    elif systemctl list-units --type=service --all --no-pager 2>/dev/null | grep -q '^ *caddy\.service'; then
      FB_CADDY_MODE="systemd"
    else
      FB_CADDY_MODE="inconnu"
    fi
  fi

  if [ -z "${FB_CADDYFILE:-}" ]; then
    case "$FB_CADDY_MODE" in
      docker)
        # Montage dont la destination est le Caddyfile, ou le dossier qui le contient.
        FB_CADDYFILE="$(docker inspect -f \
          '{{range .Mounts}}{{.Source}}|{{.Destination}}{{"\n"}}{{end}}' \
          "${FB_CADDY_CONTAINER:-caddy}" 2>/dev/null \
          | awk -F'|' -v c="${FB_CADDYFILE_CONTENEUR:-/etc/caddy/Caddyfile}" '
              $2==c {print $1; exit}
              $2==gensub(/\/[^\/]+$/,"",1,c) {print $1 "/" gensub(/^.*\//,"",1,c); exit}')"
        ;;
      systemd) FB_CADDYFILE="/etc/caddy/Caddyfile" ;;
    esac
  fi
  [ -n "${FB_CADDYFILE:-}" ] || return 1
  return 0
}

# Valide une configuration. 0 valide, 1 invalide, 2 validation impossible.
fb_caddy_valider() {
  local f="$1"
  case "${FB_CADDY_MODE:-inconnu}" in
    docker)
      command -v docker >/dev/null 2>&1 || return 2
      docker run --rm -v "$f:/tmp/Caddyfile:ro" caddy:2-alpine \
        caddy validate --config /tmp/Caddyfile >/tmp/fb-caddy-valid.$$ 2>&1 && { rm -f /tmp/fb-caddy-valid.$$; return 0; }
      return 1 ;;
    systemd)
      command -v caddy >/dev/null 2>&1 || return 2
      caddy validate --config "$f" >/tmp/fb-caddy-valid.$$ 2>&1 && { rm -f /tmp/fb-caddy-valid.$$; return 0; }
      return 1 ;;
    *) return 2 ;;
  esac
}

# Recharge Caddy sans coupure.
fb_caddy_recharger() {
  case "${FB_CADDY_MODE:-inconnu}" in
    docker)
      docker exec "${FB_CADDY_CONTAINER:-caddy}" \
        caddy reload --config "${FB_CADDYFILE_CONTENEUR:-/etc/caddy/Caddyfile}" 2>&1 ;;
    systemd)
      sx systemctl reload caddy ;;
    *) return 1 ;;
  esac
}
