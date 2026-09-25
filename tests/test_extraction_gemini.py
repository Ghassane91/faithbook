"""Fournisseur Gemini et choix des regles, sans reseau."""

import json
import unittest
from unittest import mock

import httpx

from app.config import settings
from app.services import extraction
from app.services.extraction import (
    ExtractionIndisponible,
    _appeler_gemini,
    _charge_gemini,
    _lire_reponse_gemini,
    _modele_gemini,
    extraire,
    is_configured,
)
from app.services.regles_extraction import CATALOGUE, EDITORIAL, TARIFS, regle_pour

_VRAI_CLIENT = httpx.Client


def _reponse_gemini(texte, fin="STOP"):
    return {"candidates": [{"content": {"parts": [{"text": texte}]}, "finishReason": fin}]}


class _Faux:
    """Enregistre les requetes et rejoue une suite de reponses."""

    def __init__(self, reponses):
        self.reponses = list(reponses)
        self.requetes = []

    def __call__(self, requete):
        self.requetes.append(requete)
        statut, corps = self.reponses.pop(0)
        return httpx.Response(statut, json=corps)

    def client(self, *args, **kwargs):
        kwargs.pop("trust_env", None)
        return _VRAI_CLIENT(transport=httpx.MockTransport(self), **kwargs)


class _Base(unittest.TestCase):
    CHAMPS = (
        "extraction_enabled", "extraction_provider", "extraction_model",
        "gemini_api_key", "gemini_model", "gemini_retry_delays",
    )

    def setUp(self):
        self._sauve = {c: getattr(settings, c) for c in self.CHAMPS}
        settings.extraction_enabled = True
        settings.extraction_provider = "gemini"
        settings.extraction_model = ""
        settings.gemini_api_key = "AQ.factice"
        settings.gemini_model = "gemini-2.5-flash"
        settings.gemini_retry_delays = "0,0"

    def tearDown(self):
        for c, v in self._sauve.items():
            setattr(settings, c, v)


class TestConfiguration(_Base):
    def test_configure_avec_cle(self):
        self.assertTrue(is_configured())

    def test_non_configure_sans_cle(self):
        settings.gemini_api_key = ""
        self.assertFalse(is_configured())

    def test_interrupteur_general(self):
        settings.extraction_enabled = False
        self.assertFalse(is_configured())

    def test_modele_surcharge(self):
        self.assertEqual(_modele_gemini(), "gemini-2.5-flash")
        settings.extraction_model = "gemini-flash-lite-latest"
        self.assertEqual(_modele_gemini(), "gemini-flash-lite-latest")


class TestRequete(_Base):
    def test_charge_json_et_sans_reflexion(self):
        charge = _charge_gemini("bonjour")
        gen = charge["generationConfig"]
        self.assertEqual(gen["responseMimeType"], "application/json")
        self.assertEqual(gen["temperature"], 0)
        self.assertEqual(gen["thinkingConfig"], {"thinkingBudget": 0})
        self.assertIn("N invente JAMAIS", charge["systemInstruction"]["parts"][0]["text"])

    def test_pas_de_thinking_budget_hors_25_flash(self):
        settings.extraction_model = "gemini-3.5-flash"
        self.assertNotIn("thinkingConfig", _charge_gemini("x")["generationConfig"])

    def test_cle_en_entete_jamais_dans_url(self):
        faux = _Faux([(200, _reponse_gemini('{"lignes": []}'))])
        with mock.patch("httpx.Client", faux.client):
            self.assertEqual(_appeler_gemini("x"), '{"lignes": []}')
        requete = faux.requetes[0]
        self.assertEqual(requete.headers["x-goog-api-key"], "AQ.factice")
        self.assertNotIn("AQ.factice", str(requete.url))
        self.assertTrue(str(requete.url).endswith("/models/gemini-2.5-flash:generateContent"))

    def test_reessaie_sur_503_puis_reussit(self):
        faux = _Faux([
            (503, {"error": {"message": "surcharge"}}),
            (429, {"error": {"message": "quota"}}),
            (200, _reponse_gemini('{"lignes": []}')),
        ])
        with mock.patch("httpx.Client", faux.client):
            self.assertEqual(_appeler_gemini("x"), '{"lignes": []}')
        self.assertEqual(len(faux.requetes), 3)

    def test_abandonne_apres_les_tentatives(self):
        faux = _Faux([(503, {"error": {"message": "surcharge"}})] * 3)
        with mock.patch("httpx.Client", faux.client):
            with self.assertRaises(ExtractionIndisponible) as ctx:
                _appeler_gemini("x")
        self.assertIn("503", str(ctx.exception))
        self.assertNotIn("AQ.factice", str(ctx.exception))

    def test_erreur_400_sans_nouvelle_tentative(self):
        faux = _Faux([(400, {"error": {"message": "cle invalide"}})])
        with mock.patch("httpx.Client", faux.client):
            with self.assertRaises(ExtractionIndisponible):
                _appeler_gemini("x")
        self.assertEqual(len(faux.requetes), 1)


