import { useCallback, useEffect, useRef, useState } from 'react'
import type { RunStatus } from './types'

export const STATUS_LABEL: Record<RunStatus, string> = {
  pending: 'en attente',
  running: 'en cours',
  success: 'réussie',
  failed: 'échouée',
  skipped: 'ignorée',
}

export function heure(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
}

export function dateHeure(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('fr-FR', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export function duree(ms: number | null): string {
  if (ms == null) return '—'
  return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`
}

export function poids(octets: number | null): string {
  if (octets == null) return '—'
  return octets < 1024 * 1024
    ? `${Math.round(octets / 1024)} Ko`
    : `${(octets / 1024 / 1024).toFixed(1)} Mo`
}

export function aujourdhui(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

/**
 * Traduit une erreur technique en une phrase courte et actionnable.
 * La trace complete reste consultable dans le journal de l'exécution.
 */
export function resumeErreur(brut: string | null): string {
  if (!brut) return 'Échec sans message'
  const m = brut.toLowerCase()

  if (m.includes('err_name_not_resolved')) return 'Adresse introuvable : le domaine n’existe pas.'
  if (m.includes('err_connection_refused')) return 'Connexion refusée par le serveur.'
  if (m.includes('err_internet_disconnected')) return 'Pas d’accès réseau au moment de la capture.'
  if (m.includes('err_cert') || m.includes('ssl')) return 'Certificat du site invalide.'
  if (m.includes('session probablement expiree') || m.includes('session expiree'))
    return 'Session expirée : reconnectez-vous pour cette cible.'
  if (m.includes('element attendu')) return 'La page attendue ne s’est pas affichée.'
  if (m.includes('timeout') && m.includes('goto'))
    return 'Page trop lente ou injoignable : délai dépassé.'
  if (m.includes('timeout')) return 'Délai dépassé pendant la capture.'

  const http = brut.match(/HTTP (\d{3})/)
  if (http) return `Le site a répondu avec une erreur ${http[1]}.`

  const premiere = brut.split('\n')[0].trim()
  return premiere.length > 110 ? `${premiere.slice(0, 110)}…` : premiere
}

/** Compte a rebours lisible : "dans 3 h 12" / "dans 45 min". */
export function delai(iso: string | null): string {
  if (!iso) return 'aucune'
  const diff = new Date(iso).getTime() - Date.now()
  if (diff <= 0) return 'imminente'
  const min = Math.floor(diff / 60000)
  if (min < 60) return `dans ${min} min`
  const h = Math.floor(min / 60)
  if (h < 24) return `dans ${h} h ${String(min % 60).padStart(2, '0')}`
  return `dans ${Math.floor(h / 24)} j`
}

/** Chargement de donnees avec rafraichissement optionnel. */
export function useData<T>(
  charger: () => Promise<T>,
  deps: unknown[] = [],
  intervalleMs?: number,
) {
  const [data, setData] = useState<T | null>(null)
  const [erreur, setErreur] = useState<string | null>(null)
  const [chargement, setChargement] = useState(true)
  const monte = useRef(true)
  const fnRef = useRef(charger)
  fnRef.current = charger

  const recharger = useCallback(async () => {
    try {
      const r = await fnRef.current()
      if (monte.current) {
        setData(r)
        setErreur(null)
      }
    } catch (e) {
      if (monte.current) setErreur(e instanceof Error ? e.message : 'Erreur inconnue')
    } finally {
      if (monte.current) setChargement(false)
    }
  }, [])

  useEffect(() => {
    monte.current = true
    setChargement(true)
    recharger()
    return () => {
      monte.current = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    if (!intervalleMs) return
    const id = setInterval(recharger, intervalleMs)
    return () => clearInterval(id)
  }, [intervalleMs, recharger])

  return { data, erreur, chargement, recharger }
}

/** Routeur minimal sur le hash : evite une dependance pour trois vues. */
export function useRoute(): [string, (r: string) => void] {
  const ROUTES = ['planche', 'cibles', 'comptes', 'historique', 'mentions']
  const lire = () => {
    const r = window.location.hash.replace(/^#\/?/, '')
    return ROUTES.includes(r) ? r : 'planche'
  }
  const [route, setRoute] = useState(lire)
  useEffect(() => {
    const onHash = () => setRoute(lire())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  return [route, (r: string) => { window.location.hash = `/${r}` }]
}
