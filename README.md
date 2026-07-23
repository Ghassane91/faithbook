# FaithBook — captures planifiées

Backend conteneurisé qui capture automatiquement des pages web à une heure
configurable et range les captures dans un dossier par site (nom de fichier =
site + date + heure).

- **API** : FastAPI (documentation OpenAPI sur `/docs`)
- **Navigateur** : Playwright / Chromium
- **Planification** : APScheduler (cron, avec fuseau horaire)
- **Base** : SQLite (fichier dans le volume `data/`)
- **Stockage** : un dossier de votre machine (§1). Google Drive : en suspens (§2).
- **Interface** : React + Vite, servie par nginx qui relaie l'API (§7)

Tout est piloté par variables d'environnement : **le passage du poste local au
VPS ne demande aucune modification de code**, uniquement un `.env` différent.

---

## 1. Démarrage rapide

```bash
cp .env.example .env
docker compose up -d --build
```

- **Interface web : http://localhost:3000** ← le point d'entrée
- API : http://localhost:8020
- Documentation interactive : http://localhost:8020/docs

> **Port 8020 et non 8000** : le port 8000 était déjà occupé sur ce poste par le
> conteneur `fencive-ui`. Réglé par `API_PORT=8020` dans le `.env`, sans aucune
> modification de code.

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
  facebook.com-spypoint.ca/
    facebook.com-spypoint.ca_2026-07-22_090012.png
  integr-it.com/
    integr-it.com_2026-07-22_090300.png
```

Le nom du site vient du domaine (sans `www`) plus le chemin de page éventuel,
pour distinguer deux pages d'un même domaine
(`facebook.com/SPYPOINT.CA` → `facebook.com-spypoint.ca`). Un `subfolder` de
cible, si renseigné, s'insère sous le dossier du site.

Règles pour `OUTPUT_DIR` :

- Par défaut `./captures`, à l'intérieur du projet (ignoré par Git).
- **Windows**, pour un chemin absolu : barres obliques normales
  (`C:/Users/G/Documents/Captures`), jamais d'antislash.
- **VPS** : un chemin Linux, ex. `/var/captures`. C'est la seule ligne à changer.
- Après modification : `docker compose up -d` (un simple `restart` ne suffit
  pas, le montage est recréé au démarrage du conteneur).

Créer une cible et lancer une capture immédiatement :

```bash
curl -X POST http://localhost:8020/api/targets \
  -H "Content-Type: application/json" \
  -d '{"name":"Exemple","url":"https://example.com","run_time":"09:00"}'

