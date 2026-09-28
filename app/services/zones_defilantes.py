"""Deplie les listes qui defilent a l interieur d une page avant la capture.

Beaucoup d applications affichent une liste (cameras, commandes...) dans un
cadre de hauteur fixe muni de sa propre barre de defilement. Une capture
« pleine page » ne voit alors que le haut de la liste : la page elle-meme ne
defile pas, seul le cadre defile.

Deux temps :
1. chaque cadre defilant est parcouru jusqu en bas, pour que les elements
   charges a la demande apparaissent ;
2. le cadre et ses parents sont liberes de leur hauteur fixe, pour que toute
   la liste s affiche d un bloc et entre dans la capture pleine page.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Renvoie la liste des cadres defilants (hauteur visible, hauteur totale).
_REPERER = """
() => {
  const zones = [];
  for (const el of document.querySelectorAll('body *')) {
    const st = getComputedStyle(el);
    const defile = /(auto|scroll|overlay)/.test(st.overflowY);
    if (!defile) continue;
    if (el.clientHeight < 80 || el.scrollHeight <= el.clientHeight + 10) continue;
    if (st.visibility === 'hidden' || st.display === 'none') continue;
    el.setAttribute('data-faithbook-zone', String(zones.length));
    zones.push({visible: el.clientHeight, total: el.scrollHeight});
  }
  return zones;
}
"""

# Fait defiler un cadre d un ecran ; renvoie vrai quand le bas est atteint.
_DEFILER = """
(i) => {
  const el = document.querySelector(`[data-faithbook-zone="${i}"]`);
  if (!el) return true;
  el.scrollTop = el.scrollTop + Math.max(200, el.clientHeight * 0.9);
  return el.scrollTop + el.clientHeight >= el.scrollHeight - 5;
}
"""

# Libere les cadres et leurs parents de toute hauteur imposee.
_DEPLIER = """
() => {
  const liberer = (el) => {
    el.style.setProperty('height', 'auto', 'important');
    el.style.setProperty('max-height', 'none', 'important');
    el.style.setProperty('overflow', 'visible', 'important');
  };
  let n = 0;
  for (const el of document.querySelectorAll('[data-faithbook-zone]')) {
    el.scrollTop = 0;
    liberer(el);
    let parent = el.parentElement;
    while (parent && parent !== document.documentElement) {
      const st = getComputedStyle(parent);
      if (st.overflowY !== 'visible' || st.maxHeight !== 'none' || /vh$/.test(parent.style.height)
          || parent.clientHeight < parent.scrollHeight) {
        liberer(parent);
      }
      parent = parent.parentElement;
    }
    n += 1;
  }
  for (const racine of [document.documentElement, document.body]) {
    racine.style.setProperty('height', 'auto', 'important');
    racine.style.setProperty('overflow', 'visible', 'important');
  }
  return {zones: n, hauteur: document.documentElement.scrollHeight};
}
"""


async def deplier(page, pas_max: int = 60, pause_ms: int = 350) -> dict:
    """Charge puis deplie toutes les zones defilantes. Ne leve jamais."""
    try:
        zones = await page.evaluate(_REPERER)
        if not zones:
            return {"zones": 0, "hauteur": None}
        for i in range(len(zones)):
            for _ in range(pas_max):
                fini = await page.evaluate(_DEFILER, i)
                await page.wait_for_timeout(pause_ms)
                if fini:
                    break
        resultat = await page.evaluate(_DEPLIER)
        # Laisse le navigateur recalculer la mise en page avant la photo.
        await page.wait_for_timeout(500)
        logger.info("Zones defilantes depliees : %s", resultat)
        return resultat
    except Exception:  # noqa: BLE001 - au pire, capture normale
        logger.warning("Depliage des zones defilantes impossible", exc_info=True)
        return {"zones": 0, "hauteur": None}
