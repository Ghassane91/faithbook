import { useState, type ReactNode } from 'react'
import { api, request } from '../api'
import { useData } from '../lib'

export type CaptureBatch = {
  source_target_id: number; source_name: string; source_run_id: number; capture_date: string
  total: number; captured: number; pending: number; unavailable: number; failed: number
  drive_total: number; drive_uploaded: number; drive_pending: number; drive_failed: number
  folders: {date: string; row_label: string; url: string}[]
  errors: {target_name: string; message: string}[]
}
export type CaptureDevice = {id: number; name: string; active: boolean; last_seen_at: string | null; next_at?: string | null}
export type ZyteState = {enabled: boolean; configured: boolean; daily_limit: number | null}

export function CaptureIcon({name, ...props}: {name: string; className?: string}) {
  const shapes: Record<string, ReactNode> = {
    capture: <><path d="M3 7h4l2-3h6l2 3h4v13H3z"/><circle cx="12" cy="13" r="4"/></>,
    grid: <><rect x="3" y="3" width="7" height="7" rx="1"/><rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/><rect x="14" y="14" width="7" height="7" rx="1"/></>,
    clock: <><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>,
    folder: <path d="M3 7V4h6l3 3h9v13H3z"/>,
    check: <><circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/></>,
    arrow: <path d="M5 12h14m-5-5 5 5-5 5"/>,
    external: <><path d="M14 3h7v7m0-7L10 14"/><path d="M10 3H3v18h18v-7"/></>,
    refresh: <><path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 6a8 8 0 0 1 14 6M18 18A8 8 0 0 1 4 12"/></>,
    alert: <><path d="m12 3 10 18H2zM12 9v5m0 3v1"/></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 2v6M17 2v6M3 11h18"/></>,
    browser: <><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18M6 6.5h.1m3 0h.1"/></>,
    layers: <><path d="m12 3 10 5-10 5L2 8zM2 12l10 5 10-5M2 16l10 5 10-5"/></>,
  }
  return <svg {...props} width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{shapes[name] ?? shapes.grid}</svg>
}

export function HuntxMark() {
  return <svg className="huntx-mark" viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M4 11V4h7M21 4h7v7M28 21v7h-7M11 28H4v-7" stroke="currentColor" strokeWidth="2"/><path d="M10 10h12v4h-8v3h6v4h-6v3h-4z" fill="currentColor"/></svg>
}