curl -X POST http://localhost:8020/api/targets/1/run
curl http://localhost:8020/api/runs/1            # statut + logs détaillés
curl -o capture.png http://localhost:8020/api/runs/1/screenshot
```

Ou, tout en un, avec le script de vérification :

```bash
bash scripts/run_tests.sh 8020 3000
```

---

## 2. Google Drive — EN SUSPEND

**Cette option n'est pas active.** Les captures sont enregistrées uniquement
dans `OUTPUT_DIR` (§1). L'API n'expose plus rien lié à Drive.

Rien n'a été supprimé pour autant :

| Élément | Emplacement | État |
|---|---|---|
| Client Drive | [drive.py](app/services/drive.py) | conservé, non appelé |
| Tests (39 vérifications) | [tests/suspendu/](tests/suspendu/) | conservés, hors suite par défaut |
| Colonnes `drive_*` de `runs` | [models.py](app/models.py) | conservées, non exposées |
| Variables `GOOGLE_*` | `.env.example` | commentées |

Pour réactiver plus tard : décommenter le bloc `GOOGLE_*` du `.env`, passer
`STORAGE_BACKEND=google_drive`, remettre la route `/api/drive/check` dans
[system.py](app/api/system.py) et rejouer les tests de `tests/suspendu/`.

---

## 3. Fonctionnalités demandées → où elles se trouvent

| # | Exigence | Implémentation |
|---|---|---|
| 1 | URL + heure configurables | Table `targets`, `run_time` (HH:MM) ou `cron_expression` — [models.py](app/models.py) |
| 2 | Ouverture automatique | APScheduler → [scheduler.py](app/scheduler.py) |
| 3 | Capture complète | `full_page=True` + pré-scroll lazy-load — [capture.py](app/services/capture.py) |
| 4 | Rangement par site | Un dossier par site dans `OUTPUT_DIR` — [runner.py](app/services/runner.py) |
| 5 | Dépôt de la capture | Écriture dans le dossier du site, nom = site + date + heure |
| 6 | Éviter les doublons | 3 niveaux, voir §4 — [runner.py](app/services/runner.py) |
| 7 | Réessai automatique | Backoff exponentiel, `MAX_ATTEMPTS` — [runner.py](app/services/runner.py) |
| 8 | Logs + statut par exécution | Tables `runs` / `run_logs` + fichier `data/app.log` |
| 9 | Lancement manuel | `POST /api/targets/{id}/run` |
| 10 | API REST documentée | OpenAPI sur `/docs` et `/redoc` |

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

### La plateforme vous prévient — plus de surveillance manuelle

Trois automatismes (mails envoyés via le bloc `SMTP_*` du §8 ; sans SMTP, le
contenu est journalisé) :

| Automatisme | Quand | Variable |
|---|---|---|
| **Alerte d'échec** | Immédiatement quand une capture échoue après tous les réessais — cible, erreur en clair, lien vers l'historique | `NOTIFY_ON_FAILURE=true` |
| **Contrôle des sessions** | Chaque jour : chaque compte connecté est testé en arrière-plan ; mail **uniquement si** une session est expirée / demande une vérification | `SESSION_CHECK_TIME=07:30` |
| **Rapport quotidien** | Un seul mail le matin : captures d'hier (réussites, échecs et leurs raisons), état des comptes, cibles actives | `DAILY_REPORT_TIME=08:00` |

Destinataire : `NOTIFY_EMAIL`, à défaut l'adresse du premier utilisateur.
Un horaire vide désactive la tâche.

### Nettoyage automatique

Chaque nuit (3 h 30), les exécutions **et les fichiers locaux** plus vieux que
`RUN_RETENTION_DAYS` (90 j par défaut) sont supprimés, dossiers vides compris.
La copie déjà synchronisée sur Google Drive n'est pas touchée : elle sert
d'archive longue durée.

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
| GET/POST | `/api/accounts` | Lister / créer un compte connecté |
| DELETE | `/api/accounts/{id}` | Déconnecter et supprimer la session |
| POST | `/api/accounts/{id}/login/start` · `/status` · `/finish` · `/cancel` | Connexion manuelle noVNC (voir §10) |
| POST | `/api/accounts/{id}/test` | Tester la validité de la session |
| POST | `/api/auth/forgot` · `/api/auth/reset` | Mot de passe oublié (voir §8) |

Ces routes couvrent déjà tous les besoins du frontend de la Phase 2
(gestion des URL, horaires, historique, captures, erreurs) ainsi que les comptes
connectés et la réinitialisation de mot de passe.

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

## 7. Interface web (Phase 2)

Ouvrez http://localhost:3000. Quatre vues, aucune configuration.

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

### Choix techniques

| Point | Décision |
|---|---|
| Communication | nginx relaie `/api` vers le backend : une seule origine, **aucune URL à configurer**, pas de CORS |
| Erreurs | Les messages Playwright bruts sont traduits en français (`resumeErreur`) ; la trace complète reste dans le détail |
| Vignettes | Générées par Pillow à la capture. La page Facebook passe de 188 Ko à 14 Ko — sans quoi la planche fige le navigateur |
| Polices | Aucune police distante : le monospace système porte l'identité. Fonctionne derrière un pare-feu |
| Dépendances | React et rien d'autre. Le routage tient en quinze lignes |

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
| Clé API | `API_KEY` donne un accès machine-à-machine à l'API (scripts, CI), **sans compte**. Sans rapport avec les comptes utilisateurs. |

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

| Action (onglet Comptes) | Effet |
|---|---|
| **Tester** | Rouvre la session en arrière-plan et indique son état : `connecté`, `session expirée`, `vérification requise` (2FA/checkpoint). |
| **Reconnecter** | Relance la connexion manuelle (session expirée, mot de passe changé…). |
| **Supprimer** | Efface le coffre chiffré et détache les cibles (sans les supprimer). |

Sécurité : aucun mot de passe n'est lu ni stocké. La clé de chiffrement vient de
`SESSION_ENCRYPTION_KEY` (ou d'un fichier `data/.session_key` généré au premier
démarrage — **à déplacer en variable d'environnement en production**, sinon les
sessions chiffrées deviennent illisibles si le fichier est perdu). L'écran noVNC
n'est accessible qu'à travers le proxy authentifié du frontend.

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
curl http://localhost:8020/api/targets/1/session    # etat + date d'expiration
```

