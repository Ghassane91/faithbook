import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'

export type ModeCadence = 'quotidien' | 'intervalle' | 'cron'

interface Patch {
  run_time?: string | null
  cron_expression?: string | null
  interval_minutes?: number | null
}

interface Props {
  mode: ModeCadence
  onMode: (m: ModeCadence) => void
  runTime: string | null
  cronExpression: string | null
  intervalMinutes: number | null
  onChange: (patch: Patch) => void
  targetId?: number | null
  nomCible?: string
  timezone?: string | null
}

/**
 * Reponse de POST /api/targets/preview-cadence.
 * Tant que l'endpoint n'existe pas, le composant fonctionne sans lui : il
 * affiche ce qu'il peut calculer honnetement (le nombre de captures par jour)
 * et masque les horaires reels, qu'il ne saurait pas deviner.
 */
interface Apercu {
  next_runs: string[]
  per_day: number
  per_week: number
  avg_bytes: number | null
  bytes_per_day: number | null
  bytes_per_month: number | null
  error?: string | null
}

/**
 * Les seuls intervalles proposes. On ne saisit jamais un nombre de minutes :
 * chaque cran porte un nom, et « toutes les 237 minutes » n'existe pas.
 *
 * L'echelle s'arrete a 12 h volontairement. Un intervalle de 24 h derive :
 * si une capture part en retard, toutes les suivantes glissent. Une fois par
 * jour, c'est le mode « Tous les jours », qui tient une heure fixe.
 */
const PALIERS = [5, 10, 15, 30, 60, 120, 180, 240, 360, 720]

/** APScheduler numerote a partir de lundi : 0 = lundi ... 6 = dimanche.
 *  Ce n'est PAS la convention cron standard, ou 0 = dimanche. Verifie par
 *  l'apercu reel du backend, qui utilise le vrai declencheur. */
const JOURS = [
  { code: 0, court: 'L', long: 'lundi' },
  { code: 1, court: 'M', long: 'mardi' },
  { code: 2, court: 'M', long: 'mercredi' },
  { code: 3, court: 'J', long: 'jeudi' },
  { code: 4, court: 'V', long: 'vendredi' },
  { code: 5, court: 'S', long: 'samedi' },
  { code: 6, court: 'D', long: 'dimanche' },
]

function nommerIntervalle(minutes: number): string {
  if (minutes >= 60) {
    const h = minutes / 60
    return h === 1 ? 'toutes les heures' : `toutes les ${h} heures`
  }
  return `toutes les ${minutes} minutes`
}

function nommerJours(jours: number[]): string {
  const tries = [...new Set(jours)].sort((a, b) => a - b)
  if (tries.length === 7) return 'tous les jours'
  if (tries.length === 5 && [0, 1, 2, 3, 4].every((j) => tries.includes(j))) {
    return 'du lundi au vendredi'
  }
  if (tries.length === 2 && tries.includes(5) && tries.includes(6)) {
    return 'le week-end'
  }
  const noms = tries.map((j) => JOURS.find((x) => x.code === j)?.long ?? String(j))
  if (noms.length === 1) return `le ${noms[0]}`
  return `le ${noms.slice(0, -1).join(', ')} et le ${noms[noms.length - 1]}`
}

/** Poids lisible. On compte en Go decimaux, comme les offres de stockage. */
function poids(octets: number | null | undefined): string {
  if (!octets || octets <= 0) return '—'
  const go = octets / 1_000_000_000
  if (go >= 1) return `${go.toFixed(go >= 10 ? 0 : 1).replace('.', ',')} Go`
  const mo = octets / 1_000_000
  return `${mo.toFixed(mo >= 10 ? 0 : 1).replace('.', ',')} Mo`
}

/**
 * Relit une expression cron pour repeupler le constructeur.
 * Ne reconnait que la forme que le constructeur produit lui-meme :
 * « minute heure * * jours ». Toute autre forme renvoie null, et le champ
 * brut prend le relais — mieux vaut avouer qu'on ne sait pas lire que
 * proposer une lecture fausse.
 */
