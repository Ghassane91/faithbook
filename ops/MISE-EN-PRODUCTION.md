# FaithBook — Dossier de mise en production

Ce document traite les quatre points qui restaient ouverts après la procédure de déploiement : l'inventaire préalable, le nom de domaine, la bascule, et le périmètre fonctionnel.

Le code du dépôt et l'état du serveur ont été relevés le 7 septembre 2026. Les points techniques ci-dessous sont vérifiés, pas supposés. Une seule inconnue subsiste : le chemin du Caddyfile sur l'hôte, que la version corrigée de `fb-inventaire.sh` donne directement.

**Caddy tourne dans un conteneur Docker sur ce serveur.** Tous les blocs de configuration ci-dessous doivent donc reprendre la cible `reverse_proxy` du bloc existant — un nom de service sur le réseau Docker, pas `127.0.0.1:3000`. Ne jamais l'inventer.

---

## Étape 1 — Inventaire préalable

Premier passage effectué le 7 septembre à 18:49 UTC. Il a établi que Caddy et FaithBook tournent dans Docker, que Node n'est pas installé, et qu'aucun outil de sauvegarde n'est présent. Relancer la version corrigée pour obtenir le chemin du Caddyfile :

```bash
ssh -p 2222 ghassane@62.238.108.19
cd /opt/integrit/ops
./fb-inventaire.sh > /tmp/inventaire-faithbook.txt
less /tmp/inventaire-faithbook.txt
```

Le script ne modifie rien. Il masque les mots de passe, hachages bcrypt, jetons, chaînes de connexion et clés API. Il n'affiche jamais la valeur d'une variable d'environnement, seulement son nom.

**Relisez le rapport avant de le transmettre.** Le masquage couvre les formats courants, pas tous les formats possibles.

Ce que le rapport apporte :

| Section | Lève l'hypothèse |
|---|---|
| 2. Outils | Node, npm, git, caddy présents ? Construction possible sur le serveur ? |
| 3. Dossier servi | Contenu réel, actifs référencés par l'index |
| 5. Sources | version de Node installée, présence d'un clone |
| 6. Caddy | Caddyfile réel, structure du routage actuel |
| 7. Service | Unité systemd de FaithBook, ports en écoute |
| 10. Sauvegarde | Le dossier servi est-il sauvegardé ? |
| 12. DNS | Enregistrements actuels, préalable au changement de domaine |

Après lecture, corriger `faithbook-env.sh` et la section 3 de `fb-verifier.sh`.

---

## Étape 2 — Nom de domaine

### Le problème

`veille-novostok.duckdns.org` est un DNS dynamique gratuit. Trois conséquences : aucune maîtrise du nom, une résiliation possible sans préavis, et une adresse qui ne tient pas dans un livrable client.

### Décision à prendre

Le sous-domaine dépend du positionnement du produit. Deux directions, votre choix :

| Direction | Exemple | Quand |
|---|---|---|
| Sous Novostok | `veille.novostok.com` | FaithBook est un outil Novostok, cohérent avec l'identité visuelle retenue |
| Sous Integr-IT | `veille.integr-it.com` | FaithBook est un produit Integr-IT vendu à des clients |

**Information manquante :** je ne sais pas qui exploite FaithBook ni à qui il est destiné. Ce choix vous appartient et conditionne la suite.

### Procédure

**1. DNS.** Créer un enregistrement A chez le registrar du domaine retenu :

```
veille    A    62.238.108.19    TTL 300
```

TTL court pendant la migration, à remonter à 3600 une fois stabilisé.

Vérifier la propagation avant de toucher à Caddy :

```bash
dig +short veille.novostok.com
# doit renvoyer 62.238.108.19
```

**2. Caddy.** Ajouter un bloc pour le nouveau nom. Caddy obtient le certificat Let's Encrypt automatiquement, à condition que le DNS pointe déjà correctement et que les ports 80 et 443 soient ouverts — ils le sont, publiés par le conteneur `caddy`.

```caddyfile
# Nouveau nom, configuration identique a l'ancien bloc.
# Reprendre le contenu exact du bloc duckdns de l'inventaire.
veille.novostok.com {
	encode zstd gzip

	handle_path /nouvelle-interface* {
		root * /srv/sites/faithbook-interface
		try_files {path} /index.html
		file_server
	}

	# Application FaithBook historique.
	# REPRENDRE LA CIBLE EXACTE du bloc existant : Caddy etant en conteneur,
	# c'est un nom de service Docker, pas 127.0.0.1.
	reverse_proxy CIBLE_DU_BLOC_EXISTANT
}

# L'ancien nom redirige, le temps que les signets suivent.
veille-novostok.duckdns.org {
	redir https://veille.novostok.com{uri} permanent
}
```

Le port du `reverse_proxy` vient de la section 7 de l'inventaire. Ne pas le deviner.

**3. Application.**