function displayDay(date: string) {
  return new Intl.DateTimeFormat('fr-FR', {day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC'}).format(new Date(`${date}T12:00:00Z`))
}

function displaySlot(iso: string) {
  return new Intl.DateTimeFormat('fr-FR', {day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Africa/Casablanca'}).format(new Date(iso))
}

export function HuntxOverview({onAller, onOuvrirRun, canAdmin, organizationId}: {
  onAller: (route: string) => void; onOuvrirRun: (id: number) => void; canAdmin: boolean; organizationId?: number
}) {
  const archives = useData(() => request<{sources: CaptureBatch[]}>('/browser-capture/archive'), [organizationId], 30000)
  const devices = useData(() => request<CaptureDevice[]>('/browser-capture/devices'), [organizationId], 30000)
  const zyte = useData(() => canAdmin ? request<ZyteState>('/browser-capture/zyte') : Promise.resolve(null), [organizationId, canAdmin], 30000)
  const jobs = useData(() => api.jobs(), [organizationId], 30000)
  const source = archives.data?.sources.slice().sort((a, b) => b.capture_date.localeCompare(a.capture_date) || b.source_run_id - a.source_run_id)[0]
  const next = jobs.data?.find(job => job.target_id === source?.source_target_id)?.next_run_at
    ?? devices.data?.find(device => device.active)?.next_at
  return <HuntxDashboard source={source} devices={devices.data ?? []} zyte={zyte.data ?? undefined}
    nextCapture={next ? displaySlot(next) : undefined} error={archives.erreur ?? undefined}
    loading={!archives.data && !archives.erreur} onAller={onAller} onOuvrirRun={onOuvrirRun}
    onRefresh={() => {void archives.recharger(); void devices.recharger(); void zyte.recharger(); void jobs.recharger()}} />
}

export function HuntxDashboard({source, devices = [], zyte, nextCapture, loading = false, error,
  onAller, onOuvrirRun, onRefresh, preview = false}: {
  source?: CaptureBatch; devices?: CaptureDevice[]; zyte?: ZyteState; nextCapture?: string
  loading?: boolean; error?: string; preview?: boolean
  onAller: (route: string) => void; onOuvrirRun: (id: number) => void; onRefresh: () => void
}) {
  const [query, setQuery] = useState('')
  const connected = devices.find(device => device.active && device.last_seen_at && Date.now() - new Date(device.last_seen_at).getTime() < 180000)
  const progress = source?.total ? Math.round(source.captured / source.total * 100) : 0
  const folders = (source?.folders ?? []).filter(folder => folder.row_label.toLocaleLowerCase('fr').includes(query.toLocaleLowerCase('fr')))
  const stats = [
    {icon:'capture', label:'Captures réussies', value:source?.captured, note:source ? `sur ${source.total} liens marchands` : 'Dernière campagne', tone:'orange'},
    {icon:'clock', label:'En attente', value:source?.pending, note:'Dans la file de capture', tone:'neutral'},
    {icon:'folder', label:'Fichiers dans Drive', value:source?.drive_uploaded, note:source ? `${source.drive_pending} en attente d’envoi` : 'Photos et métadonnées', tone:'green'},
    {icon:'alert', label:'À examiner', value:source ? source.failed + source.unavailable : undefined, note:source ? `${source.unavailable} indisponibles · ${source.failed} erreurs ou blocages` : 'Erreurs et liens indisponibles', tone:'neutral'},
  ]
  return <section className="hx-dashboard" aria-labelledby="hx-title">
    {preview && <div className="hx-preview-note"><span>APERÇU DE LA REFONTE</span> Données d’illustration · aucune capture déclenchée</div>}
    <div className="hx-heading"><div><p className="hx-kicker"><span/> VOTRE OBSERVATOIRE DIGITAL</p><h1 id="hx-title">Votre veille, <em>sous contrôle.</em></h1><p>Capturez l’essentiel. Retrouvez chaque preuve, au bon endroit.</p></div><button className="hx-button secondary" onClick={onRefresh}><CaptureIcon name="refresh"/>Actualiser</button></div>
    <div className="hx-stats" aria-label="Bilan de la dernière campagne">{stats.map(stat => <article className={`hx-stat ${stat.tone}`} key={stat.label}><div><span>{stat.label}</span><CaptureIcon name={stat.icon}/></div><strong>{stat.value ?? '—'}</strong><small>{stat.note}</small></article>)}</div>
    {error && <div className="hx-error" role="alert">Le suivi n’a pas pu être chargé : {error}. <button onClick={onRefresh}>Réessayer</button></div>}
    <div className="hx-primary-grid">
      <article className="hx-panel hx-campaign"><div className="hx-section-head"><div><span className="hx-overline">DERNIÈRE CAMPAGNE</span><h2>{source?.source_name ?? 'Vos captures'}</h2></div><span className="hx-tag"><span/>{loading ? 'Chargement' : source?.pending ? 'Collecte en cours' : source ? 'Collecte terminée' : 'Aucune campagne'}</span></div>
        <p className="hx-description">{source ? `Tableau capturé le ${displayDay(source.capture_date)}. Chaque lien est suivi et archivé.` : loading ? 'Récupération de votre dernière campagne…' : 'Les campagnes apparaîtront ici après la première capture de liens.'}</p>
        <div className="hx-progress-heading"><span>Captures obtenues</span><strong>{progress}<small> %</small></strong></div>
        <div className="hx-progress" role="progressbar" aria-label="Liens capturés" aria-valuemin={0} aria-valuemax={source?.total || 100} aria-valuenow={source?.captured ?? 0}>
          <span className="captured" style={{width:`${source?.total ? source.captured / source.total * 100 : 0}%`}}/><span className="waiting" style={{width:`${source?.total ? source.pending / source.total * 100 : 0}%`}}/><span className="issue" style={{width:`${source?.total ? (source.unavailable + source.failed) / source.total * 100 : 0}%`}}/>
        </div><div className="hx-legend"><span><i className="captured"/>{source?.captured ?? '—'} réussies</span><span><i className="waiting"/>{source?.pending ?? '—'} en attente</span><span><i className="issue"/>{source ? source.unavailable + source.failed : '—'} à examiner</span></div>
        <div className="hx-campaign-foot"><span><CaptureIcon name="layers"/>Une capture, une trace conservée.</span><button className="hx-text-button" onClick={() => onAller('chrome')}>Suivre la collecte <CaptureIcon name="arrow"/></button></div>
      </article>
      <article className="hx-panel hx-schedule"><div className="hx-section-head"><span className="hx-overline">PROCHAIN RENDEZ-VOUS</span><CaptureIcon name="calendar"/></div><div className="hx-calendar-mark">{nextCapture?.match(/^\d+/)?.[0] ?? '—'}<span>PROCHAINE PRISE</span></div><h2>{nextCapture ?? 'À consulter dans les pages suivies'}</h2><p>Les prises HuntX sont programmées les 1er et 15 à 09:00, heure du Maroc.</p><button className="hx-button secondary" onClick={() => onAller('cibles')}>Voir la planification< CaptureIcon name="arrow"/></button></article>
    </div>
    <div className="hx-bottom-grid"><article className="hx-panel hx-archive"><div className="hx-section-head"><div><span className="hx-overline">VOS PREUVES, BIEN RANGÉES</span><h2>Archive des captures</h2></div><CaptureIcon name="folder"/></div><div className="hx-archive-toolbar"><p>Date de prise <span>/</span> Ligne HuntX <span>/</span> Marchand</p><label><span className="sr-only">Rechercher une ligne dans les dossiers affichés</span><input value={query} onChange={event => setQuery(event.target.value)} placeholder="Rechercher une ligne…"/></label></div>
      <div className="hx-folder-list">{folders.slice(0,4).map(folder => <a className="hx-folder" key={`${folder.date}-${folder.row_label}`} href={folder.url} target="_blank" rel="noopener noreferrer"><span className="hx-folder-icon"><CaptureIcon name="folder"/></span><span><strong>{folder.row_label}</strong><small>{displayDay(folder.date)} · Dossier Drive</small></span><CaptureIcon name="external"/></a>)}{!folders.length && <p className="hx-empty">{query ? 'Aucune ligne ne correspond dans les dossiers affichés.' : loading ? 'Chargement des dossiers…' : 'Aucun dossier disponible pour cette campagne.'}</p>}</div>
      <div className="hx-archive-foot"><button className="hx-text-button" onClick={() => onAller('huntx')}>Tous les aperçus HuntX <CaptureIcon name="arrow"/></button><button className="hx-text-button" disabled={!source} onClick={() => source && onOuvrirRun(source.source_run_id)}>Voir le tableau <CaptureIcon name="arrow"/></button></div>
    </article>
    <article className="hx-panel hx-services"><span className="hx-overline">VOTRE CHAÎNE DE COLLECTE</span><h2>Chaque étape compte.</h2><div className="hx-service"><span className="hx-service-icon"><CaptureIcon name="browser"/></span><div><strong>Chrome personnel</strong><small>{connected ? connected.name : 'Appareil en attente de contact'}</small></div><span className={`hx-state ${connected ? 'ok' : ''}`}>{connected ? 'Connecté' : 'À vérifier'}</span></div><div className="hx-service"><span className="hx-service-icon zyte">Z</span><div><strong>Zyte API</strong><small>Secours après blocage Chrome</small></div><span className={`hx-state ${zyte?.enabled && zyte.configured ? 'ok' : ''}`}>{zyte ? zyte.enabled && zyte.configured ? 'Activé' : 'Inactif' : '—'}</span></div><div className="hx-service"><span className="hx-service-icon"><CaptureIcon name="folder"/></span><div><strong>Google Drive</strong><small>{source ? `${source.drive_uploaded} fichiers archivés` : 'Archivage par date et ligne'}</small></div><span className={`hx-state ${source && !source.drive_failed ? 'ok' : ''}`}>{source?.drive_failed ? 'À reprendre' : source ? source.drive_pending ? 'Envoi en cours' : 'À jour' : '—'}</span></div><p className="hx-service-note"><CaptureIcon name="check"/>L’historique reste conservé à chaque reprise.</p><button className="hx-text-button" onClick={() => onAller('chrome')}>Gérer la collecte< CaptureIcon name="arrow"/></button></article></div>
    <div className="hx-bottom-note"><span>FaithBook <i>×</i> HuntX</span><p>Une veille continue. Des preuves qui restent.</p></div>
  </section>
}
