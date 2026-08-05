"""Synthese par IA des changements detectes entre deux captures.

Deux fournisseurs sont disponibles : Anthropic (API distante) et Ollama
(modele local). La fonctionnalite reste optionnelle et une panne du fournisseur
ne doit jamais faire echouer une capture.
"""

from __future__ import annotations

import logging
import threading

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

# Au-dela, on tronque : un fil Facebook peut contenir des centaines de
# lignes et on ne veut ni payer ni attendre pour du bruit.
MAX_LIGNES = 60
MAX_CARACTERES = 6000

INSTRUCTIONS = (
    "Tu analyses les differences entre deux captures d une page web surveillee. "
    "Resume en francais simple, en 3 phrases maximum, ce qui a reellement change. "
    "Ignore les compteurs (mentions J aime, vues, partages) et les elements "
    "d interface. Si rien de significatif n a change, ecris exactement : "
    "Aucun changement notable."
)

_client = None
_client_lock = threading.Lock()


class ResumeIndisponible(RuntimeError):
    """Levee quand la synthese IA n est pas configuree."""


def is_configured() -> bool:
    """Vrai si le fournisseur choisi possede sa configuration minimale."""
    if not settings.ai_summary_enabled:
        return False
    if settings.ai_summary_provider == "ollama":
        return bool(settings.ollama_base_url.strip() and settings.ollama_model.strip())
    return bool(settings.anthropic_api_key and settings.ai_summary_model.strip())


def _get_client():
    """Client Anthropic cree a la demande (import paresseux, comme boto3)."""
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                if not is_configured():
                    raise ResumeIndisponible("Synthese IA non configuree.")
                import anthropic

                _client = anthropic.Anthropic(
                    api_key=settings.anthropic_api_key,
                    max_retries=settings.ai_summary_retries,
                )
    return _client


def _resumer_anthropic(invite: str) -> str | None:
    client = _get_client()
    reponse = client.messages.create(
        model=settings.ai_summary_model,
        max_tokens=400,
        system=INSTRUCTIONS,
        messages=[{"role": "user", "content": invite}],
    )
    if getattr(reponse, "stop_reason", None) == "refusal":
        logger.warning("Synthese IA refusee par le modele Anthropic.")
        return None
    morceaux = [
        bloc.text for bloc in reponse.content if getattr(bloc, "type", None) == "text"
    ]
    texte = "\n".join(morceaux).strip()
    return texte or None


def _resumer_ollama(invite: str) -> str | None:
    """Interroge Ollama directement, sans suivre le proxy HTTP du navigateur."""
    base_url = settings.ollama_base_url.rstrip("/")
    charge = {
        "model": settings.ollama_model,
        "stream": False,
        "keep_alive": settings.ollama_keep_alive,
        "messages": [
            {"role": "system", "content": INSTRUCTIONS},
            {"role": "user", "content": invite},
        ],
        "options": {
            "temperature": 0.1,
            "num_predict": settings.ollama_num_predict,
        },
    }
    # trust_env=False est indispensable : le worker possede un proxy sortant
    # pour Chromium, mais une adresse locale Windows ne doit jamais passer par lui.
    with httpx.Client(
        timeout=settings.ollama_timeout_seconds,
        trust_env=False,
    ) as client:
        reponse = client.post(f"{base_url}/api/chat", json=charge)
        reponse.raise_for_status()
    donnees = reponse.json()
    texte = str((donnees.get("message") or {}).get("content") or "").strip()
    logger.info(
        "Synthese IA locale terminee (modele=%s, entree=%s, sortie=%s, duree_ms=%s)",
        settings.ollama_model,
        donnees.get("prompt_eval_count", "?"),
        donnees.get("eval_count", "?"),
        round((donnees.get("total_duration") or 0) / 1_000_000),
    )
    return texte or None


def _bloc(titre: str, lignes: list[str]) -> str:
    if not lignes:
        return titre + " : aucune."
    extrait = lignes[:MAX_LIGNES]
    corps = "\n".join("- " + ligne for ligne in extrait)
    reste = len(lignes) - len(extrait)
    if reste > 0:
        corps += "\n- (... %d autres lignes)" % reste
    return titre + " :\n" + corps


def construire_invite(
    ajoutees: list[str], retirees: list[str], titre_page: str | None = None
) -> str:
    """Message envoye au modele. Isole pour etre testable sans reseau."""
    entete = "Page surveillee : " + titre_page if titre_page else "Page surveillee."
    invite = "\n\n".join(
        [
            entete,
            _bloc("Lignes apparues", ajoutees),
            _bloc("Lignes disparues", retirees),
        ]
    )
    return invite[:MAX_CARACTERES]


def resumer_changements(ajoutees, retirees, titre_page=None) -> str | None:
    """Synthese lisible des changements, ou None si indisponible.

    Une panne de l API ne doit jamais faire echouer une capture : on
    journalise et on renvoie None.
    """
    ajoutees = list(ajoutees)
    retirees = list(retirees)
    if not is_configured() or (not ajoutees and not retirees):
        return None
    try:
        invite = construire_invite(ajoutees, retirees, titre_page)
        if settings.ai_summary_provider == "ollama":
            return _resumer_ollama(invite)
        return _resumer_anthropic(invite)
    except Exception as exc:  # noqa: BLE001 - jamais bloquant pour la capture
        logger.warning(
            "Synthese IA indisponible (fournisseur=%s) : %s",
            settings.ai_summary_provider,
            exc,
        )
        return None
