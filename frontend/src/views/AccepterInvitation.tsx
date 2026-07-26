import { useEffect, useState } from 'react'
import { api } from '../api'
import { dateHeure } from '../lib'
import type { InvitationPreview } from '../types'

const ROLE: Record<string, string> = {
  admin: 'Administrateur',
  member: 'Membre',
  viewer: 'Lecture seule',
}

export function AccepterInvitation({
  token,
  onDone,
}: {
  token: string
  onDone: () => void
}) {
  const [invitation, setInvitation] = useState<InvitationPreview | null>(null)
  const [password, setPassword] = useState('')
  const [confirmation, setConfirmation] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [sending, setSending] = useState(false)
  const [accepted, setAccepted] = useState(false)

  useEffect(() => {
    api
      .invitationPreview(token)
      .then(setInvitation)
      .catch((reason) =>
        setError(reason instanceof Error ? reason.message : 'Invitation invalide'),
      )
      .finally(() => setLoading(false))
  }, [token])

  async function accept(event: React.FormEvent) {
    event.preventDefault()
    if (!invitation?.user_exists && password !== confirmation) {
      setError('Les deux mots de passe ne correspondent pas.')
      return
    }
    setSending(true)
    setError(null)
    try {
      await api.acceptInvitation(token, password)
      setAccepted(true)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Acceptation impossible')
      setSending(false)
    }
  }

  return (
    <div className="auth-screen">
      <div className="auth-card">
        <div className="auth-brand">
          <span className="brand-mark">FaithBook</span>
          <span className="brand-sub">invitation d’équipe</span>
        </div>

        {loading ? (
          <p className="mono">Vérification de l’invitation…</p>
        ) : accepted ? (
          <>
            <div className="notice info">
              Invitation acceptée. Votre accès à l’organisation est actif.
            </div>
            <button className="btn auth-wide" onClick={onDone}>
              Ouvrir FaithBook
            </button>
          </>
        ) : invitation ? (
          <form onSubmit={accept}>
            <p className="auth-intro">
              Rejoindre <strong>{invitation.organization_name}</strong> comme{' '}
              {ROLE[invitation.role] ?? invitation.role}.
            </p>
            <div className="invite-summary">
              <span>{invitation.email}</span>
              <span>Valable jusqu’au {dateHeure(invitation.expires_at)}</span>
            </div>
            <div className="field">
              <label htmlFor="invite-password">
                {invitation.user_exists
                  ? 'Mot de passe FaithBook actuel'
                  : 'Créer votre mot de passe'}
              </label>
              <input
                id="invite-password"
                type="password"
                autoComplete={
                  invitation.user_exists ? 'current-password' : 'new-password'
                }
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                autoFocus
              />
              {!invitation.user_exists && (
                <span className="hint">
                  Au moins 10 caractères, mêlant lettres et chiffres.
                </span>
              )}
            </div>
            {!invitation.user_exists && (
              <div className="field">
                <label htmlFor="invite-confirmation">Confirmer le mot de passe</label>
                <input
                  id="invite-confirmation"
                  type="password"
                  autoComplete="new-password"
                  value={confirmation}
                  onChange={(event) => setConfirmation(event.target.value)}
                  required
                />
              </div>
            )}
            {error && <div className="notice error">{error}</div>}
            <button className="btn auth-wide" disabled={sending}>
              {sending ? 'Acceptation…' : 'Accepter l’invitation'}
            </button>
          </form>
        ) : (
          <>
            <div className="notice error">{error ?? 'Invitation invalide ou expirée.'}</div>
            <button className="btn auth-wide" onClick={onDone}>
              Retour à la connexion
            </button>
          </>
        )}
      </div>
    </div>
  )
}