class TestLecture(unittest.TestCase):
    def test_reponse_tronquee(self):
        with self.assertRaises(ExtractionIndisponible):
            _lire_reponse_gemini(_reponse_gemini('{"lignes": [', fin="MAX_TOKENS"))

    def test_requete_bloquee(self):
        with self.assertRaises(ExtractionIndisponible):
            _lire_reponse_gemini({"promptFeedback": {"blockReason": "SAFETY"}})

    def test_parties_de_reflexion_ignorees(self):
        corps = {"candidates": [{"finishReason": "STOP", "content": {"parts": [
            {"text": "je reflechis", "thought": True},
            {"text": '{"lignes": []}'},
        ]}}]}
        self.assertEqual(_lire_reponse_gemini(corps), '{"lignes": []}')


class TestBoutEnBout(_Base):
    PAGE = (
        "Trail cameras. SPYPOINT FLEX-M Twin Pack. Now $179.99 CAD, was $229.99. "
        "In stock. SKU 01-FLEXM2. LINK-MICRO-S-LTE $99.99 CAD. Out of stock."
    )

    def test_catalogue_deux_prix_separes_et_devise_d_origine(self):
        modele = json.dumps({"lignes": [
            {"modele": "FLEX-M Twin Pack", "prix": 179.99, "devise": "CAD",
             "prix_barre": 229.99, "en_stock": True, "reference": "01-FLEXM2"},
            {"modele": "LINK-MICRO-S-LTE", "prix": 99.99, "devise": "CAD",
             "prix_barre": None, "en_stock": False, "reference": "INVENTEE-42"},
        ]})
        faux = _Faux([(200, _reponse_gemini(modele))])
        with mock.patch("httpx.Client", faux.client):
            res = extraire(CATALOGUE, self.PAGE, "Cameras", "https://exemple.ca")
        self.assertEqual(len(res.lignes), 2)
        premier, second = res.lignes
        self.assertEqual((premier["prix"], premier["prix_barre"]), (179.99, 229.99))
        self.assertEqual(premier["devise"], "CAD")
        self.assertIsNone(second["prix_barre"])
        # Reference absente de la page : ecartee par le garde-fou.
        self.assertIsNone(second["reference"])
        self.assertTrue(any("INVENTEE-42" in a or "reference" in a for a in res.anomalies))

    def test_panne_ne_leve_jamais(self):
        faux = _Faux([(503, {})] * 3)
        with mock.patch("httpx.Client", faux.client):
            self.assertIsNone(extraire(CATALOGUE, self.PAGE))


class TestChoixRegle(unittest.TestCase):
    def test_correspondances(self):
        self.assertIs(regle_pour("catalogue,marque"), CATALOGUE)
        self.assertIs(regle_pour("catalogue-2,marque"), CATALOGUE)
        self.assertIs(regle_pour("catalogue,revendeur"), CATALOGUE)
        self.assertIs(regle_pour("tarifs,marque"), TARIFS)
        self.assertIs(regle_pour("editorial,media"), EDITORIAL)
        self.assertIs(regle_pour("actualites,marque"), EDITORIAL)
        self.assertIs(regle_pour("accueil,marque"), EDITORIAL)

    def test_sans_regle(self):
        self.assertIsNone(regle_pour("support,marque"))
        self.assertIsNone(regle_pour(None))
        self.assertIsNone(regle_pour(""))
        self.assertIsNone(regle_pour("marque"))

    def test_casse_et_espaces(self):
        self.assertIs(regle_pour(" Tarifs , Revendeur "), TARIFS)


if __name__ == "__main__":
    unittest.main(verbosity=2)
