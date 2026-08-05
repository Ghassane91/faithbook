import { useEffect, useState, type ReactNode } from 'react'
import { api, selectOrganization, selectedOrganizationId } from './api'
import { useAuth } from './auth'
import { RunDetail } from './components/RunDetail'
import { delai, useData, useRoute } from './lib'
import { ChangerMotDePasse } from './views/ChangerMotDePasse'
import { AccepterInvitation } from './views/AccepterInvitation'
import { Accueil } from './views/Accueil'
import { Cibles } from './views/Cibles'
import { Comptes } from './views/Comptes'
import { Connexion } from './views/Connexion'
import { Historique } from './views/Historique'
import { MentionsLegales } from './views/MentionsLegales'
import { Organisation } from './views/Organisation'
import { Planche } from './views/Planche'
import { Reinitialiser } from './views/Reinitialiser'
import type { OrganizationUsage } from './types'

const VUES = [
  { cle: 'accueil', idx: '00', titre: 'Accueil', icon: 'board' },
  { cle: 'planche', idx: '01', titre: 'Planche du jour', icon: 'board' },
  { cle: 'cibles', idx: '02', titre: 'Cibles', icon: 'target' },
  { cle: 'comptes', idx: '03', titre: 'Comptes', icon: 'account' },
  { cle: 'historique', idx: '04', titre: 'Historique', icon: 'history' },
  { cle: 'organisation', idx: '05', titre: 'Équipe', icon: 'team' },
]

function dateEditoriale() {
  return new Intl.DateTimeFormat('fr-FR', {
    day: '2-digit',
    month: 'long',
    year: 'numeric',
  })
    .format(new Date())
    .toUpperCase()
}

export default function App() {
  const { user, pret } = useAuth()
  // Un lien de réinitialisation (?reset_token=...) prime sur tout : il doit
  // s'ouvrir même déconnecté et avant la résolution de la session.
  const [resetToken, setResetToken] = useState(
    () => new URLSearchParams(window.location.search).get('reset_token'),
  )
  const [inviteToken, setInviteToken] = useState(
    () => new URLSearchParams(window.location.search).get('invite_token'),
  )

  if (inviteToken) {
    return (
      <AccepterInvitation
        token={inviteToken}
        onDone={() => {
          window.history.replaceState({}, '', window.location.pathname)
          setInviteToken(null)
          window.location.reload()
        }}
      />
    )
  }

  if (resetToken) {
    return (
      <Reinitialiser
        token={resetToken}
        onDone={() => {
          window.history.replaceState({}, '', window.location.pathname)
          setResetToken(null)
        }}
      />
    )
  }

  // Tant que le premier /me n'a pas répondu, on n'affiche rien : évite de
  // faire clignoter l'écran de connexion pour une session déjà valide.
  if (!pret) return <div className="auth-screen" />
  if (!user) return <Connexion />
  if (user.must_change_password) return <ChangerMotDePasse force />

  return <AppConnecte />
}

