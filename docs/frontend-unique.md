# Frontend unique FaithBook × HuntX

Depuis le 12 octobre 2026, `/application/` et `/nouvelle-interface/` servent le même frontend, compilé à partir de `frontend/`. L’entrée DuckDNS `/` rejoint `/nouvelle-interface/` et reçoit donc aussi cette interface. La configuration existante sur le port 8081 rejoint cette même entrée HTTPS.

La présentation de référence est celle de `/application/?v=fb647f8#/accueil` : fond noir, texte blanc, accents orange et navigation FaithBook. L’accueil conserve cette présentation. Les aperçus HuntX sont disponibles dans « Archives HuntX » (`#/huntx`), avec toutes les dates, les lignes et les marchands. L’accès en lecture seule reste contrôlé par le backend.

Le code actif est `frontend/`. `interfaces/novostok` et `/opt/integrit/sites/faithbook-interface` sont conservés comme ancienne interface et sauvegarde ; ils ne sont plus servis. Les anciennes commandes de publication de ce site statique n’actualisent donc pas le frontend actif.

## Publication sur Hetzner

Compiler et vérifier `frontend/` (`npm ci`, `npm run build`). Produire un patch limité aux fichiers du frontend contre l’état déployé et le transférer avec `ops/deployer-frontend-unique.sh` sur le serveur. Publier le commit sur GitHub, puis exécuter :

```bash
sudo bash /home/ghassane/deployer-frontend-unique.sh /home/ghassane/faithbook-frontend-unique.patch SHA_GITHUB
```

Le script vérifie le patch, conserve les sources et l’image précédentes, construit uniquement le service frontend et fait converger le routage Caddy. Il conserve les anciens actifs à empreinte pour les onglets déjà ouverts. Les index des deux adresses et de l’entrée racine doivent être identiques, les CSS/JS disponibles et les API protégées.

Le Caddyfile est `/opt/integrit/02-infra/Caddyfile`, monté dans le conteneur `caddy` à `/etc/caddy/Caddyfile`. Seul le bloc `/nouvelle-interface/*` est remplacé par un relais vers `faithbook-frontend:80`. Le fichier est modifié en place pour préserver son montage. La configuration est validée avant rechargement.

Caddy 2.11.4 est lancé avec `caddy run --config ...`, sans `--resume`, avec l’API administrative désactivée. Le rechargement utilise `SIGUSR1`, pris en charge depuis Caddy 2.11 dans ces conditions : [documentation officielle](https://caddyserver.com/docs/command-line#signals). Aucun redémarrage du backend ou du worker n’est nécessaire.

La sauvegarde de chaque publication se trouve sous `/opt/integrit/backups/faithbook/frontend-unique-*`. Le script restaure les sources, l’image et la configuration Caddy en cas d’échec. Le fichier `COMPLETE` n’est écrit qu’après les contrôles HTTP. Une ancienne page déjà ouverte doit être actualisée pour afficher le nouveau frontend.
