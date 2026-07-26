# FAITHBOOK — FICHIER DE REPRISE POUR CLAUDE

Date de reprise : 26 juillet 2026  
Responsable projet : Ghassane  
Rôle attendu de Claude : reprendre le développement comme ingénieur principal, sans recommencer le projet ni annuler les modifications existantes.

## 1. Emplacement et version

- Projet Windows : `C:\Users\G\Desktop\Face Book`
- Fichier Compose principal utilisé : `docker-compose.yml`
- Autre fichier présent : `docker-compose.dev.yml`
- Version applicative actuellement déclarée : **1.8.3**
- Dernière suite de tests connue avant le correctif du jour : **95 tests réussis**
- Le correctif du proxy décrit ci-dessous est appliqué localement, mais la version **1.8.4 n’a pas encore été déclarée ni validée par la suite complète de tests**.

## 2. Objectif du produit

FaithBook automatise l’ouverture régulière de pages web, notamment Facebook, réalise des captures d’écran pleine page, compare les captures dans le temps et les archive.

Fonctions déjà opérationnelles :

- frontend local ;
- backend API ;
- PostgreSQL ;
- Redis ;
- worker asynchrone ;
- proxy de sortie Squid ;
- sessions Facebook authentifiées ;
- capture pleine page avec défilement ;
- rafraîchissement et chiffrement des cookies ;
- métriques Facebook, notamment le nombre d’abonnés ;
- détection du pourcentage de changement ;
- archivage dans `/output`, organisé par organisation et par cible ;
- planification des captures.

L’ordre stratégique reste : **stabiliser en local, terminer le backend et le frontend, puis seulement préparer le VPS Hetzner**. Ne pas lancer de chantier VPS sans demande de Ghassane.

## 3. Services Docker

Services confirmés opérationnels après réparation :

| Service | Conteneur | État |
|---|---|---|
| Backend | `faithbook-backend` | healthy |
| PostgreSQL | `faithbook-db` | healthy |
| Redis | `faithbook-redis` | healthy |
| Frontend | `faithbook-frontend` | healthy |
| Proxy Squid | `faithbook-egress-proxy` | healthy |
| Worker | `faithbook-worker` | healthy |

Le frontend est publié sur le port hôte `3000`. Les autres services restent internes au réseau Docker.

Les politiques de redémarrage de `faithbook-worker` et `faithbook-egress-proxy` sont déjà :

```text
restart=unless-stopped
```

## 4. Incident rencontré après redémarrage de Docker Desktop

Après un redémarrage de Docker Desktop :

1. `faithbook-egress-proxy` redémarrait en boucle ;
2. `faithbook-worker` était arrêté avec `Exited (137)` ;
3. le backend ne pouvait plus résoudre `egress-proxy` ;
4. les captures ne pouvaient donc plus fonctionner.

Erreur Squid observée :

```text
FATAL: Squid is already running: Found fresh instance PID file (/run/squid.pid) with PID 1
```

Cause confirmée pour le proxy : le conteneur était redémarré avec son système de fichiers existant et Squid retrouvait l’ancien fichier `/run/squid.pid`. Il croyait qu’une autre instance fonctionnait déjà, quittait, puis recommençait à cause de `restart: unless-stopped`.

Le code `137` du worker indique un arrêt par `SIGKILL`. L’événement a coïncidé avec le redémarrage de Docker Desktop. Ne pas affirmer qu’il s’agit obligatoirement d’un manque de mémoire sans preuve supplémentaire.

## 5. Correction permanente appliquée au proxy

Fichier modifié :

```text
proxy/Dockerfile
```

Ancienne commande :

```dockerfile
CMD ["squid", "--foreground", "-f", "/etc/squid/squid.conf"]
```

Nouvelle commande actuellement présente :

```dockerfile
CMD ["/bin/sh", "-c", "rm -f /run/squid.pid && exec squid --foreground -f /etc/squid/squid.conf"]
```

But :

- supprimer le PID Squid obsolète avant chaque démarrage ;
- utiliser `exec` afin que Squid devienne bien le processus PID 1 et reçoive correctement les signaux Docker.

Reconstruction effectuée avec succès :

```powershell
docker compose up -d --build --no-deps --force-recreate egress-proxy
```

Le conteneur a ensuite été redémarré sans être recréé :

```powershell
docker restart faithbook-egress-proxy
```

Résultat après 12 secondes :

```text
faithbook-egress-proxy ... Up 12 seconds (healthy)
```

Le test réseau depuis le backend a également réussi :

```text
facebook_http=200
```

La correction du PID est donc fonctionnellement validée.