function AppConnecte() {
  const { user, deconnexion } = useAuth()
  const [route, aller] = useRoute()
  const [runOuvert, setRunOuvert] = useState<number | null>(null)
  const [menuCompte, setMenuCompte] = useState(false)
  const [changerMdp, setChangerMdp] = useState(false)
  const [organisationId, setOrganisationId] = useState(selectedOrganizationId)

  const { data: organisations, recharger: rechargerOrganisations } = useData(
    () => api.organizations(),
    [],
    30000,
  )
  const { data: sante } = useData(() => api.health(), [], 30000)
  const { data: jobs } = useData(() => api.jobs(), [], 30000)
  const { data: usage } = useData(
    () => api.organizationUsage(),
    [organisationId],
    30000,
  )

  const prochaine = (jobs ?? [])
    .map((j) => j.next_run_at)
    .filter((d): d is string => Boolean(d))
    .sort()[0]
  const organisationActive =
    organisations?.find((organization) => organization.id === organisationId) ??
    organisations?.[0]
  const canEdit =
    organisationActive?.role === 'owner' ||
    organisationActive?.role === 'admin' ||
    organisationActive?.role === 'member'
  const canAdmin =
    organisationActive?.role === 'owner' || organisationActive?.role === 'admin'
  const vues = VUES.filter(
    (vue) =>
      vue.cle !== 'organisation' ||
      organisationActive?.role === 'owner' ||
      organisationActive?.role === 'admin',
  )
  const vueActive = vues.find((vue) => vue.cle === route)

  useEffect(() => {
    if (!organisations?.length) return
    if (!organisations.some((o) => o.id === organisationId)) {
      selectOrganization(organisations[0].id)
      setOrganisationId(organisations[0].id)
      window.location.reload()
    }
  }, [organisations, organisationId])

  async function nouvelleOrganisation() {
    const name = window.prompt("Nom de l'organisation")
    if (!name?.trim()) return
    const created = await api.createOrganization(name.trim())
    selectOrganization(created.id)
    setOrganisationId(created.id)
    rechargerOrganisations()
    window.location.reload()
  }

  return (
    <div className="shell app-workspace">
      <nav className="rail">
        <div className="brand">
          <span className="brand-mark">FaithBook</span>
          <span className="brand-sub">veille visuelle</span>
          <span className="brand-registration" aria-hidden="true">
            <i />
            <i />
          </span>
        </div>

        {organisations && organisations.length > 0 && (
          <div className="org-switcher">
            <label htmlFor="organization">Espace actif</label>
            <select
              id="organization"
              value={organisationId ?? organisations[0].id}
              onChange={(event) => {
                const id = Number(event.target.value)
                selectOrganization(id)
                setOrganisationId(id)
                window.location.reload()
              }}
            >
              {organisations.map((organization) => (
                <option key={organization.id} value={organization.id}>
                  {organization.name} · {organization.role}
                </option>
              ))}
            </select>
            <button className="linklike" onClick={nouvelleOrganisation}>
              + Nouvelle
            </button>
          </div>
        )}

        <div className="nav">
          {vues.map((v) => (
            <button
              key={v.cle}
              className="nav-item"
              aria-current={route === v.cle}
              onClick={() => aller(v.cle)}
            >
              <NavIcon name={v.icon} />
              <span className="idx">{v.idx}</span>
              <span>{v.titre}</span>
              {v.cle === 'cibles' && sante && <span className="nav-count">{sante.targets_enabled}</span>}
            </button>
          ))}
        </div>

        {usage && <RailUsage usage={usage} />}

        <div className="rail-foot">
          <div className="next-slot">
            prochaine capture
            <strong>{delai(prochaine ?? null)}</strong>
          </div>
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
          {sante?.storage_backend === 'google_drive' && (
            <span className={`health-dot ${sante.drive_configured ? '' : 'down'}`}>
              <i />
              {sante.drive_configured ? 'Google Drive configuré' : 'Google Drive incomplet'}
            </span>
          )}

          <div className="account">
            <button className="account-btn mono" onClick={() => setMenuCompte((v) => !v)}>
              {user!.email}
              <span aria-hidden>▾</span>
            </button>
            {menuCompte && (
              <div className="account-menu">
                <button
                  onClick={() => {
                    setChangerMdp(true)
                    setMenuCompte(false)
                  }}
                >
                  Changer le mot de passe
                </button>
                <button onClick={() => { setMenuCompte(false); aller('mentions') }}>
                  Mentions légales
                </button>
                <button onClick={deconnexion}>Se déconnecter</button>
              </div>
            )}
          </div>
        </div>
      </nav>

      <main className="main">
        <header className="workspace-topbar">
          <span>
            FAITHBOOK <i>/</i> {vueActive?.titre ?? 'DOCUMENT'} <i>/</i> {dateEditoriale()}
          </span>
          <span className={`workspace-live ${sante?.scheduler_running ? '' : 'down'}`}>
            <i />
            {sante?.scheduler_running ? 'VEILLE EN COURS' : 'VEILLE INTERROMPUE'}
          </span>
        </header>

        <div className="workspace-view" key={route}>
          {route === 'accueil' ? (
            <Accueil onAller={aller} />
          ) : route === 'cibles' ? (
            <Cibles
              onOuvrirRun={setRunOuvert}
              canEdit={canEdit}
              canDelete={canAdmin}
            />
          ) : route === 'comptes' ? (
            <Comptes canAdmin={canAdmin} />
          ) : route === 'historique' ? (
            <Historique onOuvrirRun={setRunOuvert} />
          ) : route === 'organisation' ? (
            <Organisation
              organization={organisationActive ?? null}
              health={sante ?? null}
              usage={usage ?? null}
            />
          ) : route === 'mentions' ? (
            <MentionsLegales />
          ) : (
            <Planche onOuvrirRun={setRunOuvert} onAllerCibles={() => aller('cibles')} />
          )}
        </div>

        <footer className="app-foot mono">
          <button className="linklike" onClick={() => aller('mentions')}>
            Mentions légales
          </button>
          <span>· FaithBook · accès réservé</span>
        </footer>
      </main>

      {runOuvert !== null && (
        <RunDetail
          runId={runOuvert}
          canAdmin={canAdmin}
          onClose={() => setRunOuvert(null)}
        />
      )}
      {changerMdp && <ChangerMotDePasse onClose={() => setChangerMdp(false)} />}
    </div>
  )
}

