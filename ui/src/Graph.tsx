import { useEffect, useRef, useState } from 'react'
import { MARK_BADGE, edgePath, place, verdictBadge, type Badge, type Box } from './layout'
import { Minimap, NodeEl } from './GraphParts'
import type { Frame, GraphView, HandOff, Mark } from './model'

export interface GraphProps {
  graph: GraphView
  marks?: Record<string, Mark>
  frame?: Frame | null
  pulse?: number
  labels?: HandOff[]
  verdict?: boolean
  diff?: Set<string>
  relevant?: Set<string>
  selected?: string | null
  onSelect?: (id: string) => void
}

const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(v, Math.max(lo, hi)))
const around = (b: Box, c: Box, w = 1100, h = 470): Box => {
  const vw = Math.min(c.w, w)
  const vh = Math.min(c.h, h)
  return { x: clamp(b.x + b.w / 2 - vw / 2, 0, c.w - vw), y: clamp(b.y + b.h / 2 - vh / 2, 0, c.h - vh), w: vw, h: vh }
}
const zoom = (v: Box, f: number, px = v.x + v.w / 2, py = v.y + v.h / 2): Box => ({ x: px - (px - v.x) * f, y: py - (py - v.y) * f, w: v.w * f, h: v.h * f })

/** The pipeline graph: server layout, stage bands, pan and zoom for large teams, search, follow the running node. */
export default function Graph(p: GraphProps) {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())
  const [vb, setVb] = useState<Box | null>(null)
  const [follow, setFollow] = useState(true)
  const [query, setQuery] = useState('')
  const svg = useRef<SVGSVGElement>(null)
  const drag = useRef<{ x: number; y: number; v: Box } | null>(null)
  const L = place(p.graph, collapsed)
  const big = L.nodes.length > 14 || L.width > 1500
  const content: Box = { x: 0, y: 0, w: L.width, h: L.height }
  const stageOf = (id: string) => [...L.groups].find(([s, ids]) => collapsed.has(s) && ids.includes(id))?.[0]
  const boxOf = (id: string) => {
    const s = stageOf(id)
    return L.boxes.get(s ? `stage:${s}` : id)
  }
  const f = p.frame
  const focus = f?.node ? boxOf(f.node) : undefined
  // a large team opens on a readable window: the verified nodes in a verdict, else the start of the run
  const key = L.nodes.filter((n) => p.verdict && (n.status === 'culprit' || n.status === 'cleared')).map((n) => L.boxes.get(n.id)).filter((b): b is Box => !!b)
  const kx = Math.min(...key.map((b) => b.x))
  const ky = Math.min(...key.map((b) => b.y))
  const home: Box = !big ? content : key.length ? around({ x: kx, y: ky, w: Math.max(...key.map((b) => b.x + b.w)) - kx, h: Math.max(...key.map((b) => b.y + b.h)) - ky }, content, Math.max(1300, Math.max(...key.map((b) => b.x + b.w)) - kx + 240)) : around({ x: 0, y: content.h / 2, w: 0, h: 0 }, content, 1300)
  const view = vb ?? (big && follow && focus ? around(focus, content, 1300) : home)
  const q = query.trim().toLowerCase()
  const matches = new Set(q ? L.nodes.filter((n) => n.role === 'node' && n.id.toLowerCase().includes(q)).map((n) => n.id) : [])

  useEffect(() => {
    const el = svg.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (!big && !e.ctrlKey) return
      e.preventDefault()
      const r = el.getBoundingClientRect()
      const v = el.viewBox.baseVal
      const s = Math.max(v.width / r.width, v.height / r.height)
      const px = v.x - (r.width * s - v.width) / 2 + (e.clientX - r.left) * s
      const py = v.y - (r.height * s - v.height) / 2 + (e.clientY - r.top) * s
      setFollow(false)
      setVb(zoom({ x: v.x, y: v.y, w: v.width, h: v.height }, e.deltaY > 0 ? 1.15 : 1 / 1.15, px, py))
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [big])

  const pick = (id: string) => {
    if (id.startsWith('stage:')) setCollapsed((c) => new Set([...c].filter((x) => x !== id.slice(6))))
    else p.onSelect?.(id)
  }
  const keysOf = (s: string, t: string) => p.labels?.find((e) => e.source === s && e.target === t)?.keys
  const classOf = (id: string) => {
    const n = L.nodes.find((x) => x.id === id)
    if (!n) return ''
    const mark = p.marks?.[id]
    const dim = (p.relevant && n.role === 'node' && !id.startsWith('stage:') && !p.relevant.has(id)) || (q && !matches.has(id))
    const isFocus = !!f?.node && boxOf(f.node) === L.boxes.get(id)
    return ['gn', p.verdict && n.status ? `st-${n.status}` : '', mark && !p.verdict ? `mk-${mark}` : '', isFocus ? `is-focus ph-${f?.phase ?? ''}` : '', p.selected === id ? 'is-sel' : '', n.verdict?.pruned ? 'is-pruned' : '', dim ? 'is-dim' : '', matches.has(id) ? 'is-match' : ''].filter(Boolean).join(' ')
  }
  const toFit = () => {
    setFollow(false)
    setVb(content)
  }

  const active = f?.edge
  return (
    <div className={`gwrap${big ? ' is-big' : ''}`}>
      <div className="gtools" data-noshare>
        {L.nodes.length > 8 && (
          <input type="search" placeholder="Find a node" aria-label="Find a node" value={query} onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              const b = e.key === 'Enter' ? L.boxes.get([...matches][0] ?? '') : undefined
              if (b) { setFollow(false); setVb(around(b, content)) }
            }} />
        )}
        {L.groups.size > 0 && <button type="button" onClick={() => setCollapsed(collapsed.size ? new Set() : new Set(L.groups.keys()))}>{collapsed.size ? 'Expand stages' : 'Group by stage'}</button>}
        {big && f !== undefined && <button type="button" aria-pressed={follow && !vb} onClick={() => { setVb(null); setFollow(true) }}>Follow</button>}
        <button type="button" aria-label="Zoom out" onClick={() => { setFollow(false); setVb(zoom(view, 1.25)) }}>−</button>
        <button type="button" aria-label="Zoom in" onClick={() => { setFollow(false); setVb(zoom(view, 0.8)) }}>+</button>
        <button type="button" onClick={toFit}>Fit</button>
        {big && <button type="button" onClick={() => { setFollow(true); setVb(null) }}>Reset view</button>}
      </div>
      <svg ref={svg} className={`graph${big ? ' graph-big' : ''}${view.w > 1500 ? ' is-far' : ''}`} viewBox={`${view.x} ${view.y} ${view.w} ${view.h}`} style={big ? undefined : { maxWidth: L.width }} role="img" aria-label="Pipeline graph"
        onPointerDown={(e) => {
          if (!(e.target as Element).classList.contains('gbg')) return
          drag.current = { x: e.clientX, y: e.clientY, v: view }
          e.currentTarget.setPointerCapture(e.pointerId)
        }}
        onPointerMove={(e) => {
          const d = drag.current
          if (!d) return
          const r = e.currentTarget.getBoundingClientRect()
          const s = Math.max(d.v.w / r.width, d.v.h / r.height)
          setFollow(false)
          setVb({ ...d.v, x: d.v.x - (e.clientX - d.x) * s, y: d.v.y - (e.clientY - d.y) * s })
        }}
        onPointerUp={() => { drag.current = null }}>
        <defs>
          <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" className="ge-head" /></marker>
        </defs>
        <rect className="gbg" x={-5000} y={-5000} width={20000} height={20000} />
        {[...L.groups].filter(([s]) => !collapsed.has(s)).map(([s, ids]) => {
          const bs = ids.map((id) => L.boxes.get(id)).filter((b): b is Box => !!b)
          const x = Math.min(...bs.map((b) => b.x)) - 10
          const y = Math.min(...bs.map((b) => b.y)) - 24
          return (
            <g key={s} className="gband" onClick={() => setCollapsed(new Set([...collapsed, s]))}>
              <title>Stage {s}: click to collapse</title>
              <rect x={x} y={y} width={Math.max(...bs.map((b) => b.x + b.w)) - x + 10} height={Math.max(...bs.map((b) => b.y + b.h)) - y + 10} rx={4} />
              <text x={x + 8} y={y + 15}>{s}</text>
            </g>
          )
        })}
        {L.edges.map((e, i) => {
          const A = L.boxes.get(e.source)
          const B = L.boxes.get(e.target)
          if (!A || !B) return null
          const { d, mx, my } = edgePath(A, B, e.back)
          const on = !!active && boxOf(active.source) === A && boxOf(active.target) === B
          const keys = (on ? active?.keys : undefined) ?? keysOf(e.source, e.target)
          const label = keys?.length ? (keys.length > 1 ? `${keys[0].slice(0, 8)} +${keys.length - 1}` : keys[0].slice(0, 11)) : ''
          return (
            <g key={i} className={`ge${on ? ' is-on' : ''}${e.conditional ? ' is-cond' : ''}`}>
              <path d={d} pathLength={100} markerEnd="url(#arrow)" />
              {on && <path key={p.pulse} className="ge-pulse" d={d} pathLength={100} />}
              {label && <text x={mx} y={my} textAnchor="middle" className="ge-label"><title>{keys?.join(', ')}</title>{label}</text>}
            </g>
          )
        })}
        {L.nodes.map((n) => {
          const b = L.boxes.get(n.id)
          if (!b) return null
          const mark = p.marks?.[n.id]
          const isFocus = !!f?.node && boxOf(f.node) === b
          const badge: Badge | null = p.verdict && n.status ? verdictBadge(n) : isFocus && f?.phase === 'in' ? ['dot', 'running'] : isFocus && f?.phase === 'edge' ? ['arrow', 'receiving'] : mark ? MARK_BADGE[mark] : null
          return <NodeEl key={n.id} n={n} b={b} cls={classOf(n.id)} badge={badge} diff={!!p.diff?.has(n.id)} onSelect={pick} />
        })}
      </svg>
      {big && <Minimap boxes={L.boxes} classOf={classOf} width={L.width} height={L.height} view={view} onJump={(x, y) => { setFollow(false); setVb(around({ x, y, w: 0, h: 0 }, content, view.w, view.h)) }} />}
    </div>
  )
}
