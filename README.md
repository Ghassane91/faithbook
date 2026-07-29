# FaithBook — captures planifiées

Backend conteneurisé qui capture automatiquement des pages web à une heure
configurable et range les captures dans un dossier par site (nom de fichier =
site + date + heure).

- **API** : FastAPI (documentation OpenAPI sur `/docs`)
- **Navigateur** : Playwright / Chromium
- **Planification** : APScheduler (cron, avec fuseau horaire)
- **Base** : PostgreSQL 17, avec migration automatique de l'ancienne SQLite
- **File d'exécution** : Redis + worker de captures séparé
- **Stockage** : copie locale durable + envoi facultatif vers Google Drive (§2).
- **Interface** : React + Vite, servie par nginx qui relaie l'API (§7)

Tout est piloté par variables d'environnement : **le passage du poste local au
VPS ne demande aucune modification de code**, uniquement un `.env` différent.

---

## 0. Feuille de route vers un SaaS commercial

FaithBook évolue par phases vers une plateforme multi-organisation. Chaque
phase livre un commit propre, ses tests, et cette section a jour.

| Phase | Contenu | État |
|---|---|---|
| 0 | Audit (architecture, risques, dépendances Windows, plan) | ✅ Fait |
| 1a | **Sécurité immédiate** : SSRF branché, jeton noVNC + isolation entre utilisateurs, `/docs` protégé, chiffrement du `storage_state_json` legacy, audit élargi | ✅ Fait — voir §8, §10, §11 |
| 1a.1 | **Durcissement adversarial** : redirections et sous-requêtes revalidées, proxy anti-DNS-rebinding, clé API rattachée à un utilisateur réel, backend non publié, IP réelle fiable, génération atomique de clé, audit du test de session | ✅ Fait |
| 1b | **Sessions robustes** : rescellement des cookies après capture, verrou par profil, statuts `suspended`/`disconnected`, alerte pré-expiration | ✅ Fait — v1.1.0 |
| 1c | **Exploitation fiable** : démarrage conditionné par les healthchecks, sauvegarde/restauration chiffrée, validation locale et CI | ✅ Fait — v1.2.1 |
| 2a | **Socle multi-organisation** : espaces isolés, rôles propriétaire/admin/membre/lecture seule, sélecteur d'espace, gestion des membres, captures et profils séparés sur disque | ✅ Fait — v1.3.0 |
| 2b | **Invitations d'équipe** : e-mail à usage unique, création guidée du compte, rattachement à l'organisation, révocation et récupération d'accès | ✅ Fait — v1.4.0 |
| 2c | **Exécution distribuée** : PostgreSQL, migration automatique de SQLite, file Redis fiable, worker séparé, healthchecks et sauvegarde PostgreSQL | ✅ Fait — v1.5.2 |
| 3a | **Google Drive fiable** : dossiers datés, envoi reprenable, reprise sans nouvelle capture, statut et lien dans l'interface | ✅ Fait — v1.6.0 |
| 3b | **Quotas et rétention par organisation** : limites comptes/cibles/captures/stockage, blocage avant Chromium, consommation API et purge isolée | ✅ Fait — v1.7.0 |
| 3c | **Interface premium et captures longues** : identité noir/ivoire, responsive, boutons ergonomiques, aperçus pleine hauteur et assemblage des fils Facebook virtualisés | ✅ Fait — v1.8.3 |
| 3c.1 | **Robustesse du proxy sortant** : Squid supprime le PID périmé (`/run/squid.pid`) avant chaque démarrage et devient PID 1 via `exec`, ce qui évite la boucle de crash-restart après un redémarrage brutal de Docker Desktop | ✅ Fait — v1.8.4 |
| 3c.2 | **Robustesse du backend au redémarrage** : l'entrypoint supprime le verrou X11 périmé (`/tmp/.X99-lock`) et le socket résiduel avant de lancer Xvfb, ce qui évite la boucle de crash-restart du conteneur backend après un `docker compose restart` | ✅ Fait — v1.8.4 |
| 3c.3 | **Reconnexion Facebook debloquee** : la fermeture du navigateur de connexion ne peut plus se figer indefiniment. Elle est bornee dans le temps, le verrou de profil est relache quoi qu il arrive, et les processus Chromium residuels de la session sont nettoyes. Une ouverture sur un verrou encore pris repond desormais 409 avec un message clair, au lieu d attendre 120 s puis de renvoyer une erreur 504. Le quota de cibles s applique aussi a la duplication. 6 tests | ✅ Fait — v1.12.1 |
| 3d | Stockage S3 et URLs signées | ⏳ À faire |
| 3d.1 | **Client S3 et routage du stockage** : client compatible S3 (AWS, Backblaze B2, Wasabi, MinIO), selection par STORAGE_BACKEND, envoi sans doublon et reprise automatique, 8 tests | ✅ Fait — v1.9.0 |
| 3d.2 | **Liens signes regeneres a la demande** : route GET /api/runs/{id}/lien qui recalcule l URL signee a chaque appel (une URL signee expire, elle ne peut pas etre lue en base), bouton du detail d execution branche dessus, cles de stockage passees en texte long pour ne plus tronquer une cle S3 (migration d6e7f8a9b0c1), 4 tests | ✅ Fait — v1.9.0 |
| 4.1 | **Comparaison de contenu plutot que de pixels** : le texte visible de chaque page est conserve et compare ligne a ligne, sans tenir compte de l ordre. Un fil social reordonne sans publication nouvelle donne desormais 0 % au lieu de 46 %. La comparaison pixel reste le repli pour les pages sans texte exploitable. 8 tests | ✅ Fait — v1.10.0 |
| 5.1 | **Synthese IA des changements** : les lignes apparues et disparues entre deux captures sont envoyees a Claude, qui redige en francais ce qui a reellement change. Desactivee par defaut (AI_SUMMARY_ENABLED + ANTHROPIC_API_KEY) : sans cle, FaithBook fonctionne exactement comme avant, et une panne de l API ne fait jamais echouer une capture. Migration f8a9b0c1d2e3, 15 tests | ✅ Fait — v1.11.0 |
| 6.1 | **Alertes multi-canaux** : en plus du mail, chaque alerte peut partir sur Telegram et sur un webhook unique compris par Slack, Discord et n8n. Canaux independants et inactifs par defaut ; une panne d un canal n empeche ni les autres ni la capture. Le resume IA est desormais inclus dans le mail de changement. 11 tests | ✅ Fait — v1.12.0 |
| 4–8 | Comparaison avancée, analyse de contenu (IA optionnelle), alertes multi-canaux, gestion de cibles avancée et plans commerciaux | ⏳ À faire |

Le développement continue **en local** ; le passage sur VPS (§13) n'aura lieu
qu'une fois la plateforme validée. Aucune facturation réelle n'est développée
pour l'instant (plans configurables sans paiement, voir la feuille de route
complète discutée hors README).

---

## 1. Démarrage rapide

```bash
cp .env.example .env
docker compose up -d --build
```