```bash
cd /opt/integrit/ops
./fb-caddy.sh --montrer                          # relire l'existant
cp /etc/caddy/Caddyfile /tmp/Caddyfile.nouveau   # partir de l'existant
nano /tmp/Caddyfile.nouveau                       # ajouter les blocs
./fb-caddy.sh --appliquer /tmp/Caddyfile.nouveau --dry-run
./fb-caddy.sh --appliquer /tmp/Caddyfile.nouveau
```

Le script valide, sauvegarde, installe, recharge, vérifie. **En cas d'échec à n'importe laquelle de ces étapes, il remet automatiquement la configuration précédente.**

**4. Certificat.** L'émission prend quelques secondes à quelques minutes.

```bash
journalctl -u caddy -f          # suivre l'obtention
# puis, dans un autre terminal :
FB_BASE_URL=https://veille.novostok.com ./fb-verifier.sh
```

### Points de vigilance, vérifiés dans le code

- **Cookie de session.** `app/api/auth.py` pose `planche_session` en `HttpOnly`, `SameSite=Lax`, sans paramètre `domain`. C'est donc un cookie lié à l'hôte exact. Conséquence : un changement de nom déconnecte tout le monde une fois. Rien de plus. L'authentification ne casse pas.
- **URL en dur.** Aucune. `lib/faithbook-api.ts` appelle `fetch('/api'+path, {credentials:'same-origin'})`. Aucune occurrence de `duckdns` dans les sources. Le changement de domaine ne demande aucune modification du client.
- **Origines autorisées.** `app/main.py` charge `CORSMiddleware` avec `settings.cors_origin_list`, réglable par variable d'environnement. Les appels étant de même origine, le CORS n'intervient pas pour la nouvelle interface. À ajuster seulement si un autre client appelle l'API depuis un autre domaine.
- **Ne pas supprimer l'ancien nom** avant plusieurs semaines. La redirection permanente coûte deux lignes.

---

## Étape 3 — Bascule

### Le point technique qui décide de tout

`interfaces/novostok/deploy/vite.config.ts` contient `base: '/nouvelle-interface/'`. Ce chemin est figé dans les URL d'actifs générées à la construction. **Déplacer l'interface à la racine n'est pas une affaire de configuration Caddy : il faut passer cette ligne à `base: '/'` et reconstruire.** Servie telle quelle à la racine, la page est blanche et tous les actifs répondent 404.

La modification est d'un caractère. La reconstruction et le redéploiement qui suivent sont la vraie dépense.

Conséquence : le scénario B ci-dessous coûte une modification de code et un nouveau déploiement. Les scénarios A et C n'en coûtent aucune.

### Les trois scénarios

**A — Côté à côte. État actuel.**

```
https://veille.novostok.com/                      application historique
https://veille.novostok.com/nouvelle-interface/   nouvelle interface
```

Aucun changement. Les deux interfaces cohabitent, l'utilisateur choisit. Convient tant que la recette n'est pas passée.

Configuration réellement en place, d'après `interfaces/novostok/deploy/Caddy.snippet` :

```caddyfile
redir /nouvelle-interface /nouvelle-interface/ 308
handle_path /nouvelle-interface/* {
	root * /srv/sites/faithbook-interface
	header Cache-Control "no-cache"
	file_server
}
```

**B — Nouvelle interface à la racine.**

```
https://veille.novostok.com/            nouvelle interface
https://veille.novostok.com/complet/    application historique
```

```caddyfile
veille.novostok.com {
	encode zstd gzip

	handle_path /complet* {
		reverse_proxy CIBLE_DU_BLOC_EXISTANT
	}

	# L'API reste a la meme origine, sous /api/
	handle /api/* {
		reverse_proxy CIBLE_DU_BLOC_EXISTANT
	}

	handle {
		root * /srv/sites/faithbook-interface
		try_files {path} /index.html
		file_server
	}
}
```

Impose de reconstruire avec `base: '/'`. Risque : l'application historique servie sous `/complet/` peut elle aussi contenir des chemins absolus, et casser. À tester avant de s'y engager.

**C — Deux noms de domaine. Recommandé.**

```
https://veille.novostok.com/         nouvelle interface, a la racine de son propre nom
https://app.novostok.com/            application historique, inchangee
```

```caddyfile
veille.novostok.com {
	encode zstd gzip
	handle /api/* {
		reverse_proxy CIBLE_DU_BLOC_EXISTANT
	}
	handle {
		root * /srv/sites/faithbook-interface
		try_files {path} /index.html
		file_server
	}
}

app.novostok.com {
	reverse_proxy CIBLE_DU_BLOC_EXISTANT
}
```

Chaque interface a son adresse propre, aucun préfixe de chemin, aucune interférence entre les deux routeurs. L'application historique n'est pas touchée du tout, donc aucun risque de régression sur elle. Coût : un enregistrement DNS de plus, et la même reconstruction avec `base: '/'` que le scénario B.

