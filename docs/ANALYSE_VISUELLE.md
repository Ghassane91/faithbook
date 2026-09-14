# FaithBook — analyse des captures

## Parcours
Ouvrir l'interface FaithBook à `/#/analyse` après connexion.
Importer 1 à 4 captures PNG/JPEG/WebP, ou choisir les captures existantes d'une même cible.
Pour les imports, donner un nom stable à la source et poser
une question libre. Les images sont réellement transmises au modèle multimodal
configuré. Les données de l'image ne sont jamais exécutées comme des instructions.

La synthèse, les produits, les prix et les extraits justificatifs sont conservés
dans une analyse appartenant à l'organisation active. Export CSV (formules
neutralisées), JSON et Markdown. Les prix inconnus restent null. Un rapprochement
exige une marque et une référence ; comparer des prix exige aussi la même devise,
la même taxe et la même taille de lot. Une absence signifie « non observé ».

## Configuration serveur
Fonction désactivée par défaut, sans aucune clé dans le navigateur ni le dépôt.

- VISUAL_ANALYSIS_ENABLED=true
- VISUAL_ANALYSIS_PROVIDER=anthropic ou ollama
- VISUAL_ANALYSIS_MODEL : identifiant explicite d'un modèle qui accepte les images
- ANTHROPIC_API_KEY : clé privée côté serveur pour Anthropic
- OLLAMA_BASE_URL : service Ollama existant pour un modèle visuel local
- VISUAL_ANALYSIS_DAILY_LIMIT=20 : plafond par organisation et par jour Casablanca

Les longues captures doivent être recadrées en zones de 3000 pixels maximum.
Limites : 6 Mo/image, 4 images, 16 mégapixels. Le fournisseur reçoit une copie JPEG
sans métadonnées ; les originaux sont conservés localement et archivés.

Le déploiement nécessite de reconstruire le backend et le frontend depuis cette
branche. La migration Alembic ajoute uniquement visual_analyses. Les anciennes
captures et les autres services ne sont pas modifiés.

## Google Drive partagé
Réutilise la configuration privée existante :
STORAGE_BACKEND=google_drive, GOOGLE_SERVICE_ACCOUNT_FILE,
GOOGLE_DRIVE_PARENT_FOLDER_ID et GOOGLE_DRIVE_SHARED_DRIVE_ID.
Partager le dossier avec le compte de service en lui permettant d'ajouter des
fichiers. Monter sa clé dans /secrets en lecture seule. Ne pas la mettre dans Git.

Arborescence sous le dossier configuré :
YYYY-MM-DD / organisation-ID / analyse-UUID /
originaux + resultats.json + resultats.csv + synthese.md.
La date est celle de la création de l'analyse en Africa/Casablanca, même lors d'une
reprise le lendemain. Les résultats restent disponibles si Drive échoue.
Chaque reçu est enregistré : la reprise ne relance pas l'IA. Les noms distants
incluent l'empreinte du contenu. « Archivé » exige les reçus de tous les fichiers.

Le dossier parent Drive est global à cette installation : ses permissions Workspace
doivent être réservées aux personnes autorisées à voir toutes les organisations
archivées. Les sous-dossiers ne constituent pas une isolation de permissions Drive.

## Vérifications
tests/test_visual_analysis.py couvre des pixels PNG réels, validation, refus des
prix ambigus, comparaison, accès par organisation, exports, requête multimodale
simulée et reprise d'un Drive simulé. La CI existante exécute pytest et compile
l'interface. Ces tests ne sont pas une mesure de précision d'un modèle réel.

Recette de production à effectuer avec les accès privés configurés :
1. Importer deux captures de test de la même source avec une référence et un prix
   modifié ; vérifier les extraits et le calcul.
2. Importer un prix illisible : il ne doit pas être inventé.
3. Ouvrir le dossier Drive et vérifier les quatre fichiers pour une capture.
4. Tester un refus d'accès Drive puis une reprise, sans deuxième appel IA.
5. Vérifier l'interface sur téléphone et la navigation arrière.
6. Relever les coûts et temps réels avant d'augmenter le plafond quotidien.

## Limites explicites de cette version
Pas de surveillance automatique ni d'exécution de commandes ; l'analyse est
déclenchée par l'utilisateur. Les captures sont importées depuis l'appareil ou copiées depuis les exécutions FaithBook.
Les analyses réservent le poids des originaux plus 1 Mo pour les résultats dans le quota
organisation. La comparaison suit l'ordre de création des analyses : pour comparer
chronologiquement des exécutions, analyser d'abord la capture la plus ancienne.
Les résultats sont exportables, mais l'édition en ligne n'est pas incluse.
La suppression dans FaithBook retire uniquement la copie locale ; la copie Drive
reste sous le contrôle de l'équipe Workspace. La rétention des analyses est
manuelle dans cette première version, distincte de celle des captures programmées.

Sources des protocoles : https://platform.claude.com/docs/en/build-with-claude/vision
et https://docs.ollama.com/api/chat .