- **Interface web : http://localhost:3000** ← le point d'entrée
- API via nginx : http://localhost:3000/api
- Documentation interactive : http://localhost:3000/docs

Le port du backend n'est plus publié sur la machine : passer directement par
`8000`/`8020` contournerait les protections nginx. Pour un diagnostic local
exceptionnel, utiliser le fichier dédié, lié uniquement à `127.0.0.1` :

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

Compose attend PostgreSQL, Redis et le proxy sortant, puis démarre le backend,
le worker de captures et enfin le frontend.
Avec `docker compose up -d --wait`, la commande ne rend la main que lorsque
les six services sont réellement prêts.

### Lanceur Windows (double-clic)

Pour éviter la ligne de commande sous Windows, deux lanceurs à double-cliquer
sont fournis à la racine du projet :

- **`FaithBook.exe`** — démarre Docker si besoin, lance les conteneurs et ouvre
  l'interface dans le navigateur (une petite fenêtre affiche la progression).
- **`FaithBook-Stop.exe`** — arrête les conteneurs (les données sont conservées).

Les `.exe` sont générés depuis les scripts versionnés `FaithBook.ps1` /
`FaithBook-Stop.ps1` (ils ne sont pas dans le dépôt). Pour les (re)compiler :

```powershell
Install-Module ps2exe -Scope CurrentUser        # une seule fois
Invoke-ps2exe FaithBook.ps1 FaithBook.exe -noConsole -title FaithBook
Invoke-ps2exe FaithBook-Stop.ps1 FaithBook-Stop.exe -noConsole -title "FaithBook (arret)"
```

Prérequis : **Docker Desktop** installé. Les lanceurs le démarrent au besoin.

### Capture planifiée du bureau (Windows)

En plus des pages web (capturées dans le conteneur), un petit **agent natif
Windows** capture ton **écran entier** (tous les moniteurs) à l'heure de ton
choix — le conteneur Docker, isolé, ne peut pas voir le bureau. Outils dans
[`capture-bureau/`](capture-bureau/) :

- **`Config-capture-bureau.exe`** (raccourci Bureau « FaithBook - Capture bureau »)
  — fenêtre où l'on choisit **l'heure** et le **dossier de destination**, puis
  « Enregistrer la planification » crée une **tâche Windows quotidienne**. Boutons
  *Tester maintenant* et *Supprimer la planification*.
- **`capture-bureau.exe`** — la capture elle-même, lancée par la tâche planifiée.

Le dossier de destination est mémorisé dans `capture-bureau/bureau.config.txt`.
La capture exige une **session ouverte et déverrouillée** (écran verrouillé =
image noire). Les `.exe` sont générés depuis les `.ps1` du dossier (mêmes
commandes `ps2exe` que le lanceur).

### Envoyer les captures vers Google Drive

Pas besoin de l'API Google : on écrit dans un dossier synchronisé par **Google
Drive pour ordinateur** (`google.com/drive/download`, crée un lecteur type
`G:\Mon Drive`). Deux chemins, car ils ne subissent pas la même contrainte :

- **Bureau** (agent natif Windows) : écrit **directement** dans le dossier Drive.
  Dans `Config-capture-bureau.exe`, choisis par ex. `G:\Mon Drive\FaithBook\bureau`
  comme destination (bouton « … »). ✅ direct.
- **Pages web** (écrites par le conteneur Docker) : **le conteneur ne peut pas
  écrire sur le lecteur Google Drive** (système de fichiers virtuel « Stream » —
  vérifié). On garde donc `OUTPUT_DIR=./captures` en local, et une tâche planifiée
  **`sync-drive-web.exe`** (toutes les 15 min, robocopy natif) recopie
  `captures/` vers `G:\Mon Drive\FaithBook\web`.

Résultat : tout se retrouve sous `G:\Mon Drive\FaithBook\` et Google Drive
synchronise vers le cloud — aucune clé, aucun compte de service. La destination
de la synchro web se règle dans `capture-bureau/sync-drive.config.txt`.
(L'intégration API Drive côté serveur reste une alternative, voir §2.)

> Deux tâches planifiées Windows sont créées : **« FaithBook - Capture bureau »**
> (à ton heure) et **« FaithBook - Sync Drive »** (toutes les 15 min). Visibles
> dans le Planificateur de tâches.

### Première connexion

L'interface est protégée par identifiant. Au premier démarrage, un compte est
créé automatiquement. Si `ADMIN_PASSWORD` est vide dans le `.env`, un mot de
passe aléatoire est généré et affiché **une seule fois** dans les journaux :

```bash
docker compose logs backend | grep -A5 "COMPTE INITIAL"
```

Connectez-vous avec `admin@local` et ce mot de passe ; l'application impose
aussitôt d'en choisir un nouveau. Pour fixer le mot de passe d'emblée,
renseignez `ADMIN_EMAIL` et `ADMIN_PASSWORD` avant le premier démarrage.

### Où atterrissent les captures

Une seule ligne du `.env` le décide :

```env
OUTPUT_DIR=./captures
```

Le backend crée **un dossier par site** (déduit de l'URL) et nomme le fichier
d'après le **site, la date et l'heure** — reconnaissable au premier coup d'œil :

```
captures/
  organization-1/
    facebook.com-spypoint.ca/
      facebook.com-spypoint.ca_2026-07-22_090012.png
    integr-it.com/
      integr-it.com_2026-07-22_090300.png
```

Le nom du site vient du domaine (sans `www`) plus le chemin de page éventuel,
pour distinguer deux pages d'un même domaine
(`facebook.com/SPYPOINT.CA` → `facebook.com-spypoint.ca`). Un `subfolder` de
cible, si renseigné, s'insère sous le dossier du site.

### Chargement des publications avant la capture

Pour toute cible avec **Page entière** activé, FaithBook descend
progressivement, attend le chargement des publications et images différées,
continue tant que la page s'allonge, puis remonte en haut et crée le PNG
complet. Cette règle est générale, notamment pour les groupes Facebook et les
fils à défilement infini.

Facebook virtualise certains fils : les publications déjà parcourues sont
retirées du DOM alors que la hauteur vide reste déclarée. Pour ces URL,
FaithBook v1.8.3 enregistre chaque fenêtre pendant le défilement puis assemble
les segments réellement visibles. Cela évite les PNG très longs composés
presque uniquement d'une zone grise vide.

Les limites évitent qu'un fil réellement infini bloque le worker :

```env
AUTO_SCROLL_FULL_PAGE=true
AUTO_SCROLL_DELAY_MS=900
AUTO_SCROLL_MAX_STEPS=50
AUTO_SCROLL_STABLE_ROUNDS=4
```

Pour charger davantage de publications, augmenter `AUTO_SCROLL_MAX_STEPS`.
Pour un site lent, augmenter `AUTO_SCROLL_DELAY_MS`. Les valeurs utilisées
sont consignées dans le journal de l'exécution.

Règles pour `OUTPUT_DIR` :

- Par défaut `./captures`, à l'intérieur du projet (ignoré par Git).
- **Windows**, pour un chemin absolu : barres obliques normales
  (`C:/Users/G/Documents/Captures`), jamais d'antislash.
- **VPS** : un chemin Linux, ex. `/var/captures`. C'est la seule ligne à changer.
- Après modification : `docker compose up -d` (un simple `restart` ne suffit
  pas, le montage est recréé au démarrage du conteneur).

Créer une cible et lancer une capture immédiatement :

```bash
curl -X POST http://localhost:3000/api/targets \
  -H "Content-Type: application/json" \
  -d '{"name":"Exemple","url":"https://example.com","run_time":"09:00"}'

