# Captures depuis Chrome personnel

Cette intégration ajoute une page **Chrome personnel** à FaithBook et une extension Chrome Manifest V3. Elle ouvre ses propres onglets dans le profil Chrome qui a installé l’extension ; les cookies de ce profil sont utilisés par Chrome, sans export vers FaithBook. Elle ne résout pas les CAPTCHA et ne garantit pas l’accès aux enseignes.

## Comportement

- Trois cibles distinctes sont créées à l’appairage : Walmart US, Academy et Bass Pro. Les cibles serveur existantes restent inchangées.
- Le serveur calcule les échéances des **1er et 15 de chaque mois à 09:00, Africa/Casablanca**. Le fuseau suit les données IANA du serveur, y compris les changements saisonniers ; aucun décalage UTC fixe n’est codé.
- Chrome interroge FaithBook chaque minute et traite une cible à la fois. La capture peut donc commencer quelques minutes après 09:00.
- Les captures HuntX mettent aussi en file les liens produits publics de leurs lignes, pour toutes les enseignes. Une URL identique n’est capturée qu’une fois pour une même prise HuntX. Les captures restent reliées à leur prise source.
- Le PC doit être allumé, connecté et Chrome ouvert dans le profil appairé. Le serveur ne peut pas réveiller le PC. Les trois pages de contrôle disposent d’un rattrapage pendant 48 h, uniquement pour les échéances postérieures à l’appairage ; les fiches HuntX déjà mises en file restent en attente.
- Une réservation de dix minutes évite les traitements simultanés d’une cible. Si le navigateur est interrompu, une nouvelle réservation remplace l’ancienne. Les envois répétés d’un résultat accepté ne créent pas plusieurs captures.
- Les images sont capturées depuis l’onglet de la page, sans barre de navigateur ni autres fenêtres. Le clip est limité à 2 400 px de largeur, 16 000 px de hauteur et 24 millions de pixels. Une page trop haute produit une image partielle avec sa hauteur réelle indiquée dans l’historique ; une image supérieure à 8 Mo est refusée.
- Le défilement de chargement différé est borné à trente étapes. La version 1.3 attend les images significatives visibles à chaque étape, puis les images de la zone capturée et les polices, avec des délais limités. Si aucune image principale de cette zone n’a chargé, la capture reste en erreur. Les images partiellement manquantes et la troncature sont signalées. Une page infinie ou des ressources cassées peuvent toujours produire une capture incomplète.
- Les résultats apparaissent dans l’historique et la planche FaithBook. Les images valides sont stockées sur le serveur. Si Google Drive est configuré, elles rejoignent sa file d’envoi. Le résultat contient désormais `captured_at`, l’heure UTC de la prise d’image ; cette valeur reste identique après une reprise d’envoi et permet au serveur de classer la prise au bon jour local, même après une coupure prolongée.
- Une vérification humaine détectée devient une exécution suspendue, sans image validée. Un test manuel explicite permet de réessayer ; pas de boucle de résolution de CAPTCHA.
- Les liens 404 et les refus marchands restent visibles comme indisponibles. Ils ne constituent pas des captures réussies. Le code conserve séparément un diagnostic d’écran et la raison précise d’une erreur technique ou d’une navigation bloquée. Le zéro échec ne peut être garanti lorsque le marchand refuse l’accès ou lorsque le lien n’existe plus.

## Mise en service

