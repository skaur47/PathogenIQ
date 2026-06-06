import { useQuery } from '@tanstack/react-query'
import { ExternalLink, FileText } from 'lucide-react'
import { api } from '../api/client'

function stripHtml(html: string): string {
  return html
    .replace(/<[^>]*>/g, ' ')
    .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"').replace(/&#039;/g, "'").replace(/&nbsp;/g, ' ')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

const SOURCE_STYLES: Record<string, string> = {
  pubmed:   'text-blue-400 bg-blue-500/10 border-blue-500/20',
  cdc:      'text-red-400 bg-red-500/10 border-red-500/20',
  who:      'text-cyan-400 bg-cyan-500/10 border-cyan-500/20',
  promed:   'text-orange-400 bg-orange-500/10 border-orange-500/20',
  news:     'text-purple-400 bg-purple-500/10 border-purple-500/20',
  biorxiv:  'text-green-400 bg-green-500/10 border-green-500/20',
  ecdc:     'text-yellow-400 bg-yellow-500/10 border-yellow-500/20',
  manual:   'text-slate-400 bg-slate-500/10 border-slate-500/20',
}

interface Props {
  pathogenName: string
}

export function SourcesSection({ pathogenName }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['sources', pathogenName],
    queryFn: () => api.getSources(pathogenName),
    retry: 1,
  })

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3, 4].map(i => (
          <div key={i} className="h-16 rounded-lg bg-surface animate-pulse" />
        ))}
      </div>
    )
  }

  if (error || !data || data.documents.length === 0) {
    return (
      <div className="rounded-lg border border-border bg-surface p-8 text-center">
        <p className="text-slate-500 text-sm">No source documents found for this pathogen.</p>
        <p className="text-slate-600 text-xs mt-1">Run the Sentinel Agent to index documents.</p>
      </div>
    )
  }

  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-500 mb-3">
        {data.total_documents} document{data.total_documents !== 1 ? 's' : ''} mention this pathogen
      </p>

      {data.documents.map(doc => {
        const sourceStyle = SOURCE_STYLES[doc.source] ?? SOURCE_STYLES.manual

        return (
          <div
            key={doc.document_id}
            className="flex items-start gap-3 p-3.5 rounded-lg border border-border bg-surface hover:border-white/10 transition-colors"
          >
            <FileText className="w-4 h-4 text-slate-600 shrink-0 mt-0.5" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5 flex-wrap">
                <span className={`px-2 py-0.5 rounded text-[11px] font-medium uppercase border ${sourceStyle}`}>
                  {doc.source}
                </span>
                {doc.published_date && (
                  <span className="text-[11px] text-slate-600">{doc.published_date}</span>
                )}
                <span className="text-[11px] text-slate-700">
                  {doc.mention_count} mention{doc.mention_count !== 1 ? 's' : ''}
                </span>
              </div>
              <p className="text-sm text-slate-300 leading-snug line-clamp-2">
                {doc.title ? stripHtml(doc.title) : doc.document_id}
              </p>
            </div>
            {doc.url && (
              <a
                href={doc.url}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 p-1.5 rounded-md text-slate-500 hover:text-accent hover:bg-accent/10 transition-colors"
                title="Open source"
              >
                <ExternalLink className="w-3.5 h-3.5" />
              </a>
            )}
          </div>
        )
      })}
    </div>
  )
}