curl -X POST http://localhost:3000/api/targets/1/run
curl http://localhost:3000/api/runs/1            # statut + logs détaillés
curl -o capture.png http://localhost:3000/api/runs/1/screenshot
```

Ou, tout en un, avec le script de vérification :

```bash
bash scripts/run_tests.sh 3000
```

---

## 2. Google Drive API

Le mode `google_drive` garde toujours la capture locale dans `OUTPUT_DIR`, puis
l'envoie vers Drive. Si Drive est indisponible, la capture reste réussie :
l'envoi seul est repris automatiquement, sans rouvrir Facebook et sans refaire
le PNG.

Structure créée dans le dossier parent :

```text
2026-07-25/
  organization-1/
    facebook.com-groups-exemple/
      facebook.com-groups-exemple_2026-07-25_090012.png
```

### Configuration recommandée

1. Dans Google Cloud, créer un projet, activer **Google Drive API**, créer un
   compte de service et télécharger sa clé JSON.
2. Créer un **Drive partagé** Google Workspace et un dossier parent destiné à
   FaithBook. Ajouter l'adresse du compte de service avec un rôle qui autorise
   la création de fichiers.
3. Placer la clé ici, sans jamais la publier ni l'envoyer dans une conversation :

   ```text
   Face Book/secrets/service-account.json
   ```

4. Copier les identifiants depuis les URL Google Drive et compléter `.env` :

   ```env
   STORAGE_BACKEND=google_drive
   GOOGLE_SERVICE_ACCOUNT_FILE=/secrets/service-account.json
   GOOGLE_DRIVE_PARENT_FOLDER_ID=identifiant_du_dossier_parent
   GOOGLE_DRIVE_SHARED_DRIVE_ID=identifiant_du_drive_partage
   ```

5. Recréer les services pour relire le `.env`, puis vérifier l'accès :

   ```powershell
   docker compose up -d --build --force-recreate
   docker compose exec backend python -c "from app.services.drive import drive_client; print(drive_client.check_access())"
   ```

Un administrateur peut aussi ouvrir **Équipe → Stockage Google Drive → Tester
Google Drive**. Le détail d'une exécution affiche l'état, le prochain essai, le
lien Drive et un bouton de reprise manuelle.

Les envois utilisent des sessions reprenables. Les erreurs transitoires Google
sont retentées par le client ; les autres échecs sont repris par FaithBook avec
un délai croissant, toutes les `GOOGLE_DRIVE_RETRY_MINUTES`.

Un compte de service ne dispose pas de quota de stockage propre. Un Drive
partagé est donc la configuration recommandée. Dans un domaine Workspace,
l'autre solution est une délégation d'autorité configurée par l'administrateur.

---

## 3. Fonctionnalités demandées → où elles se trouvent

| # | Exigence | Implémentation |
|---|---|---|
| 1 | URL + heure configurables | Table `targets`, `run_time` (HH:MM) ou `cron_expression` — [models.py](app/models.py) |
| 2 | Ouverture automatique | APScheduler → [scheduler.py](app/scheduler.py) |
| 3 | Capture complète | `full_page=True` + défilement progressif jusqu'à stabilisation avant le PNG — [capture.py](app/services/capture.py) |
| 4 | Rangement par site | Un dossier par site dans `OUTPUT_DIR` — [runner.py](app/services/runner.py) |
| 5 | Dépôt de la capture | Copie locale puis Drive facultatif, dossier daté, nom = site + date + heure |
| 6 | Éviter les doublons | 3 niveaux, voir §4 — [runner.py](app/services/runner.py) |
| 7 | Réessai automatique | Backoff exponentiel, `MAX_ATTEMPTS` — [runner.py](app/services/runner.py) |
| 8 | Logs + statut par exécution | Tables `runs` / `run_logs` + fichier `data/app.log` |
| 9 | Lancement manuel | `POST /api/targets/{id}/run` |
| 10 | API REST documentée | OpenAPI sur `/docs` et `/redoc` |
| 11 | Quotas par espace | Comptes, cibles, captures/jour, stockage et rétention propres à chaque organisation |

---

## 4. Déduplication (`DEDUPE_MODE`)

| Mode | Comportement |
|---|---|
| `per_day` *(défaut)* | Une seule capture réussie par cible et par jour. Une 2ᵉ exécution est marquée `skipped`. |
| `content_hash` | Capture refaite, mais si le SHA-256 est identique à une capture déjà envoyée, aucun nouvel upload. |
| `both` | Les deux règles. |
| `off` | Aucune déduplication. |

Un fichier ne peut pas non plus être écrasé par accident : chaque nom contient
la date et l'heure de capture, et le dossier du site est réutilisé, jamais recréé.

`POST /api/targets/{id}/run?force=true` contourne la déduplication (utile en test).

---

## 5. Réessais, alertes et rapport quotidien

`MAX_ATTEMPTS=3` et `RETRY_BACKOFF_SECONDS=15` → tentatives à T, T+15 s, T+45 s.
Chaque tentative est journalisée dans `run_logs`. Après épuisement, l'exécution
passe en `failed` avec le message d'erreur conservé.

Les exécutions restées `running` après un arrêt brutal du conteneur sont
marquées en échec au redémarrage (pas d'exécution « fantôme »).

Une redirection Facebook vers `login`, `checkpoint`, `captcha` ou `two_factor`
n'est pas un incident réseau : aucun réessai inutile n'est lancé. La capture
passe immédiatement en `suspended`, le compte en `disconnected` ou
`verification_required`, et une alerte invite à reconnecter le compte.

### La plateforme vous prévient — plus de surveillance manuelle

Trois automatismes (mails envoyés via le bloc `SMTP_*` du §8 ; sans SMTP, le
contenu est journalisé) :

| Automatisme | Quand | Variable |
|---|---|---|
| **Alerte d'échec** | Immédiatement quand une capture échoue après tous les réessais — cible, erreur en clair, lien vers l'historique | `NOTIFY_ON_FAILURE=true` |
| **Contrôle des sessions** | Chaque jour : chaque compte connecté est testé ; alerte en cas de déconnexion/2FA ou avant l'expiration connue des cookies | `SESSION_CHECK_TIME=07:30`, `SESSION_EXPIRY_WARNING_DAYS=7` |
| **Rapport quotidien** | Un seul mail le matin : captures d'hier (réussites, échecs et leurs raisons), état des comptes, cibles actives | `DAILY_REPORT_TIME=08:00` |

Destinataire : `NOTIFY_EMAIL`, à défaut l'adresse du premier utilisateur.
Un horaire vide désactive la tâche.

### Nettoyage automatique

Chaque nuit (3 h 30), les exécutions **et les fichiers locaux** plus vieux que
la durée de rétention de leur organisation sont supprimés, dossiers vides
compris. `RUN_RETENTION_DAYS` initialise les nouvelles organisations à 90 jours
par défaut ; `0` désactive la purge. La copie déjà synchronisée sur Google Drive
n'est pas touchée : elle sert d'archive longue durée.

### Quotas par organisation (v1.7.0)

Chaque espace possède ses propres limites. Un dépassement renvoie `409` et,
pour une capture, le refus intervient **avant** la mise en file et le lancement
de Chromium. La taille finale du PNG est recontrôlée avant son enregistrement
afin que deux workers ne puissent pas dépasser silencieusement le stockage.

| Limite initiale | Variable | Défaut |
|---|---|---:|
| Comptes connectés | `DEFAULT_QUOTA_ACCOUNTS` | 10 |
| Cibles | `DEFAULT_QUOTA_TARGETS` | 100 |
| Captures commencées par jour | `DEFAULT_QUOTA_DAILY_CAPTURES` | 500 |
| PNG locaux enregistrés | `DEFAULT_QUOTA_STORAGE_BYTES` | 10 Gio |
| Rétention locale | `RUN_RETENTION_DAYS` | 90 jours |

`0` signifie illimité pour chaque quota et « ne jamais purger » pour la
rétention. Ces variables ne définissent que les valeurs initiales : les limites
sont ensuite stockées sur chaque organisation, prêtes à être reliées à des
plans commerciaux sans intégrer de paiement dans cette phase.

### Détection de changement — de l'archivage à la veille

À chaque capture réussie, FaithBook la compare à la **capture réussie
précédente** de la même cible et calcule la **proportion de la page qui a
changé** (diff de pixels normalisé, robuste au reflow ; combine les différences
sur la zone commune et l'écart de hauteur).

- Si le changement dépasse `CHANGE_THRESHOLD` (3 % par défaut), l'exécution est
  marquée **« modifiée »** — badge visible sur la **Planche** (coin de la
  vignette) et dans l'**Historique**, avec le pourcentage.
- Avec `NOTIFY_ON_CHANGE=true`, un mail « la page X a changé » est envoyé (utile
  pour surveiller une page sans ouvrir l'interface). Désactivé par défaut car
  potentiellement bavard.

C'est ce qui transforme FaithBook d'un archiveur en **outil de veille** : on ne
regarde que ce qui a bougé.

---

## 6. API — résumé

| Méthode | Route | Rôle |
|---|---|---|
| GET | `/api/health` | État du service, planificateur, dossier de sortie |
| GET | `/api/config` | Configuration effective (sans secrets) |
| GET | `/api/scheduler/jobs` | Tâches planifiées + prochaines exécutions |
| GET/POST | `/api/targets` | Lister / créer une cible |
| GET/PATCH/DELETE | `/api/targets/{id}` | Détail / modifier / supprimer |
| POST | `/api/targets/{id}/run` | **Lancement manuel** (`?force=true`) |
| GET | `/api/targets/{id}/runs` | Historique de la cible |
| GET | `/api/runs` | Historique global (filtres `status`, `capture_date`…) |
| GET | `/api/runs/{id}` | Détail + logs |
| GET | `/api/runs/{id}/logs` | Logs seuls |
| GET | `/api/runs/{id}/screenshot` | Télécharger le PNG |
| POST | `/api/runs/{id}/drive/retry` | Reprendre l'envoi Drive sans refaire la capture (admin) |
| POST | `/api/drive/check` | Tester l'accès en écriture au dossier Drive (admin) |
| GET/POST | `/api/accounts` | Lister / créer un compte connecté |
| DELETE | `/api/accounts/{id}` | Déconnecter et supprimer la session |
| POST | `/api/accounts/{id}/login/start` · `/status` · `/finish` · `/cancel` | Connexion manuelle noVNC (voir §10) |
| POST | `/api/accounts/{id}/test` | Tester la validité de la session |
| POST | `/api/auth/forgot` · `/api/auth/reset` | Mot de passe oublié (voir §8) |
| GET/POST | `/api/organizations` | Lister / créer les organisations accessibles |
| GET | `/api/organizations/current` | Organisation active et rôle courant |
| GET | `/api/organizations/current/usage` | Consommation, quotas et rétention de l'organisation active |
| GET/POST | `/api/organizations/current/members` | Lister / ajouter les membres (admin) |
| PATCH/DELETE | `/api/organizations/current/members/{id}` | Modifier le rôle / retirer un membre (admin) |
| GET/POST | `/api/organizations/current/invitations` | Lister / envoyer les invitations actives (admin) |
| DELETE | `/api/organizations/current/invitations/{id}` | Révoquer une invitation (admin) |
| GET/POST | `/api/auth/invitations/{token}` · `/accept` | Vérifier / accepter une invitation |

Toutes les routes de comptes, cibles, exécutions, captures et planification sont
filtrées par l'organisation active (`X-Organization-ID`, sélectionné
automatiquement par l'interface). Les routes couvrent les besoins du frontend
(gestion des URL, horaires, historique, captures, erreurs) ainsi que les comptes
connectés et la réinitialisation de mot de passe.

> Deux routes internes supplémentaires (absentes de `/docs`, jamais destinées
> à être appelées directement) : `GET /api/auth/check` et
> `GET /api/accounts/novnc/authorize`. Elles ne servent qu'au relais nginx
> (`auth_request`) qui protège `/docs` et l'écran noVNC — voir §8 et §10.

### Options avancées d'une cible

`viewport_width/height`, `full_page`, `wait_until`, `wait_after_load_ms`,
`timeout_ms`, `user_agent`, `locale`, `subfolder`, et surtout :

- `dismiss_selectors` : sélecteurs CSS **cliqués** avant capture (fermer un
  bandeau cookies, une modale), séparés par `;`. Un sélecteur absent est ignoré.
- `hide_selectors` : sélecteurs CSS **masqués** avant capture, séparés par `;`
  — ex. `#cookie-banner;.modal-overlay`