1. Déployer les sources backend, migrations, frontend et extension ensemble. Reconstruire les images et appliquer les migrations selon la procédure d’exploitation habituelle. Les migrations initiales `a6b7c8d9e0f1` et `b7c8d9e0f1a2` ajoutent les appareils, leurs cibles et la file de fiches HuntX ; les mises à jour suivantes peuvent étendre ce schéma.
2. Dans FaithBook, ouvrir **Chrome personnel**, télécharger l’extension et décompresser le ZIP.
3. Dans le Chrome habituel, ouvrir `chrome://extensions`, activer le mode développeur et choisir **Charger l’extension non empaquetée**. Sélectionner le dossier contenant `manifest.json`. Chrome demande une permission de débogage nécessaire à la capture des onglets ; cette installation doit être explicitement acceptée par l’utilisateur.
4. Dans FaithBook, cliquer **Lier mon Chrome** (administrateur de l’organisation). Le code d’appairage n’est affiché qu’une fois. Sa durée de validité est d’un an ; il est révocable. Une organisation ne peut avoir qu’un appareil actif avec cette première version.
5. Ouvrir les options de l’extension. Coller l’origine HTTPS de FaithBook et le code. Autoriser uniquement cette origine lorsque Chrome le demande.
6. Tester les trois pages de contrôle dans FaithBook ou dans l’extension. Une nouvelle capture de la cible HuntX alimente la file de fiches produits. Actualiser le suivi : les résultats arrivent successivement. Vérifier les images et les motifs d’indisponibilité avant de considérer la recette terminée.
7. Une fois le test réel validé, désactiver l’ancienne automatisation Codex `captures-chrome-1er-et-15` pour éviter une seconde série de captures. Elle n’est pas modifiée par le code ni par la préparation du patch.

Les modifications de calendrier et d’URL des trois cibles appairées sont volontairement bloquées dans le formulaire général. Leur nom, activation et étiquettes restent modifiables. Le bouton de capture général indique de passer par **Chrome personnel → Tester maintenant**.

## Sécurité et déploiement

Le jeton est haché dans la base et limité aux cibles du dispositif, y compris les fiches dérivées d’une cible HuntX autorisée dans la même organisation. L’API vérifie également l’activité du compte et son rôle administrateur dans l’organisation à chaque demande. Révoquer le dispositif désactive ses cibles. Le jeton ne donne pas accès aux autres API FaithBook. L’extension garde son jeton dans son stockage local privé, pas dans Chrome Sync, et ne l’expose pas aux scripts des sites.

L’extension demande l’accès aux trois domaines marchands, puis à l’origine FaithBook choisie lors de l’appairage. La permission Chrome `debugger` a une portée technique large : le code s’attache uniquement aux onglets qu’il crée, et les détache et ferme en fin de traitement. Les liens produits sont validés côté serveur comme publics et sans identifiants. Toute navigation de document doit garder l’origine exacte de sa cible ; cette restriction peut bloquer des redirections légitimes entre alias de domaine ou HTTP et HTTPS. Elle reste inchangée dans la version 1.3 et son blocage est diagnostiqué. Aucun port de débogage distant, proxy, changement d’empreinte ni extraction de cookies n’est configuré.

Avant déploiement, sauvegarder la base, les sources modifiées et les images Docker courantes. Vérifier `git apply --check` sur l’état réel du serveur. Ne pas utiliser l’ancien script `deployer-capture-locale.sh` pour ce patch : sa sauvegarde ne couvre pas les migrations et le frontend de cette intégration.

Un retour à une ancienne image doit tenir compte des révisions Alembic déployées. Ne pas rétrograder automatiquement la base si des appairages ou des fiches ont déjà été créés : ces rétrogradations suppriment leurs données. Conserver la sauvegarde et suivre la procédure de restauration de l’application.

## Validation effectuée

Version 1.3 préparée le 9 octobre 2026 : **10 tests JavaScript réussis** avec Node, sans requête vers un marchand ni session utilisateur.

- Extension : logique de domaine et de capture, fermeture de son propre onglet après diagnostic, rejet des défis et 404, délai borné des images et polices, erreur de navigation précise, hauteur réelle de troncature et reprise d’un envoi après coupure avec conservation de son heure. Les API Chrome et le réseau sont simulés dans ces tests ; l’attente des ressources utilise aussi un DOM simulé.
- Les validations backend, migrations et frontend de cette mise à jour sont conduites séparément avant déploiement.

**Limite de recette 1.3 :** les versions précédentes sont installées et appairées, et des captures HuntX ont été prises en production le 8 octobre. Cela ne valide pas encore la version 1.3 dans le Chrome personnel : son installation et son essai réel restent à effectuer après déploiement du backend compatible.

Références : [Chrome debugger](https://developer.chrome.com/docs/extensions/reference/api/debugger), [alarmes Chrome](https://developer.chrome.com/docs/extensions/reference/api/alarms), [stockage des extensions](https://developer.chrome.com/docs/extensions/reference/api/storage).
