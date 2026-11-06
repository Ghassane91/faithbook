# FaithBook — interface Novostok

Interface de consultation connectée à l’API FaithBook, en français, inspirée de novostok.com.

## Fonctions

- Connexion et déconnexion avec le compte FaithBook existant et le cookie de session HttpOnly.
- Choix d’un espace accessible au compte ; chaque requête de données précise son organisation.
- Cibles actives/en pause, recherche et filtres Facebook/site web.
- Tableau de bord par date : réussites, échecs, taux sur les collectes terminées, évolution sur sept jours.
- Archives filtrées par date, cible et état, avec pagination côté serveur.
- Fiche de capture : aperçu, erreur éventuelle, stockage, synthèse disponible, journal et téléchargement.
- Export de la planche PDF de la journée.
- Gestion des cibles, des comptes et de l’équipe via le lien vers l’application complète.

Aucune donnée de démonstration ni aucun identifiant n’est intégré au code. Une session absente mène à la connexion ; une panne affiche une erreur et un bouton de nouvelle tentative. Les données de l’espace précédent sont retirées lors d’un changement d’espace.

## Hébergement Hetzner

```sh
npm ci
npm run build:hetzner
```

Node.js 22.13 ou supérieur pour compiler. Servir `dist-hetzner/` à `/nouvelle-interface/` sur la même origine que `/api/`. Le navigateur utilise le relais API existant, sans clé API ni changement CORS. Caddy sert les fichiers statiques ; aucun service Node supplémentaire n’est nécessaire.

`deploy/Caddy.snippet` documente le routage initial. Une fois celui-ci installé, une mise à jour remplace uniquement les fichiers de l’interface. Sauvegarder la version précédente avant remplacement. Voir `DEPLOIEMENT.md` pour l’état du serveur.

## Validation

```sh
node --experimental-strip-types --test tests/faithbook-api.test.mjs
npx tsc --noEmit
npm run build:hetzner
```

Douze tests de contrat client couvrent notamment cookies, en-têtes d’organisation, requêtes concurrentes, annulation, réponses 401/403, téléchargements, filtres, fuseaux horaires et absence de statistiques inventées. Aucun test avec les identifiants personnels du compte de production n’est exécuté.

## Version Sites

La configuration Vinext d’origine reste disponible (`npm run dev`, `npm run build`). La version connectée exige une API FaithBook sur la même origine ; la publier seule sur un autre domaine ne suffit pas. La maquette Sites publiée précédemment n’est pas modifiée par le déploiement Hetzner.
