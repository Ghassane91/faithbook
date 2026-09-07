# FaithBook — Procédure de déploiement et de retour arrière

**Objet :** rendre reproductible la publication de la nouvelle interface, et rendre le retour arrière exécutable en une commande.

**Périmètre :** le site statique servi par Caddy dans `/opt/integrit/sites/faithbook-interface`, exposé sur `/nouvelle-interface/`. L'application FaithBook historique n'est pas touchée.

**Ce que cela remplace :** les deux publications du 7 septembre 2026 ont été faites à la main, avec une clé SSH temporaire créée puis révoquée à chaque fois. Aucune trace exécutable, aucune procédure de restauration écrite. Ces scripts suppriment ces deux manques.

---

## 1. Contenu

| Fichier | Rôle |
|---|---|
| `faithbook-env.sh` | Configuration unique. Seul fichier à adapter. |
| `fb-lib.sh` | Fonctions communes. Ne se lance pas seul. |
| `fb-deployer.sh` | Déploiement : construction, sauvegarde, publication, vérification, purge. |
| `fb-restaurer.sh` | Retour arrière vers une sauvegarde horodatée. |
| `fb-verifier.sh` | Contrôles HTTP seuls. Réutilisable en supervision. |
| `fb-inventaire.sh` | Inventaire du serveur, sans modification. Lève les hypothèses du § 2. |
| `fb-caddy.sh` | Application d'une configuration Caddy avec retour arrière automatique. |
| `MISE-EN-PRODUCTION.md` | Nom de domaine, scénarios de bascule, périmètre fonctionnel. |

Aucune dépendance exotique : `bash`, `curl`, `tar`, `find`. `rsync` est utilisé s'il est présent, sinon `tar` prend le relais. `git` et `npm` uniquement pour le mode source git.

---

## 2. Valeurs de configuration

Lues dans le dépôt le 7 septembre 2026, commit `f169523`. Elles ne sont plus des hypothèses.

| Variable | Valeur | Source |
|---|---|---|
| `FB_INSTALL_CMD` | `npm ci` | usage standard |
| `FB_BUILD_CMD` | `npm run build:hetzner` | `interfaces/novostok/package.json` |
| `FB_BUILD_OUT` | `dist-hetzner` | `deploy/vite.config.ts`, champ `build.outDir` |
| `FB_NODE_MIN` | `22.13.0` | champ `engines` du `package.json` |
| `FB_APP_SUBDIR` | `interfaces/novostok` | arborescence du dépôt |
| Routes API testées | `/api/auth/me`, `/api/targets`, `/api/runs` | `app/api/`, confirmées par `DEPLOIEMENT.md` |
| Dépôt | public, clonable sans authentification | vérifié |

**Piège à connaître :** `npm run build` produit la version Cloudflare Workers, pas les fichiers statiques servis par Caddy. La bonne cible est `build:hetzner`, qui utilise `deploy/vite.config.ts`. Le script refuse de publier si la sortie ne contient pas d'`index.html`, mais autant ne pas s'y tromper.

`fb-deployer.sh` contrôle la version de Node avant de construire et s'arrête si elle est inférieure au minimum.

### Restent à confirmer sur le serveur

| Élément | Pourquoi |
|---|---|
| `FB_CADDYFILE` | `/etc/caddy/Caddyfile` est le chemin standard, non vérifié sur cette machine |
| Port du `reverse_proxy` FaithBook | nécessaire pour tout changement de routage |
| Node installé sur le serveur | si absent, construire ailleurs et utiliser `--from-archive` |
| Périmètre de la sauvegarde existante | le dossier servi y est-il inclus ? |

`./fb-inventaire.sh` répond à ces quatre points en une commande. Il ne modifie rien.

## 3. Installation sur le serveur, une seule fois

```bash
ssh -p 2222 ghassane@62.238.108.19

sudo mkdir -p /opt/integrit/ops
sudo chown "$USER" /opt/integrit/ops
# copier les cinq fichiers dans /opt/integrit/ops (scp, ou coller via un éditeur)
chmod +x /opt/integrit/ops/fb-*.sh

# adapter la configuration
nano /opt/integrit/ops/faithbook-env.sh
```

