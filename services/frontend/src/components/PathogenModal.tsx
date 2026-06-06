import { useEffect, useState } from 'react'
import { X } from 'lucide-react'
import type { PathogenProfile } from '../types'
import { ResearchSection } from './ResearchSection'
import { HypothesisSection } from './HypothesisSection'
import { SourcesSection } from './SourcesSection'

function sanitizeText(text: string): string {
  return text
    .replace(/[^\x00-ɏͰ-ϿḀ-ỿ -⋿]/g, ' ')
    .replace(/,(\s*,)+/g, ',')
    .replace(/,\s*\./g, '.')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

const CATEGORY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  virus:     { bg: 'bg-red-500/15',    text: 'text-red-400',    border: 'border-red-500/25' },
  bacterium: { bg: 'bg-amber-500/15',  text: 'text-amber-400',  border: 'border-amber-500/25' },
  fungus:    { bg: 'bg-purple-500/15', text: 'text-purple-400', border: 'border-purple-500/25' },
  parasite:  { bg: 'bg-green-500/15',  text: 'text-green-400',  border: 'border-green-500/25' },
  prion:     { bg: 'bg-pink-500/15',   text: 'text-pink-400',   border: 'border-pink-500/25' },
  unknown:   { bg: 'bg-slate-500/15',  text: 'text-slate-400',  border: 'border-slate-500/25' },
}

const TABS = [
  { key: 'overview',   label: 'Overview' },
  { key: 'research',   label: 'Research' },
  { key: 'hypothesis', label: 'Hypothesis' },
  { key: 'sources',    label: 'Sources' },
]

interface Props {
  pathogen: PathogenProfile | null
  onClose: () => void
}

export function PathogenModal({ pathogen, onClose }: Props) {
  const [tab, setTab] = useState('overview')

  // Reset tab when pathogen changes
  useEffect(() => {
    if (pathogen) setTab('overview')
  }, [pathogen?.species_name])

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handler)
    return () => document.removeEventListener('keydown', handler)
  }, [onClose])

  // Prevent body scroll
  useEffect(() => {
    if (pathogen) document.body.style.overflow = 'hidden'
    else document.body.style.overflow = ''
    return () => { document.body.style.overflow = '' }
  }, [pathogen])

  if (!pathogen) return null

  const cat = CATEGORY_STYLES[pathogen.category] ?? CATEGORY_STYLES.unknown

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Panel */}
      <div className="relative w-full max-w-3xl max-h-[90vh] flex flex-col rounded-2xl bg-surface border border-border shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="shrink-0 px-6 pt-6 pb-0 border-b border-border">
          <div className="flex items-start justify-between gap-4 mb-4">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-2 flex-wrap">
                <span className={`inline-flex items-center px-2.5 py-0.5 rounded-md text-xs font-medium border ${cat.bg} ${cat.text} ${cat.border}`}>
                  {pathogen.category}
                </span>
              </div>
              <h2 className="text-xl font-bold text-white leading-tight">{pathogen.species_name}</h2>
              {pathogen.common_name && (
                <p className="text-sm text-slate-400 mt-0.5">{pathogen.common_name}</p>
              )}
              {pathogen.ncbi_taxonomy_id && (
                <p className="text-xs text-slate-600 mt-1 font-mono">
                  NCBI:{pathogen.ncbi_taxonomy_id}
                </p>
              )}
            </div>
            <button
              onClick={onClose}
              className="shrink-0 p-2 rounded-lg text-slate-500 hover:text-white hover:bg-white/10 transition-colors"
            >
              <X className="w-5 h-5" />
            </button>
          </div>

          {/* Tabs */}
          <div className="flex gap-0.5 -mb-px">
            {TABS.map(({ key, label }) => (
              <button
                key={key}
                onClick={() => setTab(key)}
                className={[
                  'px-4 py-2.5 text-sm font-medium border-b-2 transition-all',
                  tab === key
                    ? 'border-accent text-accent'
                    : 'border-transparent text-slate-400 hover:text-slate-200',
                ].join(' ')}
              >
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* Scrollable content */}
        <div className="flex-1 overflow-y-auto p-6">
          {tab === 'overview' && (
            <div className="space-y-5">
              {/* Description */}
              {pathogen.description ? (
                <div>
                  <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Description</h3>
                  <p className="text-sm text-slate-300 leading-relaxed">{sanitizeText(pathogen.description)}</p>
                </div>
              ) : (
                <p className="text-sm text-slate-500 italic">No description available.</p>
              )}

              {/* Transmission routes */}
              {(pathogen.transmission_routes?.length ?? 0) > 0 && (
                <div>
                  <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Transmission Routes</h3>
                  <div className="flex flex-wrap gap-2">
                    {pathogen.transmission_routes!.map(r => (
                      <span key={r} className="px-2.5 py-1 rounded-md text-sm bg-red-500/10 text-red-300 border border-red-500/20">
                        {r}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Reservoir hosts */}
              {(pathogen.reservoir_hosts?.length ?? 0) > 0 && (
                <div>
                  <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-2">Reservoir Hosts</h3>
                  <div className="flex flex-wrap gap-2">
                    {pathogen.reservoir_hosts!.map(h => (
                      <span key={h} className="px-2.5 py-1 rounded-md text-sm bg-amber-500/10 text-amber-300 border border-amber-500/20">
                        {h}
                      </span>
                    ))}
                  </div>
                </div>
              )}

            </div>
          )}

          {tab === 'research' && <ResearchSection pathogenName={pathogen.species_name} />}
          {tab === 'hypothesis' && <HypothesisSection pathogenName={pathogen.species_name} />}
          {tab === 'sources' && <SourcesSection pathogenName={pathogen.species_name} />}
        </div>
      </div>
    </div>
  )
}
