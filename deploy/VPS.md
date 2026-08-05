# Héberger FaithBook sur un VPS

Compte une à deux heures la première fois. Rien ici n'est irréversible : tant
que ta machine Windows tourne, elle reste la référence.

---

## 1. Choisir la machine

Le dimensionnement dépend d'une seule question : **veux-tu le résumé IA local ?**

| | Sans résumé IA | Avec Ollama local |
|---|---|---|
| RAM | 4 Go | **8 Go** |
| vCPU | 2 | 4 |
| Disque | 40 Go SSD | **80 Go SSD** |
| Ordre de prix | 5-8 €/mois | 15-25 €/mois |

**D'où viennent ces chiffres.** `qwen2.5:7b-instruct` occupe ~5 Go de RAM une
fois chargé, et Chromium demande 1 à 2 Go en pic pendant une capture — sur une
page Facebook de 40 000 px de haut, ce n'est pas une marge théorique. En
dessous de 8 Go, le noyau tuera l'un ou l'autre au pire moment.

Pour le disque : une capture SPYPOINT pèse **35 Mo**. Sept cibles une fois par
jour font 245 Mo/jour, soit ~7,4 Go par mois. À 90 jours de conservation,
prévois **~22 Go rien que pour les images**, plus la base et le système.

> Si tu actives une cadence à 30 minutes sur ne serait-ce qu'une cible, ce
> calcul explose : 48 captures/jour × 35 Mo = **1,65 Go par jour**, 50 Go par
> mois. Le nouvel écran de cadence affiche ce chiffre en direct — lis-le avant
> de valider.

Système : **Debian 12** ou **Ubuntu 24.04**. Les deux conviennent.

---

## 2. Le domaine

Crée un enregistrement `A` qui pointe vers l'adresse IP du VPS, par exemple
`faithbook.novostok.com`. Attends que ça réponde avant d'aller plus loin :

```bash
dig +short faithbook.novostok.com
```

Sans cela, Let's Encrypt refusera le certificat et Caddy tournera en boucle.

---

## 3. Préparer le serveur

```bash
ssh root@TON_IP

apt update && apt upgrade -y
apt install -y ca-certificates curl git ufw
install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc
chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
https://download.docker.com/linux/debian $(. /etc/os-release && echo $VERSION_CODENAME) stable" \
  > /etc/apt/sources.list.d/docker.list
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

Le pare-feu, **avant** de démarrer quoi que ce soit :

```bash
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status numbered
```

C'est ce pare-feu qui ferme le port 3000 et le port noVNC. Docker Compose
*ajoute* les ports d'une surcouche à ceux du fichier de base au lieu de les
remplacer — le port 3000 reste donc publié côté Docker. Une règle `ufw`
explicite est plus fiable qu'une subtilité de fusion YAML que personne ne
relira.

Un utilisateur dédié plutôt que `root` :

```bash
adduser --disabled-password --gecos "" faithbook
usermod -aG docker faithbook
mkdir -p /opt/faithbook && chown faithbook:faithbook /opt/faithbook
```

---

## 4. Déposer le code

```bash
su - faithbook
git clone https://github.com/Ghassane91/faithbook.git /opt/faithbook
cd /opt/faithbook
```

---

## 5. La configuration

**Le `.env` ne se copie pas depuis GitHub — il n'y est pas, et c'est voulu.**
Recrée-le sur le VPS à partir de `.env.example`, en changeant tous les mots de
passe. Ne réutilise pas ceux de ta machine Windows.

```bash
cp .env.example .env
nano .env
chmod 600 .env
```

Trois valeurs qui changent par rapport à ton poste :

```env
FAITHBOOK_DOMAINE=faithbook.novostok.com

# Ollama tourne maintenant dans un conteneur voisin, pas sur un hôte Windows.
# host.docker.internal n'existe pas ici.
OLLAMA_BASE_URL=http://ollama:11434
```

Et évidemment : mot de passe PostgreSQL neuf, clé de chiffrement des sessions
neuve, jeton Telegram inchangé si tu veux garder les mêmes alertes.

---

## 6. Démarrer

Sans résumé IA :

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
```

Avec :

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml \
  --profile ia-locale up -d --build
docker compose exec ollama ollama pull qwen2.5:7b-instruct
```

Le `pull` télécharge ~4,7 Go. C'est long, et c'est normal.

Vérifie :

```bash
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml ps
curl -s https://faithbook.novostok.com/api/health | head -c 400
```

Les six services (sept avec Ollama) doivent être `healthy`, et `/api/health`
répondre `"status":"ok"`.

---

## 7. Se connecter à Facebook

C'est l'étape qu'on oublie de préparer, et elle bloque tout : les captures ont
besoin d'une session Facebook ouverte, qui s'établit dans une vraie fenêtre de
navigateur, via noVNC.

**Cette fenêtre n'est pas publiée sur Internet, volontairement.** Elle donne un
contrôle direct sur un navigateur déjà authentifié sur tes comptes : exposée,
elle vaut le mot de passe de ces comptes.

Depuis ton poste Windows, ouvre un tunnel le temps de la manipulation :

```powershell
ssh -L 6080:localhost:6080 faithbook@TON_IP
```

Puis, dans ton navigateur, `http://localhost:6080`. Connecte-toi à Facebook
comme d'habitude, ferme le tunnel, et la session reste valide côté serveur.

---

## 8. Sauvegardes

```bash
sudo cp /opt/faithbook/deploy/sauvegarde.sh /usr/local/bin/faithbook-sauvegarde
sudo chmod +x /usr/local/bin/faithbook-sauvegarde
sudo crontab -e
```

Ajoute :

```cron
30 3 * * * /usr/local/bin/faithbook-sauvegarde >> /var/log/faithbook-sauvegarde.log 2>&1
```

**Puis teste la restauration une fois.** Une sauvegarde jamais restaurée n'est
pas une sauvegarde — c'est un fichier dont on espère qu'il marche.

```bash
gunzip -c /var/backups/faithbook/db-AAAAMMJJ-HHMMSS.sql.gz | head -40
```

---

## 9. Mettre à jour

```bash
cd /opt/faithbook
git pull
docker compose -f docker-compose.yml -f deploy/docker-compose.prod.yml up -d --build
```

Les migrations Alembic s'appliquent seules au démarrage. Fais une sauvegarde
avant toute mise à jour qui touche à la base.

---

## 10. Et ta machine Windows ?

Rien ne t'oblige à l'arrêter tout de suite. Mais **ne laisse pas les deux
tourner sur les mêmes cibles** : deux FaithBook qui photographient le même
compte Facebook depuis deux adresses IP différentes, c'est le motif de
détection le plus classique — et une demande de vérification te coûterait la
session.

Quand le VPS est validé, désactive les cibles sur le poste Windows avant
d'activer celles du serveur.

---

## Ce que cette configuration ne fait pas encore

- **Supervision** : rien ne t'alerte si le VPS tombe. Un service gratuit type
  ping externe sur `/api/health` comble ce trou en dix minutes.
- **Rétention automatique des images** : les 90 jours sont une intention, pas
  encore une tâche qui supprime. Le disque se remplira sans prévenir.
- **Restauration testée** : voir l'étape 8. À faire une fois, vraiment.
