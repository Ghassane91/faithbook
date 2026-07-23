import { useEffect, useRef, useState } from 'react'
import { api } from '../api'

interface Props {
  beforeId: number
  afterId: number
  changePct: number | null
  onClose: () => void
}

/**
 * Comparateur avant/après plein écran : un curseur révèle l'ancienne capture
 * sous la nouvelle. Les deux images sont calées en haut à la même largeur, donc
 * on voit exactement ce qui a bougé. La page reste scrollable.
 */
export function Comparaison({ beforeId, afterId, changePct, onClose }: Props) {
  const [pos, setPos] = useState(50)
  const [w, setW] = useState(0)
  const stageRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const measure = () => setW(stageRef.current?.clientWidth ?? 0)
    measure()
    const id = window.setTimeout(measure, 60) // après la mise en page
    window.addEventListener('resize', measure)
    return () => {
      window.clearTimeout(id)
      window.removeEventListener('resize', measure)
    }
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="cmp-overlay" role="dialog" aria-modal="true" aria-label="Comparaison avant/après">
      <div className="cmp-bar">
        <div>
          <span className="eyebrow">Comparaison avant / après</span>
          {changePct != null && (
            <span className="tag changed" style={{ marginLeft: 10 }}>
              {changePct} % de changement
            </span>
          )}
        </div>
        <div className="cmp-legend mono">
          <span>← Avant</span>
          <span>Après →</span>
        </div>
        <button className="btn ghost sm" onClick={onClose}>
          Fermer
        </button>
      </div>

      <div className="cmp-scroll">
        <div className="cmp-stage" ref={stageRef}>
          {/* Nouvelle capture (au-dessous), définit la hauteur */}
          <img className="cmp-base" src={api.screenshotUrl(afterId)} alt="Après" />
          {/* Ancienne capture, révélée de la gauche jusqu'au curseur */}
          <div className="cmp-clip" style={{ width: `${pos}%` }}>
            <img src={api.screenshotUrl(beforeId)} alt="Avant" style={{ width: w ? `${w}px` : '100%' }} />
          </div>
          <div className="cmp-divider" style={{ left: `${pos}%` }}>
            <span className="cmp-knob" aria-hidden>
              ⇆
            </span>
          </div>
        </div>
      </div>

      <div className="cmp-control">
        <input
          type="range"
          min={0}
          max={100}
          value={pos}
          onChange={(e) => setPos(Number(e.target.value))}
          aria-label="Position du curseur de comparaison"
        />
      </div>
    </div>
  )
}
