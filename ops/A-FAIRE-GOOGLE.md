# Raccordement Drive — la partie qui se fait dans le navigateur

Dix minutes, une seule fois. Le reste est automatisé par `fb-drive.sh`.

Dossier de destination retenu :
`1ZbCQlk_aza5Bj188_jkA1P47sf2r3MEr`

---

## 1. Le compte de service existe-t-il déjà ?

Console Google Cloud → IAM et administration → Comptes de service.

Cherchez une adresse se terminant par `iam.gserviceaccount.com` créée pour FaithBook.

- **S'il existe :** relevez son adresse. Une clé JSON a peut-être déjà été générée et déposée sur le serveur — le script vous le dira.
- **S'il n'existe pas :** créez-le, étape 2.

**Ne me transmettez jamais la clé privée.** L'adresse `…iam.gserviceaccount.com` suffit et n'est pas un secret.

## 2. Créer le compte de service

1. Console Google Cloud, sélectionnez ou créez un projet.
2. API et services → Bibliothèque → activer **Google Drive API**.
3. IAM et administration → Comptes de service → Créer.
   Nom : `faithbook-archivage`. Aucun rôle IAM nécessaire : les droits viennent du partage Drive, pas d'IAM.
4. Onglet Clés → Ajouter une clé → Créer → JSON. Le fichier se télécharge.

## 3. Partager le dossier Drive

1. Ouvrez le dossier `1ZbCQlk_aza5Bj188_jkA1P47sf2r3MEr`.
2. Partager → collez l'adresse `…iam.gserviceaccount.com`.
3. Rôle : **Éditeur**, ou **Contributeur** s'il s'agit d'un Drive partagé.
4. Décochez la notification par e-mail : un compte de service n'a pas de boîte.

**Vérifiez si c'est un Drive partagé ou un dossier de Mon Drive.** Sur un Drive partagé, l'identifiant du Drive apparaît dans l'URL lorsque vous êtes à sa racine. Renseignez-le à l'exécution :

```bash
sudo FB_DRIVE_SHARED_ID=<identifiant> ./fb-drive.sh --activer
```

Un Drive partagé est préférable : les fichiers appartiennent à l'organisation, pas au compte de service, et restent accessibles si ce compte est supprimé.

## 4. Déposer la clé sur le serveur

Depuis PowerShell, sur votre PC :

```powershell
scp -P 2222 C:\Users\G\Downloads\<le-fichier>.json ghassane@62.238.108.19:/tmp/sa.json
```

Puis sur le serveur :

```bash
sudo mkdir -p /opt/integrit/secrets
sudo mv /tmp/sa.json /opt/integrit/secrets/service-account.json
sudo chown root:root /opt/integrit/secrets/service-account.json
sudo chmod 600 /opt/integrit/secrets/service-account.json
sudo chmod 700 /opt/integrit/secrets
```

Ce fichier ne doit jamais entrer dans Git. Vérifiez que `/opt/integrit/secrets` n'est pas dans un dépôt.

---

## 5. Ensuite, le lot unique

```bash
sudo /opt/integrit/ops/fb-drive.sh --verifier
```

Ne modifie rien. Affiche ce qui manque, et surtout **l'adresse du compte de service à partager** si la clé est déjà en place.

Puis, quand tout est vert :

```bash
sudo /opt/integrit/ops/fb-drive.sh --activer
```

Sauvegarde la configuration, l'écrit, redémarre les conteneurs, et **téléverse réellement un fichier témoin**. Rien n'est déclaré actif sans confirmation de Google.

En cas d'échec :

```bash
sudo /opt/integrit/ops/fb-drive.sh --restaurer
```

---

## Ce que le script ne fait pas

- Il ne crée pas le compte de service : cela passe par la console Google.
- Il ne modifie pas `docker-compose.yml`. Si un conteneur ne voit pas `/secrets/service-account.json`, il le signale mais ne touche pas au compose — c'est à vous de décider.
- Il n'invente aucun identifiant de Drive partagé.
