# FaithBook — extraction d'informations et dépôt Drive

**Objet :** extraire automatiquement des informations précises des pages capturées (prix, référence, disponibilité…), produire une synthèse quotidienne, et déposer le tout dans le dossier Drive du jour.

**Constat :** l'essentiel existe déjà dans le code. Ce document sépare ce qui s'active de ce qui se développe.

---

## 1. Ce qui existe déjà — vérifié dans le code au 14 septembre 2026

### Le texte des pages est conservé

La table `Run` contient `body_text` : le texte intégral de chaque page capturée. **L'extraction n'a donc pas besoin de lire les images.** Travailler sur le texte est vingt à cinquante fois moins coûteux, plus rapide, et bien plus fiable qu'une lecture visuelle.

La vision ne devient nécessaire que si l'information recherchée n'existe que dans une image — un prix incrusté dans un visuel produit, par exemple. C'est un cas minoritaire, à traiter en second temps.

### Un LLM est déjà branché

`app/services/ai_summary.py` expose deux fournisseurs, `anthropic` et `ollama`, avec repli silencieux : une panne du modèle ne fait jamais échouer une capture. Le service est désactivé par défaut.

### Google Drive avec un dossier par jour est déjà écrit

`app/services/drive_sync.py`, fonction `folder_names()` :

```
AAAA-MM-JJ / organisation / site / [sous-dossier]
```

Le format de date vient de `FOLDER_DATE_FORMAT`. La reprise sur échec est en base : `drive_status`, `drive_attempts`, `drive_next_retry_at`, `drive_last_error`, `drive_file_link`.

---

## 2. Le moteur : API Anthropic, pas Ollama

Décision technique, pas préférence.

| Contrainte | Conséquence |
|---|---|
| Serveur : 3,7 Gio de RAM, 1,8 utilisés, 1,2 Gio de swap consommé | Un modèle 7B en demande ~5 Gio. Impossible. |
| `OLLAMA_BASE_URL=http://host.docker.internal:11434` | Pointe vers votre poste Windows, injoignable depuis Hetzner. |
| Extraction de valeurs précises | C'est l'exercice où les petits modèles échouent le plus. |

**Levier de coût à connaître :** `AI_SUMMARY_MODEL` vaut `claude-opus-5` par défaut. Pour de l'extraction sur du texte, un modèle plus léger suffit et coûte bien moins. Gardez le modèle fort pour la synthèse quotidienne, qui ne tourne qu'une fois par jour.

L'ordre de grandeur à surveiller : une page fait typiquement 5 000 à 20 000 caractères, soit 2 000 à 6 000 jetons. Multipliez par votre nombre de captures quotidiennes. Vérifiez les tarifs en vigueur avant d'activer — je ne les invente pas.

---

## 3. Étape 1 — activer Drive. Aucun code, faisable aujourd'hui

C'est le préalable : sans Drive actif, l'extraction n'a nulle part où déposer ses fichiers. Et cela valide l'arborescence par jour avec les captures elles-mêmes, avant d'y ajouter quoi que ce soit.

### 3.1 Créer le compte de service Google

1. Console Google Cloud, créer un projet ou réutiliser un existant.
2. Activer l'API Google Drive.
3. Créer un compte de service, générer une clé JSON.
4. Sur le Drive, créer le dossier parent qui recevra tout, puis **le partager en écriture avec l'adresse e-mail du compte de service**.
5. Relever l'identifiant du dossier parent : il est dans son URL, après `/folders/`.

**Recommandé :** utiliser un Drive partagé plutôt qu'un dossier personnel. Un compte de service n'a pas de quota propre ; dans un Drive personnel, les fichiers appartiennent au compte de service et deviennent difficiles à récupérer s'il est supprimé. Dans un Drive partagé, ils appartiennent à l'organisation.

### 3.2 Déposer la clé sur le serveur

Le fichier ne doit jamais entrer dans le dépôt Git.

```bash
sudo mkdir -p /opt/integrit/secrets
sudo chmod 700 /opt/integrit/secrets
# copier le JSON dans /opt/integrit/secrets/service-account.json
sudo chmod 600 /opt/integrit/secrets/service-account.json
```

Vérifier qu'il est bien monté dans le conteneur FaithBook sur `/secrets/service-account.json`.

### 3.3 Configuration

```env
STORAGE_BACKEND=google_drive
GOOGLE_SERVICE_ACCOUNT_FILE=/secrets/service-account.json
GOOGLE_DRIVE_PARENT_FOLDER_ID=<identifiant du dossier parent>
GOOGLE_DRIVE_SHARED_DRIVE_ID=<identifiant du Drive partagé, si vous en utilisez un>
FOLDER_DATE_FORMAT=%Y-%m-%d
```

