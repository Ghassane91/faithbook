import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import type { HuntxArchivePage, HuntxArtifact, HuntxRow } from '../types'
import { CaptureIcon } from './HuntxOverview'

const PAGE_SIZE = 20
const message = (error: unknown) => error instanceof Error ? error.message : 'Archive indisponible.'

function displayDay(value: string) {
  return new Intl.DateTimeFormat('fr-FR', {
    day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC',
  }).format(new Date(`${value}T12:00:00Z`))
}

function driveUrl(value: string | null) {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && url.hostname === 'drive.google.com' ? url.href : null
  } catch { return null }
}

function ArtifactImage({ organizationId, artifact, full = false }: {
  organizationId: number; artifact: HuntxArtifact; full?: boolean
}) {
  const [url, setUrl] = useState('')
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    let objectUrl = ''
    setUrl('')
    setError('')
    api.huntxFile(organizationId, artifact.id, !full, controller.signal)
      .then(blob => {
        if (controller.signal.aborted) return
        objectUrl = URL.createObjectURL(blob)
        setUrl(objectUrl)
      })
      .catch(error => { if (!controller.signal.aborted) setError(message(error)) })
    return () => {
      controller.abort()
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [organizationId, artifact.id, full])
  return url ? (
    <img src={url} alt={artifact.marketplace ? `Capture ${artifact.marketplace}` : artifact.filename} decoding="async" />
  ) : (
    <div className="hxa-image-state"><CaptureIcon name="capture" />
      <p role={error ? 'alert' : 'status'}>{error || 'Chargement de l’aperçu…'}</p>
    </div>
  )
}

function FileActions({ organizationId, artifact }: { organizationId: number; artifact: HuntxArtifact }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const controllerRef = useRef<AbortController | null>(null)
  const href = driveUrl(artifact.drive_url)
  const folderHref = driveUrl(artifact.folder_url)
  useEffect(() => () => controllerRef.current?.abort(), [])
  async function download() {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setBusy(true)
    setError('')
    try {
      const blob = await api.huntxDownload(organizationId, artifact.id, controller.signal)
      if (controller.signal.aborted) return
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = artifact.filename.replace(/[\\/\0]/g, '_')
      document.body.appendChild(link)
      link.click()
      link.remove()
      setTimeout(() => URL.revokeObjectURL(url), 1000)
    } catch (error) {
      if (!controller.signal.aborted) setError(message(error))
    } finally {
      if (!controller.signal.aborted) setBusy(false)
    }
  }
  return <div className="hxa-file-actions">
    <div>
      <button className="btn ghost sm" onClick={download} disabled={busy}>
        {busy ? 'Téléchargement…' : 'Télécharger le fichier'}
      </button>
      {href ? <a href={href} target="_blank" rel="noopener noreferrer">Ouvrir sur Drive <CaptureIcon name="external" /></a>
        : <span>Drive : {artifact.drive_status === 'pending' ? 'envoi en attente'
          : artifact.drive_status === 'failed' ? 'envoi en échec' : 'copie indisponible'}</span>}
      {folderHref && <a href={folderHref} target="_blank" rel="noopener noreferrer">Dossier Drive <CaptureIcon name="folder" /></a>}
    </div>
    {error && <p className="notice error" role="alert">{error}</p>}
  </div>
}

function RowCard({ row, organizationId, onOpen }: {
  row: HuntxRow; organizationId: number; onOpen: () => void
}) {
  const images = row.artifacts.filter(artifact => artifact.image)
  const preview = images.find(artifact => artifact.kind === 'row') ?? images[0]
  return <article className="hxa-card">
    <button onClick={onOpen} aria-label={`Voir ${row.row_label} du ${row.capture_date}`}>
      <div className="hxa-card-preview">
        {preview ? <ArtifactImage organizationId={organizationId} artifact={preview} />
          : <div className="hxa-image-state"><CaptureIcon name="capture" /><p>Aucune image pour cette ligne</p></div>}
      </div>
      <div className="hxa-card-caption">
        <span className="hx-overline">{displayDay(row.capture_date)}</span>
        <h2>{row.row_label}</h2>
        <p>{images.length} image{images.length > 1 ? 's' : ''} · {row.artifacts.length} fichier{row.artifacts.length > 1 ? 's' : ''}</p>
        <span className="hxa-card-open">Voir la ligne et les marchands <CaptureIcon name="arrow" /></span>
      </div>
    </button>
  </article>
}