- `expected_selector` : élément qui **doit** être présent, sinon l'exécution
  échoue au lieu d'archiver une page inutilisable.
- `fail_if_url_contains` : fragments d'URL interdits (`login;checkpoint`) —
  détecte une session expirée.
- `session_profile` / `storage_state_json` : voir §10.

---

## 7. Interface web (v1.8.3)

Ouvrez http://localhost:3000. Cinq vues, aucune configuration.

L'interface v1.8 adopte une direction sobre et éditoriale : noir profond,
ivoire chaud, accent bordeaux, titres en Cormorant Garamond et interface en
Inter. Les polices sont embarquées dans l'image frontend, sans appel à un
service externe. La navigation reste compacte, les tableaux sont lisibles sur
petit écran et les animations respectent `prefers-reduced-motion`. Les boutons
ont une zone cliquable confortable, des coins modérément arrondis et des états
survol, appui, focus et désactivé clairement différenciés. La Planche conserve
désormais toute la hauteur de chaque capture dans sa vignette et permet de la
faire défiler verticalement, au lieu de recadrer l'aperçu au premier écran.

**Planche du jour** — les captures du jour en planche contact. Chaque exécution
occupe un cadre : une réussite montre sa vignette, un échec montre un cadre
*vide* hachuré avec la raison en clair. Les trous se voient d'un coup d'œil,
c'est tout l'objet de cette vue.

