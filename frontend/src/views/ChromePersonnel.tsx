import { useEffect, useState } from 'react'
import { request } from '../api'
import { dateHeure, useData } from '../lib'

type Device = {
  id: number; name: string; active: boolean; expires_at: string; last_seen_at: string | null; next_at: string | null
  targets: {target_id: number; name: string; enabled: boolean; status: string | null; error: string | null; last_run_id: number | null}[]
}

type ArchiveSource = {
  source_target_id: number; source_name: string; source_run_id: number; capture_date: string
  total: number; captured: number; pending: number; unavailable: number; failed: number
  drive_total: number; drive_uploaded: number; drive_pending: number; drive_failed: number
  folders: {date: string; row_label: string; url: string}[]
  errors: {target_name: string; message: string}[]
}

function dateCapture(date: string) {
  const parsed = new Date(`${date}T00:00:00Z`)
  return Number.isNaN(parsed.getTime()) ? date : parsed.toLocaleDateString('fr-FR', { timeZone: 'UTC' })
}

export function ChromePersonnel({ canAdmin, organizationId, onOuvrirRun }: {
  canAdmin: boolean; organizationId?: number; onOuvrirRun: (id: number) => void
}) {
  const { data, erreur, recharger } = useData(() => request<Device[]>('/browser-capture/devices'), [organizationId])
  const archive = useData(() => request<{sources: ArchiveSource[]}>('/browser-capture/archive'), [organizationId], 30_000)
  const [token, setToken] = useState('')
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { setToken(''); setMessage('') }, [organizationId])
  function actualiser() {
    void recharger()
    void archive.recharger()
  }
  async function action(path: string, create = false) {
    setBusy(true); setMessage('')
    try {
      const result = await request<{token?: string; queued?: number}>(`/browser-capture/${path}`, {
        method: 'POST', body: JSON.stringify(create ? {name: 'Mon Chrome'} : {})
      })
      if (result.token) setToken(result.token)
      if (path.endsWith('/test')) setMessage('Test demandé. Chrome doit être ouvert avec l’extension appairée. Les trois cibles passent successivement, à environ une minute d’intervalle.')
      if (path.endsWith('/revoke')) { setToken(''); setMessage('Appairage révoqué et cibles Chrome désactivées.') }
      if (path.endsWith('/retry-products')) setMessage(`${result.queued ?? 0} reprise(s) ajoutée(s) à la file. Chrome doit rester ouvert avec l’extension appairée.`)
      actualiser()
    } catch (error) { setMessage(error instanceof Error ? error.message : 'Opération impossible.') }
    finally { setBusy(false) }
  }
  return <section>
    <h1>Chrome personnel</h1>
    <p>Walmart, Academy et Bass Pro seront capturés les <strong>1er et 15 à 9 h, heure du Maroc</strong>.</p>
    <p>Les fiches produits de HuntX sont ajoutées automatiquement à cette liste après chaque capture du tableau, toutes enseignes confondues.</p>
    <p>Dans Drive, les captures sont classées par <strong>date de prise de capture, puis par ligne HuntX</strong>. Le suivi ci-dessous distingue les captures obtenues, les liens indisponibles et les erreurs à reprendre.</p>
    <p>Votre PC doit être allumé et Chrome ouvert. Si vous êtes hors ligne, une échéance peut être rattrapée pendant 48 heures. Les défis humains sont signalés dans l’historique.</p>
    <details><summary>Installation initiale</summary><ol>
      <li>Téléchargez et décompressez <a href="/api/browser-capture/extension">l’extension FaithBook</a>.</li>
      <li>Dans Chrome, ouvrez <code>chrome://extensions</code>, activez le mode développeur puis « Charger l’extension non empaquetée ». Sélectionnez le dossier décompressé.</li>
      <li>Créez l’appairage ci-dessous. Ouvrez les options de l’extension et renseignez l’adresse <code>{window.location.origin}</code> et le code reçu.</li>
      <li>Autorisez l’accès à votre serveur FaithBook puis lancez un test. Chrome affiche un avertissement pour la permission de capture par débogage. L’extension capture ses propres onglets et ne transfère pas vos cookies.</li>
    </ol></details>
    {erreur && <p role="alert">{erreur}</p>}
    {message && <p role="status">{message}</p>}
    {canAdmin && !data?.some(d => d.active) && <button disabled={busy || !data} onClick={() => action('devices', true)}>Lier mon Chrome</button>}
    {token && <div><p>Code affiché une seule fois. Copiez-le dans les options de l’extension.</p><input aria-label="Code d’appairage" readOnly value={token} style={{width: '100%'}} /><button onClick={() => setToken('')}>Masquer le code</button></div>}
    <button disabled={busy} onClick={actualiser}>Actualiser</button>
    {archive.erreur && <p role="alert">Suivi Drive : {archive.erreur}</p>}
    {archive.data?.sources.length === 0 && <p>Aucune capture de fiches HuntX à archiver pour cet espace.</p>}
    {archive.data?.sources.slice().sort((a, b) => b.capture_date.localeCompare(a.capture_date) || b.source_run_id - a.source_run_id).map(source => <article key={`${source.source_target_id}-${source.source_run_id}`} style={{marginTop: 24}}>
      <h2>{source.source_name} · {dateCapture(source.capture_date)}</h2>
      <p>Fiches : {source.captured} capturées sur {source.total} · {source.pending} en attente · {source.unavailable} indisponibles · {source.failed} erreurs techniques.</p>
      <p>Archivage Drive : {source.drive_uploaded} fichiers enregistrés sur {source.drive_total} · {source.drive_pending} en attente · {source.drive_failed} erreurs d’envoi.</p>
      <button onClick={() => onOuvrirRun(source.source_run_id)}>Voir la capture du tableau</button>
      {source.folders.length > 0 && <ul>{source.folders.slice().sort((a, b) => b.date.localeCompare(a.date) || a.row_label.localeCompare(b.row_label, 'fr', {numeric: true})).slice(0, 3).map(folder => <li key={`${folder.date}-${folder.row_label}-${folder.url}`}><a href={folder.url} target="_blank" rel="noopener noreferrer">{dateCapture(folder.date)} / {folder.row_label}</a></li>)}</ul>}
      {source.folders.length > 3 && <p>{source.folders.length} dossiers de lignes disponibles dans Drive.</p>}
      {source.errors.length > 0 && <details><summary>Détails des erreurs ({source.errors.length})</summary><ul>{source.errors.map((error, index) => <li key={`${error.target_name}-${index}`}>{error.target_name} : {error.message}</li>)}</ul></details>}
    </article>)}
    {data?.map(device => <article key={device.id} style={{marginTop: 24}}>
      <h2>{device.name} · {device.active ? 'Appairé' : 'Révoqué'}</h2>
      <p>Dernier contact : {device.last_seen_at ? dateHeure(device.last_seen_at) : 'en attente de l’extension'}. Prochaine échéance : {device.next_at ? dateHeure(device.next_at) : 'désactivée'}.</p>
      <p>Appairage valable jusqu’au {dateHeure(device.expires_at)}.</p>
      {canAdmin && device.active && <><button disabled={busy} onClick={() => action(`devices/${device.id}/test`)}>Tester les pages de contrôle</button> <button disabled={busy} onClick={() => action(`devices/${device.id}/retry-products`)}>Reprendre les erreurs techniques</button> <button disabled={busy} onClick={() => {if (window.confirm('Révoquer ce Chrome et désactiver ses cibles ?')) void action(`devices/${device.id}/revoke`)}}>Révoquer</button></>}
      <ul>{device.targets.map(target => <li key={target.target_id}>{target.name} : {target.status || 'aucune capture'}{!target.enabled && ' · désactivée'} {target.error && `— ${target.error}`} {target.last_run_id && <button onClick={() => onOuvrirRun(target.last_run_id!)}>Voir la capture</button>}</li>)}</ul>
    </article>)}
  </section>
}
