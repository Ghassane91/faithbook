import { useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'

export function Connexion() {
  const { connexion } = useAuth()
  const [mode, setMode] = useState<'login' | 'forgot'>('login')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [envoi, setEnvoi] = useState(false)

  async function soumettre(e: React.FormEvent) {
    e.preventDefault()
    setEnvoi(true)
    setErreur(null)
    try {
      await connexion(email, password)
    } catch (err) {
      setErreur(err instanceof Error ? err.message : 'Connexion impossible')
      setEnvoi(false)
    }
  }

  async function demanderLien(e: React.FormEvent) {
    e.preventDefault()
    setEnvoi(true)
    setErreur(null)
    setInfo(null)
    try {
      const r = await api.forgotPassword(email)
      setInfo(r.detail)
    } catch (err) {
      setErreur(err instanceof Error ? err.message : 'Demande impossible')
    } finally {
      setEnvoi(false)
    }
  }

  function basculer(cible: 'login' | 'forgot') {
    setMode(cible)
    setErreur(null)
    setInfo(null)
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark">FaithBook</span>
          <span className="brand-sub">
            {mode === 'login' ? 'veille visuelle' : 'mot de passe oublié'}
          </span>
        </div>

        {mode === 'login' ? (
          <form onSubmit={soumettre}>
            <div className="field">
              <label htmlFor="email">Identifiant</label>
              <input
                id="email"
                type="text"
                autoComplete="username"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="field">
              <label htmlFor="password">Mot de passe</label>
              <input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>

            {erreur && <div className="notice error">{erreur}</div>}

            <button className="btn" type="submit" disabled={envoi} style={{ width: '100%', marginTop: 6 }}>
              {envoi ? 'Connexion…' : 'Se connecter'}
            </button>
            <button
              type="button"
              className="linklike"
              onClick={() => basculer('forgot')}
              style={{ marginTop: 14, display: 'block' }}
            >
              Mot de passe oublié ?
            </button>
          </form>
        ) : (
          <form onSubmit={demanderLien}>
            <p className="auth-intro">
              Saisissez l’adresse e-mail de votre compte. Si elle correspond à un compte, un lien de
              réinitialisation vous sera envoyé.
            </p>
            <div className="field">
              <label htmlFor="email-forgot">Adresse e-mail</label>
              <input
                id="email-forgot"
                type="email"
                autoComplete="email"
                autoFocus
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>

            {erreur && <div className="notice error">{erreur}</div>}
            {info && <div className="notice info">{info}</div>}

            <button className="btn" type="submit" disabled={envoi} style={{ width: '100%', marginTop: 6 }}>
              {envoi ? 'Envoi…' : 'Envoyer le lien'}
            </button>
            <button
              type="button"
              className="linklike"
              onClick={() => basculer('login')}
              style={{ marginTop: 14, display: 'block' }}
            >
              ← Retour à la connexion
            </button>
          </form>
        )}
      </div>
      <p className="auth-foot mono">Accès réservé · consultez les mentions légales depuis l’application</p>
    </div>
  )
}