**Cibles** — ajouter, modifier, mettre en pause, supprimer. Deux boutons pour
déclencher : « Capturer » respecte la déduplication, « Forcer » l'ignore.
La colonne *Session* distingue `anonyme`, `profil sans connexion` et
`N j restants` — utile pour repérer une session Facebook qui va expirer.

**Comptes** — connecter un compte (Facebook…) une seule fois via le navigateur
intégré, tester et reconnecter sa session, le supprimer. Une cible peut ensuite
être liée à un compte pour être capturée **connectée**. Détails du parcours et de
la sécurité en §10.

**Historique** — toutes les exécutions, filtrables par état et par jour.
Un clic ouvre le détail : journal étape par étape, capture en pleine taille,
message technique complet.

**Équipe** — visible aux propriétaires et administrateurs. Elle envoie une
invitation valable 7 jours, permet de suivre les invitations en attente et de
les révoquer. Le destinataire crée son compte depuis le lien ou confirme le mot
de passe de son compte existant, puis rejoint automatiquement l'organisation.
Le rôle `viewer` consulte sans modifier, `member` peut gérer et lancer les
cibles, et `admin` gère aussi les comptes connectés et les membres. Le
propriétaire ne peut pas être retiré. Quand Google Drive est actif, cette vue
permet aussi d'en tester l'accès en écriture. Elle présente également les
quotas de comptes, cibles, captures quotidiennes, stockage et la durée de
rétention de l'espace actif.

Le sélecteur en haut de la barre latérale change d'organisation. Les comptes,
cibles, exécutions, captures, tâches planifiées et profils Chromium sont
cloisonnés. Les nouvelles captures sont rangées sous
`captures/organization-<id>/<site>/`. Les anciens profils persistants sont
déplacés automatiquement dans leur espace isolé lors de leur première
utilisation.

### Choix techniques

| Point | Décision |
|---|---|
| Communication | nginx relaie `/api` vers le backend : une seule origine, **aucune URL à configurer**, pas de CORS |
| Erreurs | Les messages Playwright bruts sont traduits en français (`resumeErreur`) ; la trace complète reste dans le détail |
| Vignettes | Générées par Pillow à la capture. La page Facebook passe de 188 Ko à 14 Ko — sans quoi la planche fige le navigateur |
| Polices | Cormorant Garamond + Inter auto-hébergées avec Fontsource : aucune requête distante, fonctionnement derrière un pare-feu |
| Dépendances | React, Fontsource et aucun framework d'interface. Le routage reste local et léger |

**Compte** — un menu en bas de la barre latérale donne accès au changement de
mot de passe, aux mentions légales et à la déconnexion.

Développement avec rechargement à chaud :

```bash
cd frontend && npm install && npm run dev   # http://localhost:5173
```

---

## 8. Authentification et sécurité

L'interface exige une connexion. L'API refuse toute requête sans session
(`401`), à l'exception de `/api/health`, `/api/auth/login` et des routes de
mot de passe oublié (`/api/auth/forgot`, `/api/auth/reset`).

| Mécanisme | Choix |
|---|---|
| Mots de passe | Hachés en **bcrypt** (sur une empreinte SHA-256, pour ne pas être tronqués à 72 octets). Le mot de passe en clair n'est jamais stocké. |
| Sessions | Jeton opaque, **stocké en base sous forme d'empreinte**. Révocable à tout moment — contrairement à un JWT valide jusqu'à expiration. Une fuite de la base ne livre aucun jeton utilisable. |
| Cookie | `HttpOnly` (inaccessible au JavaScript, protège du vol par XSS), `SameSite=Lax`. Passe `Secure` derrière HTTPS via `COOKIE_SECURE=true`. |
| Force brute | 5 tentatives par IP et par compte sur 5 minutes, puis `429`. |
| Changement de mot de passe | Révoque toutes les autres sessions. Imposé tant que le mot de passe généré n'a pas été changé. |
| Mot de passe oublié | Lien de réinitialisation **à usage unique et daté** (voir ci-dessous), envoyé par mail. Seule l'empreinte du jeton est stockée. |
| Clé API | `API_KEY` agit au nom du compte réel `API_KEY_USER_EMAIL` (repli : `ADMIN_EMAIL`). Elle conserve l'accès autorisé aux comptes Facebook/noVNC, avec exactement les mêmes contrôles de propriété. Plus aucun utilisateur artificiel `id=0`. |
| Anti-SSRF | URL initiale, redirections et sous-requêtes Chromium sont revalidées. Le proxy Squid interne refuse également les IP privées, loopback, lien-local, metadata cloud et plages réservées sur l'adresse effectivement résolue, ce qui couvre le DNS rebinding. |
| Backend | Le port `8000` est seulement exposé sur le réseau Docker. L'unique entrée publique est nginx. |
| IP réelle | nginx remplace `X-Forwarded-For` et FastAPI ne l'accepte que depuis `TRUSTED_PROXY_CIDRS`. L'audit et l'anti-brute-force utilisent ainsi l'IP du client réel. |
| Documentation API | En développement, `/docs`, `/redoc`, `/openapi.json` exigent une session ou `X-Api-Key` via nginx. Avec `ENVIRONMENT=production`, ces routes sont désactivées dans FastAPI. |
| Audit | Connexion/déconnexion, changement/réinitialisation de mot de passe, gestion des cibles, actions sur les comptes et contrôle manuel d'une session sont journalisés dans `audit_log`, sans secret. |

Routes : `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`,
`POST /api/auth/password`, `POST /api/auth/forgot`, `POST /api/auth/reset`.

### Mot de passe oublié (réinitialisation par mail)

Depuis l'écran de connexion, le lien **« Mot de passe oublié ? »** demande
l'adresse du compte. Un lien de réinitialisation est envoyé par mail ; il ouvre
une page où l'on choisit un nouveau mot de passe.

| Point | Comportement |
|---|---|
| Confidentialité | La réponse est **identique que le compte existe ou non** : impossible de sonder les adresses enregistrées. |
| Jeton | Aléatoire, **à usage unique**, valable `RESET_TOKEN_MINUTES` (60 min par défaut). Toute nouvelle demande invalide le lien précédent. |
| Après réinitialisation | Le mot de passe est remplacé et **toutes les sessions ouvertes tombent**. |
| Anti-abus | Limitation par IP sur les demandes (`429` au-delà). |

