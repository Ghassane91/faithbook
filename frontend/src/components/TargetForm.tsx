import { useEffect, useState } from 'react'
import { api } from '../api'
import type { Account, Target, TargetInput } from '../types'

interface Props {
  cible: Target | null // null = création
  canDelete: boolean
  onClose: () => void
  onSaved: () => void
}

const VIDE: TargetInput = {
  name: '',
  url: '',
  enabled: true,
  run_time: '09:00',
  cron_expression: null,
  locale: 'fr-FR',
  wait_until: 'load',
  wait_after_load_ms: 4000,
  timeout_ms: 60000,
  full_page: true,
}

// L'API refuse tout champ inconnu (extra="forbid") : on n'envoie que ceux-ci,
// jamais les champs calcules (id, next_run_at, last_run...).
const CHAMPS_ENVOYES = [
  'name', 'url', 'enabled', 'run_time', 'cron_expression', 'timezone_name',
  'viewport_width', 'viewport_height', 'full_page', 'wait_until',
  'wait_after_load_ms', 'timeout_ms', 'user_agent', 'locale',
  'hide_selectors', 'dismiss_selectors', 'session_profile', 'account_id',
  'expected_selector', 'fail_if_url_contains', 'subfolder',
  'tags',
] as const

function chargeUtile(form: TargetInput): TargetInput {
  const out: Record<string, unknown> = {}
  for (const cle of CHAMPS_ENVOYES) {
    if (cle in form) out[cle] = (form as Record<string, unknown>)[cle]
  }
  return out as TargetInput
}

// Valeurs qui ont fait leurs preuves sur Facebook pendant les essais.
const PRESET_FACEBOOK: TargetInput = {
  locale: 'fr-FR',
  wait_until: 'load',
  wait_after_load_ms: 4000,
  timeout_ms: 60000,
  dismiss_selectors: '[aria-label="Refuser les cookies optionnels"]',
  fail_if_url_contains: 'login;checkpoint',
  session_profile: 'facebook',
}