function lireCron(expr: string | null): { heure: string; jours: number[] } | null {
  if (!expr) return null
  const p = expr.trim().split(/\s+/)
  if (p.length !== 5) return null
  const [min, hr, jourMois, mois, jourSemaine] = p
  if (jourMois !== '*' || mois !== '*') return null
  if (!/^\d{1,2}$/.test(min) || !/^\d{1,2}$/.test(hr)) return null
  const heure = `${hr.padStart(2, '0')}:${min.padStart(2, '0')}`
  if (jourSemaine === '*') return { heure, jours: [0, 1, 2, 3, 4, 5, 6] }
  if (!/^[0-6](,[0-6])*$/.test(jourSemaine)) return null
  return { heure, jours: jourSemaine.split(',').map(Number) }
}

function ecrireCron(heure: string, jours: number[]): string {
  const [hh, mm] = heure.split(':')
  const tries = [...new Set(jours)].sort((a, b) => a - b)
  const js = tries.length === 7 || tries.length === 0 ? '*' : tries.join(',')
  return `${Number(mm)} ${Number(hh)} * * ${js}`
}

/** « aujourd'hui 14:30 », « demain 08:00 », « lun. 08:00 ». */
function quand(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  const heure = d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })
  const jour = d.toLocaleDateString('sv-SE')
  const maintenant = new Date()
  const aujourdhui = maintenant.toLocaleDateString('sv-SE')
  const demain = new Date(maintenant.getTime() + 86400000).toLocaleDateString('sv-SE')
  if (jour === aujourdhui) return heure
  if (jour === demain) return `demain ${heure}`
  return `${d.toLocaleDateString('fr-FR', { weekday: 'short' })} ${heure}`
}

