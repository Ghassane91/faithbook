# FaithBook — Outils d'exploitation

Scripts de déploiement, de retour arrière, de vérification et d'inventaire pour la
nouvelle interface FaithBook servie sur `/nouvelle-interface/`.

## Ordre d'exécution

| # | Commande | Modifie quelque chose ? |
|---|---|---|
| 1 | `./fb-inventaire.sh > /tmp/inventaire.txt` | non |
| 2 | Confirmer `FB_CADDYFILE` et le port du service dans `faithbook-env.sh` | — |
| 3 | `./fb-verifier.sh` | non |
| 4 | `./fb-deployer.sh --dry-run` | non |
| 5 | `./fb-deployer.sh` | oui, avec sauvegarde |
| 6 | `./fb-restaurer.sh --lister` puis `./fb-restaurer.sh <horodatage>` | oui, réversible |

## Fichiers

| Fichier | Rôle |
|---|---|
| `faithbook-env.sh` | Configuration. Seul fichier à adapter. |
| `fb-lib.sh` | Fonctions communes. Ne se lance pas seul. |
| `fb-inventaire.sh` | Inventaire du serveur, lecture seule, secrets masqués. |
| `fb-verifier.sh` | Contrôles HTTP. Sortie 0 ou 1, branchable sur un timer. |
| `fb-deployer.sh` | Déploiement avec sauvegarde et publication atomique. |
| `fb-restaurer.sh` | Retour arrière vers une sauvegarde horodatée. |
| `fb-caddy.sh` | Application d'une configuration Caddy avec retour arrière automatique. |
| `PROCEDURE-DEPLOIEMENT.md` | Procédure complète. |
| `MISE-EN-PRODUCTION.md` | Domaine, bascule, périmètre fonctionnel. |

## Installation sur le serveur

```bash
sudo mkdir -p /opt/integrit/ops && sudo chown "$USER" /opt/integrit/ops
cp <ce-dossier>/* /opt/integrit/ops/
cd /opt/integrit/ops
sed -i 's/\r$//' ./*.sh
chmod +x fb-*.sh
./fb-inventaire.sh > /tmp/inventaire-faithbook.txt
```

## Valeurs déjà réglées

Lues dans le dépôt, pas supposées :

- construction : `npm run build:hetzner`, sortie `dist-hetzner`
- Node 22.13.0 minimum, contrôlé par le script avant de construire
- routes vérifiées : `/api/auth/me`, `/api/targets`, `/api/runs`

`npm run build` produit la version Cloudflare Workers, pas les fichiers servis par Caddy. Ne pas confondre.

## Particularités de ce serveur

Relevées le 7 septembre 2026 :

- **Caddy tourne dans Docker** (conteneur `caddy`). Pas de `systemctl reload caddy`, pas de `/etc/caddy/Caddyfile` sur l'hôte. `fb-caddy.sh` le détecte seul.
- **Node et npm ne sont pas installés.** Construire ailleurs, puis `./fb-deployer.sh --from-archive`.
- **Aucun outil de sauvegarde installé.** À vérifier avant toute livraison.
- Le dossier servi appartient à `root` : les scripts passent par `sudo` automatiquement.
- `uptime-kuma` tourne déjà : c'est là qu'il faut brancher la surveillance.

## Principes

- Aucun script ne supprime quoi que ce soit lors d'un déploiement.
- Toute modification est précédée d'une sauvegarde horodatée.
- Tout retour arrière est lui-même sauvegardé, donc réversible.
- Un échec de construction ou de vérification arrête le processus et affiche la
  commande de retour arrière.
