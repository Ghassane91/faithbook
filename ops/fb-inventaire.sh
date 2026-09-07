#!/usr/bin/env bash
# Inventaire du serveur FaithBook.
# Ne modifie rien. Produit un rapport unique, secrets masques.
#
# Usage :
#   ./fb-inventaire.sh                 # affiche le rapport
#   ./fb-inventaire.sh > inventaire.txt
#
# Objectif : lever les hypotheses de la procedure de deploiement (commande de
# construction, dossier de sortie, routes API, Caddyfile, service, sauvegardes).

set -Euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[ -f "$HERE/faithbook-env.sh" ] && . "$HERE/faithbook-env.sh"
[ -f "$HERE/fb-lib.sh" ] && . "$HERE/fb-lib.sh"

: "${FB_SITE_DIR:=/opt/integrit/sites/faithbook-interface}"
: "${FB_DEPLOY_ROOT:=/opt/integrit/deployments/faithbook-interface}"
: "${FB_SRC_DIR:=/opt/integrit/src/faithbook}"
: "${FB_CADDYFILE:=/etc/caddy/Caddyfile}"
: "${FB_BASE_URL:=https://veille-novostok.duckdns.org}"
: "${FB_PATH:=/nouvelle-interface/}"

titre() { printf '\n\n===== %s =====\n' "$*"; }
sous()  { printf '\n--- %s\n' "$*"; }
absent(){ printf '  (absent : %s)\n' "$*"; }

# Masque toute ligne susceptible de contenir un secret.
masquer() {
  if declare -F fb_masquer >/dev/null 2>&1; then fb_masquer; else cat; fi
}

printf 'INVENTAIRE FAITHBOOK\n'
printf 'Date UTC   : %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
printf 'Date locale: %s\n' "$(date +%Y-%m-%dT%H:%M:%S%z)"
printf 'Hote       : %s\n' "$(hostname)"
printf 'Utilisateur: %s\n' "$(id -un)"

titre "1. SYSTEME"
sous "Distribution"
[ -f /etc/os-release ] && grep -E '^(PRETTY_NAME|VERSION)=' /etc/os-release || absent /etc/os-release
sous "Noyau, disponibilite, charge"
uname -srm; uptime
sous "Fuseau horaire"
timedatectl 2>/dev/null | sed -n '1,6p' || cat /etc/timezone 2>/dev/null || absent "timedatectl"
sous "Espace disque"
df -h / /opt 2>/dev/null | sort -u
sous "Memoire"
free -h 2>/dev/null || absent free
sous "Mises a jour en attente"
if command -v apt >/dev/null 2>&1; then
  apt list --upgradable 2>/dev/null | tail -n +2 | wc -l | sed 's/^/  paquets a mettre a jour : /'
  [ -f /var/run/reboot-required ] && printf '  REDEMARRAGE REQUIS\n'
fi

titre "2. OUTILS DE CONSTRUCTION"
for c in node npm pnpm yarn git caddy rsync unzip tar curl openssl; do
  if command -v "$c" >/dev/null 2>&1; then
    case "$c" in
      openssl) v="$(openssl version 2>/dev/null)" ;;
      unzip)   v="$(unzip -v 2>/dev/null | head -1)" ;;
      curl)    v="$(curl --version 2>/dev/null | head -1 | cut -d' ' -f1-2)" ;;
      caddy)   v="$(caddy version 2>/dev/null | head -1)" ;;
      *)       v="$("$c" --version 2>/dev/null | head -1)" ;;
    esac
    printf '  %-8s %s\n' "$c" "${v:-present}"
  else
    printf '  %-8s ABSENT\n' "$c"
  fi
done

titre "3. DOSSIER SERVI"
sous "$FB_SITE_DIR"
if [ -d "$FB_SITE_DIR" ]; then
  ls -la "$FB_SITE_DIR" | head -30
  printf '\n  fichiers totaux : %s\n' "$(find "$FB_SITE_DIR" -type f 2>/dev/null | wc -l)"
  printf '  taille          : %s\n' "$(du -sh "$FB_SITE_DIR" 2>/dev/null | cut -f1)"
  sous "index.html (entete)"
  head -c 1200 "$FB_SITE_DIR/index.html" 2>/dev/null || absent index.html
  printf '\n'
  sous "Actifs references par l'index"
  grep -Eo '(src|href)="[^"]+\.(js|css)"' "$FB_SITE_DIR/index.html" 2>/dev/null | sort -u || printf '  aucun\n'