export function TargetForm({ cible, canDelete, onClose, onSaved }: Props) {
  const [form, setForm] = useState<TargetInput>(cible ?? VIDE)
  const [erreur, setErreur] = useState<string | null>(null)
  const [envoi, setEnvoi] = useState(false)
  const [cadence, setCadence] = useState<'quotidien' | 'cron'>(
    cible?.cron_expression ? 'cron' : 'quotidien',
  )
  const [confirmeSuppression, setConfirmeSuppression] = useState(false)
  const [comptes, setComptes] = useState<Account[]>([])

  // Charge les comptes connectés pour proposer d'attacher la cible à une session.
  useEffect(() => {
    api.accounts().then(setComptes).catch(() => setComptes([]))
  }, [])

  async function supprimer() {
    if (!cible) return
    setEnvoi(true)
    try {
      await api.deleteTarget(cible.id)
      onSaved()
      onClose()
    } catch (err) {
      setErreur(err instanceof Error ? err.message : 'Suppression impossible')
      setConfirmeSuppression(false)
    } finally {
      setEnvoi(false)
    }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const set = (champs: TargetInput) => setForm((f) => ({ ...f, ...champs }))

  async function enregistrer(e: React.FormEvent) {
    e.preventDefault()
    setEnvoi(true)
    setErreur(null)
    const charge = chargeUtile({
      ...form,
      run_time: cadence === 'quotidien' ? form.run_time || '09:00' : null,
      cron_expression: cadence === 'cron' ? form.cron_expression || null : null,
    })
    try {
      if (cible) await api.updateTarget(cible.id, charge)
      else await api.createTarget(charge)
      onSaved()
      onClose()
    } catch (err) {
      setErreur(err instanceof Error ? err.message : 'Enregistrement impossible')
    } finally {
      setEnvoi(false)
    }
  }

  return (
    <div className="overlay" onClick={onClose} role="presentation">
      <aside
        className="drawer"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-label={cible ? 'Modifier la cible' : 'Nouvelle cible'}
      >
        <div className="drawer-head">
          <div>
            <span className="eyebrow">{cible ? `Cible nº ${cible.id}` : 'Nouvelle cible'}</span>
            <h2>{cible ? cible.name : 'Ajouter une page à capturer'}</h2>
          </div>
          <button type="button" className="btn ghost sm" onClick={onClose}>
            Annuler
          </button>
        </div>

        {erreur && <div className="notice error">{erreur}</div>}

        <form onSubmit={enregistrer}>
          <div className="field">
            <label htmlFor="name">Nom</label>
            <input
              id="name"
              type="text"
              required
              value={form.name ?? ''}
              onChange={(e) => set({ name: e.target.value })}
              placeholder="Page vitrine Intégr-IT"
            />
            <span className="hint">Sert à nommer le fichier et à repérer la cible.</span>
          </div>

          <div className="field">
            <label htmlFor="url">Adresse de la page</label>
            <input
              id="url"
              type="url"
              required
              value={form.url ?? ''}
              onChange={(e) => set({ url: e.target.value })}
              placeholder="https://www.facebook.com/ma-page"
            />
          </div>

          <div className="field">
            <label>Cadence</label>
            <div className="btn-row" style={{ marginBottom: 8 }}>
              <button
                type="button"
                className={`btn sm ${cadence === 'quotidien' ? '' : 'ghost'}`}
                onClick={() => setCadence('quotidien')}
              >
                Tous les jours
              </button>
              <button
                type="button"
                className={`btn sm ${cadence === 'cron' ? '' : 'ghost'}`}
                onClick={() => setCadence('cron')}
              >
                Expression cron
              </button>
            </div>
            {cadence === 'quotidien' ? (
              <>
                <input
                  type="time"
                  value={form.run_time ?? '09:00'}
                  onChange={(e) => set({ run_time: e.target.value })}
                  required
                />
                <span className="hint">Heure locale du serveur.</span>
              </>
            ) : (
              <>
                <input
                  type="text"
                  className="mono"
                  value={form.cron_expression ?? ''}
                  onChange={(e) => set({ cron_expression: e.target.value })}
                  placeholder="30 8 * * 1"
                  required
                />
                <span className="hint">
                  Cinq champs : minute, heure, jour, mois, jour de semaine. Ici : lundi à 8 h 30.
                </span>
              </>
            )}
          </div>

          <div className="field check">
            <input
              id="enabled"
              type="checkbox"
              checked={form.enabled ?? true}
              onChange={(e) => set({ enabled: e.target.checked })}
            />
            <label htmlFor="enabled" style={{ textTransform: 'none', letterSpacing: 0 }}>
              Capture automatique active
            </label>
          </div>

          <div className="field">
            <label htmlFor="account">Compte connecté</label>
            <select
              id="account"
              value={form.account_id ?? ''}
              onChange={(e) => set({ account_id: e.target.value ? Number(e.target.value) : null })}
            >
              <option value="">Aucun — capture en visiteur anonyme</option>
              {comptes.map((c) => (
                <option key={c.id} value={c.id} disabled={!c.has_session}>
                  {c.name}
                  {c.has_session ? '' : ' (session à connecter)'}
                </option>
              ))}
            </select>
            <span className="hint">
              La capture réutilise la session chiffrée de ce compte (page vue en étant connecté).
              Gérez les comptes dans l’onglet « Comptes ».
            </span>
          </div>

          {!cible && (
            <div className="notice info">
              Cible Facebook ?{' '}
              <button
                type="button"
                className="btn ghost sm"
                onClick={() => set(PRESET_FACEBOOK)}
                style={{ marginLeft: 6 }}
              >
                Appliquer les réglages Facebook
              </button>
            </div>
          )}

          <details className="advanced" open={Boolean(cible)}>
            <summary>Réglages de capture</summary>

            <div className="field">
              <label htmlFor="dismiss">Éléments à fermer avant la capture</label>
              <textarea
                id="dismiss"
                value={form.dismiss_selectors ?? ''}
                onChange={(e) => set({ dismiss_selectors: e.target.value || null })}
                placeholder='[aria-label="Refuser les cookies optionnels"]'
              />
              <span className="hint">
                Sélecteurs CSS cliqués dans l’ordre, séparés par « ; ». Un élément absent est
                ignoré.
              </span>
            </div>

            <div className="field">
              <label htmlFor="hide">Éléments à masquer</label>
              <textarea
                id="hide"
                value={form.hide_selectors ?? ''}
                onChange={(e) => set({ hide_selectors: e.target.value || null })}
                placeholder="#banniere;.popup"
              />
            </div>

            <div className="field">
              <label htmlFor="fail">Faire échouer si l’adresse contient</label>
              <input
                id="fail"
                type="text"
                className="mono"
                value={form.fail_if_url_contains ?? ''}
                onChange={(e) => set({ fail_if_url_contains: e.target.value || null })}
                placeholder="login;checkpoint"
              />
              <span className="hint">
                Détecte une session expirée : mieux vaut une erreur visible qu’une capture du mur de
                connexion.
              </span>
            </div>

            <div className="field">
              <label htmlFor="expected">Élément qui doit être présent</label>
              <input
                id="expected"
                type="text"
                className="mono"
                value={form.expected_selector ?? ''}
                onChange={(e) => set({ expected_selector: e.target.value || null })}
                placeholder='[role="main"]'
              />
            </div>

            <div className="grid-2">
              <div className="field">
                <label htmlFor="profile">Profil de session</label>
                <input
                  id="profile"
                  type="text"
                  className="mono"
                  value={form.session_profile ?? ''}
                  onChange={(e) => set({ session_profile: e.target.value || null })}
                  placeholder="facebook"
                />
              </div>
              <div className="field">
                <label htmlFor="subfolder">Sous-dossier</label>
                <input
                  id="subfolder"
                  type="text"
                  value={form.subfolder ?? ''}
                  onChange={(e) => set({ subfolder: e.target.value || null })}
                  placeholder="pages"
                />
              </div>
              <div className="field">
                <label htmlFor="tags">Étiquettes</label>
                <input
                  id="tags"
                  type="text"
                  value={form.tags ?? ''}
                  onChange={(e) => set({ tags: e.target.value || null })}
                  placeholder="client-a, diocese"
                />
              </div>
              <div className="field">
                <label htmlFor="wait">Attente au chargement</label>
                <select
                  id="wait"
                  value={form.wait_until ?? 'load'}
                  onChange={(e) => set({ wait_until: e.target.value })}
                >
                  <option value="load">page chargée</option>
                  <option value="domcontentloaded">structure prête</option>
                  <option value="networkidle">réseau au repos</option>
                  <option value="commit">navigation validée</option>
                </select>
              </div>
              <div className="field">
                <label htmlFor="delay">Délai supplémentaire (ms)</label>
                <input
                  id="delay"
                  type="number"
                  min={0}
                  max={120000}
                  value={form.wait_after_load_ms ?? 2000}
                  onChange={(e) => set({ wait_after_load_ms: Number(e.target.value) })}
                />
              </div>
              <div className="field">
                <label htmlFor="w">Largeur (px)</label>
                <input
                  id="w"
                  type="number"
                  min={320}
                  max={3840}
                  value={form.viewport_width ?? 1440}
                  onChange={(e) => set({ viewport_width: Number(e.target.value) })}
                />
              </div>
              <div className="field">
                <label htmlFor="h">Hauteur (px)</label>
                <input
                  id="h"
                  type="number"
                  min={320}
                  max={2160}
                  value={form.viewport_height ?? 900}
                  onChange={(e) => set({ viewport_height: Number(e.target.value) })}
                />
              </div>
              <div className="field">
                <label htmlFor="timeout">Délai maximal (ms)</label>
                <input
                  id="timeout"
                  type="number"
                  min={1000}
                  max={300000}
                  value={form.timeout_ms ?? 45000}
                  onChange={(e) => set({ timeout_ms: Number(e.target.value) })}
                />
              </div>
              <div className="field">
                <label htmlFor="locale">Langue</label>
                <input
                  id="locale"
                  type="text"
                  className="mono"
                  value={form.locale ?? ''}
                  onChange={(e) => set({ locale: e.target.value || null })}
                  placeholder="fr-FR"
                />
              </div>
            </div>

            <div className="field check">
              <input
                id="full"
                type="checkbox"
                checked={form.full_page ?? true}
                onChange={(e) => set({ full_page: e.target.checked })}
              />
              <label htmlFor="full" style={{ textTransform: 'none', letterSpacing: 0 }}>
                Capturer la page entière
              </label>
            </div>
          </details>

          <div className="btn-row" style={{ marginTop: 18 }}>
            <button className="btn" type="submit" disabled={envoi}>
              {envoi ? 'Enregistrement…' : cible ? 'Enregistrer' : 'Créer la cible'}
            </button>
            <button type="button" className="btn ghost" onClick={onClose}>
              Annuler
            </button>
          </div>

          {/* La suppression vit ici, à l'écart des actions courantes du tableau. */}
        {cible && canDelete && (
            <div className="section" style={{ marginTop: 30 }}>
              <h3>Supprimer cette cible</h3>
              {!confirmeSuppression ? (
                <>
                  <p style={{ margin: '0 0 10px', color: 'var(--ink-soft)', fontSize: 13.5 }}>
                    La cible et tout son historique d’exécutions seront effacés. Les fichiers PNG
                    déjà enregistrés sur le disque, eux, sont conservés.
                  </p>
                  <button
                    type="button"
                    className="btn danger sm"
                    onClick={() => setConfirmeSuppression(true)}
                  >
                    Supprimer « {cible.name} »
                  </button>
                </>
              ) : (
                <>
                  <p style={{ margin: '0 0 10px', color: 'var(--safelight)', fontSize: 13.5 }}>
                    Confirmez : cette action est définitive.
                  </p>
                  <div className="btn-row">
                    <button type="button" className="btn danger sm" onClick={supprimer}>
                      Oui, supprimer définitivement
                    </button>
                    <button
                      type="button"
                      className="btn ghost sm"
                      onClick={() => setConfirmeSuppression(false)}
                    >
                      Annuler
                    </button>
                  </div>
                </>
              )}
            </div>
          )}
        </form>
      </aside>
    </div>
  )
}
