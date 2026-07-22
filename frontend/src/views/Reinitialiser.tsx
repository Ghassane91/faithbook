import { useState } from 'react'
import { api } from '../api'

interface Props {
  token: string
  onDone: () => void // vide le lien de l'URL et renvoie à la connexion
}

export function Reinitialiser({ token, onDone }: Props) {
  const [nouveau, setNouveau] = useState('')
  const [confirme, setConfirme] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [ok, setOk] = useState(false)
  const [envoi, setEnvoi] = useState(false)

  async function soumettre(e: React.FormEvent) {
    e.preventDefault()
    if (nouveau !== confirme) {
      setErreur('Les deux mots de passe ne correspondent pas.')
      return
    }
    setEnvoi(true)
    setErreur(null)
    try {
      await api.resetPassword(token, nouveau)
      setOk(true)
    } catch (err) {
      setErreur(err instanceof Error ? err.message : 'Réinitialisation impossible')
      setEnvoi(false)
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark">FaithBook</span>
          <span className="brand-sub">nouveau mot de passe</span>
        </div>

        {ok ? (
          <>
            <div className="notice info">
              Mot de passe réinitialisé. Vous pouvez maintenant vous connecter.
            </div>
            <button
              className="btn"
              onClick={onDone}
              style={{ width: '100%', marginTop: 6 }}
            >
              Aller à la connexion
            </button>
          </>
        ) : (
          <form onSubmit={soumettre}>
            <p className="auth-intro">Choisissez un nouveau mot de passe pour votre compte.</p>
            <div className="field">
              <label htmlFor="nouveau">Nouveau mot de passe</label>
              <input
                id="nouveau"
                type="password"
                autoComplete="new-password"
                autoFocus
                value={nouveau}
                onChange={(e) => setNouveau(e.target.value)}
                required
              />
              <span className="hint">Au moins 10 caractères, mêlant lettres et chiffres.</span>
            </div>
            <div className="field">
              <label htmlFor="confirme">Confirmer</label>
              <input
                id="confirme"
                type="password"
                autoComplete="new-password"
                value={confirme}
                onChange={(e) => setConfirme(e.target.value)}
                required
              />
            </div>

            {erreur && <div className="notice error">{erreur}</div>}

            <button className="btn" type="submit" disabled={envoi} style={{ width: '100%', marginTop: 6 }}>
              {envoi ? 'Enregistrement…' : 'Réinitialiser le mot de passe'}
            </button>
            <button
              type="button"
              className="linklike"
              onClick={onDone}
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
