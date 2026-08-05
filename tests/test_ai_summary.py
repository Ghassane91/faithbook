"""Tests de la synthese IA : aucun appel reseau, aucune cle requise."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.config import settings
from app.services import ai_summary
from app.services.capture import diff_lignes


@pytest.fixture
def ia_activee(monkeypatch):
    monkeypatch.setattr(settings, "ai_summary_enabled", True)
    monkeypatch.setattr(settings, "ai_summary_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "cle-de-test")
    monkeypatch.setattr(settings, "ai_summary_model", "claude-opus-5")


@pytest.fixture
def ollama_activee(monkeypatch):
    monkeypatch.setattr(settings, "ai_summary_enabled", True)
    monkeypatch.setattr(settings, "ai_summary_provider", "ollama")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    monkeypatch.setattr(settings, "ollama_base_url", "http://ollama.test:11434")
    monkeypatch.setattr(settings, "ollama_model", "qwen2.5:7b-instruct")
    monkeypatch.setattr(settings, "ollama_timeout_seconds", 180)
    monkeypatch.setattr(settings, "ollama_keep_alive", "5m")
    monkeypatch.setattr(settings, "ollama_num_predict", 180)


def _reponse(texte, stop_reason="end_turn"):
    return SimpleNamespace(
        stop_reason=stop_reason,
        content=[SimpleNamespace(type="text", text=texte)],
    )


def test_desactivee_par_defaut():
    assert ai_summary.is_configured() is False


def test_activee_exige_une_cle(monkeypatch):
    monkeypatch.setattr(settings, "ai_summary_enabled", True)
    monkeypatch.setattr(settings, "ai_summary_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    assert ai_summary.is_configured() is False


def test_activee_avec_cle(ia_activee):
    assert ai_summary.is_configured() is True


def test_ollama_actif_sans_cle(ollama_activee):
    assert ai_summary.is_configured() is True


def test_invite_contient_les_lignes():
    invite = ai_summary.construire_invite(
        ["Nouveau post de la paroisse"], [], "Ma page"
    )
    assert "Ma page" in invite
    assert "Nouveau post de la paroisse" in invite
    assert "Lignes disparues : aucune." in invite


def test_invite_tronquee_au_dela_du_plafond():
    lignes = ["ligne numero %d" % i for i in range(200)]
    invite = ai_summary.construire_invite(lignes, [])
    assert "ligne numero 0" in invite
    assert "ligne numero 199" not in invite
    assert len(invite) <= ai_summary.MAX_CARACTERES


def test_aucun_appel_si_desactivee():
    assert ai_summary.resumer_changements(["une ligne nouvelle"], []) is None


def test_aucun_appel_si_rien_na_change(ia_activee, monkeypatch):
    client = MagicMock()
    monkeypatch.setattr(ai_summary, "_client", client)
    assert ai_summary.resumer_changements([], []) is None
    client.messages.create.assert_not_called()


def test_resume_renvoye(ia_activee, monkeypatch):
    client = MagicMock()
    client.messages.create.return_value = _reponse("Trois nouveaux posts.")
    monkeypatch.setattr(ai_summary, "_client", client)
    resume = ai_summary.resumer_changements(["un nouveau post"], [])
    assert resume == "Trois nouveaux posts."
    appel = client.messages.create.call_args.kwargs
    assert appel["model"] == "claude-opus-5"
    assert appel["messages"][0]["role"] == "user"


def test_refus_du_modele_donne_none(ia_activee, monkeypatch):
    client = MagicMock()
    client.messages.create.return_value = _reponse("", stop_reason="refusal")
    monkeypatch.setattr(ai_summary, "_client", client)
    assert ai_summary.resumer_changements(["un nouveau post"], []) is None


def test_panne_api_ne_casse_pas_la_capture(ia_activee, monkeypatch):
    client = MagicMock()
    client.messages.create.side_effect = RuntimeError("service indisponible")
    monkeypatch.setattr(ai_summary, "_client", client)
    assert ai_summary.resumer_changements(["un nouveau post"], []) is None


def test_resume_ollama_renvoye(ollama_activee, monkeypatch):
    reponse = MagicMock()
    reponse.json.return_value = {
        "message": {"role": "assistant", "content": "Une nouvelle offre est apparue."},
        "prompt_eval_count": 42,
        "eval_count": 8,
        "total_duration": 1_500_000_000,
    }
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = reponse
    fabrique = MagicMock(return_value=client)
    monkeypatch.setattr(ai_summary.httpx, "Client", fabrique)

    resume = ai_summary.resumer_changements(["Nouvelle offre a 40 %"], [])

    assert resume == "Une nouvelle offre est apparue."
    fabrique.assert_called_once_with(timeout=180, trust_env=False)
    appel = client.post.call_args
    assert appel.args[0] == "http://ollama.test:11434/api/chat"
    assert appel.kwargs["json"]["model"] == "qwen2.5:7b-instruct"
    assert appel.kwargs["json"]["stream"] is False
    assert appel.kwargs["json"]["keep_alive"] == "5m"
    assert appel.kwargs["json"]["options"]["num_predict"] == 180
    reponse.raise_for_status.assert_called_once()


def test_panne_ollama_ne_casse_pas_la_capture(ollama_activee, monkeypatch):
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.side_effect = RuntimeError("ollama indisponible")
    monkeypatch.setattr(ai_summary.httpx, "Client", MagicMock(return_value=client))

    assert ai_summary.resumer_changements(["un nouveau post"], []) is None


def test_diff_detecte_la_ligne_nouvelle():
    avant = "Premiere annonce du jour\nSeconde annonce du jour"
    apres = avant + "\nTroisieme annonce inedite"
    ajoutees, retirees = diff_lignes(avant, apres)
    assert ajoutees == ["Troisieme annonce inedite"]
    assert retirees == []


def test_diff_ignore_le_reordonnancement():
    avant = "Premiere annonce du jour\nSeconde annonce du jour"
    apres = "Seconde annonce du jour\nPremiere annonce du jour"
    assert diff_lignes(avant, apres) == ([], [])


def test_diff_conserve_la_casse_dorigine():
    ajoutees, _ = diff_lignes("", "Annonce Importante De La Paroisse")
    assert ajoutees == ["Annonce Importante De La Paroisse"]


def test_diff_ignore_les_lignes_trop_courtes():
    ajoutees, _ = diff_lignes("", "ok\n12\nUne ligne assez longue")
    assert ajoutees == ["Une ligne assez longue"]


def test_diff_ignore_le_statut_facebook_verifie_en_production():
    ajoutees, retirees = diff_lignes(
        "Publication SPYPOINT toujours visible",
        "Publication SPYPOINT toujours visible\n"
        "Indicateur de statut En ligne\n"
        "En ligne",
        "https://www.facebook.com/SPYPOINT.CA",
    )

    assert ajoutees == []
    assert retirees == []


@pytest.mark.asyncio
async def test_runner_ne_tente_rien_quand_ia_desactivee():
    from app.services.runner import _resume_ia

    prev = SimpleNamespace(body_text="ancien texte de la page surveillee")
    result = SimpleNamespace(
        body_text="nouveau texte de la page surveillee", page_title="Titre"
    )
    assert await _resume_ia(prev, result) is None


@pytest.mark.asyncio
async def test_runner_ne_tente_pas_ia_pour_statut_facebook(
    ollama_activee,
    monkeypatch,
):
    from app.services.runner import _resume_ia

    prev = SimpleNamespace(body_text="Publication SPYPOINT toujours visible")
    result = SimpleNamespace(
        body_text=(
            "Publication SPYPOINT toujours visible\n"
            "Indicateur de statut En ligne\n"
            "En ligne"
        ),
        page_title="SPYPOINT",
    )
    resumer = MagicMock()
    monkeypatch.setattr(ai_summary, "resumer_changements", resumer)

    resume = await _resume_ia(
        prev,
        result,
        "https://www.facebook.com/SPYPOINT.CA",
    )

    assert resume is None
    resumer.assert_not_called()
