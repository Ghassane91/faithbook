export const URLS = new Set(['https://www.walmart.com/', 'https://www.academy.com/', 'https://www.basspro.com/']);

export function backendOrigin(value) {
  const url = new URL(value);
  if (url.protocol !== 'https:' || url.username || url.password || url.pathname !== '/' || url.search || url.hash) {
    throw new Error('Indiquez uniquement l’origine HTTPS de FaithBook (https://votre-site).');
  }
  if (URLS.has(url.origin + '/')) throw new Error('Indiquez le serveur FaithBook, pas une enseigne.');
  return url.origin;
}

export function sameSite(expected, actual) {
  try {
    const url = new URL(actual);
    return publicProductURL(expected) && url.origin === new URL(expected).origin && !url.username && !url.password;
  } catch { return false; }
}

export function verdict(page) {
  const text = `${page.title}\n${page.text}`.normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase();
  if (/robot or human|verify (?:that )?you(?: are|'re) (?:a )?human|etes.vous (?:un )?humain|pardon our interruption|press\s*(?:&|and)\s*hold|checking your browser|just a moment|click the button below to continue shopping/.test(text)) return 'challenge';
  if (/(?:couldn['’]t|cannot|can['’]t) find (?:this|that|the) page|page not found|404\s*[-:]?\s*not found|couldn['’]t be found|page (?:does not|doesn't) exist|page introuvable/.test(text)) return 'navigation';
  if (page.text.trim().length < 50 || /something went wrong|access denied|this site can.t be reached/.test(text)) return 'capture';
  return 'success';
}

export function captureWarnings({truncated, height}, assets = {}) {
  const warnings = [];
  if (truncated) warnings.push(`Page tronquée à ${height} px de haut.`);
  if (assets.pending > 0) warnings.push(`${assets.pending} image(s) encore en chargement.`);
  if (assets.broken > 0) warnings.push(`${assets.broken} image(s) indisponible(s) sur le site.`);
  if (assets.fonts_pending) warnings.push('Polices encore en chargement.');
  return warnings.join(' ').slice(0, 300);
}

export const MAX_WIDTH = 2400, MAX_HEIGHT = 16000, MAX_AREA = 24000000;

// Les fiches Amazon dépassent souvent 16 000 px de haut : on capture le haut de
// la page (fiche, prix, avis) au lieu d'échouer. `truncated` le signale.
export function clipSize(width, height) {
  width = Math.min(Math.ceil(width), MAX_WIDTH);
  const full = Math.ceil(height);
  height = Math.min(full, MAX_HEIGHT, Math.floor(MAX_AREA / Math.max(width, 1)));
  if (width < 100 || height < 100) throw new Error('Page vide ou trop petite pour une capture.');
  return {x: 0, y: 0, width, height, scale: 1, truncated: height < full};
}

export function publicProductURL(value) {
  try {
    const u = new URL(value);
    const h = u.hostname.toLowerCase();
    return ['https:', 'http:'].includes(u.protocol) && !u.username && !u.password &&
      (!u.port || ['80', '443'].includes(u.port)) && h.includes('.') &&
      !/^[\d.]+$/.test(h) && !h.includes(':') &&
      !/(?:^|\.)(?:localhost|local|internal|test|invalid)$/.test(h) && !value.includes('\\');
  } catch { return false; }
}

// Repair legacy UTF-8 text decoded as Windows-1252, without changing valid text.
export function readableText(value) {
  let text = String(value ?? '');
  const oldChars = new TextDecoder('windows-1252').decode(Uint8Array.from({length: 32}, (_, i) => i + 128));
  const oldBytes = new Map(Array.from(oldChars, (char, i) => [char, i + 128]));
  const byte = char => char?.codePointAt(0) <= 255 ? char.codePointAt(0) : oldBytes.get(char);
  const utf8 = new TextDecoder('utf-8', {fatal: true});
  for (let pass = 0; pass < 2; pass++) {
    const chars = Array.from(text);
    let repaired = '';
    for (let i = 0; i < chars.length; i++) {
      const lead = byte(chars[i]);
      const length = lead >= 0xc2 && lead <= 0xdf ? 2 : lead >= 0xe0 && lead <= 0xef ? 3 : lead >= 0xf0 && lead <= 0xf4 ? 4 : 0;
      const bytes = length ? chars.slice(i, i + length).map(byte) : [];
      if (bytes.length === length && length && bytes.slice(1).every(b => b >= 0x80 && b <= 0xbf)) {
        try { repaired += utf8.decode(Uint8Array.from(bytes)); i += length - 1; continue; } catch { /* Preserve incomplete/invalid sequences. */ }
      }
      repaired += chars[i];
    }
    if (repaired === text) break;
    text = repaired;
  }
  return text;
}
