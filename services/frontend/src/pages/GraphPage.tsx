import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Loader2 } from 'lucide-react'
import { api } from '../api/client'
import { KnowledgeGraph } from '../components/KnowledgeGraph'

export function GraphPage() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['graph'],
    queryFn: () => api.getGraph(),
    staleTime: 5 * 60 * 1000,
  })

  return (
    <div className="h-screen flex flex-col pt-16">
      {/* Sub-header */}
      <div className="shrink-0 px-6 py-4 border-b border-border bg-bg">
        <div className="mx-auto max-w-7xl flex items-center justify-between">
          <div>
            <h1 className="text-lg font-semibold text-white">Knowledge Graph</h1>
            <p className="text-xs text-slate-500 mt-0.5">
              Pathogen relationships: categories, transmission routes, and reservoir hosts
            </p>
          </div>
          {data && (
            <div className="flex gap-4 text-right">
              <div>
                <p className="text-xs text-slate-600">Nodes</p>
                <p className="text-sm font-semibold text-slate-300">{data.nodes.length}</p>
              </div>
              <div>
                <p className="text-xs text-slate-600">Edges</p>
                <p className="text-sm font-semibold text-slate-300">{data.edges.length}</p>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Graph area */}
      <div className="flex-1 relative overflow-hidden bg-bg">
        {isLoading && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="w-6 h-6 text-accent animate-spin" />
              <p className="text-slate-500 text-sm">Building knowledge graph…</p>
            </div>
          </div>
        )}

        {error && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="flex flex-col items-center gap-3">
              <AlertCircle className="w-6 h-6 text-red-400" />
              <p className="text-slate-400 text-sm">Failed to load graph data.</p>
              <p className="text-slate-600 text-xs">Make sure the API server is running.</p>
            </div>
          </div>
        )}

        {data && data.nodes.length === 0 && (
          <div className="absolute inset-0 flex items-center justify-center">
            <div className="text-center">
              <p className="text-slate-400 text-sm">No graph data yet.</p>
              <p className="text-slate-600 text-xs mt-1">Run the pipeline to populate the knowledge graph.</p>
            </div>
          </div>
        )}

        {data && data.nodes.length > 0 && (
          <KnowledgeGraph data={data} />
        )}
      </div>
    </div>
  )
}
