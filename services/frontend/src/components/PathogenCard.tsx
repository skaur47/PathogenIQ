import type { PathogenProfile } from '../types'

function sanitizeText(text: string): string {
  return text
    .replace(/[^\x00-ɏͰ-ϿḀ-ỿ -⋿]/g, ' ')
    .replace(/,(\s*,)+/g, ',')
    .replace(/,\s*\./g, '.')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

const CATEGORY_STYLES: Record<string, { bg: string; text: string; border: string }> = {
  virus:     { bg: 'bg-red-500/10',    text: 'text-red-400',    border: 'border-red-500/20' },
  bacterium: { bg: 'bg-amber-500/10',  text: 'text-amber-400',  border: 'border-amber-500/20' },
  fungus:    { bg: 'bg-purple-500/10', text: 'text-purple-400', border: 'border-purple-500/20' },
  parasite:  { bg: 'bg-green-500/10',  text: 'text-green-400',  border: 'border-green-500/20' },
  prion:     { bg: 'bg-pink-500/10',   text: 'text-pink-400',   border: 'border-pink-500/20' },
  unknown:   { bg: 'bg-slate-500/10',  text: 'text-slate-400',  border: 'border-slate-500/20' },
}

interface Props {
  pathogen: PathogenProfile
  onClick: () => void
}

export function PathogenCard({ pathogen, onClick }: Props) {
  const cat = CATEGORY_STYLES[pathogen.category] ?? CATEGORY_STYLES.unknown
  const routes = pathogen.transmission_routes?.slice(0, 3) ?? []
  const hosts = pathogen.reservoir_hosts?.slice(0, 2) ?? []

  return (
    <button
      onClick={onClick}
      className="group w-full text-left p-5 rounded-xl bg-surface border border-border
                 hover:border-accent/30 hover:bg-surface2 hover:glow-accent-sm
                 transition-all duration-200 focus:outline-none focus:ring-2
                 focus:ring-accent/40"
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-2 mb-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <span className={`inline-flex items-center px-2 py-0.5 rounded text-[11px] font-medium border ${cat.bg} ${cat.text} ${cat.border}`}>
              {pathogen.category}
            </span>
          </div>
          <h3 className="font-semibold text-slate-100 text-sm leading-tight truncate group-hover:text-accent transition-colors">
            {pathogen.species_name}
          </h3>
          {pathogen.common_name && (
            <p className="text-xs text-slate-500 mt-0.5 truncate">{pathogen.common_name}</p>
          )}
        </div>
      </div>

      {/* Description snippet */}
      {pathogen.description && (
        <p className="text-xs text-slate-400 leading-relaxed line-clamp-2 mb-3">
          {sanitizeText(pathogen.description)}
        </p>
      )}

      {/* Chips */}
      <div className="space-y-1.5">
        {routes.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[10px] text-slate-600 uppercase tracking-wide w-12 shrink-0">Routes</span>
            {routes.map(r => (
              <span key={r} className="px-1.5 py-0.5 rounded text-[10px] bg-red-500/10 text-red-400 border border-red-500/15">
                {r}
              </span>
            ))}
            {(pathogen.transmission_routes?.length ?? 0) > 3 && (
              <span className="text-[10px] text-slate-600">+{(pathogen.transmission_routes?.length ?? 0) - 3}</span>
            )}
          </div>
        )}
        {hosts.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[10px] text-slate-600 uppercase tracking-wide w-12 shrink-0">Hosts</span>
            {hosts.map(h => (
              <span key={h} className="px-1.5 py-0.5 rounded text-[10px] bg-amber-500/10 text-amber-400 border border-amber-500/15">
                {h}
              </span>
            ))}
            {(pathogen.reservoir_hosts?.length ?? 0) > 2 && (
              <span className="text-[10px] text-slate-600">+{(pathogen.reservoir_hosts?.length ?? 0) - 2}</span>
            )}
          </div>
        )}
      </div>
    </button>
  )
}
