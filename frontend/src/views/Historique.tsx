import { useState } from 'react'
import { api, request } from '../api'
import { dateHeure, duree, resumeErreur, STATUS_LABEL, useData } from '../lib'
import type { RunStatus } from '../types'

interface Props {
  onOuvrirRun: (id: number) => void
}

const PAGE = 25
type Reprises = Record<string, { run_id: number; capture_date: string }>

export function Historique({ onOuvrirRun }: Props) {
  const [etat, setEtat] = useState<RunStatus | ''>('')
  const [jour, setJour] = useState('')
  const [page, setPage] = useState(0)

  const { data, erreur, chargement } = useData(
    () =>
      api.runs({
        status: etat || undefined,
        capture_date: jour || undefined,
        limit: PAGE,
        offset: page * PAGE,
      }),
    [etat, jour, page],
    20000,
  )

  const { data: cibles } = useData(() => api.targets(), [])
  const runIds = data?.items.map((r) => r.id).join(',') ?? ''
  const { data: reprises, erreur: erreurReprises } = useData(
    () => runIds ? request<Reprises>(`/huntx/recoveries?run_ids=${runIds}`) : Promise.resolve<Reprises>({}),
    [runIds],
    20000,
  )
  const nom = (id: number) => cibles?.find((c) => c.id === id)?.name ?? `cible ${id}`

  const total = data?.total ?? 0
  const dernierePage = Math.max(0, Math.ceil(total / PAGE) - 1)

  return (
    <>
      <div className="page-head">
        <div>
          <span className="eyebrow">Toutes les exécutions</span>
          <h1>Historique</h1>
          <p>Chaque tentative est conservée, y compris celles qui ont échoué ou été ignorées.</p>
          <p>Une tentative marquée « récupérée » possède déjà une capture réussie de la même fiche dans la même campagne. Ouvrez sa reprise pour voir l’image.</p>
        </div>
      </div>

      <div className="filters">
        <div className="field">
          <label htmlFor="f-etat">État</label>
          <select
            id="f-etat"
            value={etat}
            onChange={(e) => {
              setEtat(e.target.value as RunStatus | '')
              setPage(0)
            }}
          >
            <option value="">tous</option>
            <option value="success">réussies</option>
            <option value="failed">échouées</option>
            <option value="skipped">ignorées</option>
            <option value="running">en cours</option>
            <option value="pending">en attente</option>
          </select>
        </div>
        <div className="field">
          <label htmlFor="f-jour">Jour</label>
          <input
            id="f-jour"
            type="date"
            value={jour}
            onChange={(e) => {
              setJour(e.target.value)
              setPage(0)
            }}
          />
        </div>
        {(etat || jour) && (
          <button
            className="btn ghost sm"
            onClick={() => {
              setEtat('')
              setJour('')
              setPage(0)
            }}
          >
            Tout afficher
          </button>
        )}
        <span className="mono" style={{ marginLeft: 'auto', color: 'var(--ink-faint)', fontSize: 12 }}>
          {total} exécution{total > 1 ? 's' : ''}
        </span>
      </div>

      {erreur && <div className="notice error">{erreur}</div>}
      {erreurReprises && <div className="notice error">Le suivi des reprises est indisponible : {erreurReprises}</div>}
      {chargement && <p className="mono">Chargement…</p>}

      {data && data.items.length === 0 && (
        <div className="empty">
          <h3>Rien à afficher</h3>
          <p>
            {etat || jour
              ? 'Aucune exécution ne correspond à ce filtre.'
              : 'Les exécutions apparaîtront ici dès la première capture.'}
          </p>
        </div>
      )}

      {data && data.items.length > 0 && (
        <>
          <div className="panel">
            <table>
              <thead>
                <tr>
                  <th>nº</th>
                  <th>Cible</th>
                  <th>Démarrée</th>
                  <th>Durée</th>
                  <th>Essais</th>
                  <th>État</th>
                  <th>Détail</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.id} className="clickable" onClick={() => onOuvrirRun(r.id)}>
                    <td className="mono" style={{ color: 'var(--ink-faint)' }}>
                      {r.id}
                    </td>
                    <td className="cell-title">{nom(r.target_id)}</td>
                    <td className="cell-time">{dateHeure(r.started_at)}</td>
                    <td className="cell-time">{duree(r.duration_ms)}</td>
                    <td className="mono">{r.attempts}</td>
                    <td>
                      <span className={`tag ${r.status}`}>{STATUS_LABEL[r.status]}</span>
                      {reprises?.[r.id] && <div style={{ marginTop: 4 }}><span className="tag success">récupérée</span></div>}
                      {r.changed && (
                        <div style={{ marginTop: 4 }}>
                          <span className="tag changed" title="La page a changé depuis la capture précédente">
                            modifiée {Math.round((r.change_ratio ?? 0) * 100)} %
                          </span>
                        </div>
                      )}
                      {r.trigger === 'manual' && (
                        <div className="eyebrow" style={{ marginTop: 3 }}>
                          manuel
                        </div>
                      )}
                    </td>
                    <td style={{ maxWidth: 320, fontSize: 12.5, color: 'var(--ink-soft)' }}>
                      {r.error_message ? resumeErreur(r.error_message) : (r.skipped_reason ?? '')}
                      {reprises?.[r.id] && <div style={{ marginTop: 6 }}>
                        <button className="btn ghost sm" onClick={(event) => { event.stopPropagation(); onOuvrirRun(reprises[r.id].run_id) }}>
                          Voir la capture réussie nº {reprises[r.id].run_id} du {reprises[r.id].capture_date}
                        </button>
                      </div>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {dernierePage > 0 && (
            <div className="btn-row" style={{ marginTop: 16, alignItems: 'center' }}>
              <button className="btn ghost sm" disabled={page === 0} onClick={() => setPage((p) => p - 1)}>
                Précédent
              </button>
              <span className="mono" style={{ fontSize: 12 }}>
                page {page + 1} / {dernierePage + 1}
              </span>
              <button
                className="btn ghost sm"
                disabled={page >= dernierePage}
                onClick={() => setPage((p) => p + 1)}
              >
                Suivant
              </button>
            </div>
          )}
        </>
      )}
    </>
  )
}
