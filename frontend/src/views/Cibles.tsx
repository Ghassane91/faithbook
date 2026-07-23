import { useState } from 'react'
import { api } from '../api'
import { StatsCible } from '../components/StatsCible'
import { TargetForm } from '../components/TargetForm'
import { dateHeure, delai, STATUS_LABEL, useData } from '../lib'
import type { Target } from '../types'

interface Props {
  onOuvrirRun: (id: number) => void
}

export function Cibles({ onOuvrirRun }: Props) {
  const { data: cibles, erreur, chargement, recharger } = useData(() => api.targets(), [], 20000)
  const [edition, setEdition] = useState<Target | null | undefined>(undefined)
  const [stats, setStats] = useState<Target | null>(null)
  const [message, setMessage] = useState<{ texte: string; type: 'info' | 'error' } | null>(null)
  const [occupe, setOccupe] = useState<number | null>(null)

  async function lancer(cible: Target, force: boolean) {
    setOccupe(cible.id)
    setMessage(null)
    try {
      const r = await api.runNow(cible.id, force)
      setMessage({
        texte:
          r.status === 'skipped'
            ? `${cible.name} : ${r.detail}`
            : `${cible.name} : capture lancée. Suivez-la sur la planche.`,
        type: r.status === 'skipped' ? 'info' : 'info',
      })
      setTimeout(recharger, 1500)
    } catch (e) {
      setMessage({ texte: e instanceof Error ? e.message : 'Lancement impossible', type: 'error' })
    } finally {
      setOccupe(null)
    }
  }

  async function basculer(cible: Target) {
    try {
      await api.updateTarget(cible.id, { enabled: !cible.enabled })
      recharger()
    } catch (e) {
      setMessage({ texte: e instanceof Error ? e.message : 'Modification impossible', type: 'error' })
    }
  }


  return (
    <>
      <div className="page-head">
        <div>
          <span className="eyebrow">Pages suivies</span>
          <h1>Cibles</h1>
          <p>Une cible, c’est une adresse et une heure. Le reste n’est là que pour les cas tordus.</p>
        </div>
        <button className="btn" onClick={() => setEdition(null)}>
          Ajouter une cible
        </button>
      </div>

      {message && <div className={`notice ${message.type}`}>{message.texte}</div>}
      {erreur && <div className="notice error">{erreur}</div>}
      {chargement && <p className="mono">Chargement…</p>}

      {cibles && cibles.length === 0 && (
        <div className="empty">
          <h3>Aucune cible enregistrée</h3>
          <p>
            Ajoutez la première page à surveiller. Vous pourrez lancer une capture d’essai
            immédiatement, sans attendre l’heure prévue.
          </p>
          <button className="btn" onClick={() => setEdition(null)}>
            Ajouter une cible
          </button>
        </div>
      )}

      {cibles && cibles.length > 0 && (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>Cible</th>
                <th>Cadence</th>
                <th>Prochaine</th>
                <th>Dernière</th>
                <th>Session</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {cibles.map((c) => (
                <tr key={c.id}>
                  <td>
                    <div className="cell-title">{c.name}</div>
                    <div className="cell-url">{c.url}</div>
                  </td>
                  <td>
                    <span className="mono">{c.run_time ?? c.cron_expression ?? '—'}</span>
                    <div style={{ marginTop: 4 }}>
                      <span className={`tag ${c.enabled ? 'on' : 'off'}`}>
                        {c.enabled ? 'active' : 'en pause'}
                      </span>
                    </div>
                  </td>
                  <td className="cell-time">{c.enabled ? delai(c.next_run_at) : '—'}</td>
                  <td>
                    {c.last_run ? (
                      <button
                        className="btn ghost sm"
                        onClick={() => onOuvrirRun(c.last_run!.id)}
                        title={dateHeure(c.last_run.started_at)}
                      >
                        <span className={`tag ${c.last_run.status}`}>
                          {STATUS_LABEL[c.last_run.status]}
                        </span>
                      </button>
                    ) : (
                      <span className="mono" style={{ color: 'var(--ink-faint)' }}>
                        jamais
                      </span>
                    )}
                  </td>
                  <td>
                    <Session cible={c} />
                  </td>
                  <td>
                    <div className="btn-row">
                      <button
                        className="btn sm"
                        disabled={occupe === c.id}
                        onClick={() => lancer(c, false)}
                      >
                        {occupe === c.id ? <span className="spinner" /> : 'Capturer'}
                      </button>
                      <button className="btn ghost sm" onClick={() => lancer(c, true)} title="Ignorer la déduplication">
                        Forcer
                      </button>
                      <button className="btn ghost sm" onClick={() => setStats(c)} title="Évolution des abonnés / mentions J’aime">
                        Stats
                      </button>
                      <button className="btn ghost sm" onClick={() => setEdition(c)}>
                        Modifier
                      </button>
                      <button className="btn ghost sm" onClick={() => basculer(c)}>
                        {c.enabled ? 'Pause' : 'Reprendre'}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {edition !== undefined && (
        <TargetForm cible={edition} onClose={() => setEdition(undefined)} onSaved={recharger} />
      )}
      {stats && (
        <StatsCible targetId={stats.id} nom={stats.name} onClose={() => setStats(null)} />
      )}
    </>
  )
}

function Session({ cible }: { cible: Target }) {
  // Sans cookies enregistrés, la capture se fait en visiteur anonyme — même si
  // un profil est configuré. Le dire clairement évite de croire à tort que la
  // page est capturée connectée.
  if (!cible.has_session) {
    return (
      <span
        className="mono"
        style={{ fontSize: 11.5, color: 'var(--ink-faint)' }}
        title={
          cible.session_profile
            ? `Profil « ${cible.session_profile} » prêt, mais aucune connexion enregistrée.`
            : undefined
        }
      >
        {cible.session_profile ? 'profil sans connexion' : 'anonyme'}
      </span>
    )
  }
  if (!cible.session_expires_at) {
    return <span className="tag on">connectée</span>
  }
  const expiree = new Date(cible.session_expires_at).getTime() <= Date.now()
  const jours = Math.round((new Date(cible.session_expires_at).getTime() - Date.now()) / 86400000)
  if (expiree) return <span className="tag failed">expirée</span>
  return (
    <span className={`tag ${jours <= 7 ? 'running' : 'success'}`} title={dateHeure(cible.session_expires_at)}>
      {jours} j restants
    </span>
  )
}