## 6. Remise en service du worker

État trouvé :

```text
faithbook-worker ... Exited (137)
```

Commande utilisée :

```powershell
docker compose up -d --no-deps worker
```

Résultat :

```text
faithbook-worker ... Up ... (healthy)
```

Après son redémarrage, le worker a repris automatiquement les captures qui étaient en file d’attente.

## 7. Captures validées le 26 juillet 2026

### Run 27 — page Facebook SPYPOINT

- URL : `https://www.facebook.com/SPYPOINT.CA`
- Session du compte `spypoint` chargée ;
- cookies rafraîchis et rescellés ;
- abonnés détectés : `16000` ;
- capture : `36 896 973` octets ;
- défilements : `50` ;
- hauteur : `40 590 px` ;
- différence : `0,8 %`, page considérée inchangée ;
- durée : `84 673 ms` ;
- résultat : `step=done`.

Fichier enregistré :

```text
/output/organization-3/facebook.com-spypoint.ca/facebook.com-spypoint.ca_2026-07-26_110317.png
```

### Run 26 — groupe Facebook

- URL : `https://www.facebook.com/share/g/1aofRr8NBD/?mibextid=wwXIfr`
- session du compte `spypoint` chargée ;
- cookies rafraîchis et rescellés ;
- capture : `31 678 393` octets ;
- défilements : `50` ;
- hauteur : `40 590 px` ;
- différence détectée : `45,9 %` ;
- durée : `88 051 ms` ;
- résultat : `step=done`.

Fichier enregistré :

```text
/output/organization-3/facebook.com-share-g-1aofrr8nbd/facebook.com-share-g-1aofrr8nbd_2026-07-26_110442.png
```

Le pipeline authentification → navigation → défilement → capture → comparaison → archivage est donc opérationnel.

## 8. Travail demandé à Claude maintenant

Claude doit commencer par inspecter l’état réel du dépôt et préserver toutes les modifications de Ghassane :

```powershell
git status --short
git diff -- proxy/Dockerfile
```

Ensuite :

1. vérifier que le correctif du Dockerfile est propre et compatible avec les fichiers Compose principal et développement ;
2. ajouter un test de non-régression automatisé vérifiant que le démarrage Squid supprime le PID obsolète ;
3. tester au minimum la reconstruction, le redémarrage du même conteneur, son passage en `healthy` et un accès Facebook via le proxy ;
4. examiner la robustesse du worker après redémarrage de Docker, sans conclure à un OOM sans preuve ;
5. vérifier que toutes les données, sessions Facebook, captures et volumes persistent après redémarrage ;
6. lancer la suite complète de tests et obtenir au minimum les **95 tests déjà réussis**, plus le nouveau test de non-régression ;
7. mettre à jour la documentation et le changelog ;
8. passer officiellement en **version 1.8.4 uniquement lorsque tous les contrôles sont réussis** ;
9. fournir à Ghassane un compte rendu simple : fichiers modifiés, tests passés, résultats et éventuels risques restants.

## 9. Contraintes à respecter

- Ne pas supprimer ni réinitialiser les volumes Docker.
- Ne pas perdre les sessions Facebook existantes.
- Ne pas interdire ou casser l’accès aux sessions Facebook ou à noVNC.
- Ne jamais stocker les mots de passe Facebook.
- Ne pas modifier des fichiers sans avoir inspecté `git status` et les changements existants.
- Ne pas utiliser `git reset --hard` ni écraser les modifications de Ghassane.
- Ne pas lancer la migration VPS à ce stade.
- Ne pas considérer le produit terminé uniquement parce que les captures locales fonctionnent.
- Expliquer les résultats à Ghassane en français simple, direct et sans jargon inutile.

## 10. Critères d’acceptation de la version 1.8.4

La version 1.8.4 sera acceptée seulement si :

- tous les services Docker sont `healthy` ;
- le proxy revient automatiquement après un redémarrage du même conteneur ;
- aucune erreur liée à `/run/squid.pid` ne réapparaît ;
- Facebook répond via le proxy ;
- le worker revient automatiquement et traite la file ;
- une capture Facebook authentifiée pleine page réussit ;
- la capture est archivée au bon emplacement ;
- les données et sessions survivent au redémarrage ;
- tous les tests passent ;
- la version et la documentation sont mises à jour.

## Instruction de démarrage pour Claude

Commence par lire ce fichier, puis inspecte le dépôt réel. Ne recommence pas l’architecture. Reprends exactement à partir du correctif `proxy/Dockerfile`, consolide-le, ajoute la non-régression, vérifie le redémarrage complet et prépare la version 1.8.4.
