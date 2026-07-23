from __future__ import annotations

import re

# Extraction best-effort de métriques publiques depuis le TEXTE d'une page
# (plus stable que le DOM obfusqué). Pensé pour les pages Facebook en français,
# tolérant à l'anglais. Aucune métrique trouvée = dictionnaire vide, jamais d'erreur.

_NUM = r"(\d[\d\s  .,]*)\s*([kKmM])?"

_PATTERNS: dict[str, re.Pattern[str]] = {
    "followers": re.compile(_NUM + r"\s*(?:abonn[ée]s?|followers|personnes?\s+suivent)", re.I),
    "likes": re.compile(
        _NUM + r"\s*(?:mentions?\s+j.?aime|personnes?\s+aiment|j.?aime\s+[çc]a|likes?)", re.I
    ),
}

# Libellés lisibles pour l'interface.
LABELS = {"followers": "Abonnés", "likes": "Mentions J'aime"}


def _to_int(num: str, suffix: str | None) -> int | None:
    """Convertit un nombre affiché (français) en entier.

    Gère « 12 345 », « 1,2 M », « 12,5 k », « 1.234.567 » et « 12k ».
    """
    s = re.sub(r"[\s  ]", "", num)
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")  # 1.234,56 -> 1234.56
    elif "," in s:
        frac = s.split(",")[-1]
        # Décimale (12,5 k) si un suffixe suit, sinon séparateur de milliers.
        s = s.replace(",", ".") if (suffix or len(frac) != 3) else s.replace(",", "")
    elif s.count(".") >= 1:
        last = s.split(".")[-1]
        if len(last) == 3 and not suffix:
            s = s.replace(".", "")  # 12.345 -> milliers
    try:
        val = float(s)
    except ValueError:
        return None
    if suffix:
        val *= 1_000 if suffix.lower() == "k" else 1_000_000
    return int(round(val))


def parse_page_metrics(text: str) -> dict[str, int]:
    """Retourne les métriques repérées dans le texte, ex. {'followers': 12345}."""
    out: dict[str, int] = {}
    if not text:
        return out
    for key, pattern in _PATTERNS.items():
        match = pattern.search(text)
        if match:
            value = _to_int(match.group(1), match.group(2))
            # Garde-fou : ignore les valeurs aberrantes (0 ou > 5 milliards).
            if value is not None and 0 < value < 5_000_000_000:
                out[key] = value
    return out