function RowDetail({ row, organizationId, onClose }: {
  row: HuntxRow; organizationId: number; onClose: () => void
}) {
  const dialogRef = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = dialogRef.current
    const previousFocus = document.activeElement
    const overflow = document.body.style.overflow
    dialog?.showModal()
    document.body.style.overflow = 'hidden'
    return () => {
      dialog?.close()
      document.body.style.overflow = overflow
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus()
    }
  }, [])
  return <dialog ref={dialogRef} className="hxa-dialog" aria-labelledby="hxa-row-title"
    aria-describedby="hxa-row-date" onCancel={event => { event.preventDefault(); onClose() }}
    onClick={event => { if (event.target === event.currentTarget) onClose() }}>
    <header>
      <div><span className="hx-overline">LIGNE HUNTX</span><h2 id="hxa-row-title">{row.row_label}</h2>
        <p id="hxa-row-date">Prise du {displayDay(row.capture_date)} · images et fichiers archivés</p></div>
      <button className="btn ghost sm" onClick={onClose} autoFocus>Fermer</button>
    </header>
    <div className="hxa-row-files">
      {row.artifacts.map(artifact => <article className="hxa-file" key={artifact.id}>
        <h3>{artifact.marketplace ?? (artifact.kind === 'row' ? 'Ligne du tableau' : 'Données de la ligne')}</h3>
        {artifact.image && <div className="hxa-full-image"><ArtifactImage organizationId={organizationId} artifact={artifact} full /></div>}
        <p className="hxa-filename">{artifact.filename}</p>
        {artifact.error && <p className="notice error">{artifact.error}</p>}
        <FileActions organizationId={organizationId} artifact={artifact} />
      </article>)}
    </div>
  </dialog>
}

export function HuntxArchive({ organizationId }: { organizationId?: number }) {
  const [date, setDate] = useState('')
  const [search, setSearch] = useState('')
  const [query, setQuery] = useState('')
  const [offset, setOffset] = useState(0)
  const [revision, setRevision] = useState(0)
  const [dates, setDates] = useState<HuntxArchivePage['dates']>([])
  const [data, setData] = useState<HuntxArchivePage | null>(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [selected, setSelected] = useState<HuntxRow | null>(null)

  useEffect(() => {
    const timer = setTimeout(() => { setQuery(search.trim()); setOffset(0) }, 250)
    return () => clearTimeout(timer)
  }, [search])

  useEffect(() => {
    if (!organizationId) return
    const controller = new AbortController()
    setData(null)
    setError('')
    setLoading(true)
    api.huntxArchive(organizationId, {
      capture_date: date || undefined, query, limit: PAGE_SIZE, offset,
    }, controller.signal).then(page => {
      if (controller.signal.aborted) return
      setData(page)
      setDates(page.dates)
      setLoading(false)
    }).catch(error => {
      if (controller.signal.aborted) return
      setError(message(error))
      setLoading(false)
    })
    return () => controller.abort()
  }, [organizationId, date, query, offset, revision])

  return <section className="hx-dashboard hxa-archive" aria-labelledby="hxa-title">
    <div className="hx-heading"><div><p className="hx-kicker"><span /> VOS PREUVES, PAR DATE ET PAR LIGNE</p>
      <h1 id="hxa-title">Vos captures <em>HuntX.</em></h1>
      <p>Retrouvez les aperçus des lignes, les pages marchands et leurs copies Drive.</p></div>
      <button className="hx-button secondary" disabled={loading} onClick={() => setRevision(value => value + 1)}>
        <CaptureIcon name="refresh" />Actualiser
      </button>
    </div>
    <div className="hxa-toolbar hx-panel">
      <label>Date de prise<select value={date} onChange={event => { setDate(event.target.value); setOffset(0) }}>
        <option value="">Toutes les dates</option>
        {dates.map(item => <option key={item.date} value={item.date}>{displayDay(item.date)} · {item.files} fichiers</option>)}
      </select></label>
      <label>Rechercher une ligne ou un marchand<input type="search" value={search}
        onChange={event => setSearch(event.target.value)} placeholder="Browning, Walmart, Amazon…" /></label>
    </div>
    {loading ? <p className="hx-empty" role="status">Chargement des archives HuntX…</p>
      : error ? <div className="notice error" role="alert">{error} <button className="linklike" onClick={() => setRevision(value => value + 1)}>Réessayer</button></div>
      : data && <>
        <p className="hxa-count">{data.total} ligne{data.total > 1 ? 's' : ''} archivée{data.total > 1 ? 's' : ''}{!date && ' · toutes les dates'}</p>
        {data.items.length ? <div className="hxa-grid">{data.items.map(row => <RowCard
          key={`${row.capture_date}:${row.row_key}`} row={row} organizationId={organizationId!}
          onOpen={() => setSelected(row)} />)}</div>
          : <div className="empty"><h3>Aucune ligne pour ces filtres</h3><p>Les archives HuntX appartiennent à leur espace de travail. Vérifiez l’espace actif et les filtres.</p></div>}
        <nav className="hxa-pagination" aria-label="Pages des archives HuntX">
          <button className="btn ghost sm" disabled={offset === 0} onClick={() => setOffset(value => Math.max(0, value - PAGE_SIZE))}>Précédent</button>
          <span>{data.total ? `${offset + 1}–${offset + data.items.length} sur ${data.total}` : '0 ligne'}</span>
          <button className="btn ghost sm" disabled={offset + PAGE_SIZE >= data.total} onClick={() => setOffset(value => value + PAGE_SIZE)}>Suivant</button>
        </nav>
        {data.exports.length > 0 && <details className="hxa-exports hx-panel"><summary>Exports du tableau ({data.exports.length})</summary>
          {data.exports.map(artifact => <article key={artifact.id}><p>{displayDay(artifact.capture_date)} · {artifact.filename}</p>
            <FileActions organizationId={organizationId!} artifact={artifact} /></article>)}
        </details>}
      </>}
    {selected && organizationId && <RowDetail row={selected} organizationId={organizationId} onClose={() => setSelected(null)} />}
  </section>
}
