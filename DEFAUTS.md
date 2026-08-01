# Defauts trouves, et ce qu ils ont en commun

Ce document n est pas un journal des corrections : le README et l historique
Git le font deja. Il note les **motifs qui reviennent**, parce que sur ce
projet les memes causes reapparaissent sous des symptomes differents.

Quand quelque chose casse, commencer par les trois questions ci-dessous fait
gagner beaucoup de temps.

---

## Motif 1 — Un etat residuel que personne ne nettoie

**Quatre occurrences. C est de loin le plus frequent.**

Un fichier, un verrou ou un processus survit a un arret et empeche le
demarrage suivant. Le symptome est toujours le meme vu de l exterieur :
« ca marche une fois, puis plus jamais jusqu au redemarrage ».

| Ou | Ce qui restait | Consequence |
|---|---|---|
| Relais reseau | `/run/squid.pid` | Squid refusait de demarrer |
| Ecran virtuel | `/tmp/.X99-lock` | Xvfb refusait de demarrer, le backend bouclait |
| Connexion manuelle | Verrou de profil jamais relache | Erreur 504 sur Reconnecter |
| Connexion manuelle | Processus Chromium orphelins | 10 navigateurs vivants apres la fermeture |

**La question a poser :** qu est-ce qui a survecu a l arret precedent ?

**La regle qui en decoule :** toute ressource prise doit etre relachee dans
un `finally`, et toute fermeture qui parle a un processus externe doit etre
bornee dans le temps. Un programme qui ne repond plus ne leve pas d erreur —
il ne rend jamais la main, et un `try/except` ne rattrape pas ce cas.

---

## Motif 2 — Un chemin secondaire qui oublie un controle

La voie principale verifie ; la voie de contournement, ajoutee plus tard,
oublie de le faire.

| Ou | Ce qui manquait |
|---|---|
| Dupliquer une cible | Le quota de cibles, present sur la creation directe |

**La question a poser :** quelles sont les autres portes d entree vers cette
meme action, et font-elles les memes verifications ?

---

## Motif 3 — Une hypothese implicite sur l environnement

Le code suppose un etat qui est vrai en production mais pas partout.

| Ou | L hypothese | Quand elle tombe |
|---|---|---|
| `scheduler.py` | `job.next_run_time` existe toujours | APScheduler ne le renseigne que si le planificateur tourne |
| `test_channels.py` | Aucun canal d alerte n est configure | Des que Telegram est reellement branche sur la machine |

**La question a poser :** ce code suppose-t-il quelque chose que seule la
production garantit ?

Le second cas merite une regle a lui seul : **un test ne doit jamais dependre
du `.env` de la machine.** Ces trois tests ont echoue le jour ou Telegram a
ete configure, alors que le produit fonctionnait parfaitement. Un test qui
echoue sans defaut est pire qu un test absent.

---

## Motif 4 — Une planification qui ne rattrape rien

| Symptome | Cause |
|---|---|
| Aucune capture aux heures prevues | La machine etait eteinte a ces heures |

`misfire_grace_time` ne couvre pas ce cas : il ne s applique qu aux taches
deja enregistrees au moment ou l echeance passe. Apres un arret complet,
elles sont recreees au demarrage avec une echeance future, et la journee
manquee est perdue sans le moindre message d erreur.

**La question a poser :** que se passe-t-il si le service est arret au moment
prevu — quelqu un s en apercoit-il ?

---

## Une derniere lecon, transversale

Trois de ces defauts ont ete trouves par des tests ecrits pour verifier
**autre chose**. Aucun n avait ete signale par un utilisateur.

Et symetriquement : quatre fonctionnalites livrees, testees et documentees
n avaient jamais parle au vrai service. Telegram passait onze tests depuis le
12 juillet ; il aura fallu une demi-journee pour qu un message arrive sur un
telephone, sans qu une seule ligne de code soit en cause.

**« Teste » et « en service » sont deux etats differents.** Le README et la
page d inventaire les distinguent explicitement pour cette raison.

---

## Motif 5 — Une ressource tenue plus longtemps que necessaire

| Ou | Ce qui etait tenu | Consequence |
|---|---|---|
| `runner.py:126` | Une transaction ouverte pendant toute la capture | Une seconde capture attendait son verrou sans fin ; la boucle du backend est restee figee 1 h 29 |

Le service repondait encore : le journal montrait des `200 OK`. Mais chaque
reponse arrivait apres le delai de la sonde de sante, qui abandonne a 5 s.
Docker a donc declare le backend mort, et le frontend, qui depend de sa bonne
sante, n a jamais demarre. **L interface a disparu au moment precis ou elle
aurait servi a comprendre.**

**La question a poser :** cette ressource est-elle tenue pendant une operation
lente ? Un verrou, une transaction ou une connexion ne devraient jamais
traverser une capture de plusieurs minutes.

**Correctif applique :** deux bornes cote PostgreSQL. Une attente de verrou
echoue au bout de 10 s au lieu d attendre sans fin, et une transaction laissee
inactive 10 min est supprimee. Ce n est pas la correction de fond -- il
faudrait cesser de tenir une transaction pendant une capture -- mais elle
transforme un blocage total du service en une seule requete en erreur.
