import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { RoadmapEditorial } from '../components/RoadmapEditorial'

function moisCourant() {
  return new Intl.DateTimeFormat('fr-FR', { month: 'long', year: 'numeric' })
    .format(new Date())
    .toUpperCase()
}

function RegistrationCanvas() {
  const ref = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const canvas = ref.current
    if (!canvas) return
    const contexte = canvas.getContext('2d')
    if (!contexte) return
    const surface: HTMLCanvasElement = canvas
    const dessin: CanvasRenderingContext2D = contexte

    const mouvementReduit = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    let largeur = 0
    let hauteur = 0
    let animation = 0

    function redimensionner() {
      const ratio = Math.min(window.devicePixelRatio || 1, 2)
      largeur = window.innerWidth
      hauteur = window.innerHeight
      surface.width = Math.round(largeur * ratio)
      surface.height = Math.round(hauteur * ratio)
      surface.style.width = `${largeur}px`
      surface.style.height = `${hauteur}px`
      dessin.setTransform(ratio, 0, 0, ratio, 0, 0)
    }

    function dessiner(temps = 0) {
      dessin.clearRect(0, 0, largeur, hauteur)
      dessin.lineWidth = 1

      const progression = temps * 0.00008
      for (let index = 0; index < 7; index += 1) {
        const base = ((index * 0.173 + progression) % 1) * (largeur + 360) - 180
        const y = hauteur * (0.12 + index * 0.13)
        const longueur = 90 + (index % 3) * 54

        dessin.strokeStyle = `rgba(26, 224, 255, ${0.035 + index * 0.006})`
        dessin.beginPath()
        dessin.moveTo(base, y)
        dessin.lineTo(base + longueur, y - 18)
        dessin.stroke()

        dessin.strokeStyle = `rgba(255, 47, 150, ${0.03 + index * 0.005})`
        dessin.beginPath()
        dessin.moveTo(base + 11, y + 7)
        dessin.lineTo(base + longueur + 19, y - 9)
        dessin.stroke()
      }

      if (!mouvementReduit) animation = window.requestAnimationFrame(dessiner)
    }

    redimensionner()
    dessiner()
    window.addEventListener('resize', redimensionner)

    return () => {
      window.removeEventListener('resize', redimensionner)
      window.cancelAnimationFrame(animation)
    }
  }, [])

  return <canvas ref={ref} className="landing-canvas" aria-hidden="true" />
}

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

  function allerConnexion() {
    document.getElementById('landing-login')?.scrollIntoView({ behavior: 'smooth' })
  }

  function allerFonctions() {
    document.getElementById('landing-roadmap')?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <div className="landing">
      <RegistrationCanvas />

      <nav className="landing-nav" aria-label="Navigation publique">
        <span className="landing-wordmark">FaithBook</span>
        <span className="landing-nav-rule" />
        <span>VEILLE VISUELLE</span>
        <button type="button" onClick={allerConnexion}>
          Accès réservé <span aria-hidden="true">↘</span>
        </button>
      </nav>

      <main>
        <section className="landing-hero" aria-labelledby="landing-title">
          <p className="landing-kicker">
            FAITHBOOK <i>/</i> FEUILLE DE ROUTE <i>/</i> {moisCourant()}
          </p>
          <h1 id="landing-title">
            <span>Photographier</span>
            <span className="outline">ne suffit</span>
            <span>plus</span>
          </h1>

          <div className="landing-signal" aria-label="Exemple de changement détecté">
            <span className="removed">12 % de changement détecté</span>
            <span className="arrow" aria-hidden="true">→</span>
            <strong>Spartan a retiré une publication mise en ligne hier</strong>
          </div>

          <button type="button" className="landing-discover" onClick={allerFonctions}>
            Découvrir les cinq fonctions <span aria-hidden="true">↓</span>
          </button>
        </section>

        <section className="landing-stats" aria-label="Chiffres clés">
          <div><b>05</b><span>fonctions</span></div>
          <div><b>174</b><span>tests automatisés</span></div>
          <div><b>6</b><span>services actifs</span></div>
          <div><b>2</b><span>ressources existantes</span></div>
        </section>

        <section className="landing-constat">
          <p className="landing-section-label">Le constat</p>
          <div>
            <p>
              FaithBook capture, archive, compare et alerte. Tout cela fonctionne. Mais il ne dit
              toujours qu’une seule chose : <strong>que quelque chose a changé.</strong>
            </p>
            <p>
              Il accumule pourtant deux ressources que personne d’autre ne possède sur ces pages :
              une <strong>archive visuelle</strong> et un <strong>corpus de texte daté.</strong>{' '}
              Aujourd’hui, ces deux ressources servent surtout à comparer deux captures voisines,
              puis sont oubliées.
            </p>
            <p>
              Les cinq fonctions ci-dessous partent toutes de là. Elles exploitent ce qui existe
              déjà pour transformer une capture en information de veille.
            </p>
          </div>
        </section>

        <RoadmapEditorial variante="landing" id="landing-roadmap" />

        <section id="landing-login" className="landing-login" aria-labelledby="login-title">
          <div className="landing-login-copy">
            <p className="landing-section-label">La veille est déjà en marche</p>
            <h2>Entrez dans<br /><span>la chambre noire.</span></h2>
            <p>
              L’accès est réservé aux équipes autorisées. Connectez-vous pour ouvrir la planche du
              jour, vos cibles, les sessions Facebook et l’historique complet.
            </p>
          </div>

          <div className="auth-card landing-auth-card">
            <div className="auth-brand">
              <span id="login-title" className="brand-mark">FaithBook</span>
              <span className="brand-sub">
                {mode === 'login' ? 'accès réservé' : 'mot de passe oublié'}
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
        </section>
      </main>

      <footer className="landing-footer">
        <span>FaithBook · veille visuelle</span>
        <span>Accès réservé · données conservées localement</span>
      </footer>
    </div>
  )
}
