import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { dateHeure, useData } from '../lib'
import type { Account, AccountStatus, LoginStatus } from '../types'

const STATUT: Record<AccountStatus, { label: string; tag: string }> = {
  connected: { label: 'connecté', tag: 'success' },
  never: { label: 'jamais connecté', tag: 'off' },
  expired: { label: 'session expirée', tag: 'failed' },
  verification_required: { label: 'vérification requise', tag: 'running' },
  error: { label: 'erreur', tag: 'failed' },
}

export function Comptes() {
  const { data: comptes, erreur, chargement, recharger } = useData(() => api.accounts(), [], 30000)
  const [nouveau, setNouveau] = useState('')
  const [message, setMessage] = useState<{ texte: string; type: 'info' | 'error' } | null>(null)
  const [occupe, setOccupe] = useState<number | null>(null)
  const [login, setLogin] = useState<{ compte: Account; etat: LoginStatus } | null>(null)

  async function creer(e: React.FormEvent) {
    e.preventDefault()
    const nom = nouveau.trim()
    if (!nom) return
    setOccupe(-1)
    setMessage(null)
    try {
      await api.createAccount(nom)
      setNouveau('')
      recharger()
    } catch (err) {
      setMessage({ texte: err instanceof Error ? err.message : 'Création impossible', type: 'error' })
    } finally {
      setOccupe(null)
    }
  }

  async function supprimer(compte: Account) {
    if (!confirm(`Déconnecter et supprimer « ${compte.name} » ? La session enregistrée sera effacée.`)) return
    setOccupe(compte.id)
    setMessage(null)
    try {
      await api.deleteAccount(compte.id)
      recharger()
    } catch (err) {
      setMessage({ texte: err instanceof Error ? err.message : 'Suppression impossible', type: 'error' })
    } finally {
      setOccupe(null)
    }
  }

  async function tester(compte: Account) {
    setOccupe(compte.id)
    setMessage(null)
    try {
      const r = await api.testAccount(compte.id)
      setMessage({
        texte: `${compte.name} : ${r.detail}`,
        type: r.logged_in ? 'info' : 'error',
      })
      recharger()
    } catch (err) {
      setMessage({ texte: err instanceof Error ? err.message : 'Test impossible', type: 'error' })
    } finally {
      setOccupe(null)
    }
  }

  async function connecter(compte: Account) {
    setOccupe(compte.id)
    setMessage(null)
    try {
      const etat = await api.loginStart(compte.id)
      setLogin({ compte, etat })
    } catch (err) {
      setMessage({ texte: err instanceof Error ? err.message : 'Ouverture impossible', type: 'error' })
    } finally {
      setOccupe(null)
    }
  }

  function fermerLogin(recharge: boolean) {
    setLogin(null)
    if (recharge) recharger()
  }

  return (
    <>
      <div className="page-head">
        <div>
          <span className="eyebrow">Sessions connectées</span>
          <h1>Comptes</h1>
          <p>
            Connectez-vous une fois à un compte (Facebook…) dans le navigateur intégré. La session
            est chiffrée puis réutilisée pour capturer les pages en étant connecté. Aucun mot de
            passe n’est jamais lu ni conservé.
          </p>
        </div>
      </div>

      <form className="inline-form" onSubmit={creer}>
        <input
          type="text"
          placeholder="Nom du compte (ex. Facebook — page SPYPOINT)"
          value={nouveau}
          onChange={(e) => setNouveau(e.target.value)}
          maxLength={200}
        />
        <button className="btn" disabled={occupe === -1 || !nouveau.trim()}>
          {occupe === -1 ? <span className="spinner" /> : 'Ajouter un compte'}
        </button>
      </form>

      {message && <div className={`notice ${message.type}`}>{message.texte}</div>}
      {erreur && <div className="notice error">{erreur}</div>}
      {chargement && <p className="mono">Chargement…</p>}

      {comptes && comptes.length === 0 && (
        <div className="empty">
          <h3>Aucun compte connecté</h3>
          <p>
            Ajoutez un compte, puis cliquez « Connecter » : un navigateur s’ouvre, vous saisissez
            vous-même vos identifiants et validez la 2FA. La session est ensuite disponible pour vos
            cibles.
          </p>
        </div>
      )}

      {comptes && comptes.length > 0 && (
        <div className="panel">
          <table>
            <thead>
              <tr>
                <th>Compte</th>
                <th>État</th>
                <th>Cibles</th>
                <th>Dernière vérification</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {comptes.map((c) => {
                const st = STATUT[c.status]
                return (
                  <tr key={c.id}>
                    <td>
                      <div className="cell-title">{c.name}</div>
                      <div className="cell-url">{c.platform}</div>
                    </td>
                    <td>
                      <span className={`tag ${st.tag}`}>{st.label}</span>
                      {c.last_error && (
                        <div className="mono" style={{ fontSize: 11, color: 'var(--ink-faint)', marginTop: 4 }}>
                          {c.last_error}
                        </div>
                      )}
                    </td>
                    <td className="mono">{c.target_count}</td>
                    <td className="cell-time">{dateHeure(c.last_verified_at)}</td>
                    <td>
                      <div className="btn-row">
                        <button
                          className="btn sm"
                          disabled={occupe === c.id || login !== null}
                          onClick={() => connecter(c)}
                        >
                          {occupe === c.id ? <span className="spinner" /> : c.has_session ? 'Reconnecter' : 'Connecter'}
                        </button>
                        <button
                          className="btn ghost sm"
                          disabled={occupe === c.id || !c.has_session}
                          onClick={() => tester(c)}
                          title="Vérifier que la session est toujours valide"
                        >
                          Tester
                        </button>
                        <button
                          className="btn ghost sm"
                          disabled={occupe === c.id}
                          onClick={() => supprimer(c)}
                        >
                          Supprimer
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {login && (
        <LoginModal compte={login.compte} etat={login.etat} onClose={fermerLogin} />
      )}
    </>
  )
}

interface LoginModalProps {
  compte: Account
  etat: LoginStatus
  onClose: (recharge: boolean) => void
}

function LoginModal({ compte, etat, onClose }: LoginModalProps) {
  const [connecte, setConnecte] = useState(false)
  const [url, setUrl] = useState<string | null>(null)
  const [occupe, setOccupe] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const monte = useRef(true)

  // Sonde l'état réel de la connexion (cookies présents) pour éclairer le bouton
  // « J'ai terminé » : inutile de valider tant que Facebook n'a pas posé la session.
  useEffect(() => {
    monte.current = true
    const id = setInterval(async () => {
      try {
        const s = await api.loginStatus(compte.id)
        if (!monte.current) return
        setConnecte(s.logged_in)
        setUrl(s.current_url)
        if (!s.active) {
          clearInterval(id)
        }
      } catch {
        /* la sonde échoue silencieusement : réessai au tick suivant */
      }
    }, 2500)
    return () => {
      monte.current = false
      clearInterval(id)
    }
  }, [compte.id])

  async function terminer() {
    setOccupe(true)
    setMessage(null)
    try {
      const r = await api.loginFinish(compte.id)
      if (r.logged_in) {
        onClose(true)
      } else {
        setMessage(r.detail)
        setOccupe(false)
      }
    } catch (err) {
      setMessage(err instanceof Error ? err.message : 'Validation impossible')
      setOccupe(false)
    }
  }

  async function annuler() {
    setOccupe(true)
    try {
      await api.loginCancel(compte.id)
    } catch {
      /* on ferme quand même */
    }
    onClose(true)
  }

  const src = etat.novnc_path ?? '/novnc/vnc.html?autoconnect=true&resize=remote&reconnect=true'

  return (
    <div className="overlay novnc-overlay">
      <div className="novnc-modal">
        <div className="novnc-head">
          <div>
            <span className="eyebrow">Connexion manuelle</span>
            <h2>{compte.name}</h2>
          </div>
          <span className={`tag ${connecte ? 'success' : 'off'}`}>
            {connecte ? 'session détectée' : 'en attente de connexion'}
          </span>
        </div>

        <p className="novnc-hint mono">
          Connectez-vous dans le navigateur ci-dessous (identifiants + 2FA), puis cliquez «&nbsp;J’ai
          terminé&nbsp;». {url && <span>— page&nbsp;: {url}</span>}
        </p>

        {message && <div className="notice error">{message}</div>}

        <div className="novnc-frame">
          <iframe title="Navigateur de connexion" src={src} allow="clipboard-read; clipboard-write" />
        </div>

        <div className="novnc-foot">
          <button className="btn ghost" onClick={annuler} disabled={occupe}>
            Annuler
          </button>
          <button className="btn" onClick={terminer} disabled={occupe || !connecte}>
            {occupe ? <span className="spinner" /> : 'J’ai terminé'}
          </button>
        </div>
      </div>
    </div>
  )
}