else
  absent "$FB_SITE_DIR"
fi

titre "4. SAUVEGARDES DE DEPLOIEMENT"
sous "$FB_DEPLOY_ROOT"
if [ -d "$FB_DEPLOY_ROOT" ]; then
  ls -la "$FB_DEPLOY_ROOT"
  printf '\n  taille totale : %s\n' "$(du -sh "$FB_DEPLOY_ROOT" 2>/dev/null | cut -f1)"
else
  absent "$FB_DEPLOY_ROOT"
fi

titre "5. SOURCES ET CONSTRUCTION"
sous "$FB_SRC_DIR"
if [ -d "$FB_SRC_DIR" ]; then
  printf '  depot present\n'
  git -C "$FB_SRC_DIR" log -1 --format='  commit : %H%n  date   : %ci%n  sujet  : %s' 2>/dev/null
  git -C "$FB_SRC_DIR" branch --show-current 2>/dev/null | sed 's/^/  branche: /'
else
  absent "$FB_SRC_DIR"
fi
sous "package.json de l'interface (scripts et champs cles)"
PKG=""
for p in "$FB_SRC_DIR/interfaces/novostok/package.json" \
         /opt/*/faithbook/interfaces/novostok/package.json \
         "$HOME"/*/interfaces/novostok/package.json; do
  [ -f "$p" ] && { PKG="$p"; break; }
done
if [ -n "$PKG" ]; then
  printf '  fichier : %s\n\n' "$PKG"
  if command -v node >/dev/null 2>&1; then
    node -e '
      const p=require(process.argv[1]);
      console.log("  name       :",p.name||"—");
      console.log("  scripts    :");
      for (const [k,v] of Object.entries(p.scripts||{})) console.log("    "+k+" = "+v);
      const d=Object.keys(p.dependencies||{}), D=Object.keys(p.devDependencies||{});
      console.log("  outil build:", [...d,...D].filter(x=>/vite|webpack|parcel|rollup|next|esbuild/.test(x)).join(", ")||"non identifie");
    ' "$PKG" 2>/dev/null
  else
    grep -A20 '"scripts"' "$PKG" | head -25
  fi
else
  absent "package.json de interfaces/novostok"
  printf '  Chercher manuellement : find / -path /proc -prune -o -name package.json -path "*novostok*" -print 2>/dev/null\n'
fi
sous "Configuration de construction (dossier de sortie)"
if [ -n "$PKG" ]; then
  d="$(dirname "$PKG")"
  for f in vite.config.ts vite.config.js next.config.js webpack.config.js; do
    [ -f "$d/$f" ] && { printf '  %s :\n' "$f"; sed -n '1,40p' "$d/$f" | sed 's/^/    /'; }
  done
  for o in dist build out .next; do
    [ -d "$d/$o" ] && printf '  dossier de sortie present : %s (%s fichiers)\n' "$o" "$(find "$d/$o" -type f | wc -l)"
  done
fi

titre "6. CADDY"
sous "Service"
systemctl status caddy --no-pager 2>/dev/null | sed -n '1,8p' || absent "service caddy"
sous "Caddyfile : $FB_CADDYFILE (secrets masques)"
if [ -f "$FB_CADDYFILE" ]; then
  masquer < "$FB_CADDYFILE"
else
  absent "$FB_CADDYFILE"
  printf '  Chercher : sudo find /etc -name Caddyfile 2>/dev/null\n'
fi
sous "Validation de la configuration"
command -v caddy >/dev/null 2>&1 && caddy validate --config "$FB_CADDYFILE" 2>&1 | tail -5 || absent caddy

titre "7. SERVICE FAITHBOOK"
sous "Unites systemd correspondantes"
systemctl list-units --type=service --all --no-pager 2>/dev/null \
  | grep -Ei 'faith|planche|veille|novostok|integrit' || printf '  aucune unite correspondante\n'
