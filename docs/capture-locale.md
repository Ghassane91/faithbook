# Capture automatique locale des enseignes

Walmart, Academy et Bass Pro/Cabela's sont tentés sans fournisseur payant et
sans intervention dans le navigateur. Les vérifications automatiques du
navigateur disposent de 20 secondes supplémentaires pour se terminer seules.
Une erreur `ERR_HTTP2_PROTOCOL_ERROR` déclenche une seule nouvelle capture
avec HTTP/2 désactivé. Aucun CAPTCHA humain ni refus HTTP 429 n'est retenté
par ce mécanisme. Les protections SSRF restent actives.

Configuration du backend et du worker :

```dotenv
REMOTE_BROWSER_PROVIDER=disabled
FICHES_MARKETPLACES_IGNOREES=
LOCAL_BROWSER_GRACE_SECONDS=20
BROWSER_CHANNEL=
```

Sur Windows avec Chrome installé, `BROWSER_CHANNEL=chrome` permet de l'utiliser.
Dans Docker, laisser la valeur vide utilise Chromium fourni avec l'image.
Un ancien `.env` contenant les exclusions reste prioritaire : il faut vider
explicitement `FICHES_MARKETPLACES_IGNOREES`, puis redémarrer les services.

Ce mode n'est pas un solveur de CAPTCHA. Une page qui continue à demander une
action humaine échoue explicitement, au lieu de produire une fausse réussite.
Il ne garantit pas l'accès aux trois sites : la recette doit vérifier leurs
contenus réels depuis le serveur de déploiement.