`session_profile` crée un profil Chromium persistant dans `data/profiles/` : les
cookies rafraîchis par Facebook y sont conservés d'une exécution à l'autre. Si
une cible a **à la fois** un compte connecté et un `session_profile`, le **compte
connecté est prioritaire**.

### Points de vigilance à connaître

- **La session expire** (quelques semaines). `fail_if_url_contains` fait alors
  échouer l'exécution avec un message explicite au lieu d'archiver
  silencieusement des murs de connexion pendant des semaines. L'onglet **Comptes**
  (bouton **Tester**) et la colonne *Session* de l'onglet **Cibles** signalent une
  session expirée ou expirant bientôt ; il suffit alors de **Reconnecter**.
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

```bash
bash scripts/run_tests.sh 8020 3000
```

| Suite | Couvre |
|---|---|
| `scripts/smoke_test.py` | API réelle : création de cible, planification, capture, dossier daté, PNG, doublon, `force=true`, échec après 3 tentatives |
| Vérifs interface | Page servie, relais `/api` par nginx, route profonde (`/historique`) |

Les tests de l'intégration Drive sont dans [tests/suspendu/](tests/suspendu/) et
ne sont plus joués par défaut (voir §2).

---

## 12. Base de données et migrations

Le schéma est versionné avec **Alembic**. Les migrations s'appliquent
automatiquement au démarrage du conteneur — rien à lancer à la main.

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

### Passer à PostgreSQL (préparation SaaS)

Le driver `psycopg` est déjà installé et le code n'a aucune requête spécifique
à SQLite. Le changement est **uniquement de la configuration** :

```env
DATABASE_URL=postgresql+psycopg://user:motdepasse@db:5432/captures
```

Puis ajouter un service `db` dans `docker-compose.yml`. Les migrations
s'appliqueront au premier démarrage. Recommandé dès qu'il y a plusieurs
utilisateurs simultanés : SQLite tient bien la charge d'un usage mono-poste,
mais sérialise les écritures.

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
| `API_PORT` | `8020` | `8000` derrière un reverse-proxy HTTPS |
| `FRONTEND_PORT` | `3000` | `80`/`443` derrière un reverse-proxy HTTPS |
| `API_KEY` | vide | **à renseigner** (active `X-API-Key`) |
| `CORS_ORIGINS` | `*` | domaine du frontend |
| `PUBLIC_URL` | `http://localhost:3000` | domaine HTTPS du frontend (lien des mails de réinitialisation) |
| `SMTP_*` | vide (lien journalisé) | serveur SMTP réel pour envoyer les mails de réinitialisation |
| `TIMEZONE` | `Africa/Casablanca` | idem |

Ce qu'il faut sauvegarder : `./data` (base + journaux) et le contenu de
`OUTPUT_DIR` (les captures).

Pour récupérer les captures depuis le VPS, `OUTPUT_DIR` peut pointer vers un
montage réseau ou un dossier synchronisé — toujours sans toucher au code.
