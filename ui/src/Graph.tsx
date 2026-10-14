import { GLYPHS, type Frame, type GlyphName, type GNode, type GraphView, type HandOff, type Mark } from './model'

const W = 128
const H = 54
const COL = 200
const ROW = 86
const PAD = 22

type Badge = [GlyphName, string]
const MARK_BADGE: Record<Mark, Badge> = {
  ran: ['check', 'ran'],
  error: ['cross', 'error'],
  restored: ['restore', 'restored'],
  pruned: ['dash', 'skipped'],
  candidate: ['diamond', 'to test'],
  pass: ['check', 'passed'],
  fail: ['cross', 'failed'],
}

function verdictBadge(n: GNode): Badge | null {
  switch (n.status) {
    case 'culprit':
      return ['bang', 'must change']
    case 'cleared':
      return ['check', 'not needed']
    case 'abstained':
      return ['question', 'cannot say']
    case 'unverified':
      return n.verdict?.pruned ? ['dash', 'not tested'] : ['ring', 'not verified']
    default:
      return null
  }
}

const KIND: Record<string, string> = { deterministic: 'code', llm: 'LLM', tool: 'tool' }

export interface GraphProps {
  graph: GraphView
  marks?: Record<string, Mark>
  frame?: Frame | null
  pulse?: number
  labels?: HandOff[]
  verdict?: boolean
  diff?: Set<string>
  selected?: string | null
  onSelect?: (id: string) => void
}

function box(n: GNode) {
  const term = n.role !== 'node'
  const w = term ? 64 : W
  const h = term ? 26 : H
  return { x: PAD + n.layer * COL + (W - w) / 2, y: PAD + n.row * ROW + (H - h) / 2, w, h }
}

export default function Graph(p: GraphProps) {
  const byId = new Map(p.graph.nodes.map((n) => [n.id, n]))
  const maxL = Math.max(0, ...p.graph.nodes.map((n) => n.layer))
  const maxR = Math.max(0, ...p.graph.nodes.map((n) => n.row))
  const hasBack = p.graph.edges.some((e) => e.back)
  const width = PAD * 2 + maxL * COL + W
  const height = PAD * 2 + maxR * ROW + H + (hasBack ? 34 : 0)
  const f = p.frame
  const active = f?.edge
  const keysOf = (s: string, t: string) => p.labels?.find((e) => e.source === s && e.target === t)?.keys

  const edges = p.graph.edges.flatMap((e, i) => {
    const a = byId.get(e.source)
    const b = byId.get(e.target)
    if (!a || !b) return []
    const A = box(a)
    const B = box(b)
    let d: string
    let mx: number
    let my: number
    if (e.back || b.layer <= a.layer) {
      const y = Math.max(A.y + A.h, B.y + B.h) + 30
      d = `M${A.x + A.w / 2},${A.y + A.h} C${A.x + A.w / 2},${y} ${B.x + B.w / 2},${y} ${B.x + B.w / 2},${B.y + B.h}`
      mx = (A.x + B.x + A.w) / 2
      my = y - 4
    } else {
      const x1 = A.x + A.w
      const y1 = A.y + A.h / 2
      const x2 = B.x
      const y2 = B.y + B.h / 2
      const c = (x2 - x1) / 2
      d = `M${x1},${y1} C${x1 + c},${y1} ${x2 - c},${y2} ${x2},${y2}`
      mx = (x1 + x2) / 2
      my = (y1 + y2) / 2 - 7
    }
    const on = active && active.source === e.source && active.target === e.target
    const keys = (on ? active.keys : undefined) ?? keysOf(e.source, e.target)
    const label = keys?.length ? keys.length > 1 ? `${keys[0].slice(0, 8)} +${keys.length - 1}` : keys[0].slice(0, 11) : ''
    return [
      <g key={i} className={`ge${on ? ' is-on' : ''}${e.conditional ? ' is-cond' : ''}`}>
        <path d={d} pathLength={100} markerEnd="url(#arrow)" />
        {on && <path key={p.pulse} className="ge-pulse" d={d} pathLength={100} />}
        {label && (
          <text x={mx} y={my} textAnchor="middle" className="ge-label">
            <title>{keys?.join(', ')}</title>
            {label}
          </text>
        )}
      </g>,
    ]
  })

  return (
    <svg className="graph" viewBox={`0 0 ${width} ${height}`} style={{ maxWidth: width }} role="img" aria-label="Pipeline graph">
      <defs>
        <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto">
          <path d="M0,0 L8,4 L0,8 z" className="ge-head" />
        </marker>
      </defs>
      {edges}
      {p.graph.nodes.map((n) => {
        const b = box(n)
        if (n.role !== 'node') {
          return (
            <g key={n.id} className="gn gn-term" transform={`translate(${b.x},${b.y})`}>
              <rect width={b.w} height={b.h} rx={13} />
              <text x={b.w / 2} y={b.h / 2 + 4} textAnchor="middle">{n.role === 'start' ? 'input' : 'output'}</text>
            </g>
          )
        }
        const mark = p.marks?.[n.id]
        const isFocus = f?.node === n.id
        const badge: Badge | null = p.verdict && n.status ? verdictBadge(n) : isFocus && f?.phase === 'in' ? ['dot', 'running'] : isFocus && f?.phase === 'edge' ? ['arrow', 'receiving'] : mark ? MARK_BADGE[mark] : null
        const cls = ['gn', p.verdict && n.status ? `st-${n.status}` : '', mark && !p.verdict ? `mk-${mark}` : '', isFocus ? `is-focus ph-${f?.phase ?? ''}` : '', p.selected === n.id ? 'is-sel' : '', n.verdict?.pruned ? 'is-pruned' : ''].join(' ')
        return (
          <g key={n.id} className={cls} transform={`translate(${b.x},${b.y})`} tabIndex={0} role="button" aria-label={`${n.id} ${badge?.[1] ?? ''}`} onClick={() => p.onSelect?.(n.id)} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && p.onSelect?.(n.id)}>
            <rect width={b.w} height={b.h} rx={3} />
            <text x={10} y={20} className="gn-name">{n.id.length > 15 ? `${n.id.slice(0, 14)}…` : n.id}</text>
            {n.kind && <text x={10} y={b.h - 10} className="gn-kind">{KIND[n.kind] ?? n.kind}</text>}
            {badge && (
              <>
                <path className={`gn-glyph g-${badge[0]}`} d={GLYPHS[badge[0]]} transform={`translate(${b.w - 22 - badge[1].length * 5.4},${b.h - 19})`} />
                <text x={b.w - 8} y={b.h - 10} textAnchor="end" className="gn-badge">{badge[1]}</text>
              </>
            )}
            {p.diff?.has(n.id) && (
              <text x={b.w - 8} y={18} textAnchor="end" className="gn-diff"><title>Output differs from the known-good run</title>≠</text>
            )}
          </g>
        )
      })}
    </svg>
  )
}
