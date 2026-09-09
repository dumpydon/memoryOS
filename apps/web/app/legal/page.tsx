import Link from "next/link";

export const metadata = {
  title: "MemoryOS — terms and privacy",
  description:
    "Terms of use and privacy notes for the MemoryOS portfolio demo.",
};

export default function LegalPage() {
  return (
    <div className="page-wrap legal-page">
      <header className="page-header legal-header">
        <div>
          <div className="breadcrumb">
            <span>MemoryOS</span>
            <span>/</span>
            <strong>Legal</strong>
          </div>
          <h1>Terms and privacy</h1>
          <p className="page-subtitle">
            A short, plain-language note for this portfolio project and its demo
            environment.
          </p>
        </div>
        <Link className="secondary-button" href="/">
          Back to overview
        </Link>
      </header>

      <div className="legal-layout">
        <section className="panel legal-card" id="terms-of-use">
          <span className="eyebrow">Terms of use</span>
          <h2>Use MemoryOS responsibly</h2>
          <p>
            MemoryOS is a portfolio demonstration for exploring long-term memory
            behavior. Demo records are fictional and are provided for evaluation
            and learning.
          </p>
          <p>
            Use live mode only with data you are authorized to send. Do not
            submit passwords, private keys, access tokens, or other sensitive
            material. The project is provided as-is for demonstration purposes.
          </p>
        </section>

        <section className="panel legal-card" id="privacy-policy">
          <span className="eyebrow">Privacy policy</span>
          <h2>What the demo keeps private</h2>
          <p>
            Demo content is fictional. The owner token entered in Settings stays
            in React runtime memory and is cleared when the page reloads; it is
            not written to localStorage or cookies.
          </p>
          <p>
            Live interactions may be sent to the model provider configured by
            the owner. Review that provider’s policies before using live mode,
            and avoid sending information that should not leave your
            environment.
          </p>
        </section>
      </div>

      <div className="legal-watermark" title="Built by Dumpydon">
        <span className="legal-watermark-mark" aria-hidden="true">
          D
        </span>
        <div>
          <strong>Built by Dumpydon</strong>
          <a href="mailto:apiyush171@gmail.com">apiyush171@gmail.com</a>
        </div>
      </div>
    </div>
  );
}
