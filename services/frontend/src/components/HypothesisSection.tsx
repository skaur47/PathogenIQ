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

function renderContent(text: string): ReactNode {
  const lines = text.split('\n')
  const elements: ReactNode[] = []
  let i = 0
  let key = 0

  while (i < lines.length) {
    const line = lines[i].trim()

    if (!line) { i++; continue }

    // Numbered list: "1." or "1)"
    const numMatch = line.match(/^(\d+)[.)]\s+(.+)/)
    if (numMatch) {
      const items: { n: string; t: string }[] = [{ n: numMatch[1], t: numMatch[2] }]
      i++
      while (i < lines.length) {
        const t = lines[i].trim()
        const m = t.match(/^(\d+)[.)]\s+(.+)/)
        if (m) { items.push({ n: m[1], t: m[2] }); i++ }
        else if (!t) { i++; break }
        else break
      }
      elements.push(
        <ol key={key++} className="space-y-2.5">
          {items.map((item, idx) => (
            <li key={idx} className="flex gap-3 items-start">
              <span className="shrink-0 w-5 h-5 rounded-full bg-accent/15 text-accent text-[10px] font-bold flex items-center justify-center mt-0.5">
                {item.n}
              </span>
              <span className="text-sm text-slate-300 leading-relaxed">{renderBold(item.t)}</span>
            </li>
          ))}
        </ol>
      )
      continue
    }

    // Bullet list: "- " or "• " or "* "
    const bulletMatch = line.match(/^[-•*]\s+(.+)/)
    if (bulletMatch) {
      const items: string[] = [bulletMatch[1]]
      i++
      while (i < lines.length) {
        const t = lines[i].trim()
        const m = t.match(/^[-•*]\s+(.+)/)
        if (m) { items.push(m[1]); i++ }
        else if (!t) { i++; break }
        else break
      }
      elements.push(
        <ul key={key++} className="space-y-2">
          {items.map((item, idx) => (
            <li key={idx} className="flex gap-2.5 items-start">
              <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-slate-500 mt-[7px]" />
              <span className="text-sm text-slate-300 leading-relaxed">{renderBold(item)}</span>
            </li>
          ))}
        </ul>
      )
      continue
    }

    elements.push(
      <p key={key++} className="text-sm text-slate-300 leading-relaxed">{renderBold(line)}</p>
    )
    i++
  }

  return <div className="space-y-3">{elements}</div>
}

const SECTIONS = [
  { key: 'overall_recommendation' as const, title: 'Overall Recommendation', icon: Target,    accent: true  },
  { key: 'research_gap'           as const, title: 'Research Gap',           icon: Brain,     accent: false },
  { key: 'proposed_strategy'      as const, title: 'Proposed Strategy',      icon: Lightbulb, accent: false },
  { key: 'wetlab_experiments'     as const, title: 'Wet-lab Experiments',    icon: FlaskConical, accent: false },
  { key: 'clinical_approaches'    as const, title: 'Clinical Approaches',    icon: Users,     accent: false },
  { key: 'rationale'              as const, title: 'Biological Rationale',   icon: Microscope, accent: false },
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
      <div className="space-y-4">
        {[1, 2, 3].map(i => (
          <div key={i} className="h-32 rounded-xl bg-surface animate-pulse" />
        ))}
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="rounded-xl border border-border bg-surface p-8 text-center">
        <p className="text-slate-500 text-sm">No hypothesis data available for this pathogen yet.</p>
        <p className="text-slate-600 text-xs mt-1">Run the Hypothesis Agent to populate this section.</p>
      </div>
    )
  }

  return (
    <div className="space-y-5">
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
              'rounded-xl border p-5',
              accent ? 'border-accent/30 bg-accent/5' : 'border-border bg-surface',
            ].join(' ')}
          >
            <div className="flex items-center gap-2 mb-4 pb-3 border-b border-white/5">
              <Icon className={`w-4 h-4 ${accent ? 'text-accent' : 'text-slate-500'}`} />
              <h4 className={`text-sm font-semibold ${accent ? 'text-accent' : 'text-slate-200'}`}>
                {title}
              </h4>
            </div>
            {renderContent(content)}
          </div>
        )
      })}
    </div>
  )
}