Point d'attention, désormais confirmé : le cookie `planche_session` est posé sans paramètre `domain`, donc lié à l'hôte exact. Deux sous-domaines signifient **deux sessions distinctes**. Il faudra soit ajouter `domain=.novostok.com` côté serveur, soit accepter une connexion par interface. Le second cas est acceptable puisque l'application historique ne sert plus qu'à l'administration.

### Recommandation

Rester en **A** jusqu'à la fin de la recette. Passer en **C** pour la livraison. Le scénario B mélange deux applications sur un même nom pour aucun gain par rapport à C.

### Ordre d'exécution du scénario C

1. Recette passée sur A.
2. Modifier la base de construction, reconstruire, déployer sur `/nouvelle-interface/`, vérifier que **rien ne s'affiche** — c'est le comportement attendu, la preuve que la base a changé.
3. Appliquer le Caddyfile de C avec `fb-caddy.sh --appliquer`.
4. Vérifier avec `FB_BASE_URL=https://veille.novostok.com ./fb-verifier.sh`.
5. En cas d'échec, `fb-caddy.sh --restaurer <horodatage>` puis redéployer la version précédente avec `fb-restaurer.sh`.

Les deux retours arrière sont indépendants et testés.

---

## Étape 4 — Périmètre fonctionnel

### L'état

La nouvelle interface couvre la consultation : vue d'ensemble, cibles, archives, détail de capture, téléchargement, export PDF. Elle ne couvre pas la modification : gestion des cibles, des comptes, de l'équipe. Ces trois fonctions n'existent que dans l'application historique.

En scénario C, l'utilisateur qui veut ajouter une cible doit changer d'adresse. C'est une rupture d'usage, pas un détail.

### Trois options

**Option 1 — Assumer et documenter.**

La nouvelle interface est un poste de consultation, l'application complète reste l'outil d'administration. Ajouter dans la nouvelle interface un lien visible « Administration » vers l'application historique, et le dire dans la documentation utilisateur.

Coût : quelques heures. Livrable immédiat. Défaut : deux outils à connaître.

**Option 2 — Développer les écrans manquants.**

Recréer gestion des cibles, des comptes et de l'équipe dans la nouvelle interface, puis retirer l'application historique de la vue des utilisateurs.

Coût : significatif, et non chiffrable sans lecture du code des routes de modification. Ce sont des écrans d'écriture : validation, gestion d'erreur, confirmation, droits. Défaut : repousse la livraison.

**Option 3 — Périmètre intermédiaire.**

Ne recréer que la gestion des cibles, qui est l'action quotidienne. Comptes et équipe restent dans l'application complète, où ils sont utilisés rarement.

Coût : intermédiaire. C'est le meilleur rapport entre l'effort et le confort d'usage, si une deuxième phase est prévue.

### Recommandation

**Option 1 pour livrer**, option 3 en lot 2 si l'usage le justifie. Livrer un outil de consultation assumé vaut mieux que retarder pour des écrans d'administration utilisés une fois par mois.

**Information manquante :** la fréquence réelle d'ajout de cibles. Si c'est quotidien, l'option 3 devient nécessaire dès le lot 1.

---

## Ordre d'exécution recommandé

| # | Action | Bloquant | Outil |
|---|---|---|---|
| 1 | Inventaire du serveur | oui | `fb-inventaire.sh` |
| 2 | Corriger `faithbook-env.sh` et les routes de `fb-verifier.sh` | oui | — |
| 3 | Valider le déploiement à blanc | oui | `fb-deployer.sh --dry-run` |
| 4 | Recette des 60 cas en scénario A | oui | cahier de recette |
| 5 | Corriger les KO par gravité | oui | — |
| 6 | Trancher le domaine et le périmètre | oui | ce document |
| 7 | Décider : cookie sur le domaine parent, ou deux sessions | si scénario C | — |
| 8 | Passer `base` à `'/'` dans `deploy/vite.config.ts` et reconstruire | si scénario C | `fb-deployer.sh` |
| 9 | DNS et Caddy | si scénario C | `fb-caddy.sh` |
| 10 | Trois moniteurs dans Uptime Kuma, déjà installé | non | — |
| 11 | **Établir s'il existe une sauvegarde. Aucune n'est visible sur la machine.** | oui | — |
| 11 bis | Appliquer les 23 mises à jour et redémarrer | non | — |
| 12 | Documentation utilisateur | non | — |

Les étapes 1 à 5 ne dépendent d'aucune décision. Elles peuvent démarrer aujourd'hui.

---

## Ce que ce document ne traite pas

Rotation des secrets, HTTPS des autres services hébergés, mises à jour système, correctif Spypoint et hauteur des captures. Ces sujets sont hors périmètre depuis le début et n'ont jamais été revalidés. Ils devront faire l'objet d'un point distinct.
