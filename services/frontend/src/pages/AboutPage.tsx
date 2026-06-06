const SOURCES = [
  { name: 'CDC', img: '/logos/cdc.png' },
  { name: 'WHO', img: '/logos/who.png' },
  { name: 'ECDC', img: '/logos/ecdc.png' },
  { name: 'ProMED', img: '/logos/promed.png' },
  { name: 'PubMed / NCBI', img: '/logos/pubmed.png' },
  { name: 'bioRxiv', img: '/logos/biorxiv.png' },
  { name: 'News Feeds', img: null },
]

function NewsIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-slate-500">
      <path strokeLinecap="round" strokeLinejoin="round" d="M12 7.5h1.5m-1.5 3h1.5m-7.5 3h7.5m-7.5 3h7.5m3-9h3.375c.621 0 1.125.504 1.125 1.125V18a2.25 2.25 0 01-2.25 2.25M16.5 7.5V18a2.25 2.25 0 002.25 2.25M16.5 7.5V4.875c0-.621-.504-1.125-1.125-1.125H4.125C3.504 3.75 3 4.254 3 4.875V18a2.25 2.25 0 002.25 2.25h13.5M6 7.5h3v3H6v-3z" />
    </svg>
  )
}

function PhaseNode({ color }: { color: string }) {
  return (
    <div
      className={`absolute -left-[21px] top-[18px] w-3 h-3 rounded-full border-2 ${color}`}
      style={{ backgroundColor: 'var(--color-bg, #0b0f1a)' }}
    />
  )
}

