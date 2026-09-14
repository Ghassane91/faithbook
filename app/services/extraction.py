"""Extraction d'informations structurees depuis le texte des pages capturees.

Le texte integral de chaque page est deja conserve dans Run.body_text : il est
inutile de faire lire l'image par un modele de vision, dix a cinquante fois plus
couteux et moins fiable sur des valeurs precises.

Principe directeur : une valeur introuvable vaut None. Le modele n'invente
jamais. Les champs marques `verifiable` sont en plus confrontes au texte source,
et ecartes s'ils n'y figurent pas.

Comme pour ai_summary, une panne du fournisseur ne doit jamais faire echouer une
capture : on journalise et on renvoie None.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Literal

from app.config import settings

logger = logging.getLogger(__name__)

# Une page catalogue peut peser plusieurs centaines de milliers de caracteres.
# On tronque : au-dela, on paie pour du pied de page et des mentions legales.
MAX_CARACTERES = 24000

TypeChamp = Literal["texte", "nombre", "booleen", "date"]


class ExtractionIndisponible(RuntimeError):
    """Levee quand l'extraction n'est pas configuree."""


@dataclass(frozen=True)
class Champ:
    """Un champ a extraire.

    verifiable : la valeur doit apparaitre telle quelle dans le texte source.
    A activer pour tout ce qui est recopie (modele, reference, libelle) et a
    laisser a False pour ce qui est deduit (disponibilite normalisee, booleen).
    """

    nom: str
    description: str
    type: TypeChamp = "texte"
    obligatoire: bool = False
    verifiable: bool = False


@dataclass(frozen=True)
class Regle:
    """Ce qu'on cherche sur une page, et ce qu'est une ligne de resultat."""

    nom: str
    ligne: str  # ce que represente une ligne : « un produit du catalogue »
    champs: tuple[Champ, ...]
    max_lignes: int = 60

    def champ(self, nom: str) -> Champ | None:
        return next((c for c in self.champs if c.nom == nom), None)


@dataclass
class Extraction:
    regle: str
    lignes: list[dict[str, Any]] = field(default_factory=list)
    anomalies: list[str] = field(default_factory=list)
    tronque: bool = False


INSTRUCTIONS = (
    "Tu extrais des informations factuelles du texte d une page web.\n"
    "Regles imperatives :\n"
    "- Reponds UNIQUEMENT par un objet JSON, sans texte autour, sans balises de code.\n"
    "- Forme attendue : {\"lignes\": [ {...}, {...} ]}\n"
    "- N invente JAMAIS une valeur. Si une information est absente, mets null.\n"
    "- Recopie les valeurs telles qu elles apparaissent, sans reformuler.\n"
    "- N ajoute aucun champ qui ne soit pas demande.\n"
    "- Si la page ne contient aucun element correspondant, renvoie {\"lignes\": []}."
)


def is_configured() -> bool:
    if not getattr(settings, "extraction_enabled", False):
        return False
    if settings.ai_summary_provider == "ollama":
        return bool(settings.ollama_base_url.strip() and settings.ollama_model.strip())
    return bool(settings.anthropic_api_key and _modele().strip())


def _modele() -> str:
    """Modele dedie a l extraction, sinon celui de la synthese.

    L extraction tourne a chaque capture ; la synthese une fois par jour. Il est
    normal de vouloir un modele plus leger pour la premiere.
    """
    return getattr(settings, "extraction_model", "") or settings.ai_summary_model


def construire_invite(regle: Regle, texte: str, titre: str | None, url: str | None) -> tuple[str, bool]:
    """Message envoye au modele. Isole pour etre testable sans reseau."""
    corps = (texte or "").strip()
    tronque = len(corps) > MAX_CARACTERES
    if tronque:
        corps = corps[:MAX_CARACTERES]

    colonnes = []
    for c in regle.champs:
        mention = "obligatoire" if c.obligatoire else "facultatif"
        colonnes.append(f'- "{c.nom}" ({c.type}, {mention}) : {c.description}')

    entete = []
    if titre:
        entete.append("Titre de la page : " + titre)
    if url:
        entete.append("Adresse : " + url)

    invite = "\n\n".join(
        [
            "\n".join(entete) if entete else "Page web surveillee.",
            f"Une ligne represente : {regle.ligne}.",
            f"Au maximum {regle.max_lignes} lignes.",
            "Champs de chaque ligne :\n" + "\n".join(colonnes),
            "Texte de la page :\n" + corps,
        ]
    )
    return invite, tronque


# --------------------------------------------------------------- conversions

_ESPACES = ("\u00a0", "\u202f", "\u2009", "\u2007")


def _normaliser(valeur: str) -> str:
    """Minuscules, sans accents ni espaces multiples : pour comparer, pas pour afficher."""
    texte = unicodedata.normalize("NFKD", valeur)
    texte = "".join(c for c in texte if not unicodedata.combining(c))
    for e in _ESPACES:
        texte = texte.replace(e, " ")
    return re.sub(r"\s+", " ", texte).strip().lower()


def convertir_nombre(valeur: Any) -> float | None:
    """Nombre depuis un prix ecrit a l europeenne ou a l americaine.

    Gere « 1 299,00 $ », « $1,299.00 », « 1299 », « 249.99 USD ». Renvoie None
    si la chaine ne contient pas de nombre exploitable.
    """
    if valeur is None or isinstance(valeur, bool):
        return None
    if isinstance(valeur, (int, float)):
        return float(valeur)
    brut = str(valeur)
    for e in _ESPACES:
        brut = brut.replace(e, " ")
    # On ne garde que chiffres, separateurs et signe.
    garde = re.sub(r"[^0-9,.\-]", "", brut)
    if not re.search(r"\d", garde):
        return None
    garde = garde.lstrip("-") if garde.count("-") > 1 else garde
    dernier_point, derniere_virgule = garde.rfind("."), garde.rfind(",")
    if dernier_point >= 0 and derniere_virgule >= 0:
        # Le separateur le plus a droite est le decimal.
        if derniere_virgule > dernier_point:
            garde = garde.replace(".", "").replace(",", ".")
        else:
            garde = garde.replace(",", "")
    elif derniere_virgule >= 0:
        # Virgule seule : decimale si 1 ou 2 chiffres apres, sinon milliers.
        apres = len(garde) - derniere_virgule - 1
        garde = garde.replace(",", "." if apres in (1, 2) else "")
    elif dernier_point >= 0:
        apres = len(garde) - dernier_point - 1
        if apres == 3 and garde.count(".") >= 1 and len(garde.replace(".", "")) > 3:
            garde = garde.replace(".", "")
    try:
        return float(garde)
    except ValueError:
        return None


_VRAI = {
    "true", "vrai", "oui", "yes", "1",
    "en stock", "disponible", "in stock", "instock", "available",
    "add to cart", "ajouter au panier",
}
_FAUX = {
    "false", "faux", "non", "no", "0",
    "rupture", "rupture de stock", "indisponible", "epuise",
    "out of stock", "outofstock", "sold out", "unavailable",
    "notify me", "me prevenir",
}


def convertir_booleen(valeur: Any) -> bool | None:
    if isinstance(valeur, bool):
        return valeur
    if valeur is None:
        return None
    t = _normaliser(str(valeur))
    if t in _VRAI:
        return True
    if t in _FAUX:
        return False
    return None


def convertir_date(valeur: Any) -> str | None:
    """Date ISO si elle est reconnaissable, sinon None. Aucune invention."""
    if valeur is None:
        return None
    t = str(valeur).strip()
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        return m.group(0)
    m = re.search(r"\b(\d{2})[/.](\d{2})[/.](\d{4})\b", t)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None


# --------------------------------------------------------------- analyse

_ENTOURAGE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def analyser_reponse(regle: Regle, texte: str, source: str = "") -> Extraction:
    """Transforme la reponse du modele en lignes validees.

    Toute valeur douteuse devient None et alimente `anomalies`. Le but est qu une
    extraction fausse soit visible, pas silencieuse.
    """
    resultat = Extraction(regle=regle.nom)
    brut = _ENTOURAGE.sub("", (texte or "").strip())
    if not brut:
        resultat.anomalies.append("Reponse vide du modele.")
        return resultat
    try:
        donnees = json.loads(brut)
    except json.JSONDecodeError as exc:
        resultat.anomalies.append(f"Reponse illisible (JSON invalide) : {exc.msg}.")
        return resultat
    if not isinstance(donnees, dict) or not isinstance(donnees.get("lignes"), list):
        resultat.anomalies.append("Reponse hors format : objet avec une liste 'lignes' attendu.")
        return resultat

    source_normalisee = _normaliser(source) if source else ""
    connus = {c.nom for c in regle.champs}

    for index, entree in enumerate(donnees["lignes"][: regle.max_lignes], start=1):
        if not isinstance(entree, dict):
            resultat.anomalies.append(f"Ligne {index} ignoree : ce n est pas un objet.")
            continue
        for inconnu in set(entree) - connus:
            resultat.anomalies.append(f"Ligne {index} : champ inattendu '{inconnu}' ignore.")
        ligne: dict[str, Any] = {}
        for champ in regle.champs:
            valeur = entree.get(champ.nom)
            if isinstance(valeur, str) and not valeur.strip():
                valeur = None
            if valeur is not None:
                if champ.type == "nombre":
                    converti = convertir_nombre(valeur)
                    if converti is None:
                        resultat.anomalies.append(
                            f"Ligne {index} : '{champ.nom}' n est pas un nombre exploitable ({valeur!r})."
                        )
                    valeur = converti
                elif champ.type == "booleen":
                    valeur = convertir_booleen(valeur)
                elif champ.type == "date":
                    converti = convertir_date(valeur)
                    if converti is None:
                        resultat.anomalies.append(
                            f"Ligne {index} : '{champ.nom}' n est pas une date reconnaissable ({valeur!r})."
                        )
                    valeur = converti
                else:
                    valeur = str(valeur).strip()
            # Garde-fou anti-invention : la valeur doit exister dans la page.
            if (
                valeur is not None
                and champ.verifiable
                and source_normalisee
                and _normaliser(str(valeur)) not in source_normalisee
            ):
                resultat.anomalies.append(
                    f"Ligne {index} : '{champ.nom}' absent du texte source, valeur ecartee ({valeur!r})."
                )
                valeur = None
            if valeur is None and champ.obligatoire:
                resultat.anomalies.append(f"Ligne {index} : '{champ.nom}' obligatoire et absent.")
            ligne[champ.nom] = valeur
        if any(v is not None for v in ligne.values()):
            resultat.lignes.append(ligne)
        else:
            resultat.anomalies.append(f"Ligne {index} ignoree : entierement vide.")

    reste = len(donnees["lignes"]) - len(donnees["lignes"][: regle.max_lignes])
    if reste > 0:
        resultat.anomalies.append(f"{reste} ligne(s) au-dela de la limite de {regle.max_lignes}, ignorees.")
    return resultat