Contrôle immédiat, sans rien modifier :

```bash
cd /opt/integrit/ops
./fb-verifier.sh
./fb-deployer.sh --dry-run
```

---

## 4. Déploiement courant

```bash
cd /opt/integrit/ops

# 1. Toujours commencer à blanc
./fb-deployer.sh --dry-run

# 2. Déploiement de la branche par défaut
./fb-deployer.sh

# 3. Ou d'une référence précise
./fb-deployer.sh --ref 9a460430984d3c650dce19f1114d330cd5be6472
```

Si le dépôt n'est pas accessible depuis le serveur, construire ailleurs puis publier l'archive :

```bash
./fb-deployer.sh --from-archive /tmp/faithbook-hetzner.zip
```

### Ce que le script fait, dans l'ordre

1. Contrôles préliminaires : commandes présentes, dossier servi existant, élévation si nécessaire.
2. Obtention des fichiers : clone ou mise à jour, `npm ci`, construction. **Un échec de construction arrête tout avant la moindre modification du site.**
3. Sauvegarde de l'état courant dans `/opt/integrit/deployments/faithbook-interface/<horodatage>/site.before`, plus le Caddyfile.
4. Publication : d'abord tous les actifs sauf `index.html`, ensuite `index.html` par renommage atomique. Les anciens fichiers à empreinte sont conservés, ce qui protège les onglets déjà ouverts et rend le retour arrière possible.
5. Écriture d'un `manifeste.json` : horodatage, commit, source, opérateur, nombre de fichiers.
6. Vérification HTTP. **Un échec ici renvoie un code de sortie 1 et affiche la commande de retour arrière.**
7. Purge : seules les dix dernières sauvegardes sont conservées.

### Garde-fous

- Un résultat de construction sans `index.html` est refusé.
- Un résultat de moins de deux fichiers est refusé.
- Rien n'est jamais supprimé du dossier servi lors d'un déploiement.
- Aucune modification du Caddyfile. Le déploiement ne touche pas au routage.
- Aucun redémarrage de FaithBook n'est nécessaire.

---

## 5. Retour arrière

```bash
cd /opt/integrit/ops

# Voir ce qui est disponible
./fb-restaurer.sh --lister

# Restaurer une version précise
./fb-restaurer.sh 20260907T105154Z

# Ou la plus récente
./fb-restaurer.sh --derniere
```

Le script :

1. sauvegarde l'état courant sous `<horodatage>-avant-restauration` — **un retour arrière est lui-même réversible** ;
2. restaure le site en miroir, suppressions comprises ;
3. relance la vérification.

Une confirmation est demandée en mode interactif. `--oui` la saute, `--dry-run` n'exécute rien.

### Cas particulier : le Caddyfile

Le routage n'a été modifié qu'une seule fois, lors de la première installation. Ne restaurer le Caddyfile que si le routage lui-même est cassé :

```bash
./fb-restaurer.sh 20260907T102456Z --caddy
```

Le fichier sauvegardé est validé par `caddy validate` avant remplacement. Si la validation échoue, rien n'est remplacé.

### Que faire si la vérification échoue après déploiement

```bash
./fb-restaurer.sh --derniere --oui    # revient à l'état d'avant le déploiement
./fb-verifier.sh                      # confirme le retour à la normale
```

Puis lire `/opt/integrit/deployments/faithbook-interface/<horodatage>/deploiement.log`.

---

## 6. Vérification seule

```bash
./fb-verifier.sh; echo "code de sortie : $?"
```

Contrôles effectués :

1. `/nouvelle-interface/` en 200, chemin sans barre finale en 308, application historique en 200.
2. Chaque fichier `.js` et `.css` référencé par l'index en 200.
3. Routes API en 401 sans session. **Un 200 sans session est signalé comme fuite de données potentielle.**
4. Type de contenu JSON sur les routes API, jamais une page HTML de repli.
5. Expiration du certificat TLS, alerte sous quinze jours.

