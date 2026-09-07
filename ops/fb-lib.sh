#!/usr/bin/env bash
# Fonctions communes aux scripts FaithBook. N'est pas destine a etre lance seul.

FB_LOG=""

log()   { local m; m="$(date -u +%H:%M:%S)  $*"; printf '%s\n' "$m"; _journal "$m"; }
etape() { local m; m="== $*"; printf '\n%s\n' "$m"; _journal "" ; _journal "$m"; }
mort()  { printf '\nECHEC : %s\n' "$*" >&2; _journal "ECHEC : $*"; exit 1; }
_journal() { [ -n "$FB_LOG" ] && printf '%s\n' "$1" >> "$FB_LOG" 2>/dev/null; return 0; }

# Elevation : uniquement si le dossier cible n'est pas accessible en ecriture.
fb_sudo_init() {
  FB_SUDO=""
  local cible="$1"
  if [ -e "$cible" ] && [ ! -w "$cible" ]; then
    command -v sudo >/dev/null 2>&1 && FB_SUDO="sudo"
  elif [ ! -e "$cible" ] && [ ! -w "$(dirname "$cible")" ]; then
    command -v sudo >/dev/null 2>&1 && FB_SUDO="sudo"
  fi
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
  if [ -n "$exclu" ]; then
    tar -C "$src" --exclude="./$exclu" -cf - . | { [ -n "${FB_SUDO:-}" ] && $FB_SUDO tar -C "$dst" -xf - || tar -C "$dst" -xf -; }
  else
    tar -C "$src" -cf - . | { [ -n "${FB_SUDO:-}" ] && $FB_SUDO tar -C "$dst" -xf - || tar -C "$dst" -xf -; }
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