**Envoi des mails (SMTP).** Renseigner le bloc `SMTP_*` du `.env` :

```env
PUBLIC_URL=http://localhost:3000      # base du lien (domaine HTTPS sur VPS)
RESET_TOKEN_MINUTES=60
INVITATION_DAYS=7
SMTP_HOST=smtp.exemple.com            # vide = aucun envoi (voir ci-dessous)
SMTP_PORT=587
SMTP_USER=compte@exemple.com
SMTP_PASSWORD=…
SMTP_STARTTLS=true
SMTP_FROM=no-reply@exemple.com        # à défaut, SMTP_USER
```

> **Sans SMTP configuré** (`SMTP_HOST` vide), aucun mail n'est envoyé : le lien
> de réinitialisation est écrit **dans les journaux**, ce qui permet de tester
> en local sans serveur mail —
> `docker compose logs backend | grep -A8 "E-MAIL NON ENVOYÉ"`.
> Les invitations créées depuis l'écran **Équipe** affichent aussi leur lien
> local avec un bouton « Copier ».

L'adresse du compte doit être une **vraie boîte mail** pour recevoir le lien
(l'`admin@local` par défaut n'en est pas une). Le lien pointe vers
`PUBLIC_URL/?reset_token=…`, servi par la page de réinitialisation du frontend.

> **Avant la mise en production** : servir le tout derrière HTTPS et passer
> `COOKIE_SECURE=true`. Sans HTTPS, le cookie de session circule en clair.

---

## 9. Mentions légales

Une page **Mentions légales** est intégrée à l'interface (menu compte et pied de
page). Elle couvre l'éditeur, l'hébergement, le RGPD (données de compte et
contenu capturé, durées de conservation, droits, contact CNIL), les cookies et
la propriété intellectuelle.

**Le texte est un modèle à compléter.** Les passages surlignés en jaune
(`[RAISON SOCIALE]`, `[HÉBERGEUR]`, `[DURÉE]`…) doivent être renseignés avec les
informations réelles de l'exploitant avant toute mise en ligne. Le fichier :
[MentionsLegales.tsx](frontend/src/views/MentionsLegales.tsx).

Deux points de fond y sont signalés, parce qu'ils engagent votre
responsabilité :

- **La capture automatisée de Facebook peut être contraire à ses conditions
  d'utilisation.** La page le mentionne et en place la responsabilité sur
  l'utilisateur ; ce n'est pas un avis juridique.
- Les captures peuvent contenir **des données personnelles de tiers** : à ce
  titre, l'exploitant est responsable de traitement au sens du RGPD.

Ce modèle n'est pas un conseil juridique : faites-le relire avant publication.

---

## 10. Cas Facebook (cible du projet)

### Ce qui a été mesuré, pas supposé

Trois captures réelles ont été faites pendant le développement :

| Configuration | Résultat |
|---|---|
| Sans rien | Bandeau cookies plein écran, page entièrement floutée — **inexploitable** |
| Avec `dismiss_selectors` | Page lisible : couverture, nom, abonnés, 1ʳᵉ publication, photos |
| Sans connexion | Bannière « Connectez-vous… » en bas + publications suivantes **jamais chargées** (squelettes gris) |

**Conclusion : une session connectée est nécessaire** pour obtenir des captures
complètes et fiables.

### Configuration recommandée pour une page Facebook

```json
{
  "name": "Page X",
  "url": "https://www.facebook.com/<page>",
  "run_time": "09:00",
  "locale": "fr-FR",
  "wait_until": "load",
  "wait_after_load_ms": 4000,
  "timeout_ms": 60000,
  "dismiss_selectors": "[aria-label=\"Refuser les cookies optionnels\"]",
  "fail_if_url_contains": "login;checkpoint",
  "session_profile": "facebook"
}
```

> Le sélecteur par défaut clique **« Refuser les cookies optionnels »**, pas
> « Autoriser tous les cookies » : c'est le choix le moins intrusif. Il dépend
> de la langue (`locale`) — à adapter si vous passez en anglais.

> Pour la connexion, préférez **lier la cible à un compte connecté** (champ
> « Compte connecté » du formulaire, voir ci-dessous) plutôt que de gérer
> `session_profile` à la main.

### Comptes connectés — se connecter une fois, dans l'interface

**Méthode recommandée.** L'onglet **Comptes** permet de connecter un compte
(Facebook…) sans quitter FaithBook, puis de le réutiliser pour toutes les cibles
qui lui sont liées. Le parcours :

1. **Comptes → « Ajouter un compte »** : donnez-lui un nom (ex. `Facebook — SPYPOINT`).
2. **« Connecter »** : un navigateur s'ouvre **dans la fenêtre** (via noVNC).
   **Vous** saisissez vos identifiants et validez la 2FA — le backend ne voit ni
   ne stocke aucun mot de passe.
3. **« J'ai terminé »** : la session (cookies) est exportée, **chiffrée** (Fernet)
   et rangée dans un coffre `data/profiles/<slug>.tar.enc`. Seule sa présence est
   exposée par l'API, jamais les cookies.
4. Dans une **cible**, choisissez ce compte dans **« Compte connecté »**
   (`account_id`). À chaque capture, la page est alors ouverte **connectée** — le
   journal de l'exécution indique *« Session du compte … chargée »*.

Après chaque capture, FaithBook exporte les cookies éventuellement renouvelés
par Facebook, actualise la copie `storage_state`, puis rescelle le profil
Chromium dans son coffre chiffré. Un verrou propre à chaque profil empêche une
capture, un test de session et une connexion noVNC d'ouvrir le même coffre au
même moment. Cela ne supprime pas l'accès noVNC : une reconnexion manuelle reste
possible depuis l'onglet **Comptes** dès que l'opération en cours est terminée.

| Action (onglet Comptes) | Effet |
|---|---|
| **Tester** | Rouvre la session en arrière-plan et indique son état : `connecté`, `déconnecté`, `session expirée`, `vérification requise` (2FA/checkpoint). |
| **Reconnecter** | Relance la connexion manuelle (session expirée, mot de passe changé…). |
| **Supprimer** | Efface le coffre chiffré et détache les cibles (sans les supprimer). |

Sécurité : aucun mot de passe n'est lu ni stocké. La clé de chiffrement vient de
`SESSION_ENCRYPTION_KEY` (ou d'un fichier `data/.session_key` généré au premier
démarrage en développement). La génération locale est atomique, même avec
plusieurs requêtes concurrentes. Avec `ENVIRONMENT=production`, le backend
refuse de démarrer sans `SESSION_ENCRYPTION_KEY`.