---

## 7. Supervision

Le script renvoie 0 ou 1, il se branche donc directement sur un ordonnanceur.

```bash
sudo tee /etc/systemd/system/faithbook-verif.service >/dev/null <<'UNIT'
[Unit]
Description=Verification de la nouvelle interface FaithBook

[Service]
Type=oneshot
ExecStart=/opt/integrit/ops/fb-verifier.sh
User=ghassane
UNIT

sudo tee /etc/systemd/system/faithbook-verif.timer >/dev/null <<'UNIT'
[Unit]
Description=Verification FaithBook toutes les 15 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min

[Install]
WantedBy=timers.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now faithbook-verif.timer
systemctl list-timers faithbook-verif.timer
```

Consultation : `journalctl -u faithbook-verif.service -n 50`.

**Reste à faire :** brancher ce résultat sur la supervision existante mentionnée dans le compte rendu, pour qu'un échec génère une alerte plutôt qu'une ligne de journal. Le mécanisme d'alerte en place n'est pas documenté et n'a pas pu être identifié depuis cette session.

---

## 8. Sauvegarde

Le compte rendu mentionne des sauvegardes testées pour FaithBook, sans préciser leur portée. À vérifier :

```bash
# Le dossier servi est-il inclus dans la sauvegarde existante ?
ls -la /opt/integrit/sites/faithbook-interface
ls -la /opt/integrit/deployments/faithbook-interface
```

Deux dossiers doivent être couverts :

- `/opt/integrit/sites/faithbook-interface` — le site en production ;
- `/opt/integrit/deployments/faithbook-interface` — les sauvegardes de déploiement, sans lesquelles le retour arrière est impossible.

S'ils ne le sont pas, les ajouter avant la mise en production.

---

## 9. Journal des déploiements

Chaque déploiement laisse dans son dossier horodaté :

- `deploiement.log` — la trace complète ;
- `manifeste.json` — horodatage, commit, source, opérateur, hôte, nombre de fichiers ;
- `site.before/` — l'état exact d'avant ;
- `Caddyfile.before` — la configuration d'avant.

Recherche du commit actuellement en production :

```bash
cat "$(ls -d /opt/integrit/deployments/faithbook-interface/*/ | sort | tail -1)manifeste.json"
```

---

## 10. Limites connues

- Les scripts n'ont pas été exécutés sur le serveur réel depuis cette session. Ils ont été validés sur une arborescence de test reproduisant le dossier servi, la racine des sauvegardes et le Caddyfile : déploiement, conservation des anciens actifs, bascule d'index, listage, restauration en miroir, mode à blanc, archives `zip` et `tar.gz`, archive avec dossier racine unique. **La première exécution réelle doit se faire avec `--dry-run`.**
- Le mode git suppose que `npm` et Node 22.13 ou plus sont installés sur le serveur. Sinon, construire ailleurs et utiliser `--from-archive`.
- Deux déploiements lancés dans la même seconde partageraient le même horodatage. Sans conséquence pratique.
- Les scripts ne gèrent pas le nom de domaine, le certificat ni le routage. Ces trois points restent manuels.

---

## 11. Points de livraison non couverts par ces scripts

Rappel des éléments qui restent ouverts et qui demandent une décision, non un script :

1. **Recette réelle** — les soixante cas du cahier de recette, avec un compte réel. Bloquant.
2. **Bascule** — la nouvelle interface reste-t-elle sur `/nouvelle-interface/` ou devient-elle la racine ? Décision non prise.
3. **Périmètre fonctionnel** — gestion des cibles, des comptes et de l'équipe absente de la nouvelle interface. À assumer et documenter, ou à développer.
4. **Nom de domaine** — `veille-novostok.duckdns.org` est un DNS dynamique gratuit, inadapté à une livraison client. Un domaine propre implique un nouveau certificat et une reprise du Caddyfile.

Les points 2, 3 et 4 sont traités dans `MISE-EN-PRODUCTION.md`, avec les modèles de Caddyfile correspondants.
