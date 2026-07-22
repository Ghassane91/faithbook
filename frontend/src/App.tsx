import { useState } from 'react'
import { api } from './api'
import { useAuth } from './auth'
import { RunDetail } from './components/RunDetail'
import { delai, useData, useRoute } from './lib'
import { ChangerMotDePasse } from './views/ChangerMotDePasse'
import { Cibles } from './views/Cibles'
import { Comptes } from './views/Comptes'
import { Connexion } from './views/Connexion'
import { Historique } from './views/Historique'
import { MentionsLegales } from './views/MentionsLegales'
import { Planche } from './views/Planche'
import { Reinitialiser } from './views/Reinitialiser'

const VUES = [
  { cle: 'planche', idx: '01', titre: 'Planche du jour' },
  { cle: 'cibles', idx: '02', titre: 'Cibles' },
  { cle: 'comptes', idx: '03', titre: 'Comptes' },
  { cle: 'historique', idx: '04', titre: 'Historique' },
]

export default function App() {
  const { user, pret } = useAuth()
  // Un lien de réinitialisation (?reset_token=...) prime sur tout : il doit
  // s'ouvrir même déconnecté et avant la résolution de la session.
  const [resetToken, setResetToken] = useState(
    () => new URLSearchParams(window.location.search).get('reset_token'),
  )

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

  const { data: sante } = useData(() => api.health(), [], 30000)
  const { data: jobs } = useData(() => api.jobs(), [], 30000)

  const prochaine = (jobs ?? [])
    .map((j) => j.next_run_at)
    .filter((d): d is string => Boolean(d))
    .sort()[0]

  return (
    <div className="shell">
      <nav className="rail">
        <div className="brand">
          <span className="brand-mark">FaithBook</span>
          <span className="brand-sub">captures planifiées</span>
        </div>

        <div className="nav">
          {VUES.map((v) => (
            <button
              key={v.cle}
              className="nav-item"
              aria-current={route === v.cle}
              onClick={() => aller(v.cle)}
            >
              <span className="idx">{v.idx}</span>
              {v.titre}
              {v.cle === 'cibles' && sante && <span className="nav-count">{sante.targets_enabled}</span>}
            </button>
          ))}
        </div>

        <div className="rail-foot">
          <div className="next-slot">
            prochaine capture
            <strong>{delai(prochaine ?? null)}</strong>
          </div>
          <span className={`health-dot ${sante?.scheduler_running ? '' : 'down'}`}>
            <i />
            {sante ? (sante.scheduler_running ? 'planificateur actif' : 'planificateur arrêté') : '…'}
          </span>

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
        {route === 'cibles' ? (
          <Cibles onOuvrirRun={setRunOuvert} />
        ) : route === 'comptes' ? (
          <Comptes />
        ) : route === 'historique' ? (
          <Historique onOuvrirRun={setRunOuvert} />
        ) : route === 'mentions' ? (
          <MentionsLegales />
        ) : (
          <Planche onOuvrirRun={setRunOuvert} onAllerCibles={() => aller('cibles')} />
        )}

        <footer className="app-foot mono">
          <button className="linklike" onClick={() => aller('mentions')}>
            Mentions légales
          </button>
          <span>· FaithBook · accès réservé</span>
        </footer>
      </main>

      {runOuvert !== null && <RunDetail runId={runOuvert} onClose={() => setRunOuvert(null)} />}
      {changerMdp && <ChangerMotDePasse onClose={() => setChangerMdp(false)} />}
    </div>
  )
}