function RailUsage({ usage }: { usage: OrganizationUsage }) {
  const metrics = [
    { label: 'Captures / jour', metric: usage.daily_captures },
    { label: 'Stockage', metric: usage.storage_bytes, bytes: true },
  ]
  return (
    <div className="rail-usage">
      <div className="rail-section-title">
        <span>Capacité</span>
        <span>{usage.retention_days === 0 ? '∞' : `${usage.retention_days} j`}</span>
      </div>
      {metrics.map(({ label, metric, bytes }) => (
        <div className="rail-meter" key={label}>
          <div>
            <span>{label}</span>
            <b>
              {bytes ? formatBytes(metric.used) : metric.used}
              {' / '}
              {metric.unlimited
                ? '∞'
                : bytes
                  ? formatBytes(metric.limit)
                  : metric.limit}
            </b>
          </div>
          <span className="meter-track">
            <i
              className={(metric.percent ?? 0) >= 80 ? 'warning' : ''}
              style={{ width: `${metric.percent ?? 0}%` }}
            />
          </span>
        </div>
      ))}
    </div>
  )
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} o`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} Ko`
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} Mo`
  return `${(value / 1024 ** 3).toFixed(1)} Go`
}

function NavIcon({ name }: { name: string }) {
  const paths: Record<string, ReactNode> = {
    board: (
      <>
        <rect x="3" y="3" width="7" height="7" />
        <rect x="14" y="3" width="7" height="7" />
        <rect x="3" y="14" width="7" height="7" />
        <rect x="14" y="14" width="7" height="7" />
      </>
    ),
    target: (
      <>
        <circle cx="12" cy="12" r="8" />
        <circle cx="12" cy="12" r="3" />
        <path d="M12 2v3M12 19v3M2 12h3M19 12h3" />
      </>
    ),
    account: (
      <>
        <circle cx="12" cy="8" r="4" />
        <path d="M4 21c.8-4.2 3.5-6 8-6s7.2 1.8 8 6" />
      </>
    ),
    history: (
      <>
        <path d="M3 12a9 9 0 1 0 3-6.7L3 8" />
        <path d="M3 3v5h5M12 7v6l4 2" />
      </>
    ),
    team: (
      <>
        <circle cx="9" cy="8" r="3" />
        <circle cx="17" cy="9" r="2.5" />
        <path d="M3 20c.6-4 2.7-6 6-6s5.4 2 6 6M15 15c3.3 0 5.2 1.7 5.8 5" />
      </>
    ),
  }
  return (
    <svg className="nav-icon" viewBox="0 0 24 24" aria-hidden="true">
      {paths[name]}
    </svg>
  )
}
