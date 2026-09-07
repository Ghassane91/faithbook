# Déploiement Hetzner — interface connectée

Adresse : https://veille-novostok.duckdns.org/nouvelle-interface/

Mise à jour du 7 septembre 2026 à 10:51 UTC : l’interface utilise désormais l’API FaithBook de la même origine, avec le cookie de session existant. Aucune donnée de démonstration ni aucun identifiant n’est intégré.

Connexion, sélection d’espace, cibles, statistiques par date, archives paginées, aperçus, téléchargements et planche PDF sont raccordés. Les modifications de cibles et la gestion des comptes restent accessibles dans l’application complète.

- Source : `9a460430984d3c650dce19f1114d330cd5be6472`, dossier `interfaces/novostok`.
- Fichiers servis : `/opt/integrit/sites/faithbook-interface`.
- Sauvegarde avant cette mise à jour : `/opt/integrit/deployments/faithbook-interface/20260907T105154Z/site.before`.
- Archive des sources et manifeste : même dossier de déploiement.
- Aucun changement Caddy ni redémarrage pour cette mise à jour. L’index est publié après les nouveaux fichiers à empreinte ; les anciens fichiers restent disponibles pour les onglets déjà ouverts.

## Validation

12 tests de contrat client réussis, vérification TypeScript et compilation statique réussies. Après déploiement : interface, JavaScript, CSS et application existante en HTTP 200 sur HTTPS ; redirection du chemin sans slash en 308. Le contenu des fichiers servis a été comparé à celui de la compilation testée. Les routes `/api/auth/me`, `/api/targets` et `/api/runs` retournent 401 sans session, comme attendu.

Aucun test avec les identifiants personnels du compte de production ni test visuel automatisé n’a été effectué. Les tests automatisés vérifient les contrats du client ; une connexion utilisateur normale reste nécessaire pour consulter ses données.

## Retour arrière

Restaurer l’index de `site.before/index.html` dans le dossier servi. Les anciens fichiers à empreinte ayant été conservés, aucun redémarrage n’est nécessaire. Vérifier d’abord qu’aucun déploiement ultérieur n’a eu lieu.

La sauvegarde de la configuration Caddy initiale reste disponible dans `/opt/integrit/deployments/faithbook-interface/20260907T102456Z/Caddyfile.before` ; elle n’est pas nécessaire pour revenir à l’interface précédente.
