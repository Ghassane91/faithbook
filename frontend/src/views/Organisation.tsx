import { useState } from 'react'
import { api } from '../api'
import { dateHeure, useData } from '../lib'
import type {
  Health,
  MembershipRole,
  Organization,
  OrganizationInvitation,
  OrganizationMember,
  OrganizationUsage,
  QuotaMetric,
} from '../types'

const ROLE_LABEL: Record<MembershipRole, string> = {
  owner: 'Propriétaire',
  admin: 'Administrateur',
  member: 'Membre',
  viewer: 'Lecture seule',
}

export function Organisation({
  organization,
  health,
  usage,
}: {
  organization: Organization | null
  health: Health | null
  usage: OrganizationUsage | null
}) {
  const {
    data: members,
    erreur,
    chargement,
    recharger,
  } = useData(() => api.organizationMembers(), [organization?.id])
  const {
    data: invitations,
    erreur: invitationError,
    recharger: reloadInvitations,
  } = useData(() => api.organizationInvitations(), [organization?.id])
  const [email, setEmail] = useState('')
  const [role, setRole] = useState<MembershipRole>('member')
  const [message, setMessage] = useState<{
    text: string
    type: 'info' | 'error'
  } | null>(null)
  const [inviteLink, setInviteLink] = useState<string | null>(null)
  const [occupe, setOccupe] = useState<number | 'new' | null>(null)
  const [driveBusy, setDriveBusy] = useState(false)
  const [driveMessage, setDriveMessage] = useState<{
    text: string
    type: 'info' | 'error'
  } | null>(null)

  async function testerDrive() {
    setDriveBusy(true)
    setDriveMessage(null)
    try {
      const result = await api.checkDrive()
      setDriveMessage({ text: result.detail, type: 'info' })
    } catch (error) {
      setDriveMessage({
        text: error instanceof Error ? error.message : 'Google Drive inaccessible',
        type: 'error',
      })
    } finally {
      setDriveBusy(false)
    }
  }

  async function ajouter(event: React.FormEvent) {
    event.preventDefault()
    if (!email.trim()) return
    setOccupe('new')
    setMessage(null)
    setInviteLink(null)
    try {
      const invitation = await api.createOrganizationInvitation(email.trim(), role)
      setEmail('')
      reloadInvitations()
      setMessage({
        text:
          invitation.delivery === 'sent'
            ? 'Invitation envoyée par e-mail.'
            : 'SMTP non configuré : utilisez le lien local ci-dessous.',
        type: 'info',
      })
      setInviteLink(invitation.invite_url)
    } catch (error) {
      setMessage({
        text: error instanceof Error ? error.message : 'Ajout impossible',
        type: 'error',
      })
    } finally {
      setOccupe(null)
    }
  }

  async function revoquer(invitation: OrganizationInvitation) {
    if (!confirm(`Révoquer l'invitation envoyée à ${invitation.email} ?`)) return
    setOccupe(invitation.id)
    setMessage(null)
    try {
      await api.revokeOrganizationInvitation(invitation.id)
      reloadInvitations()
    } catch (error) {
      setMessage({
        text: error instanceof Error ? error.message : 'Révocation impossible',
        type: 'error',
      })
    } finally {
      setOccupe(null)
    }
  }

  async function changer(member: OrganizationMember, nextRole: MembershipRole) {
    setOccupe(member.membership_id)
    setMessage(null)
    try {
      await api.updateOrganizationMember(member.membership_id, nextRole)
      recharger()
    } catch (error) {
      setMessage({
        text: error instanceof Error ? error.message : 'Modification impossible',
        type: 'error',
      })
    } finally {
      setOccupe(null)
    }
  }

  async function supprimer(member: OrganizationMember) {
    if (!confirm(`Retirer ${member.email} de l'organisation ?`)) return
    setOccupe(member.membership_id)
    setMessage(null)
    try {
      await api.removeOrganizationMember(member.membership_id)
      recharger()
    } catch (error) {
      setMessage({
        text: error instanceof Error ? error.message : 'Suppression impossible',
        type: 'error',
      })
    } finally {
      setOccupe(null)
    }
  }

  return (
    <>
      <div className="page-head">
        <div>
          <span className="eyebrow">Organisation active</span>
          <h1>{organization?.name ?? 'Équipe'}</h1>
          <p>
            Gérez les personnes autorisées à consulter, lancer ou administrer
            les captures de cet espace.
          </p>
        </div>
      </div>

      {usage && <QuotaOverview usage={usage} />}

      <form className="member-form" onSubmit={ajouter}>
        <input
          type="email"
          placeholder="E-mail de la personne à inviter"
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          maxLength={255}
        />
        <select
          value={role}
          onChange={(event) => setRole(event.target.value as MembershipRole)}
        >
          <option value="admin">Administrateur</option>
          <option value="member">Membre</option>
          <option value="viewer">Lecture seule</option>
        </select>
        <button className="btn" disabled={occupe === 'new' || !email.trim()}>
          Inviter
        </button>
      </form>
      <p className="form-hint">
        La personne recevra un lien valable 7 jours. Si elle n’a pas encore de
        compte FaithBook, elle pourra le créer directement depuis ce lien.
      </p>

      {message && <div className={`notice ${message.type}`}>{message.text}</div>}
      {inviteLink && (
        <div className="local-invite">
          <a href={inviteLink}>{inviteLink}</a>
          <button
            className="btn ghost sm"
            onClick={() => navigator.clipboard.writeText(inviteLink)}
          >
            Copier
          </button>
        </div>
      )}
      {erreur && <div className="notice error">{erreur}</div>}
      {invitationError && <div className="notice error">{invitationError}</div>}
      {chargement && <p className="mono">Chargement…</p>}

      {members && (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>Utilisateur</th>
                <th>Rôle</th>
                <th>Ajouté le</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {members.map((member) => (
                <tr key={member.membership_id}>
                  <td className="cell-title">{member.email}</td>
                  <td>
                    {member.role === 'owner' ? (
                      <span className="tag success">{ROLE_LABEL.owner}</span>
                    ) : (
                      <select
                        className="role-select"
                        value={member.role}
                        disabled={occupe === member.membership_id}
                        onChange={(event) =>
                          changer(member, event.target.value as MembershipRole)
                        }
                      >
                        <option value="admin">Administrateur</option>
                        <option value="member">Membre</option>
                        <option value="viewer">Lecture seule</option>
                      </select>
                    )}
                  </td>
                  <td className="cell-time">{dateHeure(member.created_at)}</td>
                  <td>
                    {member.role !== 'owner' && (
                      <button
                        className="btn ghost sm"
                        disabled={occupe === member.membership_id}
                        onClick={() => supprimer(member)}
                      >
                        Retirer
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {invitations && invitations.length > 0 && (
        <>
          <h2 className="section-title">Invitations en attente</h2>
          <div className="panel">
            <table>
              <thead>
                <tr>
                  <th>E-mail</th>
                  <th>Rôle</th>
                  <th>Expiration</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {invitations.map((invitation) => (
                  <tr key={invitation.id}>
                    <td className="cell-title">{invitation.email}</td>
                    <td>
                      <span className="tag pending">
                        {ROLE_LABEL[invitation.role]}
                      </span>
                    </td>
                    <td className="cell-time">{dateHeure(invitation.expires_at)}</td>
                    <td>
                      <button
                        className="btn ghost sm"
                        disabled={occupe === invitation.id}
                        onClick={() => revoquer(invitation)}
                      >
                        Révoquer
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {health?.storage_backend === 'google_drive' && (
        <>
          <h2 className="section-title">Stockage Google Drive</h2>
          <div className="panel storage-panel">
            <div>
              <strong>
                {health.drive_configured
                  ? 'Configuration détectée'
                  : 'Configuration incomplète'}
              </strong>
              <p className="form-hint">
                Le test vérifie que le dossier parent existe et que FaithBook
                peut y créer les dossiers datés.
              </p>
            </div>
            <button
              className="btn ghost"
              onClick={testerDrive}
              disabled={driveBusy || !health.drive_configured}
            >
              {driveBusy ? <span className="spinner" /> : 'Tester Google Drive'}
            </button>
          </div>
          {driveMessage && (
            <div className={`notice ${driveMessage.type}`}>{driveMessage.text}</div>
          )}
        </>
      )}
    </>
  )
}

function QuotaOverview({ usage }: { usage: OrganizationUsage }) {
  const items: Array<{
    label: string
    metric: QuotaMetric
    formatter?: (value: number) => string
  }> = [
    { label: 'Comptes', metric: usage.accounts },
    { label: 'Cibles', metric: usage.targets },
    { label: 'Captures aujourd’hui', metric: usage.daily_captures },
    { label: 'Stockage local', metric: usage.storage_bytes, formatter: formatBytes },
  ]

  return (
    <section className="quota-section" aria-label="Utilisation de l’organisation">
      <div className="quota-head">
        <div>
          <span className="eyebrow">Utilisation de l’espace</span>
          <h2>Capacité & rétention</h2>
        </div>
        <span className="retention-badge">
          {usage.retention_days === 0
            ? 'Conservation illimitée'
            : `Conservation ${usage.retention_days} jours`}
        </span>
      </div>
      <div className="quota-grid">
        {items.map(({ label, metric, formatter }) => {
          const format = formatter ?? ((value: number) => String(value))
          const percent = metric.percent ?? 0
          return (
            <article className="quota-card" key={label}>
              <div className="quota-label">
                <span>{label}</span>
                <small>{metric.unlimited ? 'illimité' : `${Math.round(percent)} %`}</small>
              </div>
              <strong>
                {format(metric.used)}
                <small>
                  {' / '}
                  {metric.unlimited ? '∞' : format(metric.limit)}
                </small>
              </strong>
              <span className="quota-track">
                <i
                  className={percent >= 80 ? 'warning' : ''}
                  style={{ width: `${percent}%` }}
                />
              </span>
            </article>
          )
        })}
      </div>
    </section>
  )
}

function formatBytes(value: number) {
  if (value < 1024) return `${value} o`
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} Ko`
  if (value < 1024 ** 3) return `${(value / 1024 ** 2).toFixed(1)} Mo`
  return `${(value / 1024 ** 3).toFixed(1)} Go`
}
