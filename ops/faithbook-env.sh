#!/usr/bin/env bash
# Configuration commune aux scripts de deploiement, de retour arriere et de verification.
# A adapter une seule fois, puis a laisser tel quel.
# Toute valeur peut aussi etre surchargee par une variable d'environnement.

# --- Emplacements sur le serveur -------------------------------------------
: "${FB_SITE_DIR:=/opt/integrit/sites/faithbook-interface}"
: "${FB_DEPLOY_ROOT:=/opt/integrit/deployments/faithbook-interface}"
: "${FB_SRC_DIR:=/opt/integrit/src/faithbook}"
: "${FB_CADDYFILE:=/etc/caddy/Caddyfile}"

# --- Source du code ---------------------------------------------------------
: "${FB_GIT_URL:=https://github.com/Ghassane91/faithbook.git}"
: "${FB_GIT_REF:=main}"
: "${FB_APP_SUBDIR:=interfaces/novostok}"

# --- Construction -----------------------------------------------------------
# Valeurs lues dans interfaces/novostok/package.json et deploy/vite.config.ts.
# Ne PAS utiliser "npm run build" : cette cible produit la version Cloudflare
# Workers, pas les fichiers statiques servis par Caddy.
: "${FB_INSTALL_CMD:=npm ci}"
: "${FB_BUILD_CMD:=npm run build:hetzner}"
: "${FB_BUILD_OUT:=dist-hetzner}"
# Node >= 22.13.0 requis (champ engines du package.json).
: "${FB_NODE_MIN:=22.13.0}"

# --- Adresses publiques -----------------------------------------------------
: "${FB_BASE_URL:=https://veille-novostok.duckdns.org}"
: "${FB_PATH:=/nouvelle-interface/}"

# --- Retention des sauvegardes ---------------------------------------------
: "${FB_KEEP_BACKUPS:=10}"

# --- Divers -----------------------------------------------------------------
: "${FB_CURL_TIMEOUT:=20}"
