import { useState, useMemo } from 'react'
import { useQuery, useQueries } from '@tanstack/react-query'
import { ExternalLink, AlertCircle } from 'lucide-react'
import { api } from '../api/client'
import type { ResearchArticle } from '../types'

const CATEGORY_STYLES: Record<string, string> = {
  molecular_biology:    'text-blue-400 bg-blue-500/10 border-blue-500/20',
  experiments:          'text-green-400 bg-green-500/10 border-green-500/20',
  therapeutics:         'text-cyan-400 bg-cyan-500/10 border-cyan-500/20',
  clinical_epidemiology:'text-orange-400 bg-orange-500/10 border-orange-500/20',
  infection_mechanism:  'text-purple-400 bg-purple-500/10 border-purple-500/20',
  wet_lab:              'text-slate-400 bg-slate-500/10 border-slate-500/20',
  clinical_trial:       'text-yellow-400 bg-yellow-500/10 border-yellow-500/20',
  vaccine_therapy:      'text-pink-400 bg-pink-500/10 border-pink-500/20',
  unknown:              'text-slate-400 bg-slate-500/10 border-slate-500/20',
}

const CATEGORY_LABELS: Record<string, string> = {
  molecular_biology:    'Molecular Biology',
  experiments:          'Experiments',
  therapeutics:         'Therapeutics',
  clinical_epidemiology:'Clinical Epi',
  infection_mechanism:  'Infection Mechanism',
  wet_lab:              'Wet Lab',
  clinical_trial:       'Clinical Trial',
  vaccine_therapy:      'Vaccine / Therapy',
  unknown:              'Unknown',
}

interface ArticleWithPathogen extends ResearchArticle {
  pathogen_name: string
}

function ArticleCard({ article }: { article: ArticleWithPathogen }) {
  const catStyle = CATEGORY_STYLES[article.article_category] ?? CATEGORY_STYLES.unknown
  const catLabel = CATEGORY_LABELS[article.article_category] ?? article.article_category

  return (
    <article className="flex gap-4 p-4 rounded-xl border border-border bg-surface hover:border-white/10 hover:bg-surface2 transition-all group">
      <div className="flex-1 min-w-0 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`px-2 py-0.5 rounded text-[11px] font-semibold uppercase border ${catStyle}`}>
            {catLabel}
          </span>
          <span className="text-[11px] text-slate-500 px-2 py-0.5 rounded border border-slate-700/50 bg-slate-800/30 italic">
            {article.pathogen_name}
          </span>
          {article.published_date && (
            <span className="text-xs text-slate-600">{article.published_date}</span>
          )}
        </div>
        <p className="text-sm font-medium text-slate-200 leading-snug group-hover:text-white transition-colors line-clamp-2">
          {article.title || 'Untitled article'}
        </p>
        {article.authors && (
          <p className="text-xs text-slate-600 truncate">{article.authors}</p>
        )}
        {article.article_summary && (
          <p className="text-xs text-slate-500 leading-relaxed line-clamp-2">{article.article_summary}</p>
        )}
      </div>
      {article.source_url && (
        <a
          href={article.source_url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 self-start p-2 rounded-lg text-slate-500 hover:text-accent hover:bg-accent/10 transition-colors"
          title="Open on PubMed"
        >
          <ExternalLink className="w-4 h-4" />
        </a>
      )}
    </article>
  )
}

export function ResearchPage() {
  const [selected, setSelected] = useState('all')

  const { data: pathogensData } = useQuery({
    queryKey: ['pathogens'],
    queryFn: () => api.getPathogens(),
  })
  const pathogens = pathogensData?.pathogens ?? []

  const researchQueries = useQueries({
    queries: pathogens.map(p => ({
      queryKey: ['research', p.species_name],
      queryFn: () => api.getResearch(p.species_name).catch(() => null),
      staleTime: 5 * 60 * 1000,
      retry: false,
    })),
  })

  const allArticles: ArticleWithPathogen[] = useMemo(() => {
    return researchQueries
      .filter(q => q.data?.articles?.length)
      .flatMap(q =>
        (q.data!.articles ?? []).map(a => ({
          ...a,
          pathogen_name: q.data!.pathogen_name,
        }))
      )
  }, [researchQueries])

  const pathogensWithResearch = useMemo(() => {
    return pathogens.filter((_, i) => researchQueries[i]?.data?.articles?.length)
  }, [pathogens, researchQueries])

  const displayedArticles = useMemo(() => {
    if (selected === 'all') return allArticles
    return allArticles.filter(a => a.pathogen_name === selected)
  }, [allArticles, selected])

  const isLoading = !pathogensData || (pathogens.length > 0 && researchQueries.some(q => q.isLoading))

  return (
    <div className="min-h-screen pt-24 pb-16 px-6">
      <div className="mx-auto max-w-4xl">

        {/* Header */}
        <div className="mb-10">
          <h1 className="text-3xl font-bold text-white mb-2">Research</h1>
          <p className="text-slate-400 text-sm">
            Peer-reviewed articles gathered by the Research Agent across molecular biology, therapeutics, experiments, and clinical epidemiology.
          </p>
        </div>

        {/* Pathogen filter chips */}
        <div className="flex gap-1.5 flex-wrap mb-6">
          {['all', ...pathogensWithResearch.map(p => p.species_name)].map(name => (
            <button
              key={name}
              onClick={() => setSelected(name)}
              className={[
                'px-3 py-1.5 rounded-md text-xs font-medium transition-all',
                selected === name
                  ? 'bg-accent/15 text-accent border border-accent/30'
                  : 'text-slate-400 hover:text-slate-200 border border-transparent hover:border-border hover:bg-white/5',
              ].join(' ')}
            >
              {name}
            </button>
          ))}
        </div>

        {/* Results */}
        {isLoading ? (
          <div className="space-y-3">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-28 rounded-xl bg-surface animate-pulse" />
            ))}
          </div>
        ) : !displayedArticles.length ? (
          <div className="py-16 text-center">
            <AlertCircle className="w-6 h-6 text-slate-600 mx-auto mb-3" />
            <p className="text-slate-500">No research articles found.</p>
            {selected !== 'all' && (
              <p className="text-slate-600 text-xs mt-1">Try selecting a different pathogen or "all".</p>
            )}
          </div>
        ) : (
          <>
            <p className="text-xs text-slate-600 mb-4">
              {displayedArticles.length} article{displayedArticles.length !== 1 ? 's' : ''}
              {selected !== 'all' ? ` for ${selected}` : ''}
            </p>
            <div className="space-y-3">
              {displayedArticles.map((article, i) => (
                <ArticleCard
                  key={`${article.pathogen_name}-${article.pmid ?? i}`}
                  article={article}
                />
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
