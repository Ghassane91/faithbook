import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import unittest
from app.services.extraction import (
    Champ, Regle, analyser_reponse, construire_invite,
    convertir_nombre, convertir_booleen, convertir_date,
)

CATALOGUE = Regle(
    nom="catalogue-cameras",
    ligne="un produit propose a la vente sur la page",
    champs=(
        Champ("modele", "Nom du modele tel qu'affiche", "texte", obligatoire=True, verifiable=True),
        Champ("prix", "Prix de vente affiche, hors prix barre", "nombre"),
        Champ("devise", "Code de la devise : USD, CAD, EUR, MAD", "texte"),
        Champ("prix_barre", "Prix barre avant remise, s'il existe", "nombre"),
        Champ("en_stock", "Le produit est-il disponible", "booleen"),
    ),
)

PAGE = ("Spypoint Flex-M Cellular Trail Camera $119.99 In stock. "
        "Spypoint Flex-G36 $169.99 was $199.99 Out of stock. "
        "Livraison offerte des 99 $.")


class Conversions(unittest.TestCase):
    def test_prix_americain(self):
        self.assertEqual(convertir_nombre("$1,299.00"), 1299.0)
        self.assertEqual(convertir_nombre("249.99 USD"), 249.99)

    def test_prix_europeen(self):
        self.assertEqual(convertir_nombre("1 299,00 $"), 1299.0)
        self.assertEqual(convertir_nombre("2 450,50 MAD"), 2450.5)

    def test_entier_simple(self):
        self.assertEqual(convertir_nombre("1299"), 1299.0)
        self.assertEqual(convertir_nombre(1299), 1299.0)

    def test_non_nombre(self):
        self.assertIsNone(convertir_nombre("sur devis"))
        self.assertIsNone(convertir_nombre(""))
        self.assertIsNone(convertir_nombre(None))

    def test_booleens_francais(self):
        self.assertTrue(convertir_booleen("Oui"))
        self.assertTrue(convertir_booleen("En stock"))
        self.assertFalse(convertir_booleen("rupture"))
        self.assertFalse(convertir_booleen("\u00e9puis\u00e9"))

    def test_booleens_anglais(self):
        # Les cibles reelles sont americaines et canadiennes.
        self.assertTrue(convertir_booleen("In stock"))
        self.assertTrue(convertir_booleen("Available"))
        self.assertFalse(convertir_booleen("Out of stock"))
        self.assertFalse(convertir_booleen("Sold out"))

    def test_booleen_ambigu_reste_vide(self):
        self.assertIsNone(convertir_booleen("peut-etre"))
        self.assertIsNone(convertir_booleen("bientot disponible"))

    def test_dates(self):
        self.assertEqual(convertir_date("mis a jour le 2026-09-14"), "2026-09-14")
        self.assertEqual(convertir_date("14/09/2026"), "2026-09-14")
        self.assertIsNone(convertir_date("la semaine prochaine"))


class Invite(unittest.TestCase):
    def test_contient_les_champs_et_le_texte(self):
        invite, tronque = construire_invite(CATALOGUE, PAGE, "Catalogue Spypoint", "https://spypoint.com/x")
        self.assertIn('"modele"', invite)
        self.assertIn("obligatoire", invite)
        self.assertIn("Flex-M", invite)
        self.assertIn("Catalogue Spypoint", invite)
        self.assertFalse(tronque)

    def test_troncature_signalee(self):
        _, tronque = construire_invite(CATALOGUE, "a" * 50000, None, None)
        self.assertTrue(tronque)


class Analyse(unittest.TestCase):
    def test_extraction_nominale(self):
        reponse = """{"lignes":[
          {"modele":"Spypoint Flex-M","prix":"$119.99","devise":"USD","prix_barre":null,"en_stock":"In stock"},
          {"modele":"Spypoint Flex-G36","prix":"169.99","devise":"USD","prix_barre":"$199.99","en_stock":"Out of stock"}
        ]}"""
        r = analyser_reponse(CATALOGUE, reponse, PAGE)
        self.assertEqual(len(r.lignes), 2)
        self.assertEqual(r.lignes[0]["prix"], 119.99)
        self.assertEqual(r.lignes[1]["prix_barre"], 199.99)
        self.assertIsNone(r.lignes[0]["prix_barre"])
        self.assertTrue(r.lignes[0]["en_stock"])
        self.assertFalse(r.lignes[1]["en_stock"])

    def test_valeur_inventee_ecartee(self):
        reponse = '{"lignes":[{"modele":"Spypoint Flex-XXL 4K","prix":"299.00"}]}'
        r = analyser_reponse(CATALOGUE, reponse, PAGE)
        self.assertIsNone(r.lignes[0]["modele"])
        self.assertTrue(any("absent du texte source" in a for a in r.anomalies))
        self.assertTrue(any("obligatoire et absent" in a for a in r.anomalies))

    def test_balises_de_code_tolerees(self):
        r = analyser_reponse(CATALOGUE, '```json\n{"lignes":[{"modele":"Spypoint Flex-M"}]}\n```', PAGE)
        self.assertEqual(len(r.lignes), 1)

    def test_json_invalide(self):
        r = analyser_reponse(CATALOGUE, "je n'ai pas trouve de produits", PAGE)
        self.assertEqual(r.lignes, [])
        self.assertTrue(any("illisible" in a for a in r.anomalies))

    def test_page_sans_produit(self):
        r = analyser_reponse(CATALOGUE, '{"lignes":[]}', PAGE)
        self.assertEqual(r.lignes, [])
        self.assertEqual(r.anomalies, [])

    def test_champ_inattendu_ignore(self):
        r = analyser_reponse(CATALOGUE, '{"lignes":[{"modele":"Spypoint Flex-M","couleur":"noir"}]}', PAGE)
        self.assertNotIn("couleur", r.lignes[0])
        self.assertTrue(any("inattendu" in a for a in r.anomalies))

    def test_prix_non_numerique_signale(self):
        r = analyser_reponse(CATALOGUE, '{"lignes":[{"modele":"Spypoint Flex-M","prix":"sur devis"}]}', PAGE)
        self.assertIsNone(r.lignes[0]["prix"])
        self.assertTrue(any("pas un nombre" in a for a in r.anomalies))

    def test_limite_de_lignes(self):
        petite = Regle("x", "un produit", (Champ("modele", "nom"),), max_lignes=2)
        corps = ",".join(['{"modele":"Spypoint Flex-M"}'] * 5)
        r = analyser_reponse(petite, '{"lignes":[' + corps + ']}', PAGE)
        self.assertEqual(len(r.lignes), 2)
        self.assertTrue(any("au-dela de la limite" in a for a in r.anomalies))

    def test_sans_source_pas_de_verification(self):
        r = analyser_reponse(CATALOGUE, '{"lignes":[{"modele":"Modele inconnu"}]}', "")
        self.assertEqual(r.lignes[0]["modele"], "Modele inconnu")


if __name__ == "__main__":
    unittest.main(verbosity=2)
