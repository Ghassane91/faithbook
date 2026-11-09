"""Reconnaître les pages de vérification avant de les archiver comme contenu.

Le détecteur ne résout pas les défis : il distingue un interstitiel bloquant
d'un simple widget CAPTCHA intégré à une page utile.
"""

from __future__ import annotations

import asyncio
import re
import unicodedata


_READ_TIMEOUT_MS = 5000
_MAX_INTERSTITIAL_LENGTH = 4000
_MAX_HEADING_LENGTH = 220

_HUMAN_REASON = "Le site demande une vérification humaine."
_HOLD_REASON = "Le site demande une vérification par appui prolongé."
_INTERRUPTION_REASON = "Le site affiche une page d'interruption anti-robot."
_BROWSER_REASON = "Le site vérifie le navigateur avant d'ouvrir la page."
_GENERIC_REASON = "Le site affiche un défi de sécurité."
_SAFE_REASONS = frozenset(
    (_HUMAN_REASON, _HOLD_REASON, _INTERRUPTION_REASON, _BROWSER_REASON)
)


class WebChallenge(RuntimeError):
    """Interstitiel bloquant, distinct d'une session de compte expirée.

    Le message est issu d'une liste fixe : ni URL, ni extrait de page, ni
    identifiant de session ne doivent rejoindre les journaux par ce chemin.
    """

    def __init__(self, reason: str = _GENERIC_REASON) -> None:
        self.reason = reason if reason in _SAFE_REASONS else _GENERIC_REASON
        super().__init__(self.reason)


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.casefold())
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = value.replace("’", "'").replace("&", " and ")
    value = re.sub(r"[-–—]", " ", value)
    return " ".join(value.split()).strip(" .!?:…")


_HUMAN_HEADING = re.compile(
    r"(?:"
    r"robot or human|are you (?:a )?human|human verification|"
    r"(?:please )?(?:verify|confirm) (?:that )?you(?: are|'re) (?:a )?human|"
    r"etes vous (?:un )?humain|verification humaine|"
    r"(?:veuillez )?(?:verifiez|confirmez) que vous etes (?:bien )?(?:un )?humain"
    r")"
)
_HOLD = re.compile(r"\b(?:press and hold|appuyez et maintenez|maintenez (?:le bouton|appuye))\b")
_HOLD_VERIFICATION = re.compile(
    r"\b(?:human|humain|humaine|not a robot|not a bot|pas un robot)\b"
)
_VERIFICATION = re.compile(
    r"\b(?:human|humain|humaine|robot|bot|verif(?:y|ying|ication|ier|ions)|"
    r"checking your browser|security check|connexion est securisee|"
    r"connection is secure)\b"
)
_INTERRUPTION_HEADINGS = frozenset(
    ("pardon our interruption", "sorry for the interruption", "veuillez excuser cette interruption")
)
_BROWSER_HEADINGS = frozenset(
    (
        "just a moment",
        "un instant",
        "checking your browser",
        "verification de votre navigateur",
    )
)


def detect_challenge(title: str, body_text: str) -> str | None:
    """Retourne une raison fixe pour un interstitiel manifeste, sinon ``None``.

    Les marqueurs doivent être le titre ou une courte ligne d'en-tête, jamais
    un mot isolé ou une mention dans un pied de page. Une détection fondée sur
    le corps est limitée aux pages courtes pour préserver les pages produit
    contenant un CAPTCHA, une notice de confidentialité ou un article sur les
    robots. « Just a moment » exige un second indice de vérification.
    """
    normalized_title = _normalize(title)
    normalized_body = _normalize(body_text)
    short_page = len(normalized_body) <= _MAX_INTERSTITIAL_LENGTH

    # Une page de vérification peut avoir un titre générique (nom du marchand).
    # Seules les trois premières lignes et les 220 premiers caractères peuvent
    # alors servir de titre ; une mention de CAPTCHA plus bas ne suffit pas.
    headings = [normalized_title]
    if short_page:
        heading_length = 0
        for line in (line for line in body_text.splitlines() if line.strip()):
            # Certains interstitiels rendent titre et explication sur une
            # même ligne. Ne regarder que la première phrase conserve un
            # ancrage strict, sans chercher ces mots dans une description.
            first_sentence = re.split(r"[?!.](?:\s|$)", line.strip(), maxsplit=1)[0]
            normalized_heading = _normalize(first_sentence)
            if heading_length + len(normalized_heading) > _MAX_HEADING_LENGTH or len(headings) >= 4:
                break
            headings.append(normalized_heading)
            heading_length += len(_normalize(line))

    for heading in headings:
        if _HUMAN_HEADING.fullmatch(heading):
            return _HUMAN_REASON
        if heading in _INTERRUPTION_HEADINGS and short_page:
            return _INTERRUPTION_REASON
        if heading in _BROWSER_HEADINGS and _VERIFICATION.search(normalized_body):
            return _BROWSER_REASON

    # L'appui prolongé est aussi une instruction normale dans un manuel : il
    # ne désigne un défi qu'en début de page courte, associé à une vérification.
    if short_page and _HOLD.search(normalized_body[:_MAX_HEADING_LENGTH]):
        if _HOLD_VERIFICATION.search(normalized_body[:_MAX_HEADING_LENGTH]):
            return _HOLD_REASON
    return None


async def assert_no_challenge(page) -> None:
    """Lit le titre et le texte visible, puis lève ``WebChallenge`` si besoin.

    La lecture entière est bornée. Une page fermée ou un échec de lecture reste
    une erreur de capture, jamais la preuve qu'une page est exploitable.
    """

    async def read_page() -> tuple[str, str]:
        title = await page.title()
        body_text = await page.inner_text("body", timeout=_READ_TIMEOUT_MS)
        return title, body_text

    title, body_text = await asyncio.wait_for(read_page(), timeout=_READ_TIMEOUT_MS / 1000)
    reason = detect_challenge(title, body_text)
    if reason is not None:
        raise WebChallenge(reason)