export function ChoixCadence({
  mode,
  onMode,
  runTime,
  cronExpression,
  intervalMinutes,
  onChange,
  targetId,
  nomCible,
  timezone,
}: Props) {
  const [cronAvance, setCronAvance] = useState(false)
  const [apercu, setApercu] = useState<Apercu | null>(null)

  const minutes = intervalMinutes && intervalMinutes > 0 ? intervalMinutes : 30
  const heureQuotidienne = runTime || '09:00'
  const cronLu = lireCron(cronExpression)

  // Position du curseur : le palier le plus proche de la valeur enregistree.
  // On ne corrige pas la valeur elle-meme — une cible reglee a 45 min par
  // l'API garde ses 45 min tant que personne ne touche au curseur.
  const index = useMemo(() => {
    let meilleur = 0
    for (let i = 1; i < PALIERS.length; i += 1) {
      if (Math.abs(PALIERS[i] - minutes) < Math.abs(PALIERS[meilleur] - minutes)) meilleur = i
    }
    return meilleur
  }, [minutes])
  const horsPalier = !PALIERS.includes(minutes)

  const capturesParJour =
    mode === 'intervalle'
      ? Math.max(1, Math.round(1440 / minutes))
      : mode === 'quotidien'
        ? 1
        : cronLu
          ? cronLu.jours.length / 7
          : null

  // Aperçu reel calcule par le backend. Le navigateur ne sait pas reproduire
  // APScheduler ni le fuseau du serveur : un apercu approximatif mentirait.
  useEffect(() => {
    const client = api as unknown as { previewCadence?: (p: unknown) => Promise<Apercu> }
    if (!client.previewCadence) {
      setApercu(null)
      return
    }
    let vivant = true
    const minuteur = setTimeout(() => {
      client
        .previewCadence!({
          target_id: targetId ?? null,
          timezone_name: timezone ?? null,
          run_time: mode === 'quotidien' ? heureQuotidienne : null,
          cron_expression: mode === 'cron' ? cronExpression || null : null,
          interval_minutes: mode === 'intervalle' ? minutes : null,
        })
        .then((r) => {
          if (vivant) setApercu(r)
        })
        .catch(() => {
          if (vivant) setApercu(null)
        })
    }, 250)
    return () => {
      vivant = false
      clearTimeout(minuteur)
    }
  }, [mode, heureQuotidienne, cronExpression, minutes, targetId, timezone])

  function intention(cle: string) {
    if (cle === 'jour') {
      onMode('quotidien')
      onChange({ run_time: '08:00' })
    } else if (cle === 'matin-soir') {
      onMode('intervalle')
      onChange({ interval_minutes: 720 })
    } else if (cle === 'heure') {
      onMode('intervalle')
      onChange({ interval_minutes: 60 })
    } else if (cle === 'rapproche') {
      onMode('intervalle')
      onChange({ interval_minutes: 15 })
    }
  }

  function basculerJour(code: number) {
    const actuels = cronLu?.jours ?? [0, 1, 2, 3, 4]
    const heure = cronLu?.heure ?? '09:00'
    const suivants = actuels.includes(code)
      ? actuels.filter((j) => j !== code)
      : [...actuels, code]
    if (suivants.length === 0) return // au moins un jour, sinon rien ne part
    onChange({ cron_expression: ecrireCron(heure, suivants) })
  }

  const phrase = (() => {
    const cible = nomCible?.trim() ? `« ${nomCible.trim()} »` : 'cette page'
    if (mode === 'quotidien') return `photographiera ${cible} tous les jours à ${heureQuotidienne}`
    if (mode === 'intervalle') return `photographiera ${cible} ${nommerIntervalle(minutes)}`
    if (cronLu) return `photographiera ${cible} ${nommerJours(cronLu.jours)} à ${cronLu.heure}`
    return `photographiera ${cible} selon l'expression saisie`
  })()

  return (
    <div className="field cadence">
      <label>Cadence</label>

      {/* 1. L'intention, avant le reglage. */}
      <div className="cadence-intentions">
        <button type="button" className="btn sm ghost" onClick={() => intention('jour')}>
          Une fois par jour
        </button>
        <button type="button" className="btn sm ghost" onClick={() => intention('matin-soir')}>
          Matin et soir
        </button>
        <button type="button" className="btn sm ghost" onClick={() => intention('heure')}>
          Toutes les heures
        </button>
        <button type="button" className="btn sm ghost" onClick={() => intention('rapproche')}>
          Surveillance rapprochée
        </button>
      </div>

      {/* 2. Le mode, pour ceux qui veulent regler finement. */}
      <div className="btn-row cadence-modes">
        <button
          type="button"
          className={`btn sm ${mode === 'quotidien' ? '' : 'ghost'}`}
          onClick={() => onMode('quotidien')}
        >
          Tous les jours
        </button>
        <button
          type="button"
          className={`btn sm ${mode === 'intervalle' ? '' : 'ghost'}`}
          onClick={() => onMode('intervalle')}
        >
          Plusieurs fois par jour
        </button>
        <button
          type="button"
          className={`btn sm ${mode === 'cron' ? '' : 'ghost'}`}
          onClick={() => onMode('cron')}
        >
          Certains jours
        </button>
      </div>

      {mode === 'quotidien' && (
        <input
          type="time"
          value={heureQuotidienne}
          onChange={(e) => onChange({ run_time: e.target.value })}
          required
        />
      )}

      {mode === 'intervalle' && (
        <div className="cadence-echelle">
          <input
            type="range"
            min={0}
            max={PALIERS.length - 1}
            step={1}
            value={index}
            onChange={(e) => onChange({ interval_minutes: PALIERS[Number(e.target.value)] })}
            aria-label="Intervalle entre deux captures"
          />
          <div className="cadence-graduations">
            {PALIERS.map((m, i) => (
              <span key={m} className={i === index && !horsPalier ? 'actif' : ''}>
                {m >= 60 ? `${m / 60} h` : `${m} min`}
              </span>
            ))}
          </div>
          {horsPalier && (
            <p className="cadence-note">
              Valeur enregistrée : {minutes} min — hors des paliers proposés. Elle est conservée
              tant que tu ne touches pas au curseur.
            </p>
          )}
        </div>
      )}

      {mode === 'cron' && (
        <div className="cadence-cron">
          <div className="cadence-jours">
            {JOURS.map((j) => {
              const actif = (cronLu?.jours ?? [0, 1, 2, 3, 4]).includes(j.code)
              return (
                <button
                  key={j.code}
                  type="button"
                  className={`btn sm ${actif ? '' : 'ghost'}`}
                  onClick={() => basculerJour(j.code)}
                  title={j.long}
                  aria-pressed={actif}
                >
                  {j.court}
                </button>
              )
            })}
          </div>
          <input
            type="time"
            value={cronLu?.heure ?? '09:00'}
            onChange={(e) =>
              onChange({
                cron_expression: ecrireCron(e.target.value, cronLu?.jours ?? [0, 1, 2, 3, 4]),
              })
            }
          />
          <button
            type="button"
            className="btn sm ghost"
            onClick={() => setCronAvance((v) => !v)}
          >
            {cronAvance ? 'Masquer' : 'Avancé'}
          </button>
          {(cronAvance || (cronExpression && !cronLu)) && (
            <>
              <input
                className="mono"
                value={cronExpression ?? ''}
                onChange={(e) => onChange({ cron_expression: e.target.value })}
                placeholder="30 8 * * 1"
              />
              {cronExpression && !cronLu && (
                <p className="cadence-note">
                  Expression trop libre pour être relue par les boutons ci-dessus. Elle reste
                  active telle quelle.
                </p>
              )}
            </>
          )}
        </div>
      )}

      {/* 3. Ce que ce reglage produit, en clair. */}
      <div className="cadence-consequences">
        <p className="cadence-phrase">
          FaithBook {phrase}
          {apercu?.next_runs?.length ? <>, à partir de {quand(apercu.next_runs[0])}</> : null}.
        </p>

        {apercu?.error && <p className="cadence-erreur">Réglage invalide : {apercu.error}</p>}

        {apercu?.next_runs?.length ? (
          <p className="cadence-horaires">
            <span>Prochaines captures</span>
            {apercu.next_runs.slice(0, 5).map((d) => (
              <b key={d}>{quand(d)}</b>
            ))}
          </p>
        ) : null}

        <p className="cadence-volume">
          {/* En dessous d'une capture par jour, « 0,7 par jour » n'aide personne :
              on bascule sur la semaine, qui est l'unite reelle du reglage. */}
          {apercu && apercu.per_day < 1 ? (
            <>
              <b>{apercu.per_week}</b> capture(s) par semaine
            </>
          ) : (
            <>
              <b>
                {apercu
                  ? Math.round(apercu.per_day)
                  : capturesParJour === null
                    ? '—'
                    : Math.round(capturesParJour)}
              </b>{' '}
              capture(s) par jour
            </>
          )}
          {apercu?.bytes_per_day ? (
            <>
              {' · '}
              <b>{poids(apercu.bytes_per_day)}</b> par jour {' · '}
              <b>{poids(apercu.bytes_per_month)}</b> par mois
            </>
          ) : null}
        </p>

        {apercu?.bytes_per_month && apercu.bytes_per_month > 15_000_000_000 && (
          <p className="cadence-alerte">
            Plus de 15 Go par mois pour cette seule cible. Vérifie l'espace disque et ta
            politique de conservation avant de laisser tourner.
          </p>
        )}

        {mode === 'intervalle' && minutes < 15 && (
          <p className="cadence-alerte">
            En dessous de 15 minutes sur une page consultée avec un compte connecté, Facebook
            peut demander une vérification et couper la session. Si la page est publique,
            préfère le compte « Aucun ».
          </p>
        )}
      </div>
    </div>
  )
}
