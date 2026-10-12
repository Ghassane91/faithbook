# Frontend FaithBook × HuntX

Refonte préparée et compilée le 12 octobre 2026. La palette est relevée sur la page de connexion HuntX : fond `#08090B`, surface `#0C0E10`, orange `#CC5500`, accent `#E0724E`, texte `#E8E6E3`, gris `#8A97A3`.

Le tableau de bord affiche le bilan de la dernière campagne HuntX, sa progression, les dossiers Drive, la prochaine prise et l’état des appareils Chrome et du secours Zyte. Les données sont actualisées toutes les 30 secondes et suivent l’organisation sélectionnée. La navigation et l’authentification existantes sont conservées. L’écran Chrome déjà installé sur Hetzner est également versionné pour conserver cette navigation dans une compilation du dépôt.

Les API `/api/browser-capture/archive`, `/api/browser-capture/devices`, `/api/browser-capture/zyte` (administrateurs) et `/api/scheduler/jobs` doivent être disponibles sur le backend. Elles sont déjà installées sur le serveur Hetzner ; cette livraison frontend ne redéploie pas le backend ni le worker. Un backend dépourvu de ces API affichera une erreur de chargement des archives, sans inventer de résultats.

Vérification locale : `cd frontend`, `npm ci`, `npm run build`. L’aperçu illustratif et son image ne sont pas inclus dans cette publication de production.

Le script `ops/deployer-huntx-frontend.sh` applique le patch de cette refonte à l’état préalable du serveur, conserve une archive des sources et une image Docker de retour arrière, puis reconstruit uniquement le service frontend. Usage : `sudo bash ops/deployer-huntx-frontend.sh /home/ghassane/faithbook-huntx-frontend.patch SHA_DU_COMMIT`. Il refuse un état déjà modifié et restaure automatiquement l’ancienne interface si la construction ou le contrôle de santé échoue. Les sauvegardes restent réservées à root sous `/opt/integrit/backups/faithbook/`.
