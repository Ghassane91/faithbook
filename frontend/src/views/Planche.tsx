import { api } from '../api'
import { aujourdhui, delai, duree, heure, resumeErreur, STATUS_LABEL, useData } from '../lib'
import type { RunSummary } from '../types'

interface Props {
  onOuvrirRun: (id: number) => void
  onAllerCibles: () => void
}

/**
 * La planche contact du jour : chaque exécution occupe un cadre.
 * Un échec occupe le même cadre, mais vide — les trous se voient.
 */
export function Planche({ onOuvrirRun, onAllerCibles }: Props) {
  const jour = aujourdhui()
  const { data, erreur, chargement } = useData(
    async () => {
      const [runs, cibles] = await Promise.all([
        api.runs({ capture_date: jour, limit: 200 }),
        api.targets(),
      ])
      return { runs: runs.items, cibles }
    },
    [jour],
    15000,
  )

  if (chargement) return <p className="mono">Chargement…</p>
  if (erreur) return <div className="notice error">{erreur}</div>
  if (!data) return null

  const { runs, cibles } = data
  const nom = (id: number) => cibles.find((c) => c.id === id)?.name ?? `cible ${id}`

  const reussies = runs.filter((r) => r.status === 'success')
  const echouees = runs.filter((r) => r.status === 'failed')
  const actives = cibles.filter((c) => c.enabled)
  const prochaine = actives
    .map((c) => c.next_run_at)
    .filter((d): d is string => Boolean(d))
    .sort()[0]

  // Les cibles actives qui n'ont encore rien produit aujourd'hui : cadres à venir.
  const enAttente = actives.filter((c) => !runs.some((r) => r.target_id === c.id))

  const affichees = [...runs].sort((a, b) => a.started_at.localeCompare(b.started_at))

  return (
    <>
      <div className="page-head">
        <div>
          <span className="eyebrow">
            Planche du{' '}
            {new Date().toLocaleDateString('fr-FR', {
              weekday: 'long',
              day: 'numeric',
              month: 'long',
            })}
          </span>
          <h1>Captures du jour</h1>
        </div>
      </div>

      <div className="ribbon">
        <div className="ribbon-cell">
          <span className="eyebrow">Réussies</span>
          <b>{reussies.length}</b>
        </div>
        <div className={`ribbon-cell ${echouees.length ? 'alert' : ''}`}>
          <span className="eyebrow">En échec</span>
          <b>{echouees.length}</b>
        </div>
        <div className="ribbon-cell">
          <span className="eyebrow">Cibles actives</span>
          <b>{actives.length}</b>
        </div>
        <div className="ribbon-cell">
          <span className="eyebrow">Prochaine</span>
          <b style={{ fontSize: 16, paddingTop: 5 }}>{delai(prochaine ?? null)}</b>
        </div>
      </div>

      {echouees.length > 0 && (
        <div className="notice error">
          {echouees.length === 1
            ? '1 capture a échoué aujourd’hui.'
            : `${echouees.length} captures ont échoué aujourd’hui.`}{' '}
          Ouvrez le cadre concerné pour lire le journal.
        </div>
      )}

      {affichees.length === 0 && enAttente.length === 0 && (
        <div className="empty">
          <h3>Aucune cible pour l’instant</h3>
          <p>
            Ajoutez une page et une heure : la première capture partira au prochain créneau, ou tout
            de suite si vous la lancez à la main.
          </p>
          <button className="btn" onClick={onAllerCibles}>
            Ajouter une cible
          </button>
        </div>
      )}

      <div className="sheet">
        {affichees.map((run, i) => (
          <Cadre
            key={run.id}
            run={run}
            nom={nom(run.target_id)}
            rang={i}
            onClick={() => onOuvrirRun(run.id)}
          />
        ))}

        {enAttente.map((c) => (
          <div key={`att-${c.id}`} className="frame" style={{ borderStyle: 'dashed', cursor: 'default' }}>
            <div className="frame-window">
              <div className="frame-empty" style={{ background: 'none' }}>
                <span className="sign" style={{ color: 'var(--ink-faint)' }}>
                  ○
                </span>
                <span className="why">Prévue {delai(c.next_run_at)}</span>
              </div>
            </div>
            <div className="frame-gutter">
              <span className="frame-time" style={{ color: 'var(--ink-faint)' }}>
                {c.run_time ?? c.cron_expression ?? '—'}
              </span>
              <span className="tag skipped">à venir</span>
            </div>
            <div className="frame-name">{c.name}</div>
          </div>
        ))}
      </div>
    </>
  )
}

function Cadre({
  run,
  nom,
  rang,
  onClick,
}: {
  run: RunSummary
  nom: string
  rang: number
  onClick: () => void
}) {
  const aUneImage = run.status === 'success'
  const raison =
    run.status === 'failed'
      ? resumeErreur(run.error_message)
      : run.status === 'skipped'
        ? run.skipped_reason
        : null

  return (
    <button
      className="frame"
      onClick={onClick}
      style={{ animationDelay: `${Math.min(rang * 45, 400)}ms` }}
      aria-label={`${nom} — ${STATUS_LABEL[run.status]}`}
    >
      <div className="frame-window">
        {aUneImage && run.changed && (
          <span className="frame-changed" title={`Page modifiée : ${Math.round((run.change_ratio ?? 0) * 100)} % de changement`}>
            ● modifiée
          </span>
        )}
        {aUneImage ? (
          <>
            <img src={api.thumbnailUrl(run.id)} alt={`Capture complète de ${nom}`} loading="lazy" decoding="async" />
            <span className="frame-scroll-hint">aperçu déroulant</span>
          </>
        ) : (
          <div className="frame-empty">
            <span className="sign">{run.status === 'failed' ? '✕' : '–'}</span>
            <span className="why">
              {raison ?? (run.status === 'running' ? 'Capture en cours…' : 'En attente')}
            </span>
          </div>
        )}
      </div>
      <div className="frame-gutter">
        <span className="frame-time">{heure(run.started_at)}</span>
        <span className={`tag ${run.status}`}>{STATUS_LABEL[run.status]}</span>
      </div>
      <div className="frame-name">
        {nom}
        {run.duration_ms != null && (
          <span className="mono" style={{ color: 'var(--ink-faint)', fontSize: 11 }}>
            {' '}
            · {duree(run.duration_ms)}
          </span>
        )}
      </div>
    </button>
  )
}
