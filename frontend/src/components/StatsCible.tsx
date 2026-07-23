import { api } from '../api'
import { useData } from '../lib'
import type { MetricsSeries } from '../types'

interface Props {
  targetId: number
  nom: string
  onClose: () => void
}

const COULEURS = ['var(--cyan)', 'var(--ok)', 'var(--safelight)']

function formatNombre(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1).replace('.0', '')} M`
  if (n >= 1_000) return `${(n / 1_000).toFixed(1).replace('.0', '')} k`
  return String(n)
}

export function StatsCible({ targetId, nom, onClose }: Props) {
  const { data, erreur, chargement } = useData<MetricsSeries>(
    () => api.targetMetrics(targetId),
    [targetId],
  )

  return (
    <div className="overlay" onClick={onClose} role="presentation">
      <aside
        className="drawer"
        style={{ width: 'min(720px, 100%)' }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={`Statistiques de ${nom}`}
      >
        <div className="drawer-head">
          <div>
            <span className="eyebrow">Évolution dans le temps</span>
            <h2>{nom}</h2>
          </div>
          <button className="btn ghost sm" onClick={onClose}>
            Fermer
          </button>
        </div>

        {erreur && <div className="notice error">{erreur}</div>}
        {chargement && <p className="mono">Chargement…</p>}

        {data && data.points.length === 0 && (
          <div className="empty">
            <h3>Pas encore de métriques</h3>
            <p>
              Les abonnés et mentions J’aime sont relevés à chaque capture d’une page qui les
              affiche (Facebook connecté). La courbe apparaîtra après quelques captures.
            </p>
          </div>
        )}

        {data && data.points.length > 0 && (
          <>
            <div className="stat-tiles">
              {data.keys.map((k, i) => {
                const dernier = [...data.points].reverse().find((p) => p[k] != null)
                const premier = data.points.find((p) => p[k] != null)
                const val = dernier ? Number(dernier[k]) : null
                const delta =
                  premier && dernier && premier !== dernier
                    ? Number(dernier[k]) - Number(premier[k])
                    : 0
                return (
                  <div className="stat-tile" key={k}>
                    <span className="eyebrow" style={{ color: COULEURS[i % COULEURS.length] }}>
                      {data.labels[k] ?? k}
                    </span>
                    <b>{val != null ? formatNombre(val) : '—'}</b>
                    {delta !== 0 && (
                      <span className={`stat-delta ${delta > 0 ? 'up' : 'down'}`}>
                        {delta > 0 ? '▲' : '▼'} {formatNombre(Math.abs(delta))} depuis le début
                      </span>
                    )}
                  </div>
                )
              })}
            </div>

            <div className="section">
              <Graphe data={data} />
            </div>
          </>
        )}
      </aside>
    </div>
  )
}

function Graphe({ data }: { data: MetricsSeries }) {
  const W = 640
  const H = 240
  const P = { top: 16, right: 16, bottom: 28, left: 52 }
  const iw = W - P.left - P.right
  const ih = H - P.top - P.bottom

  const toutes = data.points.flatMap((p) => data.keys.map((k) => Number(p[k])).filter((v) => !isNaN(v)))
  const max = Math.max(1, ...toutes)
  const min = Math.min(...toutes, max)
  const bas = Math.max(0, min - (max - min) * 0.1)
  const n = data.points.length

  const x = (i: number) => (n <= 1 ? P.left + iw / 2 : P.left + (i * iw) / (n - 1))
  const y = (v: number) => P.top + ih - ((v - bas) / (max - bas || 1)) * ih

  // 3 repères d'axe Y
  const ticks = [bas, (bas + max) / 2, max]

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="graphe" role="img" aria-label="Graphique d'évolution">
      {ticks.map((t, i) => (
        <g key={i}>
          <line x1={P.left} y1={y(t)} x2={W - P.right} y2={y(t)} className="graphe-grid" />
          <text x={P.left - 8} y={y(t) + 4} className="graphe-axe" textAnchor="end">
            {formatNombre(Math.round(t))}
          </text>
        </g>
      ))}

      {data.keys.map((k, ki) => {
        const pts = data.points
          .map((p, i) => (p[k] != null ? `${x(i)},${y(Number(p[k]))}` : null))
          .filter(Boolean)
          .join(' ')
        const couleur = COULEURS[ki % COULEURS.length]
        return (
          <g key={k}>
            <polyline points={pts} fill="none" stroke={couleur} strokeWidth={2} />
            {data.points.map((p, i) =>
              p[k] != null ? (
                <circle key={i} cx={x(i)} cy={y(Number(p[k]))} r={3} fill={couleur} />
              ) : null,
            )}
          </g>
        )
      })}

      {data.points.map((p, i) =>
        n <= 12 || i % Math.ceil(n / 8) === 0 ? (
          <text key={i} x={x(i)} y={H - 8} className="graphe-axe" textAnchor="middle">
            {String(p.date).slice(5)}
          </text>
        ) : null,
      )}
    </svg>
  )
}
