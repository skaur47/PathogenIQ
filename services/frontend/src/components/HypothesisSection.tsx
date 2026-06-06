import { useQuery } from '@tanstack/react-query'
import { Microscope, FlaskConical, Users, Brain, Lightbulb, Target } from 'lucide-react'
import { api } from '../api/client'
import type { ReactNode } from 'react'

function renderBold(text: string): ReactNode[] {
  const parts = text.split(/\*\*(.+?)\*\*/g)
  return parts.map((part, i) =>
    i % 2 === 1
      ? <strong key={i} className="font-semibold text-slate-100">{part}</strong>
      : part
  )
}

const SECTIONS = [
  {
    key: 'overall_recommendation' as const,
    title: 'Overall Recommendation',
    icon: Target,
    accent: true,
  },
  {
    key: 'research_gap' as const,
    title: 'Research Gap',
    icon: Brain,
    accent: false,
  },
  {
    key: 'proposed_strategy' as const,
    title: 'Proposed Strategy',
    icon: Lightbulb,
    accent: false,
  },
  {
    key: 'wetlab_experiments' as const,
    title: 'Wet-lab Experiments',
    icon: FlaskConical,
    accent: false,
  },
  {
    key: 'clinical_approaches' as const,
    title: 'Clinical Approaches',
    icon: Users,
    accent: false,
  },
  {
    key: 'rationale' as const,
    title: 'Biological Rationale',
    icon: Microscope,
    accent: false,
  },
]

interface Props {
  pathogenName: string
}

export function HypothesisSection({ pathogenName }: Props) {
  const { data, isLoading, error } = useQuery({
    queryKey: ['hypothesis', pathogenName],
    queryFn: () => api.getHypothesis(pathogenName),
    retry: 1,
  })

  if (isLoading) {
    return (
      <div className="space-y-3">
        {[1, 2, 3].map(i => (
          <div key={i} className="h-28 rounded-lg bg-surface animate-pulse" />
        ))}
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-border bg-surface p-8 text-center">
        <p className="text-slate-500 text-sm">No hypothesis data available for this pathogen yet.</p>
        <p className="text-slate-600 text-xs mt-1">Run the Hypothesis Agent to populate this section.</p>
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {data.last_synthesized_at && (
        <p className="text-xs text-slate-600">
          Synthesized {new Date(data.last_synthesized_at).toLocaleDateString('en-US', {
            year: 'numeric', month: 'long', day: 'numeric',
          })}
        </p>
      )}

      {SECTIONS.map(({ key, title, icon: Icon, accent }) => {
        const content = data[key]
        if (!content) return null

        return (
          <div
            key={key}
            className={[
              'rounded-lg border p-4 space-y-2',
              accent
                ? 'border-accent/30 bg-accent/5'
                : 'border-border bg-surface',
            ].join(' ')}
          >
            <div className="flex items-center gap-2">
              <Icon className={`w-4 h-4 ${accent ? 'text-accent' : 'text-slate-500'}`} />
              <h4 className={`text-sm font-medium ${accent ? 'text-accent' : 'text-slate-300'}`}>
                {title}
              </h4>
            </div>
            <p className="text-sm text-slate-300 leading-relaxed whitespace-pre-line">{renderBold(content)}</p>
          </div>
        )
      })}
    </div>
  )
}
