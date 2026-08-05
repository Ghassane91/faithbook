import { api } from '../api'
import { RoadmapEditorial } from '../components/RoadmapEditorial'
import { useData } from '../lib'

interface Props {
  onAller: (cle: string) => void
}

/** Date du jour au format AAAA-MM-JJ, dans le fuseau local. */
function aujourdhui(): string {
  return new Date().toLocaleDateString('sv-SE')
}

export function Accueil({ onAller }: Props) {
  const jour = aujourdhui()
  const { data: sante } = useData(() => api.health(), [], 30000)
  const { data: dujour } = useData(() => api.runs({ capture_date: jour, limit: 200 }), [], 30000)
  const { data: comptes } = useData(() => api.accounts(), [], 60000)
  const { data: cibles } = useData(() => api.targets(), [], 30000)

  const runs = dujour?.items ?? []
  const reussies = runs.filter((r) => r.status === 'success')
  const changements = runs.filter((r) => r.changed)
  const signal = [...changements].sort(
    (a, b) => (b.change_ratio ?? 0) - (a.change_ratio ?? 0),
  )[0]
  const cibleSignal = cibles?.find((c) => c.id === signal?.target_id)
  const dateLongue = new Intl.DateTimeFormat('fr-FR', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
  })
    .format(new Date())
    .toUpperCase()

  const chiffres = [
    {
      cle: 'cibles',
      valeur: sante?.targets_enabled,
      libelle: 'pages suivies',
      aide: 'Voir et régler les pages surveillées',
    },
    {
      cle: 'planche',
      valeur: reussies.length,
      libelle: 'captures du jour',
      aide: 'Ouvrir la planche du jour',
    },
    {
      cle: 'historique',
      valeur: changements.length,
      libelle: 'changements détectés',
      aide: 'Parcourir l’historique',
    },
    {
      cle: 'comptes',
      valeur: comptes?.filter((c) => c.status === 'connected').length,
      libelle: 'comptes connectés',
      aide: 'Gérer les sessions Facebook',
    },
  ]

  return (
    <section className="accueil-dashboard" aria-labelledby="accueil-title">
      <div className="accueil-hero">
        <p className="accueil-kicker">SIGNAL DU JOUR <i>/</i> {dateLongue}</p>
        <h1 id="accueil-title">
          <span>Ce qui a</span>
          <span className="creux">bougé</span>
          <span>aujourd’hui</span>
        </h1>

        <div className={`accueil-signal ${signal ? 'changed' : ''}`}>
          <span>
            {signal
              ? `${Math.round((signal.change_ratio ?? 0) * 100)} % de changement détecté`
              : reussies.length
                ? 'Aucun changement prioritaire'
                : 'Captures en attente'}
          </span>
          <i aria-hidden="true">→</i>
          <strong>
            {signal
              ? `${cibleSignal?.name ?? `Cible ${signal.target_id}`} a changé depuis sa capture précédente`
              : reussies.length
                ? `${reussies.length} capture${reussies.length > 1 ? 's' : ''} vérifiée${reussies.length > 1 ? 's' : ''} aujourd’hui`
                : 'La planche se remplira au prochain passage du worker'}
          </strong>
        </div>

        <div className="accueil-actions">
          <button type="button" className="btn" onClick={() => onAller('planche')}>
            Ouvrir la planche <span aria-hidden="true">↘</span>
          </button>
          <button type="button" className="btn ghost" onClick={() => onAller('cibles')}>
            Gérer les cibles
          </button>
          <button
            type="button"
            className="btn ghost"
            onClick={() => document.getElementById('accueil-roadmap')?.scrollIntoView({ behavior: 'smooth' })}
          >
            Voir ce qui vient <span aria-hidden="true">↓</span>
          </button>
        </div>
      </div>

      <div className="accueil-chiffres" aria-label="État réel de FaithBook">
        {chiffres.map((c, index) => (
          <button
            key={c.cle}
            type="button"
            className="accueil-stat"
            onClick={() => onAller(c.cle)}
            title={c.aide}
          >
            <small>0{index + 1}</small>
            <b>{c.valeur ?? '—'}</b>
            <span>{c.libelle}</span>
          </button>
        ))}
      </div>

      <div className="accueil-systeme">
        <div>
          <span className="accueil-systeme-label">État du système</span>
          <strong>{sante?.status === 'ok' ? 'Tous les services répondent.' : 'Vérification en cours.'}</strong>
        </div>
        <p className="accueil-etat">
          <span className={`health-dot ${sante?.scheduler_running ? '' : 'down'}`}>
            <i />
            {sante ? (sante.scheduler_running ? 'planificateur actif' : 'planificateur arrêté') : '…'}
          </span>
          {sante?.queue_backend === 'redis' && (
            <span className={`health-dot ${sante.worker_alive && sante.redis_ok ? '' : 'down'}`}>
              <i />
              {sante.worker_alive && sante.redis_ok
                ? `worker actif · file ${sante.queue_depth}`
                : 'worker indisponible'}
            </span>
          )}
        </p>
      </div>

      <section className="accueil-roadmap-intro" aria-labelledby="accueil-roadmap-title">
        <p className="accueil-section-label">Feuille de route · cinq fonctions</p>
        <div>
          <h2 id="accueil-roadmap-title">
            Photographier<br /><span>ne suffit plus.</span>
          </h2>
          <div>
            <p>
              FaithBook capture, archive, compare et alerte. Tout cela fonctionne. Mais il ne dit
              toujours qu’une seule chose : <strong>que quelque chose a changé.</strong>
            </p>
            <p>
              Les cinq fonctions suivantes exploitent l’archive visuelle et le corpus de texte
              daté qui existent déjà pour transformer les captures en information de veille.
            </p>
          </div>
        </div>
      </section>

      <RoadmapEditorial variante="accueil" id="accueil-roadmap" />

      <div className="accueil-roadmap-footer">
        <span>FaithBook · veille visuelle</span>
        <span>Feuille de route · août 2026</span>
      </div>
    </section>
  )
}
