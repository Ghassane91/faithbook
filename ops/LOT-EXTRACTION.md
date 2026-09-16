# Lot à exécuter — premier test d'extraction sur vos vraies pages

Deux blocs. Le premier sur votre PC, le second sur le serveur. Rien n'est
reconstruit, rien n'est écrit en base, aucun service n'est redémarré.

---

## Bloc 1 — publier le code (PowerShell, sur votre PC)

```powershell
cd C:\Users\G\Hetzner\faithbook-git
git pull --rebase
git add app/services/extraction.py app/config.py .env.example `
        tests/test_extraction.py `
        ops/tester-extraction.py ops/tester-extraction.sh `
        ops/REGLES-EXTRACTION.md ops/EXTRACTION-IA-DRIVE.md ops/A-FAIRE-GOOGLE.md `
        ops/fb-drive.sh ops/envoyer-sauvegardes-b2.sh app/services/drive.py
git commit -m "Extraction structuree : service, reglages, banc de test lecture seule"
git push
```

`git status` avant de committer si vous voulez vérifier qu'aucun `.env` réel
ni fichier de `secrets/` ne part avec. Ils sont déjà dans `.gitignore`.

---

## Bloc 2 — sur le serveur

```bash
ssh -p 2222 ghassane@62.238.108.19
cd /opt/integrit/src/faithbook
sudo git pull

# --- la clé Anthropic, sans jamais l'afficher ni la laisser dans l'historique
sudo -v
read -rsp "Cle Anthropic (collez, puis Entree) : " CLE; echo
if sudo grep -q '^ANTHROPIC_API_KEY=' .env; then
  sudo sed -i "s|^ANTHROPIC_API_KEY=.*|ANTHROPIC_API_KEY=${CLE}|" .env
else
  echo "ANTHROPIC_API_KEY=${CLE}" | sudo tee -a .env >/dev/null
fi
unset CLE
if sudo grep -q '^EXTRACTION_ENABLED=' .env; then
  sudo sed -i 's|^EXTRACTION_ENABLED=.*|EXTRACTION_ENABLED=true|' .env
else
  echo "EXTRACTION_ENABLED=true" | sudo tee -a .env >/dev/null
fi

# --- contrôle : doit afficher 1 puis EXTRACTION_ENABLED=true. Jamais la clé.
sudo grep -c '^ANTHROPIC_API_KEY=.\+' .env
sudo grep '^EXTRACTION_ENABLED=' .env

# --- les pages disponibles
sudo bash ops/tester-extraction.sh --lister
```

Notez un numéro de **cible** dans la liste, puis :

```bash
# 1. voir l'invite, sans appeler le modèle : aucun coût, aucune connexion sortante
sudo bash ops/tester-extraction.sh --cible 12 --invite

# 2. le vrai test
sudo bash ops/tester-extraction.sh --cible 12
```

Autres règles : `--regle forfaits` sur une page de tarifs,
`--regle editorial` sur une page d'actualités.

---

## Ce que fait exactement le test

Il lit le texte d'une capture déjà en base, l'envoie au modèle, et affiche les
lignes retenues plus les anomalies. **Il ne fait que des SELECT.**

Le conteneur `faithbook-backend` embarque le code figé à sa construction : il ne
connaît pas encore `extraction.py`. Le script y dépose les deux fichiers
nécessaires le temps du test, puis **remet les versions d'origine en sortant**,
même si le test échoue. Aucune image n'est reconstruite.

---

## Ce que vous devez juger sur la sortie

| Regardez | La question |
|---|---|
| Le nombre de lignes | Est-ce que tous les produits de la page y sont ? |
| La colonne `prix` | Est-ce bien le prix courant, ou le prix barré ? |
| Les anomalies | Une valeur écartée signale une invention du modèle **ou** une description à corriger |
| Une ligne écartée | Elle n'avait pas son champ obligatoire. Vérifiez qu'elle méritait de partir |

Les descriptions des champs sont en haut de `ops/tester-extraction.py`.
Modifiez-les, relancez, comparez : c'est la boucle de réglage. Quand une
formulation vous convient, reportez-la dans `ops/REGLES-EXTRACTION.md`.

---

## Après, et seulement après

Le branchement sur le pipeline de capture et l'export quotidien vers Drive
supposent une migration de base et un `docker compose build`. Je ne les touche
pas tant que vous n'avez pas jugé la qualité de l'extraction sur vos pages,
et tant que les quatre décisions de `REGLES-EXTRACTION.md` sont ouvertes :
prix barré, seuil d'alerte, devise, périmètre.

Note technique pour l'export : `openpyxl` n'est pas dans `requirements.txt`.
Il faudra l'ajouter pour produire le `.xlsx` quotidien.