`google_drive` **conserve la copie locale** puis l'envoie vers Drive. Vous ne perdez rien en basculant.

### 3.4 Contrôle

Après redémarrage, lancer une collecte et vérifier :

- le dossier `2026-09-14/` apparaît sous le dossier parent, avec ses sous-dossiers organisation puis site ;
- dans l'interface, la fiche de collecte affiche « Copie distante disponible » au lieu de « Local » ;
- en base, `drive_status = uploaded` et `drive_file_link` est renseigné.

Si `drive_status` reste à `failed`, `drive_last_error` donne la cause exacte.

---

## 4. Étape 2 — l'extraction. À développer

### 4.1 Principe

Une **règle d'extraction** attachée à une cible définit les champs à chercher. À chaque collecte réussie, le texte de la page est soumis au modèle avec cette règle, et les valeurs sont enregistrées.

Une règle se compose de :

| Élément | Rôle | Exemple |
|---|---|---|
| Cible | Sur quelle page elle s'applique | Site fournisseur X |
| Nom du champ | Identifiant stable, utilisé en colonne | `prix_ttc` |
| Description | Ce que le modèle doit chercher | « Prix affiché TTC en dirhams de la caméra, hors promotion barrée » |
| Type | Contrôle de forme | nombre, texte, date, booléen |
| Obligatoire | Si l'absence est une anomalie à signaler | oui / non |

Le modèle est contraint à répondre en JSON selon ce schéma. Une valeur introuvable vaut `null` — **jamais une valeur inventée.** C'est le point le plus important : une extraction qui devine est pire que pas d'extraction.

### 4.2 Ce qui est produit chaque jour

Dans le dossier Drive du jour, à côté des captures :

1. **`extractions-AAAA-MM-JJ.xlsx`** — une ligne par capture, une colonne par champ, plus la cible, l'heure, le lien vers la capture et un indicateur de confiance.
2. **`synthese-AAAA-MM-JJ.md`** — ce qui a changé sur l'ensemble des cibles, les valeurs qui ont bougé depuis la veille, et les anomalies : champ obligatoire absent, variation de prix au-delà d'un seuil, cible en échec.

### 4.3 Ce que cela demande côté code

- Deux tables : `extraction_rule` et `extraction_value`, plus une migration Alembic.
- Un service `app/services/extraction.py`, sur le modèle de `ai_summary.py` : jamais bloquant pour la capture.
- Un accrochage dans le pipeline après la capture réussie.
- Une tâche quotidienne produisant les deux fichiers et les déposant via `drive_sync.upload_capture`.
- Un écran de gestion des règles dans l'application complète.

---

## 5. Ce qu'il me manque pour commencer

Je ne peux pas inventer ces éléments.

| Manquant | Pourquoi c'est bloquant |
|---|---|
| **La liste réelle des champs** | « Le prix d'une caméra » est un exemple. Il me faut les champs exacts, leur description et leur type. C'est ce qui détermine la qualité de l'extraction. |
| **Les cibles concernées** | Toutes, ou seulement certaines ? Une règle par cible ou une règle commune ? |
| **Le seuil d'anomalie** | À partir de quelle variation de prix voulez-vous être alerté ? |
| **La clé Anthropic et le budget** | Sans clé, rien ne tourne. Sans plafond, la dépense n'est pas maîtrisée. |
| **Le Drive de destination** | Compte personnel ou Drive partagé, et quel dossier parent. |

Le plus utile : donnez-moi **une cible réelle et trois champs**. Je construis la règle, je la teste sur des captures existantes, et vous jugez sur pièce avant qu'on généralise.

---

## 6. Ordre recommandé

| # | Action | Code ? | Vérifiable |
|---|---|---|---|
| 1 | Activer Drive, contrôler le dossier du jour | non | immédiatement |
| 2 | Fournir une cible et trois champs | non | — |
| 3 | Développer l'extraction, la tester sur des captures passées | oui | sur pièce |
| 4 | Généraliser aux autres cibles | non | — |
| 5 | Synthèse quotidienne et dépôt automatique | oui | le lendemain |

L'étape 1 ne dépend de rien et prouve la moitié de la chaîne.

---

## 7. Deux réserves

**La recette de l'interface n'est toujours pas faite.** Quatre versions ont été publiées en deux jours sans qu'un compte réel ouvre l'application. Ajouter une fonction par-dessus une base non validée accroît la dette, sans la solder.

**Aucune sauvegarde n'est visible sur le serveur.** Une extraction qui accumule des données en base rend ce point plus sérieux qu'il ne l'était pour de simples images, qui existent en double sur Drive.
