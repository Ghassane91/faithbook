#!/usr/bin/env bash
# Verifications HTTP de la nouvelle interface FaithBook et de l'application historique.
# Usage : ./fb-verifier.sh
# Code de sortie : 0 si tous les controles passent, 1 sinon.

set -Eeuo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=faithbook-env.sh
. "$HERE/faithbook-env.sh"

FAIL=0
PASS=0

_c() { printf '%s' "$1"; }
ok()   { PASS=$((PASS+1)); printf '  [ OK ] %s\n' "$1"; }
ko()   { FAIL=$((FAIL+1)); printf '  [ KO ] %s\n' "$1"; }

code_of() {
  local out
  out="$(curl -sS -o /dev/null -w '%{http_code}' --max-time "$FB_CURL_TIMEOUT" "$1" 2>/dev/null)" || out=""
  case "$out" in ''|*[!0-9]*) out="000" ;; esac
  printf '%s' "$out"
}

attendu() {
  local url="$1" want="$2" label="$3" got
  got="$(code_of "$url")"
  if [ "$got" = "$want" ]; then
    ok "$label — $got"
  else
    if [ "$got" = "000" ]; then
      ko "$label — serveur injoignable  ($url)"
    else
      ko "$label — attendu $want, obtenu $got  ($url)"
    fi
  fi
}

base="${FB_BASE_URL%/}"
chemin="${FB_PATH}"
url_new="${base}${chemin}"
url_new_noslash="${base}${chemin%/}"

echo "Verification FaithBook — $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "Base : $base"
echo

echo "1. Pages"
attendu "$url_new"          "200" "Nouvelle interface"
attendu "$url_new_noslash"  "308" "Redirection du chemin sans barre finale"
# La racine peut renvoyer 200 (ancien routage) ou une redirection vers la
# nouvelle interface (routage du 8 septembre 2026). Les deux sont valides.
racine="$(code_of "${base}/")"
case "$racine" in
  200)         ok "Racine — 200 (sert directement une interface)" ;;
  301|302|308) ok "Racine — $racine (redirige vers la nouvelle interface)" ;;
  000)         ko "Racine — serveur injoignable" ;;
  *)           ko "Racine — attendu 200 ou une redirection, obtenu $racine" ;;
esac
attendu "${base}${FB_LEGACY_PATH:-/application/}" "200" "Application historique"

echo
echo "2. Actifs references par l'index"
html="$(curl -sS --max-time "$FB_CURL_TIMEOUT" "$url_new" 2>/dev/null || true)"
if [ -z "$html" ]; then
  ko "Index vide ou injoignable, actifs non verifies"
else
  # Extraction des src/href pointant vers des .js et .css
  mapfile -t actifs < <(
    printf '%s' "$html" \
      | grep -Eo '(src|href)="[^"]+\.(js|css)"' \
      | sed -E 's/^(src|href)="//; s/"$//' \
      | sort -u
  )
  if [ "${#actifs[@]}" -eq 0 ]; then
    ko "Aucun fichier .js ou .css reference dans l'index"
  else
    for a in "${actifs[@]}"; do
      case "$a" in
        http://*|https://*) u="$a" ;;
        /*)                 u="${base}${a}" ;;
        *)                  u="${url_new}${a}" ;;
      esac
      attendu "$u" "200" "Actif $(basename "$a")"
    done
  fi
fi

echo
echo "3. Routes API sans session (401 attendu)"
for route in /api/auth/me /api/targets /api/runs; do
  got="$(code_of "${base}${route}")"
  case "$got" in
    401)     ok  "$route — 401" ;;
    404)     ko  "$route — 404, route inexistante ou chemin API different (a confirmer)" ;;
    200)     ko  "$route — 200 SANS SESSION, fuite de donnees potentielle" ;;
    *)       ko  "$route — attendu 401, obtenu $got" ;;
  esac
done

echo
echo "4. Type de contenu des routes API (JSON attendu, jamais du HTML)"
for route in /api/targets /api/runs; do
  ct="$(curl -sS -o /dev/null -w '%{content_type}' --max-time "$FB_CURL_TIMEOUT" "${base}${route}" 2>/dev/null || echo "")"
  case "$ct" in
    *json*) ok "$route — $ct" ;;
    "")     ko "$route — pas de type de contenu" ;;
    *html*) ko "$route — $ct, page HTML de repli servie a la place des donnees" ;;
    *)      ko "$route — type inattendu : $ct" ;;
  esac
done

echo
echo "5. Certificat TLS"
hote="${base#https://}"; hote="${hote%%/*}"
if command -v openssl >/dev/null 2>&1; then
  fin="$(echo | openssl s_client -servername "$hote" -connect "${hote}:443" 2>/dev/null \
         | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2 || true)"
  if [ -n "$fin" ]; then
    fin_ts="$(date -d "$fin" +%s 2>/dev/null || echo 0)"
    now_ts="$(date +%s)"
    if [ "$fin_ts" -gt 0 ]; then
      jours=$(( (fin_ts - now_ts) / 86400 ))
      if [ "$jours" -lt 15 ]; then
        ko "Certificat expire dans $jours jours ($fin)"
      else
        ok "Certificat valide encore $jours jours ($fin)"
      fi
    else
      ko "Date d'expiration du certificat illisible : $fin"
    fi
  else
    ko "Certificat non lisible pour $hote"
  fi
else
  echo "  [ -- ] openssl absent, controle du certificat ignore"
fi

echo
echo "Resultat : $PASS controle(s) reussi(s), $FAIL en echec."
[ "$FAIL" -eq 0 ] || exit 1
