import { useState, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import * as d3 from 'd3'
import { Loader2, AlertCircle } from 'lucide-react'
import { api } from '../api/client'
import type { PathogenTrendsData } from '../types'

// Deterministic color from pathogen name — stable across renders and new additions
function pathogenColor(name: string): string {
  let h = 5381
  for (let i = 0; i < name.length; i++) {
    h = ((h << 5) + h + name.charCodeAt(i)) & 0x7fffffff
  }
  return `hsl(${h % 360}, 60%, 62%)`
}

interface TooltipState {
  x: number
  y: number
  date: string
  items: { name: string; count: number; color: string }[]
}

function TrendChart({
  data,
  hidden,
  cumulative,
}: {
  data: PathogenTrendsData
  hidden: Set<string>
  cumulative: boolean
}) {
  const svgRef = useRef<SVGSVGElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [tooltip, setTooltip] = useState<TooltipState | null>(null)

  useEffect(() => {
    if (!svgRef.current || !containerRef.current) return

    const el = containerRef.current
    const totalWidth = el.clientWidth
    const height = 420
    const margin = { top: 20, right: 20, bottom: 48, left: 46 }
    const iw = totalWidth - margin.left - margin.right
    const ih = height - margin.top - margin.bottom

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()
    svg.attr('width', totalWidth).attr('height', height)

    const g = svg.append('g').attr('transform', `translate(${margin.left},${margin.top})`)

    // Parse dates as noon UTC to avoid timezone-edge shifts
    const dates = data.dates.map(d => new Date(d + 'T12:00:00'))

    const toCumulative = (counts: number[]) => {
      const out = [...counts]
      for (let i = 1; i < out.length; i++) out[i] += out[i - 1]
      return out
    }

    const visibleSeries = data.series
      .filter(s => !hidden.has(s.pathogen_name))
      .map(s => ({ ...s, counts: cumulative ? toCumulative(s.counts) : s.counts }))

    if (!dates.length) return

    const xScale = d3.scaleTime()
      .domain([dates[0], dates[dates.length - 1]])
      .range([0, iw])

    const maxY = Math.max(
      1,
      d3.max(visibleSeries.flatMap(s => s.counts)) ?? 1,
    )
    const yScale = d3.scaleLinear().domain([0, maxY]).nice().range([ih, 0])

    // Subtle horizontal grid
    g.append('g')
      .call(
        d3.axisLeft(yScale)
          .ticks(5)
          .tickSize(-iw)
          .tickFormat(() => ''),
      )
      .call(sel => {
        sel.select('.domain').remove()
        sel.selectAll('line').attr('stroke', 'rgba(255,255,255,0.04)')
      })

    // X axis — cap tick count to actual date count to prevent repeated labels on short windows
    const tickCount = Math.min(dates.length, Math.max(3, Math.floor(iw / 85)))
    g.append('g')
      .attr('transform', `translate(0,${ih})`)
      .call(
        d3.axisBottom(xScale)
          .ticks(tickCount)
          .tickFormat(d => d3.timeFormat('%b %d')(d as Date)),
      )
      .call(sel => {
        sel.select('.domain').attr('stroke', '#1e293b')
        sel.selectAll('line').attr('stroke', '#1e293b')
        sel.selectAll('text')
          .attr('fill', '#475569')
          .attr('font-size', '11px')
          .attr('dy', '1.2em')
      })

    // Y axis
    g.append('g')
      .call(d3.axisLeft(yScale).ticks(5).tickFormat(d => String(d)))
      .call(sel => {
        sel.select('.domain').attr('stroke', '#1e293b')
        sel.selectAll('line').attr('stroke', '#1e293b')
        sel.selectAll('text').attr('fill', '#475569').attr('font-size', '11px')
      })

    // Lines + dots
    const line = d3.line<number>()
      .x((_, i) => xScale(dates[i]))
      .y(d => yScale(d))
      .curve(d3.curveMonotoneX)

    visibleSeries.forEach(series => {
      const color = pathogenColor(series.pathogen_name)

      g.append('path')
        .datum(series.counts)
        .attr('fill', 'none')
        .attr('stroke', color)
        .attr('stroke-width', 1.5)
        .attr('opacity', 0.75)
        .attr('d', line)

      // Dots only at non-zero data points
      series.counts.forEach((count, i) => {
        if (count === 0) return
        g.append('circle')
          .attr('cx', xScale(dates[i]))
          .attr('cy', yScale(count))
          .attr('r', 3.5)
          .attr('fill', color)
          .attr('stroke', '#0c1420')
          .attr('stroke-width', 1.5)
          .attr('pointer-events', 'none')
      })
    })

    // Vertical hover line
    const hoverLine = g.append('line')
      .attr('stroke', 'rgba(255,255,255,0.18)')
      .attr('stroke-width', 1)
      .attr('stroke-dasharray', '4,3')
      .attr('y1', 0)
      .attr('y2', ih)
      .attr('opacity', 0)
      .attr('pointer-events', 'none')

    // Transparent overlay captures mouse events
    const bisect = d3.bisector<Date, Date>(d => d).left

    g.append('rect')
      .attr('width', iw)
      .attr('height', ih)
      .attr('fill', 'transparent')
      .style('cursor', 'crosshair')
      .on('mousemove', (event) => {
        const [mx] = d3.pointer(event)
        const x0 = xScale.invert(mx)
        let idx = bisect(dates, x0) - 1
        if (idx < 0) idx = 0
        if (idx + 1 < dates.length) {
          const d0 = Math.abs(dates[idx].getTime() - x0.getTime())
          const d1 = Math.abs(dates[idx + 1].getTime() - x0.getTime())
          if (d1 < d0) idx++
        }
        if (idx >= dates.length) idx = dates.length - 1

        hoverLine
          .attr('x1', xScale(dates[idx]))
          .attr('x2', xScale(dates[idx]))
          .attr('opacity', 1)

        const items = visibleSeries
          .filter(s => s.counts[idx] > 0)
          .map(s => ({
            name: s.pathogen_name,
            count: s.counts[idx],
            color: pathogenColor(s.pathogen_name),
          }))
          .sort((a, b) => b.count - a.count)
          .slice(0, 10)

        if (items.length > 0) {
          const [cx, cy] = d3.pointer(event, svgRef.current!)
          setTooltip({ x: cx, y: cy, date: data.dates[idx], items })
        } else {
          setTooltip(null)
        }
      })
      .on('mouseleave', () => {
        hoverLine.attr('opacity', 0)
        setTooltip(null)
      })
  }, [data, hidden, cumulative])

  return (
    <div ref={containerRef} className="relative w-full">
      <svg ref={svgRef} className="w-full block" />

      {tooltip && (
        <div
          className="absolute pointer-events-none z-10 bg-bg border border-border rounded-xl px-3 py-2.5 shadow-2xl text-xs"
          style={{
            left: Math.min(
              tooltip.x + 14,
              (containerRef.current?.clientWidth ?? 600) - 230,
            ),
            top: Math.max(4, tooltip.y - 24),
            minWidth: 160,
            maxWidth: 220,
          }}
        >
          <p className="text-slate-500 mb-2 font-medium">
            {new Date(tooltip.date + 'T12:00:00').toLocaleDateString('en-US', {
              month: 'short',
              day: 'numeric',
              year: 'numeric',
            })}
          </p>
          {tooltip.items.map(({ name, count, color }) => (
            <div key={name} className="flex items-center gap-2 mb-1">
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ background: color }}
              />
              <span className="text-slate-300 truncate flex-1 text-[11px]">{name}</span>
              <span className="text-slate-400 font-mono tabular-nums">{count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export function TrendsPage() {
  const [days, setDays] = useState(30)
  const [hidden, setHidden] = useState<Set<string>>(new Set())
  const [cumulative, setCumulative] = useState(false)

  const { data, isLoading, error } = useQuery({
    queryKey: ['pathogen-trends', days],
    queryFn: () => api.getTrends(days),
    refetchInterval: 6 * 60 * 60 * 1000, // refresh every 6 hours
    staleTime: 2 * 60 * 1000,             // treat as stale after 2 min so today always loads fresh
  })

  const togglePathogen = (name: string) => {
    setHidden(prev => {
      const next = new Set(prev)
      next.has(name) ? next.delete(name) : next.add(name)
      return next
    })
  }

  return (
    <div className="min-h-screen pt-24 pb-16 px-6">
      <div className="mx-auto max-w-7xl">

        {/* Header */}
        <div className="mb-8 flex items-end justify-between gap-4 flex-wrap">
          <div>
            <h1 className="text-3xl font-bold text-white mb-1">Pathogen Trends</h1>
            <p className="text-sm text-slate-400">
              Documents published per pathogen per day, grouped by publication date.
            </p>
          </div>

          {/* Controls */}
          <div className="flex items-center gap-3">
            {/* Cumulative toggle */}
            <button
              onClick={() => setCumulative(c => !c)}
              className={[
                'px-3 py-1.5 rounded-md text-xs font-medium transition-all border',
                cumulative
                  ? 'bg-accent/15 text-accent border-accent/30'
                  : 'text-slate-400 hover:text-slate-200 border-transparent hover:border-border hover:bg-white/5',
              ].join(' ')}
            >
              Cumulative
            </button>

            {/* Day range selector */}
            <div className="flex gap-1">
            {[7, 14, 30, 60, 90].map(d => (
              <button
                key={d}
                onClick={() => setDays(d)}
                className={[
                  'px-3 py-1.5 rounded-md text-xs font-medium transition-all',
                  days === d
                    ? 'bg-accent/15 text-accent border border-accent/30'
                    : 'text-slate-400 hover:text-slate-200 border border-transparent hover:border-border hover:bg-white/5',
                ].join(' ')}
              >
                {d}d
              </button>
            ))}
            </div>
          </div>
        </div>

        {isLoading ? (
          <div className="flex items-center justify-center h-80">
            <Loader2 className="w-6 h-6 text-accent animate-spin" />
          </div>
        ) : error ? (
          <div className="flex flex-col items-center py-24 gap-3">
            <AlertCircle className="w-6 h-6 text-red-400" />
            <p className="text-slate-400 text-sm">Failed to load trend data.</p>
            <p className="text-slate-600 text-xs">Make sure the API server is running.</p>
          </div>
        ) : !data?.series.length ? (
          <div className="py-24 text-center">
            <p className="text-slate-500">
              No pathogen mention data in the last {days} days.
            </p>
            <p className="text-slate-600 text-xs mt-1">
              Run the Sentinel Agent to start tracking mentions.
            </p>
          </div>
        ) : (
          <>
            {/* Chart */}
            <div className="rounded-2xl border border-border bg-surface p-5 mb-5">
              <TrendChart data={data} hidden={hidden} cumulative={cumulative} />
            </div>

            {/* Legend */}
            <div className="rounded-2xl border border-border bg-surface p-5">
              <div className="flex items-center justify-between mb-3">
                <p className="text-[11px] font-semibold text-slate-600 uppercase tracking-wider">
                  {data.series.length} pathogen{data.series.length !== 1 ? 's' : ''} — click to toggle
                </p>
                {hidden.size > 0 && (
                  <button
                    onClick={() => setHidden(new Set())}
                    className="text-[11px] text-accent hover:underline"
                  >
                    Show all
                  </button>
                )}
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-1">
                {data.series.map(s => {
                  const color = pathogenColor(s.pathogen_name)
                  const isHidden = hidden.has(s.pathogen_name)
                  const total = cumulative
                    ? s.counts[s.counts.length - 1] ?? 0
                    : s.counts.reduce((a, b) => a + b, 0)
                  return (
                    <button
                      key={s.pathogen_name}
                      onClick={() => togglePathogen(s.pathogen_name)}
                      title={s.pathogen_name}
                      className={[
                        'flex items-center gap-2 px-2.5 py-1.5 rounded-md text-left transition-all group',
                        isHidden
                          ? 'opacity-30 hover:opacity-60'
                          : 'hover:bg-white/5',
                      ].join(' ')}
                    >
                      <span
                        className="w-2.5 h-2.5 rounded-full shrink-0 transition-colors"
                        style={{ background: isHidden ? '#334155' : color }}
                      />
                      <span className="text-[11px] text-slate-300 truncate flex-1 min-w-0">
                        {s.pathogen_name}
                      </span>
                      <span className="text-[10px] text-slate-600 tabular-nums shrink-0">
                        {total}
                      </span>
                    </button>
                  )
                })}
              </div>
            </div>
          </>
        )}
      </div>
    </div>
  )
}
