import { useEffect, useState } from 'react'
import { request, selectedOrganizationId } from '../api'
import './analyse.css'

type Item = {
  image: number; name: string; brand: string | null; reference: string | null
  price: string | null; currency: string | null; tax: string | null; pack: number | null
  availability: string | null; evidence: string; zone: string; needs_review: boolean
}
type Analysis = {
  id: string; created_at: string; question: string; source: string; status: string
  error: string | null; archive_status: string
  images?: {image: number; file: string}[]
  result?: {summary: string; items: Item[]; limitations: string[]}
  archive: {folder_id?: string; error?: string; files?: Record<string, unknown>}
}
type Config = {configured: boolean; drive_configured: boolean; provider: string; model: string}
type Change = {kind: string; brand: string; reference: string; before?: string; after?: string; delta?: string; currency?: string}
const labels: Record<string, string> = {
  price: 'Prix modifié', availability: 'Disponibilité modifiée', ambiguous: 'Référence ambiguë',
  not_observed: 'Non observé dans la nouvelle capture', newly_observed: 'Nouvellement observé',
  not_comparable: 'Prix non comparable : vérifier devise, taxe, lot ou lisibilité',
}
const states: Record<string, string> = {
  local: 'Conservé dans FaithBook', uploaded: 'Archivé dans Google Drive',
  failed: 'Envoi Drive à reprendre', uploading: 'Envoi Drive en cours',
}
export function Analyse({canEdit}: {canEdit: boolean}) {
  const [config, setConfig] = useState<Config | null>(null)
  const [history, setHistory] = useState<Analysis[]>([])
  const [current, setCurrent] = useState<Analysis | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [previews, setPreviews] = useState<string[]>([])
  const [question, setQuestion] = useState('Quelles caméras sont visibles et quels sont leurs prix ?')
  const [source, setSource] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [changes, setChanges] = useState<Change[] | null>(null)
  const [before, setBefore] = useState('')
  const [autoArchive, setAutoArchive] = useState(true)
  async function refresh() {
    const [c, h] = await Promise.all([request<Config>('/visual/config'), request<Analysis[]>('/visual')])
    setConfig(c); setHistory(h)
  }
  useEffect(() => { refresh().catch(e => setError(e.message)) }, [])
  useEffect(() => {
    const urls = files.map(f => URL.createObjectURL(f)); setPreviews(urls)
    return () => urls.forEach(url => URL.revokeObjectURL(url))
  }, [files])
  async function archive(a: Analysis) {
    const updated = await request<Analysis>('/visual/' + a.id + '/archive', {method: 'POST'})
    setCurrent(updated); await refresh()
  }
  async function analyze() {
    setError(''); setBusy(true); setChanges(null); setBefore('')
    try {
      if (!source.trim() || !question.trim() || !files.length || files.length > 4)
        throw new Error('Ajoutez une source, une question et entre 1 et 4 images.')
      const body = new FormData()
      body.append('source', source); body.append('question', question)
      files.forEach(file => body.append('images', file))
      const a = await request<Analysis>('/visual', {method: 'POST', body})
      setCurrent(a)
      if (a.status === 'success' && autoArchive && config?.drive_configured) await archive(a)
      else await refresh()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Impossible de terminer. Consultez l’historique avant de relancer.')
      await refresh().catch(() => {})
    } finally { setBusy(false) }
  }
  async function act(action: () => Promise<void>) {
    setError(''); setBusy(true)
    try { await action() } catch (e) { setError(e instanceof Error ? e.message : 'Opération impossible') }
    finally { setBusy(false) }
  }
  async function download(format: string) {
    if (!current) return
    const org = selectedOrganizationId()
    const res = await fetch('/api/visual/' + current.id + '/export?format=' + format,
      {headers: org ? {'X-Organization-ID': String(org)} : {}})
    if (!res.ok) throw new Error('Téléchargement impossible. Vérifiez votre connexion.')
    const url = URL.createObjectURL(await res.blob())
    const a = document.createElement('a'); a.href = url; a.download = 'analyse-' + current.id + '.' + format
    a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000)
  }
  return <section className="visual-workspace">
    <header><p className="visual-eyebrow">FAITHBOOK / INTELLIGENCE VISUELLE</p>
      <h1>Vos captures deviennent des informations.</h1>
      <p>Posez une question, retrouvez les preuves et comparez ce qui a changé.</p></header>
    {error && <p role="alert" className="visual-error">{error}</p>}
    {config && !config.configured && <p role="status" className="visual-notice">
      La connexion à un modèle capable de lire les images reste à configurer sur le serveur.
      L’historique et les exports déjà disponibles restent accessibles.</p>}
    <div className="visual-grid">
      <section className="visual-card">
        <h2>1. Choisir les captures</h2>
        <label className="visual-upload">PNG, JPEG ou WebP · 4 images maximum · 6 Mo par image
          <input aria-label="Captures à analyser" type="file" multiple accept="image/png,image/jpeg,image/webp"
            disabled={busy || !canEdit} onChange={e => setFiles(Array.from(e.target.files || []))} />
        </label>
        <p>Pour une longue page, importez des zones recadrées de 3000 pixels maximum.</p>
        <div className="visual-previews">{previews.map((url, i) => <figure key={url}>
          <img src={url} alt={'Capture ' + (i + 1)} /><figcaption>Image {i + 1} · {files[i]?.name}</figcaption>
        </figure>)}</div>
        <label>Source suivie (même nom pour les comparaisons)
          <input maxLength={300} value={source} placeholder="Ex. Catalogue fournisseur — caméras"
            onChange={e => setSource(e.target.value)} disabled={busy} /></label>
        <label>2. Votre question
          <textarea rows={4} maxLength={2000} value={question} onChange={e => setQuestion(e.target.value)} disabled={busy} /></label>
        <label className="visual-check"><input type="checkbox" checked={autoArchive}
          onChange={e => setAutoArchive(e.target.checked)} disabled={busy} /> Archiver les résultats et les images dans Drive</label>
        {!config?.drive_configured && <p>Drive non configuré : les analyses resteront conservées dans FaithBook.</p>}
        <p>Les images seront transmises au modèle configuré : {config?.provider || '…'}. Vérifiez leur contenu avant l’envoi.</p>
        <button className="visual-primary" disabled={busy || !canEdit || !config?.configured || !files.length}
          onClick={analyze}>{busy ? 'Traitement en cours…' : 'Analyser les captures'}</button>
      </section>
      <aside className="visual-card"><h2>Analyses récentes</h2>
        <button disabled={busy} onClick={() => act(refresh)}>Actualiser</button>
        {!history.length && <p>Votre première analyse apparaîtra ici.</p>}
        <div className="visual-history">{history.map(a => <button key={a.id} disabled={busy}
          aria-pressed={a.id === current?.id}
          onClick={() => act(async () => {
            setCurrent(await request<Analysis>('/visual/' + a.id)); setChanges(null); setBefore('')
          })}><strong>{a.source}</strong><span>{new Date(a.created_at).toLocaleString('fr-FR')}</span>
          <span>{a.status === 'success' ? states[a.archive_status] : a.status === 'running' ? 'Analyse en cours' : 'Analyse échouée'}</span></button>)}</div>
      </aside>
    </div>
    {current && <section className="visual-card visual-result">
      <p className="visual-eyebrow">3. RÉSULTATS / {current.source}</p>
      <h2>{current.question}</h2>
      {current.error && <p role="alert">{current.error}</p>}
      {current.result && <>
        <p className="visual-summary">{current.result.summary}</p>
        <p>Résultats produits par l’IA : contrôlez les extraits avant toute décision.</p>
        {current.result.limitations.map((line, i) => <p className="visual-notice" key={i}>{line}</p>)}
        <div className="visual-table"><table><thead><tr><th>Produit</th><th>Prix</th><th>Conditions</th><th>Preuve</th></tr></thead>
          <tbody>{current.result.items.map((item, i) => <tr key={i}>
            <td><strong>{item.name}</strong><br />{item.brand} {item.reference}<br />{item.availability}</td>
            <td>{item.price ?? 'Non lisible / absent'} {item.currency}<br />{item.needs_review ? 'À vérifier' : ''}</td>
            <td>{item.tax ?? 'Taxe inconnue'} · {item.pack ? 'Lot de ' + item.pack : 'Lot inconnu'}</td>
            <td>Image {item.image} · {item.zone}<blockquote>{item.evidence}</blockquote>
              <a target="_blank" rel="noreferrer" href={'/api/visual/' + current.id + '/image/' + item.image}>Voir la capture</a></td>
          </tr>)}</tbody></table></div>
        {!current.result.items.length && <p>Aucun produit identifiable. Consultez la synthèse et les limites.</p>}
        <div className="visual-actions">{['csv', 'json', 'md'].map(format =>
          <button key={format} disabled={busy} onClick={() => act(() => download(format))}>Exporter {format.toUpperCase()}</button>)}
          <button disabled={busy || !canEdit || !config?.drive_configured || current.archive_status === 'uploaded'}
            onClick={() => act(() => archive(current))}>Archiver / reprendre Drive</button></div>
        <p role="status">{states[current.archive_status]}{current.archive.error && ' — ' + current.archive.error}</p>
        {current.archive_status === 'uploaded' && current.archive.folder_id &&
          <a target="_blank" rel="noreferrer" href={'https://drive.google.com/drive/folders/' + encodeURIComponent(current.archive.folder_id)}>Ouvrir le dossier Drive</a>}
        <h3>Comparer avec une analyse précédente</h3>
        <select aria-label="Analyse précédente" value={before} disabled={busy}
          onChange={e => {setBefore(e.target.value); setChanges(null)}}>
          <option value="">Choisir la référence</option>
          {history.filter(a => a.source === current.source && a.created_at < current.created_at && a.status === 'success')
            .map(a => <option key={a.id} value={a.id}>{new Date(a.created_at).toLocaleString('fr-FR')}</option>)}
        </select>
        <button disabled={busy || !before} onClick={() => act(async () => {
          const result = await request<{changes: Change[]}>('/visual/' + current.id + '/compare/' + before)
          setChanges(result.changes)
        })}>Comparer</button>
        {changes && <div aria-live="polite">
          <p>Une absence signifie « non observé », pas « supprimé ». Seules les références identifiables sont rapprochées.</p>
          {!changes.length && <p>Aucun changement comparable identifié. Cela ne prouve pas que les captures sont identiques.</p>}
          {changes.map((change, i) => <p key={i}><strong>{change.brand} {change.reference}</strong> — {labels[change.kind]}
            {change.before !== undefined && ' : ' + change.before + ' → ' + change.after}
            {change.delta && ' (écart : ' + change.delta + ' ' + change.currency + ')'}</p>)}
        </div>}
      </>}
      <details><summary>Captures sources</summary>{current.images?.map(image =>
        <p key={image.image}><a target="_blank" rel="noreferrer"
          href={'/api/visual/' + current.id + '/image/' + image.image}>Image {image.image}</a></p>)}</details>
      {canEdit && <button disabled={busy || current.status === 'running' || current.archive_status === 'uploading'}
        onClick={() => {
          if (window.confirm('Supprimer cette analyse et ses images locales ? Les fichiers déjà archivés dans Drive sont conservés.'))
            act(async () => {await request('/visual/' + current.id, {method: 'DELETE'}); setCurrent(null); await refresh()})
        }}>Supprimer de FaithBook</button>}
    </section>}
  </section>
}
