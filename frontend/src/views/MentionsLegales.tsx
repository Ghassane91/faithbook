/**
 * Mentions légales et politique de confidentialité.
 *
 * Les zones entre crochets [À COMPLÉTER] doivent être renseignées avec les
 * informations réelles de l'exploitant avant toute mise en ligne publique.
 * Ce texte est un socle conforme RGPD, pas un avis juridique.
 */
export function MentionsLegales() {
  return (
    <div style={{ maxWidth: 760 }}>
      <div className="page-head">
        <div>
          <span className="eyebrow">Informations légales</span>
          <h1>Mentions légales</h1>
          <p>Dernière mise à jour : à renseigner à la première publication.</p>
        </div>
      </div>

      <div className="legal">
        <section>
          <h2>1. Éditeur</h2>
          <p>
            Le présent service « FaithBook — captures planifiées » est édité par{' '}
            <mark>[RAISON SOCIALE]</mark>, <mark>[FORME JURIDIQUE]</mark> au capital de{' '}
            <mark>[MONTANT]</mark>, immatriculée au RCS de <mark>[VILLE]</mark> sous le numéro{' '}
            <mark>[SIREN/SIRET]</mark>.
          </p>
          <dl className="legal-kv">
            <dt>Siège social</dt>
            <dd><mark>[ADRESSE COMPLÈTE]</mark></dd>
            <dt>Directeur de la publication</dt>
            <dd><mark>[NOM DU RESPONSABLE]</mark></dd>
            <dt>Contact</dt>
            <dd><mark>[E-MAIL]</mark> · <mark>[TÉLÉPHONE]</mark></dd>
            <dt>TVA intracommunautaire</dt>
            <dd><mark>[N° TVA]</mark></dd>
          </dl>
        </section>

        <section>
          <h2>2. Hébergement</h2>
          <p>
            Le service est hébergé par <mark>[HÉBERGEUR]</mark>, <mark>[ADRESSE DE L’HÉBERGEUR]</mark>,{' '}
            <mark>[CONTACT HÉBERGEUR]</mark>.
          </p>
        </section>

        <section>
          <h2>3. Objet du service</h2>
          <p>
            L’application réalise, à des horaires configurés par l’utilisateur, des captures d’écran
            automatisées de pages web désignées par ce dernier, puis les archive et en conserve
            l’historique. Elle est destinée à un usage professionnel de veille et d’archivage.
          </p>
        </section>

        <section>
          <h2>4. Accès et responsabilité de l’utilisateur</h2>
          <p>
            L’accès est strictement réservé aux personnes disposant d’un identifiant. L’utilisateur
            est responsable de la confidentialité de ses identifiants et des adresses qu’il choisit
            de capturer.
          </p>
          <p>
            L’utilisateur s’engage à ne configurer que des captures qu’il est légalement autorisé à
            réaliser, dans le respect des conditions d’utilisation des sites tiers concernés, du
            droit d’auteur et des droits des personnes. La capture automatisée de plateformes
            tierces peut être contraire à leurs conditions d’utilisation : cette appréciation
            relève de la seule responsabilité de l’utilisateur.
          </p>
        </section>

        <section>
          <h2>5. Données personnelles (RGPD)</h2>
          <p>
            <strong>Données de compte.</strong> Pour permettre l’authentification, le service
            traite votre identifiant, une empreinte chiffrée de votre mot de passe, ainsi que les
            dates et adresses IP de connexion. La base légale est l’exécution du service et
            l’intérêt légitime à en sécuriser l’accès.
          </p>
          <p>
            <strong>Contenu capturé.</strong> Les captures d’écran peuvent contenir des données
            personnelles présentes sur les pages ciblées. <mark>[RESPONSABLE DE TRAITEMENT]</mark>{' '}
            en est responsable de traitement ; l’éditeur n’agit qu’en qualité de fournisseur
            technique.
          </p>
          <p>
            <strong>Conservation.</strong> Les captures et l’historique sont conservés{' '}
            <mark>[DURÉE, ex. 90 jours]</mark>, puis supprimés automatiquement. Les journaux de
            connexion sont conservés <mark>[DURÉE]</mark>.
          </p>
          <p>
            <strong>Destinataires.</strong> Les données ne sont ni cédées ni vendues. Elles sont
            stockées sur l’infrastructure de l’éditeur et ne sont accessibles qu’aux utilisateurs
            authentifiés et à <mark>[TIERS ÉVENTUELS]</mark>.
          </p>
          <p>
            <strong>Vos droits.</strong> Vous disposez d’un droit d’accès, de rectification,
            d’effacement, de limitation et d’opposition. Pour les exercer, écrivez à{' '}
            <mark>[E-MAIL DPO / CONTACT]</mark>. Vous pouvez introduire une réclamation auprès de la
            CNIL (www.cnil.fr).
          </p>
        </section>

        <section>
          <h2>6. Cookies</h2>
          <p>
            Le service dépose un unique cookie strictement nécessaire à l’authentification
            (maintien de la session). Aucun cookie de mesure d’audience ni de publicité n’est
            utilisé ; aucun consentement préalable n’est donc requis pour ce cookie technique.
          </p>
        </section>

        <section>
          <h2>7. Propriété intellectuelle</h2>
          <p>
            L’interface, sa structure et son code sont la propriété de l’éditeur. Les contenus
            capturés demeurent la propriété de leurs titulaires respectifs ; leur archivage via ce
            service ne confère aucun droit sur ceux-ci.
          </p>
        </section>

        <section>
          <h2>8. Contact</h2>
          <p>
            Pour toute question relative aux présentes mentions ou au traitement de vos données :{' '}
            <mark>[E-MAIL DE CONTACT]</mark>.
          </p>
        </section>

        <p className="legal-note">
          Ce document est un modèle de base fourni avec l’application. Il doit être relu et complété
          par l’exploitant, au besoin avec un conseil juridique, avant toute mise en production.
        </p>
      </div>
    </div>
  )
}
