import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink, BookOpen, FlaskConical, Pill, Activity } from 'lucide-react'
import { api } from '../api/client'
import type { ResearchArticle } from '../types'

const TABS = [
  { key: 'all',                  label: 'All',               icon: BookOpen },
  { key: 'molecular_biology',    label: 'Molecular Biology', icon: Dna },
  { key: 'clinical_epidemiology',label: 'Clinical Epidemiology', icon: Activity },
  { key: 'therapeutics',         label: 'Therapeutics',      icon: Pill },
  { key: 'experiments',          label: 'Experiments',       icon: FlaskConical },
]

// Inline Dna icon (lucide doesn't export Dna in all versions)
function Dna({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M2 15c6.667-6 13.333 0 20-6"/>
      <path d="M9 22c1.798-1.998 2.518-3.995 2.807-5.993"/>
      <path d="M10 9.33c-1 .773-2 1.54-2 2.67"/>
      <path d="M5 20.06c.15-.79.55-1.61 1.23-2.39"/>
      <path d="M2 9c6.667 6 13.333 0 20 6"/>
      <path d="M15 2c-1.798 1.998-2.518 3.995-2.807 5.993"/>
      <path d="M14 14.67c1-.773 2-1.54 2-2.67"/>
      <path d="M19 3.94c-.15.79-.55 1.61-1.23 2.39"/>
    </svg>
  )
}

const CATEGORY_LABEL: Record<string, string> = {
  molecular_biology: 'Molecular Biology',
  experiments: 'Experiments',
  therapeutics: 'Therapeutics',
  clinical_epidemiology: 'Clinical Epidemiology',
  infection_mechanism: 'Infection Mechanism',
  wet_lab: 'Wet Lab',
  clinical_trial: 'Clinical Trial',
  vaccine_therapy: 'Vaccine/Therapy',
}

const CATEGORY_COLOR: Record<string, string> = {
  molecular_biology: 'text-blue-400 bg-blue-500/10 border-blue-500/20',
  experiments: 'text-purple-400 bg-purple-500/10 border-purple-500/20',
  therapeutics: 'text-green-400 bg-green-500/10 border-green-500/20',
  clinical_epidemiology: 'text-orange-400 bg-orange-500/10 border-orange-500/20',
  infection_mechanism: 'text-red-400 bg-red-500/10 border-red-500/20',
  wet_lab: 'text-cyan-400 bg-cyan-500/10 border-cyan-500/20',
  clinical_trial: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20',
  vaccine_therapy: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/20',
}

function ArticleCard({ article }: { article: ResearchArticle }) {
  const catColor = CATEGORY_COLOR[article.article_category] ?? 'text-slate-400 bg-slate-500/10 border-slate-500/20'
  const catLabel = CATEGORY_LABEL[article.article_category] ?? article.article_category

  return (
    <div className="rounded-lg border border-border bg-bg p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1.5 flex-wrap">
            <span className={`px-2 py-0.5 rounded text-[11px] font-medium border ${catColor}`}>
              {catLabel}
            </span>
            {article.published_date && (
              <span className="text-[11px] text-slate-600">{article.published_date}</span>
            )}
          </div>
          <p className="text-sm font-medium text-slate-200 leading-snug">{article.title}</p>
          {article.authors && (
            <p className="text-xs text-slate-500 mt-0.5 truncate">{article.authors}</p>
          )}
        </div>
        {article.source_url && (
          <a
            href={article.source_url}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 p-1.5 rounded-md text-slate-500 hover:text-accent hover:bg-accent/10 transition-colors"
            title="Open source"
          >
            <ExternalLink className="w-3.5 h-3.5" />
          </a>
        )}
      </div>
    </div>
  )
}

interface Props {
  pathogenName: string
}

export function ResearchSection({ pathogenName }: Props) {
  const [activeTab, setActiveTab] = useState('all')

  const { data, isLoading, error } = useQuery({
    queryKey: ['research', pathogenName],
    queryFn: () => api.getResearch(pathogenName),
    retry: 1,
  })

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map(i => (
          <div key={i} className="h-24 rounded-lg bg-surface animate-pulse" />
        ))}
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-border bg-surface p-8 text-center">
        <p className="text-slate-500 text-sm">No research data available for this pathogen yet.</p>
        <p className="text-slate-600 text-xs mt-1">Run the Research Agent to populate this section.</p>
      </div>
    )
  }

  const filtered =
    activeTab === 'all'
      ? data.articles
      : data.articles.filter(a => a.article_category === activeTab)

  return (
    <div className="space-y-4">
      {/* Tabs */}
      <div className="flex gap-1 flex-wrap">
        {TABS.map(({ key, label, icon: Icon }) => {
          const count = key === 'all'
            ? data.articles.length
            : data.articles.filter(a => a.article_category === key).length
          if (key !== 'all' && count === 0) return null
          return (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={[
                'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all',
                activeTab === key
                  ? 'bg-accent/15 text-accent border border-accent/30'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-white/5 border border-transparent',
              ].join(' ')}
            >
              <Icon className="w-3 h-3" />
              {label}
              <span className="text-[10px] opacity-60">({count})</span>
            </button>
          )
        })}
      </div>

      {/* Articles */}
      <div className="space-y-2">
        {filtered.length === 0 ? (
          <p className="text-slate-500 text-sm text-center py-6">No articles in this category.</p>
        ) : (
          filtered.map((article, i) => (
            <ArticleCard key={article.pmid ?? i} article={article} />
          ))
        )}
      </div>
    </div>
  )
}