export function AboutPage() {
  return (
    <div className="min-h-screen pt-24 pb-16 px-6">
      <div className="mx-auto max-w-3xl">

        <div className="mb-12">
          <h1 className="text-3xl font-bold text-white mb-5">About PathogenIQ</h1>
          <p className="text-slate-400 leading-relaxed">
            PathogenIQ is an AI-powered platform that continuously ingests documents from global
            health authorities and news sources. A multi-agent pipeline extracts pathogen signals,
            synthesizes biological profiles, mines the research literature, and generates
            hypothesis-driven research strategies — all without manual curation.
          </p>
          <p className="text-slate-500 text-sm mt-4 leading-relaxed">
            All AI-generated outputs require expert review before clinical or public health
            application. PathogenIQ is a research and intelligence tool, not a diagnostic or
            treatment platform.
          </p>
        </div>

        {/* Pipeline Schematic */}
        <section className="mb-14">
          <h2 className="text-lg font-semibold text-white mb-6">Pipeline Architecture</h2>

          {/* Data Sources row with logos */}
          <div className="mb-2 p-5 rounded-xl border border-slate-700 bg-slate-800/40">
            <p className="text-xs font-medium text-slate-500 uppercase tracking-widest mb-4">Data Sources</p>
            <div className="grid grid-cols-4 sm:grid-cols-7 gap-3">
              {SOURCES.map(s => (
                <div key={s.name} className="flex flex-col items-center gap-2">
                  <div className="w-10 h-10 rounded-lg bg-white/8 border border-slate-700/60 flex items-center justify-center overflow-hidden">
                    {s.img ? (
                      <img src={s.img} alt={s.name} width={28} height={28} className="object-contain" />
                    ) : (
                      <NewsIcon />
                    )}
                  </div>
                  <span className="text-[10px] text-slate-500 text-center leading-tight font-medium">{s.name}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Timeline */}
          <div className="relative pl-7">
            <div className="absolute left-[13px] top-0 bottom-10 w-px bg-slate-700/70" />

            {/* Sentinel */}
            <div className="relative mb-3">
              <PhaseNode color="border-red-500/70" />
              <div className="p-4 rounded-xl border border-red-500/25 bg-red-500/5">
                <div className="mb-1.5">
                  <span className="text-xs font-medium px-2 py-0.5 rounded bg-red-500/15 text-red-300">Signal Detection</span>
                </div>
                <h3 className="text-sm font-semibold text-slate-200 mb-1">Sentinel Agent</h3>
                <p className="text-xs text-slate-500 leading-relaxed">
                  Scans every ingested document for pathogen mentions, normalizes extracted names to
                  canonical scientific forms, and counts occurrences per source document.
                </p>
              </div>
            </div>

            {/* Deduplicator */}
            <div className="relative mb-3">
              <PhaseNode color="border-purple-500/70" />
              <div className="p-4 rounded-xl border border-purple-500/25 bg-purple-500/5">
                <div className="mb-1.5">
                  <span className="text-xs font-medium px-2 py-0.5 rounded bg-purple-500/15 text-purple-300">Data Quality</span>
                </div>
                <h3 className="text-sm font-semibold text-slate-200 mb-1">Deduplicator</h3>
                <p className="text-xs text-slate-500 leading-relaxed">
                  Merges pathogen records that refer to the same organism across name variants,
                  abbreviations, and casing differences — prevents duplicate entries in the database.
                </p>
              </div>
            </div>

            {/* Scholar */}
            <div className="relative mb-3">
              <PhaseNode color="border-blue-500/70" />
              <div className="p-4 rounded-xl border border-blue-500/25 bg-blue-500/5">
                <div className="mb-1.5">
                  <span className="text-xs font-medium px-2 py-0.5 rounded bg-blue-500/15 text-blue-300">Biological Profiling</span>
                </div>
                <h3 className="text-sm font-semibold text-slate-200 mb-1">Scholar Agent</h3>
                <p className="text-xs text-slate-500 leading-relaxed">
                  Queries PubMed for recent peer-reviewed literature and synthesizes a structured
                  biological profile: genome type, transmission routes, reservoir hosts, fatality
                  estimates, and WHO priority status.
                </p>
              </div>
            </div>

            {/* Research + Hypothesis (parallel) */}
            <div className="relative mb-3">
              <PhaseNode color="border-slate-600" />
              <p className="text-xs text-slate-600 mb-2 pl-1">runs in parallel</p>
              <div className="grid grid-cols-2 gap-3">
                <div className="p-4 rounded-xl border border-green-500/25 bg-green-500/5">
                  <div className="mb-1.5">
                    <span className="text-xs font-medium px-2 py-0.5 rounded bg-green-500/15 text-green-300">Literature Mining</span>
                  </div>
                  <h3 className="text-sm font-semibold text-slate-200 mb-1">Research Agent</h3>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    Four domain sub-agents run PubMed queries per pathogen across molecular biology,
                    therapeutics, and clinical epidemiology.
                  </p>
                </div>
                <div className="p-4 rounded-xl border border-yellow-500/25 bg-yellow-500/5">
                  <div className="mb-1.5">
                    <span className="text-xs font-medium px-2 py-0.5 rounded bg-yellow-500/15 text-yellow-300">Research Strategy</span>
                  </div>
                  <h3 className="text-sm font-semibold text-slate-200 mb-1">Hypothesis Agent</h3>
                  <p className="text-xs text-slate-500 leading-relaxed">
                    Synthesizes research recommendations: identifies critical knowledge gaps, proposes
                    interventions, and specifies wet-lab experiments.
                  </p>
                </div>
              </div>
            </div>

            {/* Verifier */}
            <div className="relative mb-3">
              <PhaseNode color="border-orange-500/70" />
              <div className="p-4 rounded-xl border border-orange-500/25 bg-orange-500/5">
                <div className="mb-1.5">
                  <span className="text-xs font-medium px-2 py-0.5 rounded bg-orange-500/15 text-orange-300">Quality Gating</span>
                </div>
                <h3 className="text-sm font-semibold text-slate-200 mb-1">Verifier Agent</h3>
                <p className="text-xs text-slate-500 leading-relaxed">
                  Runs deterministic coherence checks and LLM-based biological-relevance validation
                  over all research and hypothesis outputs. Writes corrections back automatically.
                </p>
              </div>
            </div>

            {/* Graph Sync */}
            <div className="relative mb-3">
              <PhaseNode color="border-cyan-500/70" />
              <div className="p-4 rounded-xl border border-cyan-500/25 bg-cyan-500/5">
                <div className="mb-1.5">
                  <span className="text-xs font-medium px-2 py-0.5 rounded bg-cyan-500/15 text-cyan-300">Knowledge Graph</span>
                </div>
                <h3 className="text-sm font-semibold text-slate-200 mb-1">Graph Sync Agent</h3>
                <p className="text-xs text-slate-500 leading-relaxed">
                  Syncs all pathogen profiles into Neo4j, building a relationship graph across
                  pathogens, categories, transmission routes, and reservoir hosts.
                </p>
              </div>
            </div>

            {/* Output */}
            <div className="relative">
              <div
                className="absolute -left-[21px] top-[18px] w-3 h-3 rounded-full border-2 border-accent/70"
                style={{ backgroundColor: 'var(--color-bg, #0b0f1a)' }}
              />
              <div className="p-4 rounded-xl border border-accent/25 bg-accent/5">
                <p className="text-xs font-medium text-accent/60 uppercase tracking-widest mb-1">Output</p>
                <h3 className="text-sm font-semibold text-white mb-1">PathogenIQ Dashboard</h3>
                <p className="text-xs text-slate-500">
                  Pathogen profiles · research summaries · hypothesis reports · knowledge graph
                </p>
              </div>
            </div>
          </div>
        </section>

      </div>
    </div>
  )
}
