import type { Badge, Box } from './layout'
import { GLYPHS, type GNode } from './model'

const KIND: Record<string, string> = { deterministic: 'code', llm: 'LLM', tool: 'tool' }

interface NodeProps {
  n: GNode
  b: Box
  cls: string
  badge: Badge | null
  diff: boolean
  onSelect?: (id: string) => void
}

/** One pipeline node: name, kind, a drawn status mark with its word, and ≠ when it differs from the good run. */
export function NodeEl({ n, b, cls, badge, diff, onSelect }: NodeProps) {
  if (n.role !== 'node') {
    return (
      <g className="gn gn-term" transform={`translate(${b.x},${b.y})`}>
        <rect width={b.w} height={b.h} rx={13} />
        <text x={b.w / 2} y={b.h / 2 + 4} textAnchor="middle">{n.role === 'start' ? 'input' : 'output'}</text>
      </g>
    )
  }
  const stage = n.id.startsWith('stage:')
  const name = stage ? n.id.slice(6) : n.id
  const pick = () => onSelect?.(n.id)
  return (
    <g className={`${cls}${stage ? ' gn-stage' : ''}`} transform={`translate(${b.x},${b.y})`} tabIndex={0} role="button" aria-label={`${name} ${badge?.[1] ?? ''}`} onClick={pick} onKeyDown={(e) => (e.key === 'Enter' || e.key === ' ') && pick()}>
      <title>{stage ? `Stage ${name}: ${n.reason}. Click to expand.` : n.id}</title>
      <rect width={b.w} height={b.h} rx={3} />
      {stage && <rect className="gn-stack" x={4} y={-4} width={b.w} height={b.h} rx={3} />}
      <text x={10} y={20} className="gn-name">{name.length > 17 ? `${name.slice(0, 16)}…` : name}</text>
      {(n.kind || stage) && <text x={10} y={b.h - 10} className="gn-kind">{stage ? n.reason : KIND[n.kind ?? ''] ?? n.kind}</text>}
      {badge && (
        <g className="gn-mark">
          <path className={`gn-glyph g-${badge[0]}`} d={GLYPHS[badge[0]]} transform={`translate(${b.w - 22 - badge[1].length * 6},${b.h - 19})`} />
          <text x={b.w - 8} y={b.h - 10} textAnchor="end" className="gn-badge">{badge[1]}</text>
        </g>
      )}
      {diff && (
        <text x={b.w - 8} y={18} textAnchor="end" className="gn-diff"><title>Output differs from the known-good run</title>≠</text>
      )}
    </g>
  )
}

/** Overview of a large graph: every node as a dot-sized box, the visible window outlined; click to move there. */
export function Minimap({ boxes, classOf, width, height, view, onJump }: { boxes: Map<string, Box>; classOf: (id: string) => string; width: number; height: number; view: Box; onJump: (x: number, y: number) => void }) {
  return (
    <svg
      style={{ height: Math.max(36, Math.min(110, (230 * height) / width)) }}
      className="minimap"
      viewBox={`0 0 ${width} ${height}`}
      aria-label="Overview; click to move the view"
      onClick={(e) => {
        const r = e.currentTarget.getBoundingClientRect()
        const s = Math.max(width / r.width, height / r.height)
        onJump((e.clientX - r.left) * s - (r.width * s - width) / 2, (e.clientY - r.top) * s - (r.height * s - height) / 2)
      }}
    >
      {[...boxes].map(([id, b]) => <rect key={id} className={`mm ${classOf(id)}`} x={b.x} y={b.y} width={b.w} height={b.h} />)}
      <rect className="mm-view" x={view.x} y={view.y} width={view.w} height={view.h} />
    </svg>
  )
}
