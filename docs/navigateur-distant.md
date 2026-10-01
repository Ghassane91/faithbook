# Pages publiques Walmart, Academy et Bass Pro/Cabela's

Le backend peut utiliser un navigateur distant Playwright/CDP pour les domaines
configurés. Le connecteur est **désactivé par défaut**. Sans compte fournisseur,
le code détecte les interstitiels mais ne débloque pas les pages.

## Ce que fait le parcours

- Une page publique appartenant aux domaines configurés utilise directement le
  navigateur distant quand le fournisseur est activé. Les autres cibles gardent
  Chromium local et son proxy sortant.
- Chaque capture ouvre un nouveau contexte, fermé en fin d'exécution. Aucun
  profil, cookie ou identifiant HuntX/Facebook n'est envoyé au fournisseur.
  Une cible liée à un compte ou une session reste locale.
- Le mode `brightdata` attend la commande documentée `Captcha.waitForSolve`.
  La gestion des IP, des empreintes et des CAPTCHA dépend du service choisi.
  Le mode `cdp` est un connecteur générique : il n'ajoute aucun solveur.
- Le texte visible est vérifié avant login/interactions et après chargement/scroll.
  Un interstitiel détecté ou un HTTP 403/429 produit un blocage, pas une capture
  réussie. Un blocage ou échec distant termine le run sans retry automatique et
  sans déconnecter le compte. Une nouvelle exécution planifiée reste possible.
- Les fiches lisibles sont envoyées sur Drive ; les fiches bloquées sont comptées
  et supprimées localement. Un envoi Drive échoué ne compte plus comme réussite.

## Configuration (serveur, jamais dans le frontend)

Créer/configurer d'abord un service de navigateur distant. Copier son endpoint
Playwright WSS complet dans le fichier d'environnement privé du serveur :

```dotenv
REMOTE_BROWSER_PROVIDER=brightdata
REMOTE_BROWSER_CDP_URL=wss://UTILISATEUR:MOT_DE_PASSE@brd.superproxy.io:9222
REMOTE_BROWSER_DOMAINS=walmart.com,academy.com,basspro.com,cabelas.com
REMOTE_BROWSER_TIMEOUT_SECONDS=120
ALLOW_PRIVATE_TARGETS=false
```

L'URL ci-dessus est un exemple, pas un identifiant utilisable. Elle ne doit pas
être commitée, affichée dans un chat ou transmise au navigateur de l'utilisateur.
Les exceptions CDP sont remplacées par un message sans endpoint ni secret.

Pour réactiver les liens marchands actuellement exclus du traitement HuntX,
vider aussi la variable existante, après un essai sur une seule fiche :

```dotenv
FICHES_MARKETPLACES_IGNOREES=
```

Tant que cette variable conserve ses exclusions, ces liens ne sont pas visités,
même avec un navigateur distant activé. Aucune exclusion n'est levée en silence.
Les paramètres sont chargés au démarrage : reconstruire/redémarrer le backend
et le worker selon le déploiement existant. Aucun changement de schéma SQL requis.

## Coûts et limites à vérifier avant activation

Le connecteur n'achète aucun service. Une capture distante activée peut être
facturée. Régler les plafonds et alertes de dépense chez le fournisseur avant
de réactiver un lot de centaines de fiches. Une seule connexion distante est
tentée par appel de capture ; les tentatives internes du fournisseur dépendent
de son offre. Le délai de 120 s couvre connexion, navigation, CAPTCHA et capture,
avec jusqu'à dix secondes supplémentaires pour fermer contexte et navigateur.

Le domaine de départ et les redirections principales doivent rester dans la liste.
Les sous-ressources conservent la validation SSRF existante et les Service Workers
sont bloqués. Les cibles privées sont refusées en mode distant. Le proxy Squid
local ne protège pas le réseau du fournisseur : la restriction des sorties et
la protection contre le DNS rebinding distant relèvent de ce dernier. Valider
cette propriété dans sa configuration avant l'activation.

Les textes de challenge évoluent : la détection réduit les faux succès sans
garantir leur élimination. Le passage des protections de ces enseignes n'a pas
été testé avec un service réel. Ne pas interpréter les tests simulés comme une
garantie de déblocage. Utiliser une fiche produit publique réelle par enseigne
pour la recette, vérifier le contenu et le coût, puis augmenter progressivement.

Retour arrière : `REMOTE_BROWSER_PROVIDER=disabled`, puis redémarrer les services.
Restaurer les exclusions initiales pour arrêter les tentatives de fiches bloquées.

## Références

- [Bright Data : exemples Playwright Python et attente CAPTCHA](https://docs.brightdata.com/products/scraping-browser/code-examples)
- [Playwright : connexion CDP](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp)

## Tests locaux (aucun fournisseur appelé)

```sh
python -m pytest -q tests/test_web_challenges.py tests/test_remote_browser.py tests/test_web_access_runner.py tests/test_fiches_liens.py tests/test_session_robustness.py tests/test_ssrf.py
```

Les tests forcent le fournisseur à `disabled` et une clé vide avant le chargement
des paramètres. Les tests CDP injectent de faux navigateurs et de fausses réponses.
