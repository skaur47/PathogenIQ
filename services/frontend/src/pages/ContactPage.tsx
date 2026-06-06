import { useEffect, useState } from 'react'
import { CheckCircle, Mail, XCircle } from 'lucide-react'
import { api } from '../api/client'

const INPUT =
  'w-full px-3 py-2.5 rounded-lg bg-surface border border-border text-sm text-slate-200 ' +
  'placeholder:text-slate-700 focus:outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/30'

export function ContactPage() {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [loading, setLoading] = useState(false)
  const [subscribed, setSubscribed] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Unsubscribe flow — triggered when landing with ?unsubscribe=<token>
  const [unsubToken, setUnsubToken] = useState<string | null>(null)
  const [unsubState, setUnsubState] = useState<'idle' | 'loading' | 'done' | 'error'>('idle')
  const [unsubError, setUnsubError] = useState<string | null>(null)

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const token = params.get('unsubscribe')
    if (token) setUnsubToken(token)
  }, [])

  async function handleSubscribe(e: React.FormEvent) {
    e.preventDefault()
    setLoading(true)
    setError(null)
    try {
      await api.subscribe(name.trim(), email.trim())
      setSubscribed(true)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Something went wrong.')
    } finally {
      setLoading(false)
    }
  }

  async function handleUnsubscribe() {
    if (!unsubToken) return
    setUnsubState('loading')
    try {
      await api.unsubscribe(unsubToken)
      setUnsubState('done')
      // Clear the token from the URL without a reload
      window.history.replaceState({}, '', window.location.pathname)
    } catch (err: unknown) {
      setUnsubError(err instanceof Error ? err.message : 'Something went wrong.')
      setUnsubState('error')
    }
  }

  // ── Unsubscribe view ────────────────────────────────────────────────────────
  if (unsubToken) {
    return (
      <div className="min-h-screen pt-24 pb-16 px-6">
        <div className="mx-auto max-w-md text-center">
          {unsubState === 'done' ? (
            <div className="flex flex-col items-center gap-4 py-16">
              <CheckCircle className="w-12 h-12 text-accent" />
              <h2 className="text-lg font-semibold text-white">Unsubscribed</h2>
              <p className="text-slate-400 text-sm">
                You have been removed from the daily digest. You can re-subscribe any time.
              </p>
              <button
                onClick={() => setUnsubToken(null)}
                className="mt-2 text-xs text-accent hover:underline"
              >
                Subscribe again
              </button>
            </div>
          ) : unsubState === 'error' ? (
            <div className="flex flex-col items-center gap-4 py-16">
              <XCircle className="w-12 h-12 text-red-400" />
              <h2 className="text-lg font-semibold text-white">Could not unsubscribe</h2>
              <p className="text-slate-400 text-sm">{unsubError}</p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-6 py-16">
              <Mail className="w-12 h-12 text-slate-500" />
              <div>
                <h2 className="text-lg font-semibold text-white mb-2">Unsubscribe from daily digest?</h2>
                <p className="text-slate-400 text-sm">
                  You will no longer receive the PathogenIQ daily pathogen update.
                </p>
              </div>
              <button
                onClick={handleUnsubscribe}
                disabled={unsubState === 'loading'}
                className="px-5 py-2.5 rounded-lg bg-red-500/10 border border-red-500/30 text-red-300
                           text-sm font-medium hover:bg-red-500/20 transition-colors disabled:opacity-50"
              >
                {unsubState === 'loading' ? 'Unsubscribing…' : 'Yes, unsubscribe me'}
              </button>
              <button
                onClick={() => {
                  setUnsubToken(null)
                  window.history.replaceState({}, '', window.location.pathname)
                }}
                className="text-xs text-slate-600 hover:text-slate-400 transition-colors"
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      </div>
    )
  }

  // ── Subscribe view ──────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen pt-24 pb-16 px-6">
      <div className="mx-auto max-w-md">
        <div className="mb-10">
          <h1 className="text-3xl font-bold text-white mb-2">Daily Digest</h1>
          <p className="text-slate-400 text-sm leading-relaxed">
            Get a daily email summary of pathogens currently tracked by PathogenIQ —
            transmission routes, reservoir hosts, WHO priority status, and more.
            Unsubscribe at any time from the email.
          </p>
        </div>

        {subscribed ? (
          <div className="flex flex-col items-center gap-4 py-12 text-center">
            <CheckCircle className="w-12 h-12 text-accent" />
            <h2 className="text-lg font-semibold text-white">You're subscribed</h2>
            <p className="text-slate-400 text-sm">
              Your first digest will arrive tomorrow morning. Check your spam folder if you don't see it.
            </p>
            <button
              onClick={() => { setSubscribed(false); setName(''); setEmail('') }}
              className="mt-2 text-xs text-accent hover:underline"
            >
              Subscribe another address
            </button>
          </div>
        ) : (
          <form onSubmit={handleSubscribe} className="space-y-4">
            <div>
              <label className="block text-xs text-slate-500 mb-1.5">Name</label>
              <input
                type="text"
                required
                value={name}
                onChange={e => setName(e.target.value)}
                className={INPUT}
                placeholder="Your name"
              />
            </div>
            <div>
              <label className="block text-xs text-slate-500 mb-1.5">Email</label>
              <input
                type="email"
                required
                value={email}
                onChange={e => setEmail(e.target.value)}
                className={INPUT}
                placeholder="you@example.com"
              />
            </div>

            {error && (
              <p className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg
                         bg-accent text-bg font-semibold text-sm hover:bg-accent-dim
                         transition-colors disabled:opacity-60"
            >
              <Mail className="w-4 h-4" />
              {loading ? 'Subscribing…' : 'Subscribe to daily digest'}
            </button>

            <p className="text-xs text-slate-600 text-center">
              Sent every morning. Unsubscribe at any time.
            </p>
          </form>
        )}
      </div>
    </div>
  )
}