> **Écran noVNC protégé par un jeton à usage court (Phase 1a).** `/novnc/` et
> `/websockify` sont gardés par nginx (`auth_request`) : l'accès exige (1) une
> session FaithBook valide (ou la clé API rattachée au même propriétaire)
> **et** (2) un jeton à usage court posé en cookie
> `HttpOnly` par `POST /login/start`, régénéré à chaque connexion et invalidé
> à la fin (`login/finish`/`login/cancel`) ou après `NOVNC_TOKEN_TTL_MINUTES`
> (10 min par défaut). Le jeton est en plus lié à l'utilisateur qui a démarré
> la connexion : **un autre utilisateur, même en possession du jeton, ne peut
> pas rejoindre l'écran** — vérifié par `tests/test_api_security.py`.

> **Prérequis infra** : la connexion manuelle affiche un vrai navigateur sur un
> écran virtuel (`Xvfb`) exposé via noVNC. Tout est intégré à l'image Docker
> (`xvfb`, `x11vnc`, `novnc`, `websockify`, `DISPLAY=:99`) — rien à installer.

**Alternative en ligne de commande** (sans interface). Le script historique
récupère les cookies et les pousse directement sur une cible via son
`session_profile` / `storage_state_json` — utile pour un serveur sans accès à
l'interface :

```bash
pip install playwright && playwright install chromium
python scripts/login_session.py --url https://www.facebook.com/ --push 1
curl http://localhost:3000/api/targets/1/session    # etat + date d'expiration
```

`session_profile` crée un profil Chromium persistant dans `data/profiles/` : les
cookies rafraîchis par Facebook y sont conservés d'une exécution à l'autre. Si
une cible a **à la fois** un compte connecté et un `session_profile`, le **compte
connecté est prioritaire**. Le `storage_state_json` de la cible est **chiffré
au repos** (Fernet, même clé que les comptes connectés) : une migration
(`b3d4e5f6a7c8`) a chiffré les valeurs existantes, et l'API chiffre désormais
toute nouvelle valeur écrite via `PUT /api/targets/{id}/session`.

### Points de vigilance à connaître

- **La session expire** (quelques semaines). La détection du mur de connexion
  suspend l'exécution avec un message explicite au lieu de l'archiver ou de
  réessayer inutilement. L'onglet **Comptes** affiche l'expiration estimée et le
  contrôle quotidien prévient `SESSION_EXPIRY_WARNING_DAYS` jours avant une
  échéance connue ; il suffit alors de **Reconnecter**.
- **Conditions d'utilisation de Facebook** : l'accès automatisé n'est pas prévu
  par leurs CGU. Un usage à faible fréquence (1 capture/jour/page) reste discret,
  mais le risque de blocage temporaire du compte utilisé n'est pas nul. Il est
  prudent d'utiliser un compte dédié plutôt que votre compte principal.
- **Pour vos propres pages**, l'API Graph / Meta Business Suite est la voie
  officielle et stable pour les *métriques*. Elle ne remplace pas une capture
  visuelle, mais elle est plus fiable si c'est de la donnée chiffrée que vous
  cherchez. À arbitrer selon l'usage final des captures.
- Le fichier `secrets/session.json` vaut un accès au compte : il est exclu du
  dépôt par `.gitignore`, ne le partagez pas.

---

## 11. Tests

### Suite pytest (unitaire + intégration)

```bash
docker compose exec backend python -m pytest tests/ -v
```

| Fichier | Couvre |
|---|---|
| `tests/test_ssrf.py` | Anti-SSRF : boucle locale, réseaux privés, metadata cloud, liste blanche, redirection et sous-requête navigateur |
| `tests/test_crypto.py` | Chiffrement Fernet, coffre de profil, génération concurrente atomique, clé obligatoire en production |
| `tests/test_session_state.py` | Déchiffrement transparent du `storage_state_json` (valeur chiffrée, repli legacy en clair, donnée illisible) |
| `tests/test_login_authorize.py` | `LoginManager.authorize()` : jeton correct/incorrect, expiré, isolation entre utilisateurs |
| `tests/test_audit.py` | Le journal d'audit écrit et relit correctement, sans fuite quand `user=None` |
| `tests/test_api_security.py` | SSRF, gates nginx, isolation noVNC, audit des connexions et du contrôle de session |
| `tests/test_api_key_identity.py` | Clé API liée à un utilisateur réel, accès Facebook/noVNC conservé, isolation entre propriétaires |
| `tests/test_client_ip.py` | IP réelle acceptée uniquement depuis un proxy de confiance |
| `tests/test_deployment_security.py` | Backend non publié, ACL du proxy sortant et suppression du PID Squid périmé au démarrage |
| `tests/test_session_robustness.py` | Verrou de profil, statut déconnecté, suspension sans retry et rotation des cookies |
| `tests/test_ops_phase1c.py` | Sauvegarde SQLite/PostgreSQL, chiffrement, contrôle d'intégrité, restauration et CI |
| `tests/test_run_queue.py` | Mise en file Redis et verrou anti-concurrence par cible |
| `tests/test_legacy_migration.py` | Conservation des données lors de la migration SQLite, y compris depuis un ancien schéma |
| `tests/test_capture_scroll.py` | Défilement progressif, stabilisation des pages dynamiques et limite des fils infinis |
| `tests/test_drive.py` | Dossiers datés, Drive partagé, upload reprenable, déduplication et reprise sans recapture |
| `tests/test_quotas.py` | Consommation, limites comptes/cibles/captures/stockage, course entre workers et rétention isolée |

`tests/conftest.py` isole totalement les tests de la base et des fichiers
réels du conteneur (base SQLite temporaire, clé de chiffrement générée,
dossiers de travail à part) — aucun risque pour les données de production.
Le relais nginx lui-même (`auth_request`) n'est pas rejouable en pytest (pas
de nginx dans ces tests) ; il a été vérifié manuellement de bout en bout
(session absente → `401`, session sans jeton → `403`, session + jeton → `200`
puis handshake WebSocket `101`).

### Smoke test (bout en bout, conteneurs réels)

```bash
API_KEY=... bash scripts/run_tests.sh 3000   # ou SMOKE_PASSWORD=...
```

| Suite | Couvre |
|---|---|
| `scripts/smoke_test.py` | API réelle : création de cible, planification, capture, dossier par site, PNG, doublon, `force=true`, échec après 3 tentatives (URL réelle à port fermé, pour ne pas être intercepté plus tôt par le garde anti-SSRF) |
| Vérifs interface | Page servie, relais `/api` par nginx, route profonde (`/historique`) |

### Validation locale complète

Cette commande contrôle Compose, reconstruit les images, attend les
healthchecks, exécute pytest dans le backend et vérifie le frontend :

```powershell
python scripts\validate_local.py
```

Après une première construction, `--skip-build` accélère la vérification.
`--smoke` ajoute le scénario réel de capture si `API_KEY` ou
`SMOKE_PASSWORD` est défini dans l'environnement.

La CI définie dans `.github/workflows/ci.yml` exécute séparément les tests
backend, le build frontend et la validation Compose à chaque push et pull
request.

---

## 12. Base de données et migrations

