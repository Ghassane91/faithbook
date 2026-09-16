#!/usr/bin/env bash
# Teste l'extraction sur une capture REELLE, sans rien casser ni rien ecrire.
#
# Le conteneur backend embarque le code au moment de sa construction : il ne
# connait donc pas encore extraction.py. Ce script y depose les deux fichiers
# necessaires le temps du test, puis REMET les versions d'origine en sortant,
# quel que soit le resultat. Aucune image n'est reconstruite, aucun service
# n'est redemarre, aucune ecriture en base.
#
#   ./ops/tester-extraction.sh --lister
#   ./ops/tester-extraction.sh --cible 12
#   ./ops/tester-extraction.sh --cible 12 --invite     (aucun appel au modele)
#   ./ops/tester-extraction.sh --run 8421 --regle forfaits

set -euo pipefail

SRC="${FB_SRC_DIR:-/opt/integrit/src/faithbook}"
CONTENEUR="${FB_CONTENEUR_BACKEND:-faithbook-backend}"

cd "$SRC" 2>/dev/null || { echo "Depot introuvable : $SRC" >&2; exit 1; }

for f in app/services/extraction.py app/config.py ops/tester-extraction.py; do
  [ -f "$f" ] || { echo "Fichier manquant : $SRC/$f" >&2; exit 1; }
done

if ! docker inspect -f '{{.State.Running}}' "$CONTENEUR" 2>/dev/null | grep -q true; then
  echo "Le conteneur $CONTENEUR ne tourne pas." >&2
  echo "Verifier avec : docker compose ps" >&2
  exit 1
fi

# --- Controle de la configuration, sans jamais afficher la cle --------------
if [ -f .env ]; then
  if grep -q '^ANTHROPIC_API_KEY=.\+' .env; then cle="renseignee"; else cle="ABSENTE"; fi
  act="$(grep -m1 '^EXTRACTION_ENABLED=' .env | cut -d= -f2 || true)"
  echo "  .env : ANTHROPIC_API_KEY ${cle} | EXTRACTION_ENABLED=${act:-absent}"
  echo
fi

SAUVE="$(mktemp -d)"
restaurer() {
  for f in app/config.py app/services/extraction.py; do
    if [ -f "$SAUVE/$(basename "$f")" ]; then
      docker cp "$SAUVE/$(basename "$f")" "$CONTENEUR:/app/$f" >/dev/null 2>&1 || true
    fi
  done
  rm -rf "$SAUVE"
  echo
  echo "  Conteneur remis dans son etat d'origine."
}
trap restaurer EXIT

# Copie de sortie : ce qui est actuellement DANS le conteneur.
docker cp "$CONTENEUR:/app/app/config.py" "$SAUVE/config.py" >/dev/null 2>&1 || true
docker cp "$CONTENEUR:/app/app/services/extraction.py" "$SAUVE/extraction.py" >/dev/null 2>&1 || true

# Depot temporaire des versions a tester.
docker cp app/config.py "$CONTENEUR:/app/app/config.py" >/dev/null
docker cp app/services/extraction.py "$CONTENEUR:/app/app/services/extraction.py" >/dev/null

# Le script de test passe par l'entree standard : rien n'est ecrit dans l'image.
docker exec -i -e PYTHONPATH=/app -w /app "$CONTENEUR" \
  python - "$@" < ops/tester-extraction.py