sous "Ports en ecoute"
(ss -tlnp 2>/dev/null || netstat -tlnp 2>/dev/null) | head -25
sous "Conteneurs Docker"
command -v docker >/dev/null 2>&1 && docker ps --format '  {{.Names}}  {{.Image}}  {{.Status}}  {{.Ports}}' 2>/dev/null || printf '  docker absent ou inaccessible\n'

titre "8. ROUTES API"
printf '  Recherche des definitions de routes dans les sources trouvees.\n'
ROOTS=""
[ -d "$FB_SRC_DIR" ] && ROOTS="$FB_SRC_DIR"
[ -n "$PKG" ] && ROOTS="$ROOTS $(dirname "$(dirname "$(dirname "$PKG")")")"
if [ -n "${ROOTS// /}" ]; then
  # shellcheck disable=SC2086
  grep -rhoE "(app|router)\.(get|post|put|patch|delete)\(['\"][^'\"]+" $ROOTS \
       --include='*.ts' --include='*.js' --include='*.tsx' 2>/dev/null \
    | sed -E "s/.*\(['\"]//" | sort -u | head -60 | sed 's/^/  /' || printf '  aucune route trouvee\n'
  printf '\n  Appels API cote client :\n'
  # shellcheck disable=SC2086
  grep -rhoE "['\"]/api/[A-Za-z0-9_/-]+" $ROOTS \
       --include='*.ts' --include='*.tsx' --include='*.js' 2>/dev/null \
    | tr -d "'\"" | sort -u | head -40 | sed 's/^/  /' || printf '  aucun appel trouve\n'
else
  printf '  sources introuvables sur le serveur, section ignoree\n'
fi

titre "9. VARIABLES D'ENVIRONNEMENT (NOMS SEULEMENT, VALEURS JAMAIS AFFICHEES)"
for e in "$FB_SRC_DIR/.env" /opt/integrit/.env /etc/faithbook/.env; do
  if [ -f "$e" ]; then
    printf '  %s :\n' "$e"
    grep -oE '^[A-Za-z_][A-Za-z0-9_]*' "$e" 2>/dev/null | sed 's/^/    /'
  fi
done
printf '  (aucune valeur n a ete lue)\n'

titre "10. SAUVEGARDE SYSTEME"
sous "Outils de sauvegarde installes"
for b in restic borg borgmatic duplicity rsnapshot rclone; do
  command -v "$b" >/dev/null 2>&1 && printf '  %s present\n' "$b"
done
sous "Taches planifiees"
crontab -l 2>/dev/null | grep -v '^#' | grep -v '^$' | sed 's/^/  /' || printf '  aucune crontab utilisateur\n'
ls /etc/cron.d/ 2>/dev/null | sed 's/^/  \/etc\/cron.d\/: /'
sous "Timers systemd actifs"
systemctl list-timers --no-pager 2>/dev/null | head -15

titre "11. CONTROLES HTTP"
base="${FB_BASE_URL%/}"
for u in "${base}${FB_PATH}" "${base}${FB_PATH%/}" "${base}/"; do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 15 "$u" 2>/dev/null)" || code=""
  case "$code" in ''|000|*[!0-9]*) code="injoignable" ;; esac
  printf '  %-70s %s\n' "$u" "$code"
done
sous "Certificat TLS"
hote="${base#https://}"; hote="${hote%%/*}"
command -v openssl >/dev/null 2>&1 && \
  echo | openssl s_client -servername "$hote" -connect "${hote}:443" 2>/dev/null \
  | openssl x509 -noout -subject -issuer -dates 2>/dev/null | sed 's/^/  /' \
  || printf '  openssl absent\n'

titre "12. DNS"
for t in A AAAA; do
  printf '  %s : %s\n' "$t" "$( (dig +short "$t" "$hote" 2>/dev/null || host -t "$t" "$hote" 2>/dev/null) | tr '\n' ' ')"
done

printf '\n\n===== FIN DE L INVENTAIRE =====\n'
printf 'Verifier ce rapport avant de le transmettre : aucun mot de passe, aucune cle.\n'
