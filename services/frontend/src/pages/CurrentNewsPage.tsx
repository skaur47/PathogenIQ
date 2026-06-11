import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ExternalLink, AlertCircle } from 'lucide-react'
import { api } from '../api/client'
import type { DocumentItem } from '../types'

const SOURCE_STYLES: Record<string, string> = {
  pubmed:  'text-blue-400 bg-blue-500/10 border-blue-500/20',
  cdc:     'text-red-400 bg-red-500/10 border-red-500/20',
  who:     'text-cyan-400 bg-cyan-500/10 border-cyan-500/20',
  promed:  'text-orange-400 bg-orange-500/10 border-orange-500/20',
  news:    'text-purple-400 bg-purple-500/10 border-purple-500/20',
  biorxiv: 'text-green-400 bg-green-500/10 border-green-500/20',
  ecdc:    'text-yellow-400 bg-yellow-500/10 border-yellow-500/20',
  manual:  'text-slate-400 bg-slate-500/10 border-slate-500/20',
}

function stripHtml(html: string): string {
  return html
    .replace(/<[^>]*>/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#039;/g, "'")
    .replace(/&nbsp;/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

function DocumentCard({ doc }: { doc: DocumentItem }) {
  const style = SOURCE_STYLES[doc.source] ?? SOURCE_STYLES.manual
  const title = doc.title ? stripHtml(doc.title) : `Document ${doc.external_id}`
  const abstract = doc.abstract ? stripHtml(doc.abstract) : null

  return (
    <article className="flex gap-4 p-4 rounded-xl border border-border bg-surface hover:border-white/10 hover:bg-surface2 transition-all group">
      <div className="flex-1 min-w-0 space-y-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`px-2 py-0.5 rounded text-[11px] font-semibold uppercase border ${style}`}>
            {doc.source}
          </span>
          {doc.published_date && (
            <span className="text-xs text-slate-600">{doc.published_date}</span>
          )}
        </div>
        <p className="text-sm font-medium text-slate-200 leading-snug group-hover:text-white transition-colors line-clamp-2">
          {title}
        </p>
        {abstract && (
          <p className="text-xs text-slate-500 leading-relaxed line-clamp-2">{abstract}</p>
        )}
      </div>
      {doc.url && (
        <a
          href={doc.url}
          target="_blank"
          rel="noopener noreferrer"
          className="shrink-0 self-start p-2 rounded-lg text-slate-500 hover:text-accent hover:bg-accent/10 transition-colors"
          title="Open source"
        >
          <ExternalLink className="w-4 h-4" />
        </a>
      )}
    </article>
  )
}

export function CurrentNewsPage() {
  const [source, setSource] = useState('all')
  const [page, setPage] = useState(0)
  const LIMIT = 30

  // Fetch a wide sample once to discover which sources actually have data
  const { data: allSample } = useQuery({
    queryKey: ['documents', 'source-discovery'],
    queryFn: () => api.getDocuments({ limit: 200, offset: 0 }),
    staleTime: 10 * 60 * 1000,
  })

  const availableSources = useMemo(() => {
    if (!allSample) return []
    const seen = new Set(allSample.items.map(d => d.source))
    return Array.from(seen).sort()
  }, [allSample])

  const { data, isLoading, error } = useQuery({
    queryKey: ['documents', source, page],
    queryFn: () => api.getDocuments({
      source: source === 'all' ? undefined : source,
      limit: LIMIT,
      offset: page * LIMIT,
    }),
  })

  const totalPages = data ? Math.ceil(data.total / LIMIT) : 0

  return (
    <div className="min-h-screen pt-24 pb-16 px-6">
      <div className="mx-auto max-w-4xl">

        {/* Header */}
        <div className="mb-10">
          <h1 className="text-3xl font-bold text-white mb-2">Current News</h1>
          <p className="text-slate-400 text-sm">
            Relevant articles sourced from WHO, CDC, and news feeds.
          </p>
        </div>

        {/* Source filter — only shows sources present in the DB */}
        <div className="flex gap-1.5 flex-wrap mb-6">
          {['all', ...availableSources].map(s => (
            <button
              key={s}
              onClick={() => { setSource(s); setPage(0) }}
              className={[
                'px-3 py-1.5 rounded-md text-xs font-medium uppercase tracking-wide transition-all',
                source === s
                  ? 'bg-accent/15 text-accent border border-accent/30'
                  : 'text-slate-400 hover:text-slate-200 border border-transparent hover:border-border hover:bg-white/5',
              ].join(' ')}
            >
              {s}
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
        ) : error ? (
          <div className="flex flex-col items-center py-16 gap-3">
            <AlertCircle className="w-6 h-6 text-red-400" />
            <p className="text-slate-400 text-sm">Failed to load documents.</p>
          </div>
        ) : !data?.items.length ? (
          <div className="py-16 text-center">
            <p className="text-slate-500">No documents found for this source.</p>
          </div>
        ) : (
          <>
            <p className="text-xs text-slate-600 mb-4">
              {data.total.toLocaleString()} total document{data.total !== 1 ? 's' : ''}
              {source !== 'all' ? ` from ${source.toUpperCase()}` : ''}
            </p>
            <div className="space-y-3">
              {data.items.map(doc => (
                <DocumentCard key={doc.id} doc={doc} />
              ))}
            </div>

            {/* Pagination */}
            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-2 mt-8">
                <button
                  onClick={() => setPage(p => Math.max(0, p - 1))}
                  disabled={page === 0}
                  className="px-4 py-2 rounded-lg text-sm text-slate-400 border border-border hover:border-accent/30 hover:text-accent disabled:opacity-30 transition-all"
                >
                  Previous
                </button>
                <span className="text-xs text-slate-600 px-2">
                  Page {page + 1} of {totalPages}
                </span>
                <button
                  onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                  disabled={page >= totalPages - 1}
                  className="px-4 py-2 rounded-lg text-sm text-slate-400 border border-border hover:border-accent/30 hover:text-accent disabled:opacity-30 transition-all"
                >
                  Next
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
