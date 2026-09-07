# FaithBook — interface Novostok

Prototype interactif en français inspiré de novostok.com : noir #080808, ivoire #e8e6e3, Cormorant Garamond et Inter. Tableau de bord, recherche et filtres, navigation cibles/archives, fiches de collecte.

**Données de démonstration uniquement.** L'API, l'authentification, les captures réelles et la gestion des cibles ne sont pas raccordées. Ce prototype doit rester à côté de l'application existante.

## Hébergement Hetzner

Node.js 22.13 ou supérieur est nécessaire pour compiler, mais aucun serveur Node n'est requis en production.

```sh
npm ci
npm run build:hetzner
```

Servir le contenu de `dist-hetzner/` par Caddy au chemin `/nouvelle-interface/`. `deploy/Caddy.snippet` contient le bloc à intégrer au site HTTPS FaithBook après vérification de la configuration réelle. Le montage Caddy attendu est `/opt/integrit/sites:/srv/sites:ro`.

Avant modification, sauvegarder le Caddyfile actuel. Valider la configuration avec `caddy validate` avant de la charger. Ne pas remplacer le proxy de l'application existante. Si la configuration contient `admin off`, le rechargement Caddy nécessite la procédure de redémarrage utilisée sur le serveur.

## Développement et version Sites

`npm run dev` et `npm run build` conservent la version Vinext/Sites d'origine. La compilation `build:hetzner` utilise la même interface React et produit des fichiers statiques indépendants de Sites, sans identifiants intégrés.

## Vérifications

Compilation production et TypeScript. Les données, URL de sources et historiques sont illustratifs. L'outil WebMCP optionnel `read_demo_sources` n'a pas été vérifié dans un navigateur compatible ; son absence n'affecte pas l'interface.
