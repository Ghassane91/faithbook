import { useEffect, useState } from 'react'
import { api } from '../api'
import { dateHeure, duree, poids, resumeErreur, STATUS_LABEL, useData } from '../lib'
import type { Run } from '../types'
import { Comparaison } from './Comparaison'

interface Props {
  runId: number
  canAdmin: boolean
  onClose: () => void
}

export function RunDetail({ runId, canAdmin, onClose }: Props) {
  const enCours = (r: Run | null) => r?.status === 'pending' || r?.status === 'running'
  const { data: run, erreur, recharger } = useData<Run>(() => api.run(runId), [runId], 3000)
  const [compare, setCompare] = useState(false)
  const [driveBusy, setDriveBusy] = useState(false)
  const [driveMessage, setDriveMessage] = useState<string | null>(null)
  const [lienBusy, setLienBusy] = useState(false)

  async function retryDrive() {
    setDriveBusy(true)
    setDriveMessage(null)
    try {
      const result = await api.retryDrive(runId)
      setDriveMessage(result.detail)
      recharger()
    } catch (err) {
      setDriveMessage(err instanceof Error ? err.message : 'Envoi Drive impossible')
    } finally {
      setDriveBusy(false)
    }
  }

  async function ouvrirCapture() {
    // L onglet doit etre ouvert AVANT la requete : ouvert apres un await,
    // il serait bloque comme fenetre surgissante par le navigateur.
    const onglet = window.open('', '_blank')
    setLienBusy(true)
    setDriveMessage(null)
    try {
      const { url } = await api.lienCapture(runId)
      if (!url) throw new Error('Lien indisponible pour cette execution.')
      if (onglet) onglet.location.href = url
      else window.location.href = url
    } catch (err) {
      onglet?.close()
      setDriveMessage(err instanceof Error ? err.message : 'Lien indisponible')
    } finally {
      setLienBusy(false)
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <>
    <div className="overlay" onClick={onClose} role="presentation">
      <aside
        className="drawer"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Exécution ${runId}`}
      >
        <div className="drawer-head">
          <div>
            <span className="eyebrow">Exécution nº {runId}</span>
            <h2>{run?.page_title || 'Détail de l’exécution'}</h2>
          </div>
          <button className="btn ghost sm" onClick={onClose}>
            Fermer
          </button>
        </div>

        {erreur && <div className="notice error">{erreur}</div>}
        {!run && !erreur && <p className="mono">Chargement…</p>}

        {run && (
          <>
            {run.status === 'failed' && run.error_message && (
              <div className="notice error">
                <strong>{resumeErreur(run.error_message)}</strong>
                <br />
                Échec après {run.attempts} tentative(s).
                <details style={{ marginTop: 8 }}>
                  <summary className="mono" style={{ cursor: 'pointer', fontSize: 11 }}>
                    message technique
                  </summary>
                  <pre className="mono" style={{ whiteSpace: 'pre-wrap', fontSize: 11.5, margin: '6px 0 0' }}>
                    {run.error_message}
                  </pre>
                </details>
              </div>
            )}
            {run.status === 'skipped' && run.skipped_reason && (
              <div className="notice info">{run.skipped_reason}</div>
            )}
            {enCours(run) && (
              <div className="notice info">
                <span className="spinner" /> Capture en cours — cette vue se met à jour seule.
              </div>
            )}

            <div className="section">
              <h3>Résumé</h3>
              <dl className="kv">
                <dt>état</dt>
                <dd>
                  <span className={`tag ${run.status}`}>{STATUS_LABEL[run.status]}</span>
                </dd>
                <dt>déclenchement</dt>
                <dd>{run.trigger === 'manual' ? 'manuel' : 'planifié'}</dd>
                <dt>démarrée</dt>
                <dd className="mono">{dateHeure(run.started_at)}</dd>
                <dt>durée</dt>
                <dd className="mono">{duree(run.duration_ms)}</dd>
                <dt>tentatives</dt>
                <dd className="mono">{run.attempts}</dd>
                {run.change_ratio != null && (
                  <>
                    <dt>changement</dt>
                    <dd>
                      {run.changed ? (
                        <span className="tag changed">
                          modifiée · {Math.round(run.change_ratio * 100)} %
                        </span>
                      ) : (
                        <span className="mono" style={{ color: 'var(--ink-faint)' }}>
                          inchangée ({Math.round(run.change_ratio * 100)} %)
                        </span>
                      )}
                    </dd>
                  </>
                )}
                {run.ai_summary && (
                  <>
                    <dt>résumé IA</dt>
                    <dd>{run.ai_summary}</dd>
                  </>
                )}
                {run.final_url && (
                  <>
                    <dt>url finale</dt>
                    <dd className="mono" style={{ fontSize: 12 }}>
                      {run.final_url}
                    </dd>
                  </>
                )}
                {run.screenshot_bytes != null && (
                  <>
                    <dt>poids</dt>
                    <dd className="mono">{poids(run.screenshot_bytes)}</dd>
                  </>
                )}
                {run.screenshot_path && (
                  <>
                    <dt>fichier</dt>
                    <dd className="mono" style={{ fontSize: 12 }}>
                      {run.screenshot_path}
                    </dd>
                  </>
                )}
              </dl>
            </div>

            {run.drive_status !== 'local' && (
              <div className="section">
                <h3>Google Drive</h3>
                <dl className="kv">
                  <dt>état</dt>
                  <dd>
                    <span className={`tag ${run.drive_status === 'uploaded' ? 'success' : run.drive_status === 'failed' ? 'failed' : 'running'}`}>
                      {run.drive_status === 'uploaded'
                        ? 'envoyée'
                        : run.drive_status === 'failed'
                          ? 'à reprendre'
                          : 'en attente'}
                    </span>
                  </dd>
                  <dt>tentatives</dt>
                  <dd className="mono">{run.drive_attempts}</dd>
                  {run.drive_uploaded_at && (
                    <>
                      <dt>envoyée le</dt>
                      <dd className="mono">{dateHeure(run.drive_uploaded_at)}</dd>
                    </>
                  )}
                  {run.drive_next_retry_at && run.drive_status !== 'uploaded' && (
                    <>
                      <dt>prochain essai</dt>
                      <dd className="mono">{dateHeure(run.drive_next_retry_at)}</dd>
                    </>
                  )}
                </dl>
                {run.drive_last_error && (
                  <div className="notice error" style={{ marginTop: 10 }}>
                    {run.drive_last_error}
                  </div>
                )}
                {driveMessage && <div className="notice info">{driveMessage}</div>}
                <div className="btn-row" style={{ marginTop: 10 }}>
                  {run.drive_status === 'uploaded' && (
                    <button
                      className="btn sm"
                      onClick={ouvrirCapture}
                      disabled={lienBusy}
                    >
                      {lienBusy ? <span className="spinner" /> : 'Ouvrir le fichier distant'}
                    </button>
                  )}
                  {canAdmin && run.drive_status !== 'uploaded' && (
                    <button className="btn ghost sm" onClick={retryDrive} disabled={driveBusy}>
                      {driveBusy ? <span className="spinner" /> : 'Relancer l’envoi'}
                    </button>
                  )}
                </div>
              </div>
            )}

            {run.screenshot_bytes != null && (
              <div className="section">
                <h3>Capture</h3>
                <img className="preview" src={api.screenshotUrl(run.id)} alt="Capture de la page" />
                <div className="btn-row" style={{ marginTop: 10 }}>
                  {run.previous_run_id && (
                    <button className="btn sm" onClick={() => setCompare(true)}>
                      Comparer avant / après
                    </button>
                  )}
                  <a className="btn ghost sm" href={api.screenshotUrl(run.id)} download>
                    Télécharger le PNG
                  </a>
                  <a
                    className="btn ghost sm"
                    href={api.screenshotUrl(run.id)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Ouvrir en pleine taille
                  </a>
                </div>
              </div>
            )}

            <div className="section">
              <h3>Journal — {run.logs.length} étape(s)</h3>
              <div className="log">
                {run.logs.map((l) => (
                  <div key={l.id} className={`log-line ${l.level === 'ERROR' ? 'error' : ''}`}>
                    <span className="t">
                      {new Date(l.ts).toLocaleTimeString('fr-FR', {
                        hour: '2-digit',
                        minute: '2-digit',
                        second: '2-digit',
                      })}
                    </span>
                    <span className="s">{l.step}</span>
                    <span className="m">{l.message}</span>
                  </div>
                ))}
              </div>
            </div>
          </>
        )}
      </aside>
    </div>
    {compare && run?.previous_run_id != null && (
      <Comparaison
        beforeId={run.previous_run_id}
        afterId={run.id}
        changePct={run.change_ratio != null ? Math.round(run.change_ratio * 100) : null}
        onClose={() => setCompare(false)}
      />
    )}
    </>
  )
}
