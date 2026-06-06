import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle } from 'lucide-react'
import { api } from '../api/client'
import { PathogenCard } from '../components/PathogenCard'
import { PathogenModal } from '../components/PathogenModal'
import type { PathogenProfile, PipelineStatus } from '../types'

function StatBadge({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex flex-col items-center px-6 py-3">
      <span className="text-2xl font-bold text-accent tabular-nums">{value}</span>
      <span className="text-xs text-slate-500 mt-0.5">{label}</span>
    </div>
  )
}

function formatTimestamp(iso: string | null | undefined): string {
  if (!iso) return 'Never'
  const d = new Date(iso)
  return d.toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit',
    timeZoneName: 'short',
  })
}

function mostRecent(...timestamps: (string | null | undefined)[]): string | null {
  const valid = timestamps.filter(Boolean) as string[]
  if (!valid.length) return null
  return valid.reduce((a, b) => (new Date(a) > new Date(b) ? a : b))
}

export function HomePage() {
  const [selected, setSelected] = useState<PathogenProfile | null>(null)
  const [phase, setPhase] = useState(0)

  useEffect(() => {
    const t1 = setTimeout(() => setPhase(1), 80)
    const t2 = setTimeout(() => setPhase(2), 480)
    const t3 = setTimeout(() => setPhase(3), 880)
    const t4 = setTimeout(() => setPhase(4), 1280)
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); clearTimeout(t4) }
  }, [])

  const { data, isLoading, error } = useQuery({
    queryKey: ['pathogens'],
    queryFn: () => api.getPathogens(),
  })

  const { data: status } = useQuery<PipelineStatus>({
    queryKey: ['pipeline-status'],
    queryFn: () => api.getPipelineStatus(),
  })

  const pathogens = data?.pathogens ?? []

  const lastUpdated = status
    ? mostRecent(status.last_research_run_at, status.last_hypothesis_run_at, status.last_ingested_at)
    : null

  return (
    <div className="min-h-screen">
      {/* Hero */}
      <section className="pt-32 pb-12 px-6 text-center">
        {/* Title — appears first */}
        <h1
          className="text-5xl font-bold text-white mb-4 tracking-tight transition-all duration-700"
          style={{
            opacity: phase >= 1 ? 1 : 0,
            transform: phase >= 1 ? 'translateY(0)' : 'translateY(16px)',
          }}
        >
          PathogenIQ
        </h1>

        {/* Caption — appears second */}
        <div
          className="transition-all duration-700"
          style={{
            opacity: phase >= 2 ? 1 : 0,
            transform: phase >= 2 ? 'translateY(0)' : 'translateY(14px)',
          }}
        >
          <p className="text-lg text-slate-400 max-w-xl mx-auto leading-relaxed">
            Real-time intelligence on infectious diseases.
          </p>
          <p className="text-lg text-slate-400 max-w-xl mx-auto leading-relaxed">
            Track pathogens, understand disease dynamics, advance research.
          </p>
        </div>
      </section>

      {/* Stats bar — appears third */}
      {status && (
        <div
          className="mx-auto max-w-2xl px-6 mb-12 transition-all duration-700"
          style={{
            opacity: phase >= 3 ? 1 : 0,
            transform: phase >= 3 ? 'translateY(0)' : 'translateY(12px)',
          }}
        >
          <div className="flex divide-x divide-border rounded-2xl border border-border bg-surface overflow-hidden">
            <StatBadge label="Pathogens Tracked" value={status.total_pathogens} />
            <StatBadge label="News Articles" value={status.total_documents.toLocaleString()} />
            <StatBadge label="Research Articles" value={status.total_research_articles.toLocaleString()} />
            <div className="flex flex-col items-center justify-center px-6 py-3 flex-1">
              <span className="text-xs font-medium text-accent">Last Updated</span>
              <span className="text-xs text-slate-500 mt-0.5 text-center leading-tight">
                {formatTimestamp(lastUpdated)}
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Pathogen grid — appears last, cards stagger in */}
      <div className="mx-auto max-w-7xl px-6 pb-16">
        {isLoading ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
            {Array.from({ length: 9 }).map((_, i) => (
              <div key={i} className="h-44 rounded-xl bg-surface animate-pulse" />
            ))}
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center py-24 gap-3">
            <AlertCircle className="w-8 h-8 text-red-400" />
            <p className="text-slate-400 text-sm">Failed to load pathogens.</p>
            <p className="text-slate-600 text-xs">Make sure the API server is running at localhost:8000</p>
          </div>
        ) : (
          <>
            <p
              className="text-xs text-slate-600 mb-4 transition-all duration-500"
              style={{
                opacity: phase >= 4 ? 1 : 0,
              }}
            >
              {data?.total ?? 0} pathogen{(data?.total ?? 0) !== 1 ? 's' : ''} tracked
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {pathogens.map((p, i) => (
                <div
                  key={p.species_name}
                  className="transition-all duration-500"
                  style={{
                    opacity: phase >= 4 ? 1 : 0,
                    transform: phase >= 4 ? 'translateY(0)' : 'translateY(20px)',
                    transitionDelay: phase >= 4 ? `${i * 80}ms` : '0ms',
                  }}
                >
                  <PathogenCard
                    pathogen={p}
                    onClick={() => setSelected(p)}
                  />
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      <PathogenModal pathogen={selected} onClose={() => setSelected(null)} />
    </div>
  )
}
