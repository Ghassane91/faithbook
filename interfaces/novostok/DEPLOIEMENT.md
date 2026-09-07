# Déploiement Hetzner — 7 septembre 2026

Interface : https://veille-novostok.duckdns.org/nouvelle-interface/

L’interface est publiée à côté de FaithBook. Elle contient des données de démonstration ; le raccordement à l’API et à l’authentification reste à réaliser.

- Source de l’interface : commit `57977e8b29fd3d32ff70a36bff3924fb3d1f07f9`, dossier `interfaces/novostok`.
- Fichiers servis : `/opt/integrit/sites/faithbook-interface`.
- Configuration : `/opt/integrit/02-infra/Caddyfile`.
- Sauvegarde et archive des sources : `/opt/integrit/deployments/faithbook-interface/20260907T102456Z`.
- La route `/nouvelle-interface` redirige vers `/nouvelle-interface/` ; le reste du domaine conserve le proxy FaithBook.

## Vérification effectuée

Validation Caddy réussie avant redémarrage. Contrôles HTTPS après publication depuis le serveur et depuis l’extérieur : application existante 200, interface 200, JavaScript et CSS 200, redirection 308. Compilation statique et vérification TypeScript réussies. Pas de test visuel automatisé réalisé.

## Retour arrière

Restaurer le contenu de `Caddyfile.before` dans le Caddyfile existant, en préservant son inode car il est monté dans le conteneur, puis redémarrer Caddy. La sauvegarde se trouve dans le dossier de déploiement ci-dessus. Tenir compte d’éventuelles modifications ultérieures avant toute restauration.
