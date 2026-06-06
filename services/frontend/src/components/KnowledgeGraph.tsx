import { useEffect, useRef, useState } from 'react'
import * as d3 from 'd3'
import type { GraphData, GraphNode, GraphEdge } from '../types'

const NODE_COLORS: Record<string, string> = {
  Pathogen:         '#0dd9bb',
  Category:         '#3b82f6',
  ReservoirHost:    '#f59e0b',
  TransmissionRoute:'#ef4444',
}

const EDGE_COLORS: Record<string, string> = {
  IN_CATEGORY: 'rgba(59,130,246,0.4)',
  HOSTED_BY:   'rgba(245,158,11,0.4)',
  SPREADS_VIA: 'rgba(239,68,68,0.4)',
}

const NODE_RADIUS: Record<string, number> = {
  Pathogen:         10,
  Category:         8,
  ReservoirHost:    7,
  TransmissionRoute:7,
}

interface InfoPanel {
  id: string
  label: string
  type: string
  x: number
  y: number
}

interface Props {
  data: GraphData
}

export function KnowledgeGraph({ data }: Props) {
  const svgRef = useRef<SVGSVGElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [info, setInfo] = useState<InfoPanel | null>(null)

  useEffect(() => {
    if (!data?.nodes?.length || !svgRef.current || !containerRef.current) return

    const el = containerRef.current
    const width = el.clientWidth
    const height = el.clientHeight

    const svg = d3.select(svgRef.current)
    svg.selectAll('*').remove()
    svg.attr('width', width).attr('height', height)

    const g = svg.append('g')

    // Zoom
    const zoomBehavior = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.05, 6])
      .on('zoom', e => {
        g.attr('transform', e.transform)
        setInfo(null)
      })
    svg.call(zoomBehavior)

    // Clone data for D3 mutation
    const nodes: GraphNode[] = data.nodes.map(n => ({ ...n }))
    const edges: GraphEdge[] = data.edges.map(e => ({
      ...e,
      source: e.source as string,
      target: e.target as string,
    }))

    // Arrow markers
    const defs = svg.append('defs')
    Object.entries(EDGE_COLORS).forEach(([type, color]) => {
      defs.append('marker')
        .attr('id', `arrow-${type}`)
        .attr('viewBox', '0 -4 8 8')
        .attr('refX', 18)
        .attr('refY', 0)
        .attr('markerWidth', 5)
        .attr('markerHeight', 5)
        .attr('orient', 'auto')
        .append('path')
        .attr('d', 'M0,-4L8,0L0,4')
        .attr('fill', color.replace(/[\d.]+\)$/, '0.6)'))
    })

    // Force simulation — tuned for readability: wide spacing, strong repulsion
    const simulation = d3.forceSimulation<GraphNode>(nodes)
      .force('link', d3.forceLink<GraphNode, GraphEdge>(edges)
        .id(d => d.id)
        .distance(d => {
          const target = d.target as GraphNode
          if (target.type === 'Category') return 240
          if (target.type === 'Pathogen')  return 180
          return 160
        })
        .strength(0.3)
      )
      .force('charge', d3.forceManyBody<GraphNode>().strength(-800).distanceMax(600))
      .force('center', d3.forceCenter(width / 2, height / 2).strength(0.05))
      .force('collision', d3.forceCollide<GraphNode>(d => (NODE_RADIUS[d.type] ?? 7) + 28))
      .alphaDecay(0.015)
      .velocityDecay(0.35)

    // Edges
    const linkSel = g.append('g').attr('class', 'links')
      .selectAll<SVGLineElement, GraphEdge>('line')
      .data(edges)
      .join('line')
      .attr('stroke', d => EDGE_COLORS[d.type] ?? 'rgba(100,116,139,0.3)')
      .attr('stroke-width', 1.5)
      .attr('marker-end', d => `url(#arrow-${d.type})`)

    // Edge labels (hidden until moderate zoom)
    const linkLabelSel = g.append('g').attr('class', 'link-labels')
      .selectAll<SVGTextElement, GraphEdge>('text')
      .data(edges)
      .join('text')
      .attr('font-size', '6.5px')
      .attr('fill', '#475569')
      .attr('text-anchor', 'middle')
      .attr('pointer-events', 'none')
      .text(d => d.type.replace(/_/g, ' '))

    // Node groups
    const nodeSel = g.append('g').attr('class', 'nodes')
      .selectAll<SVGGElement, GraphNode>('g')
      .data(nodes, d => d.id)
      .join('g')
      .attr('cursor', 'pointer')
      .call(
        d3.drag<SVGGElement, GraphNode>()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart()
            d.fx = d.x; d.fy = d.y
          })
          .on('drag', (event, d) => {
            d.fx = event.x; d.fy = event.y
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0)
            d.fx = null; d.fy = null
          })
      )
      .on('click', (event, d) => {
        event.stopPropagation()
        const [cx, cy] = d3.pointer(event, svgRef.current!)
        setInfo({ id: d.id, label: d.label, type: d.type, x: cx, y: cy })
      })

    svg.on('click', () => setInfo(null))

    // Glow filter
    const filter = defs.append('filter').attr('id', 'glow')
    filter.append('feGaussianBlur').attr('stdDeviation', '3').attr('result', 'coloredBlur')
    const feMerge = filter.append('feMerge')
    feMerge.append('feMergeNode').attr('in', 'coloredBlur')
    feMerge.append('feMergeNode').attr('in', 'SourceGraphic')

    // Circles
    nodeSel.append('circle')
      .attr('r', d => NODE_RADIUS[d.type] ?? 7)
      .attr('fill', d => (NODE_COLORS[d.type] ?? '#888') + '22')
      .attr('stroke', d => NODE_COLORS[d.type] ?? '#888')
      .attr('stroke-width', d => d.type === 'Pathogen' ? 2 : 1.5)
      .on('mouseenter', function(_, d) {
        const datum = d as GraphNode
        d3.select(this).attr('filter', 'url(#glow)').attr('fill', (NODE_COLORS[datum.type] ?? '#888') + '44')
      })
      .on('mouseleave', function(_, d) {
        const datum = d as GraphNode
        d3.select(this).attr('filter', null).attr('fill', (NODE_COLORS[datum.type] ?? '#888') + '22')
      })

    // Labels
    nodeSel.append('text')
      .attr('dy', d => (NODE_RADIUS[d.type] ?? 7) + 10)
      .attr('font-size', d => d.type === 'Pathogen' ? '8.5px' : '7.5px')
      .attr('fill', d => d.type === 'Pathogen' ? '#e2e8f0' : '#94a3b8')
      .attr('text-anchor', 'middle')
      .attr('pointer-events', 'none')
      .text(d => {
        const max = d.type === 'Pathogen' ? 22 : 16
        return d.label.length > max ? d.label.slice(0, max) + '…' : d.label
      })

    // Tick
    simulation.on('tick', () => {
      linkSel
        .attr('x1', d => (d.source as GraphNode).x ?? 0)
        .attr('y1', d => (d.source as GraphNode).y ?? 0)
        .attr('x2', d => (d.target as GraphNode).x ?? 0)
        .attr('y2', d => (d.target as GraphNode).y ?? 0)

      linkLabelSel
        .attr('x', d => (((d.source as GraphNode).x ?? 0) + ((d.target as GraphNode).x ?? 0)) / 2)
        .attr('y', d => (((d.source as GraphNode).y ?? 0) + ((d.target as GraphNode).y ?? 0)) / 2)

      nodeSel.attr('transform', d => `translate(${d.x ?? 0},${d.y ?? 0})`)
    })

    // Auto fit after simulation cools
    const timer = setTimeout(() => {  // longer wait matches slower alphaDecay
      const bbox = (g.node() as SVGGElement).getBBox()
      if (bbox.width === 0) return
      const scale = Math.min(0.9, 0.9 / Math.max(bbox.width / width, bbox.height / height))
      svg.transition().duration(800).call(
        zoomBehavior.transform,
        d3.zoomIdentity
          .translate(width / 2, height / 2)
          .scale(scale)
          .translate(-bbox.x - bbox.width / 2, -bbox.y - bbox.height / 2)
      )
    }, 3500)

    return () => {
      simulation.stop()
      clearTimeout(timer)
    }
  }, [data])

  return (
    <div ref={containerRef} className="relative w-full h-full select-none">
      <svg ref={svgRef} className="w-full h-full" />

      {/* Floating info panel */}
      {info && (
        <div
          className="absolute pointer-events-none bg-surface2 border border-border rounded-lg px-3 py-2 shadow-xl text-xs max-w-[200px]"
          style={{ left: Math.min(info.x + 12, (containerRef.current?.clientWidth ?? 400) - 220), top: info.y - 10 }}
        >
          <p className="font-semibold text-slate-100 truncate">{info.label}</p>
          <p className="text-slate-500 mt-0.5">{info.type}</p>
        </div>
      )}

      {/* Legend */}
      <div className="absolute bottom-4 left-4 bg-bg/90 border border-border rounded-xl p-3 space-y-1.5 backdrop-blur-sm">
        <p className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider mb-2">Nodes</p>
        {Object.entries(NODE_COLORS).map(([type, color]) => (
          <div key={type} className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full border" style={{ borderColor: color, background: color + '22' }} />
            <span className="text-[11px] text-slate-400">{type}</span>
          </div>
        ))}
        <p className="text-[10px] font-semibold text-slate-600 uppercase tracking-wider mt-3 mb-1">Edges</p>
        {[
          { label: 'IN_CATEGORY', color: '#3b82f6' },
          { label: 'HOSTED_BY',   color: '#f59e0b' },
          { label: 'SPREADS_VIA', color: '#ef4444' },
        ].map(({ label, color }) => (
          <div key={label} className="flex items-center gap-2">
            <span className="w-3 h-0.5 rounded" style={{ background: color + '80' }} />
            <span className="text-[11px] text-slate-400">{label}</span>
          </div>
        ))}
      </div>

      {/* Hint */}
      <div className="absolute bottom-4 right-4 text-[11px] text-slate-700 text-right">
        <p>Scroll to zoom · Drag to pan</p>
        <p>Click node for details</p>
      </div>
    </div>
  )
}
