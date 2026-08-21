import { useState, type ReactNode } from 'react'

interface FonctionRoadmap {
  numero: string
  titre: string
  texte: ReactNode
  complement: ReactNode
  exempleLabel: string
  exemple: ReactNode
  effort: string
  valeur: string
  donnee: string
  couleur: 'cyan' | 'magenta'
}

const FONCTIONS: FonctionRoadmap[] = [
  {
    numero: '01',
    titre: 'Ce qui disparaît',
    texte: (
      <>
        Une publication retirée est souvent l’événement le plus révélateur d’une veille :
        communication corrigée, promotion annulée, message de crise effacé.{' '}
        <strong>Aucun outil ne le signale</strong> — tous regardent ce qui apparaît.
      </>
    ),
    complement: (
      <>
        Le plus frappant : la donnée existe déjà et se perd. La fonction qui compare deux
        captures renvoie deux listes, les lignes apparues et les lignes disparues. Seule la
        première sert vraiment aujourd’hui.
      </>
    ),
    exempleLabel: 'Ce que vous recevriez',
    exemple:
      'Spartan a retiré une publication mise en ligne hier à 14 h. Elle annonçait une offre à −40 % jusqu’au 15 août.',
    effort: 'une demi-journée',
    valeur: 'très élevée',
    donnee: 'déjà calculée',
    couleur: 'cyan',
  },
  {
    numero: '02',
    titre: 'Regarder les images',
    texte: (
      <>
        C’est la contradiction actuelle du produit :{' '}
        <strong>un outil de veille visuelle qui n’analyse que du texte.</strong> Les captures
        pleine page s’empilent depuis des semaines sans que personne ne les regarde.
      </>
    ),
    complement: (
      <>
        Un modèle capable de voir signalerait ce que le texte tait : une publication qui n’est
        qu’une affiche, un changement de charte graphique, une photo de couverture remplacée, un
        badge ou une certification ajoutés.
      </>
    ),
    exempleLabel: 'Ce que vous recevriez',
    exemple:
      'La photo de couverture de Spypoint a changé. Le nouveau visuel met en avant un produit absent du précédent.',
    effort: '2 à 3 jours',
    valeur: 'différenciante',
    donnee: 'déjà stockée',
    couleur: 'magenta',
  },
  {
    numero: '03',
    titre: 'Interroger la mémoire',
    texte: (
      <>
        Le texte de chaque capture est conservé depuis des semaines. C’est un corpus daté que
        personne d’autre ne possède sur ces pages — et il ne sert aujourd’hui qu’à comparer deux
        instants voisins.
      </>
    ),
    complement: (
      <>
        Le rendre interrogeable transforme un outil de surveillance en mémoire consultable. C’est
        le genre de fonction dont on ne se passe plus une fois qu’on l’a essayée.
      </>
    ),
    exempleLabel: 'Ce que vous pourriez demander',
    exemple: (
      <>
        <span>Depuis quand Spypoint parle-t-il de son nouveau produit ?</span>
        <span>
          Première mention le 12 juin, puis sept publications jusqu’au 28 juillet. Le rythme
          s’accélère depuis trois semaines.
        </span>
      </>
    ),
    effort: 'une semaine',
    valeur: 'justifie un abonnement',
    donnee: 'déjà en base',
    couleur: 'cyan',
  },
  {
    numero: '04',
    titre: 'L’anormal, sans réglage',
    texte: (
      <>
        Plutôt que d’exiger une liste de mots-clés, le système apprend le rythme propre à chaque
        page — fréquence, longueur, ton — et signale ce qui en sort.
      </>
    ),
    complement: (
      <>
        C’est ici que le mot « intelligent » prend un sens concret : aucune configuration. L’outil
        découvre seul ce qui est normal pour chaque page, et ce qui ne l’est pas.
      </>
    ),
    exempleLabel: 'Ce que vous recevriez',
    exemple: (
      <>
        <span>Spartan publie deux fois par semaine en moyenne. Six publications en deux jours.</span>
        <span>
          Spypoint n’a rien publié depuis 21 jours — son plus long silence depuis six mois.
        </span>
      </>
    ),
    effort: '3 à 4 jours',
    valeur: 'élevée',
    donnee: 'historique existant',
    couleur: 'magenta',
  },
  {
    numero: '05',
    titre: 'Lire une stratégie',
    texte: (
      <>
        Chaque publication nouvelle étiquetée automatiquement : recrutement, produit, événement,
        promotion, communication de crise. Puis les proportions dans le temps.
      </>
    ),
    complement: (
      <>
        Une suite de captures devient une lecture stratégique. Un concurrent qui recrute
        massivement prépare quelque chose ; celui qui ne parle plus que de promotions a un
        problème de volume.
      </>
    ),
    exempleLabel: 'Ce que vous liriez',
    exemple:
      '40 % des publications de Spypoint ce trimestre concernent le recrutement, contre 12 % au trimestre précédent.',
    effort: '3 jours',
    valeur: 'lecture de long terme',
    donnee: 'corpus existant',
    couleur: 'cyan',
  },
]

interface RoadmapProps {
  variante: 'landing' | 'accueil'
  id: string
}

export function RoadmapEditorial({ variante, id }: RoadmapProps) {
  // Une seule fonction ouverte a la fois : c est ce qui garde la page courte.
  const [ouverte, setOuverte] = useState<string | null>(null)

  return (
    <div id={id} className={`${variante}-roadmap editorial-roadmap`}>
      {FONCTIONS.map((fonction) => (
        <details
          key={fonction.numero}
          open={ouverte === fonction.numero}
          onToggle={(e) => {
            if (e.currentTarget.open) setOuverte(fonction.numero)
            else if (ouverte === fonction.numero) setOuverte(null)
          }}
          className={`${variante}-feature editorial-feature ${fonction.couleur}`}
        >
          <summary className={`${variante}-feature-tete editorial-feature-tete`}>
            <span
              className={`${variante}-feature-number editorial-feature-number`}
              aria-hidden="true"
            >
              {fonction.numero}
            </span>
            <span className="editorial-feature-intitule">
              <span className={`${variante}-section-label editorial-section-label`}>
                Fonction {fonction.numero}
              </span>
              <h2 id={`${variante}-fonction-${fonction.numero}`}>{fonction.titre}</h2>
            </span>
          </summary>
          <div className={`${variante}-feature-body editorial-feature-body`}>
            <p>{fonction.texte}</p>
            <p>{fonction.complement}</p>
            <div className={`${variante}-example editorial-example`}>
              <span>{fonction.exempleLabel}</span>
              <strong>{fonction.exemple}</strong>
            </div>
            <dl className={`${variante}-meta editorial-meta`}>
              <div><dt>Effort</dt><dd>{fonction.effort}</dd></div>
              <div><dt>Valeur</dt><dd>{fonction.valeur}</dd></div>
              <div><dt>Donnée</dt><dd>{fonction.donnee}</dd></div>
            </dl>
          </div>
        </details>
      ))}
    </div>
  )
}