Le schéma est versionné avec **Alembic**. Les migrations s'appliquent
automatiquement au démarrage du conteneur — rien à lancer à la main.

La migration v1.3.0 crée une organisation par utilisateur existant et rattache
automatiquement tous les comptes et toutes les cibles déjà présents. Aucune
capture ni session Facebook/noVNC n'est supprimée.

```bash
docker exec capture-backend alembic current    # révision appliquée
docker exec capture-backend alembic history    # historique
```

Après toute modification de [models.py](app/models.py) :

```bash
docker compose run --rm --no-deps -v "$(pwd)/migrations:/app/migrations" \
  backend alembic revision --autogenerate -m "description du changement"
docker compose up -d --build
```

> Pourquoi Alembic plutôt que `create_all` : `create_all` crée les tables
> manquantes mais **ne modifie jamais une table existante**. Lors du renommage
> de `drive_subfolder` en `subfolder`, la base est partie en erreur au
> démarrage (`no such column`). En développement on efface la base ; avec des
> données réelles, ce n'est pas une option.

### PostgreSQL et migration de l'ancienne base

PostgreSQL 17 est maintenant la base active de Compose. Au premier démarrage
de la v1.5.2 :

1. Alembic crée le schéma PostgreSQL à jour.
2. Si PostgreSQL est vide et que `data/app.db` existe, toutes les lignes SQLite
   sont copiées dans une transaction.
3. Les séquences d'identifiants sont recalées.
4. `data/app.db` reste intacte : aucune donnée historique n'est supprimée.

La migration conserve utilisateurs, organisations, cibles, historique,
invitations, sessions applicatives et références des sessions Facebook. Les
coffres chiffrés et captures restent dans leurs dossiers existants.

La migration v1.6.0 ajoute le suivi des envois Drive (`pending`, `uploaded`,
`failed`, erreur, date et prochaine reprise). La copie depuis une ancienne
SQLite ne lit que les colonnes réellement présentes : les données v1.5.x
restent donc migrables sans modification manuelle.

La migration v1.7.0 ajoute à chaque organisation ses quotas et sa durée de
rétention. Les espaces existants reçoivent les valeurs par défaut sans modifier
leurs membres, cibles, comptes, sessions Facebook, captures ni références
Google Drive.

La v1.5.2 attend que Xvfb accepte réellement les connexions avant de lancer
x11vnc. Elle évite ainsi un écran noVNC « Échec de connexion au serveur »
provoqué par une course au démarrage du conteneur.

Configuration locale par défaut :

```env
POSTGRES_DB=faithbook
POSTGRES_USER=faithbook
POSTGRES_PASSWORD=faithbook-local-change-me
```

Avant un VPS, remplacer le mot de passe et renseigner au besoin
`POSTGRES_DATABASE_URL` avec un mot de passe encodé comme URL.

### Redis et worker de captures

L'API ne lance plus Chromium dans son propre processus. Elle crée une exécution
`pending`, réserve la cible dans Redis et place le run dans une file persistante.
Le conteneur `faithbook-worker` récupère le message, exécute la capture et met à
jour PostgreSQL.

- Une seule capture simultanée par cible.
- Liste `processing` séparée : un message réservé n'est acquitté qu'après
  traitement.
- Après un arrêt du worker, les messages interrompus sont remis en file.
- Le healthcheck expose `redis_ok`, `worker_alive`, `queue_depth` et
  `database_backend`.

### Sauvegarde et restauration

Lorsque PostgreSQL tourne, la sauvegarde appelle `pg_dump` dans le conteneur
`db`. Pour une ancienne installation SQLite, elle conserve le mécanisme de
copie cohérente existant. L'archive contient également les profils Facebook
chiffrés, la clé locale et `.env`, puis elle est chiffrée en AES-GCM.

```powershell
python scripts\backup.py
```

Le fichier est créé dans `backups\faithbook-AAAAMMJJ-HHMMSS.fbk`. Le mot de
passe demandé n'est pas enregistré. Pour une tâche planifiée :

```powershell
$env:FAITHBOOK_BACKUP_PASSPHRASE="un-mot-de-passe-long-et-unique"
python scripts\backup.py
Remove-Item Env:FAITHBOOK_BACKUP_PASSPHRASE
```

Les captures et `secrets` sont exclus par défaut. Les options
`--include-captures` et `--include-secrets` les ajoutent.

Restauration :

```powershell
docker compose down
python scripts\restore.py "backups\faithbook-AAAAMMJJ-HHMMSS.fbk"
docker compose up -d --wait
```

Le script vérifie tous les SHA-256 avant d'écrire, refuse de travailler si les
conteneurs tournent et crée automatiquement une sauvegarde `pre-restore`.
Par sécurité, `.env`, les captures et `secrets` ne sont pas écrasés sans
`--restore-env`, `--restore-captures` ou `--restore-secrets`.

---

## 13. Passage sur VPS (Phase 3)

Aucun changement de code. Sur le VPS :

```bash
git clone <repo> && cd <repo>
cp .env.example .env
mkdir -p data secrets /var/captures
docker compose up -d --build
```

À adapter dans le `.env` de production, **et rien d'autre** :

| Variable | Local | VPS |
|---|---|---|
| `OUTPUT_DIR` | `./captures` | `/var/captures` |
| `FRONTEND_PORT` | `3000` | `80`/`443` derrière un reverse-proxy HTTPS |
| `API_KEY` | vide | **à renseigner** (active `X-API-Key`) |
| `API_KEY_USER_EMAIL` | `admin@local` | compte réel propriétaire utilisé par les intégrations |
| `ENVIRONMENT` | `development` | `production` |
| `SESSION_ENCRYPTION_KEY` | génération locale possible | **obligatoire** et sauvegardée |
| `POSTGRES_PASSWORD` | mot de passe local à remplacer | secret fort, jamais publié |
| `REDIS_URL` | `redis://redis:6379/0` | réseau Docker privé |
| `BROWSER_PROXY_URL` | proxy Squid interne | proxy Squid interne |
| `TRUSTED_PROXY_CIDRS` | réseau nginx Docker | uniquement les réseaux des reverse-proxys de confiance |
| `CORS_ORIGINS` | `*` | domaine du frontend |
| `PUBLIC_URL` | `http://localhost:3000` | domaine HTTPS du frontend (réinitialisation et invitations) |
| `INVITATION_DAYS` | `7` | durée de validité d'une invitation |
| `SMTP_*` | vide (lien journalisé) | serveur SMTP réel pour envoyer les mails et invitations |
| `TIMEZONE` | `Africa/Casablanca` | idem |

Utiliser `python scripts/backup.py` pour la base, les sessions et la clé. Les
captures peuvent être ajoutées avec `--include-captures` ou sauvegardées
séparément depuis `OUTPUT_DIR`.

Pour récupérer les captures depuis le VPS, `OUTPUT_DIR` peut pointer vers un
montage réseau ou un dossier synchronisé — toujours sans toucher au code.
