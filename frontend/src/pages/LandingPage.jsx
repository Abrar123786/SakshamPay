import BackendStatus from '../components/BackendStatus'

/**
 * Minimal placeholder that verifies the P-2 setup (rendering, routing, styling,
 * API client). The real landing page is built in a later prompt.
 */
export default function LandingPage() {
  return (
    <div className="mx-auto grid max-w-6xl gap-12 px-6 py-16 lg:grid-cols-[1fr_380px] lg:py-24">
      <div>
        <p className="text-sm font-medium text-brand">Pre-transaction risk assessment</p>
        <h1 className="mt-3 max-w-2xl text-4xl font-semibold tracking-tight text-ink sm:text-5xl">
          Check a payment before it leaves.
        </h1>
        <p className="mt-5 max-w-xl text-lg leading-relaxed text-ink-muted">
          SakshamPay scores each simulated payment with transparent rules and an anomaly model,
          explains what looks unusual, and lets you cancel, verify or continue.
        </p>
        <p className="mt-8 max-w-xl border-l-2 border-line-strong pl-4 text-sm text-ink-subtle">
          Project setup preview. Product pages arrive in later development stages.
        </p>
      </div>

      <div className="self-start">
        <BackendStatus />
      </div>
    </div>
  )
}
