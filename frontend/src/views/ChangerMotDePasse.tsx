import { useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'

interface Props {
  force?: boolean // true = changement imposé à la première connexion
  onClose?: () => void
}

export function ChangerMotDePasse({ force = false, onClose }: Props) {
  const { rafraichir } = useAuth()
  const [actuel, setActuel] = useState('')
  const [nouveau, setNouveau] = useState('')
  const [confirme, setConfirme] = useState('')
  const [erreur, setErreur] = useState<string | null>(null)
  const [envoi, setEnvoi] = useState(false)

  async function soumettre(e: React.FormEvent) {
    e.preventDefault()
    if (nouveau !== confirme) {
      setErreur('Les deux nouveaux mots de passe ne correspondent pas.')
      return
    }
    setEnvoi(true)
    setErreur(null)
    try {
      await api.changePassword(actuel, nouveau)
      await rafraichir()
      onClose?.()
    } catch (err) {
      setErreur(err instanceof Error ? err.message : 'Changement impossible')
      setEnvoi(false)
    }
  }

  const corps = (
    <form onSubmit={soumettre}>
      {force && (
        <div className="notice info">
          Ce compte utilise encore le mot de passe généré à l’installation. Choisissez-en un
          nouveau pour continuer.
        </div>
      )}
      <div className="field">
        <label htmlFor="actuel">Mot de passe actuel</label>
        <input
          id="actuel"
          type="password"
          autoComplete="current-password"
          value={actuel}
          onChange={(e) => setActuel(e.target.value)}
          required
          autoFocus
        />
      </div>
      <div className="field">
        <label htmlFor="nouveau">Nouveau mot de passe</label>
        <input
          id="nouveau"
          type="password"
          autoComplete="new-password"
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

      <div className="btn-row" style={{ marginTop: 12 }}>
        <button className="btn" type="submit" disabled={envoi}>
          {envoi ? 'Enregistrement…' : 'Changer le mot de passe'}
        </button>
        {!force && onClose && (
          <button type="button" className="btn ghost" onClick={onClose}>
            Annuler
          </button>
        )}
      </div>
    </form>
  )

  // Imposé : plein écran, aucune échappatoire. Volontaire : dans un panneau.
  if (force) {
    return (
      <div className="auth-screen">
        <div className="auth-card">
          <div className="auth-brand">
            <span className="brand-mark">FaithBook</span>
            <span className="brand-sub">changer le mot de passe</span>
          </div>
          {corps}
        </div>
      </div>
    )
  }

  return (
    <div className="overlay" onClick={onClose} role="presentation">
      <aside
        className="drawer"
        style={{ width: 'min(460px, 100%)' }}
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label="Changer le mot de passe"
      >
        <div className="drawer-head">
          <div>
            <span className="eyebrow">Compte</span>
            <h2>Changer le mot de passe</h2>
          </div>
        </div>
        {corps}
      </aside>
    </div>
  )
}
