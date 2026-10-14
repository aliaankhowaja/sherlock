import type { GEdge, GlyphName, GNode, GraphView, Mark } from './model'
import type { NodeStatus } from './api'

export const W = 148
export const H = 54
export const COL = 214
export const ROW = 86
export const PAD = 22

export interface Box {
  x: number
  y: number
  w: number
  h: number
}

export interface Placed {
  nodes: GNode[]
  edges: GEdge[]
  boxes: Map<string, Box>
  groups: Map<string, string[]>
  width: number
  height: number
}

/** A node's stage: the server's `stage`/`group` when given, else the name before the first `.`, `/`, `:` or `_`. */
function stageOf(n: GNode): string | null {
  const s = (n as { stage?: unknown; group?: unknown }).stage ?? (n as { group?: unknown }).group
  if (typeof s === 'string' && s) return s
  const m = /^([A-Za-z0-9]+)[._/:]/.exec(n.id)
  return m ? m[1] : null
}

/** Stages worth drawing: at least two of them, each with two or more nodes. */
export function stages(g: GraphView): Map<string, string[]> {
  const all = new Map<string, string[]>()
  for (const n of g.nodes) {
    if (n.role !== 'node') continue
    const s = stageOf(n)
    if (s) all.set(s, [...(all.get(s) ?? []), n.id])
  }
  const keep = new Map([...all].filter(([, ids]) => ids.length >= 2))
  return keep.size >= 2 ? keep : new Map()
}

const RANK: Record<NodeStatus, number> = { culprit: 4, abstained: 3, cleared: 2, unverified: 1 }

/** Place nodes from the server's layer/row, collapse chosen stages into one box, and never let two boxes overlap. */
export function place(g: GraphView, collapsed: Set<string>): Placed {
  const groups = stages(g)
  const owner = new Map<string, string>()
  for (const [s, ids] of groups) if (collapsed.has(s)) for (const id of ids) owner.set(id, `stage:${s}`)
  const nodes: GNode[] = g.nodes.filter((n) => !owner.has(n.id))
  for (const [s, ids] of groups) {
    if (!collapsed.has(s)) continue
    const members = g.nodes.filter((n) => ids.includes(n.id))
    const worst = members.map((m) => m.status).filter((x): x is NodeStatus => !!x).sort((a, b) => RANK[b] - RANK[a])[0] ?? null
    nodes.push({
      id: `stage:${s}`, role: 'node', kind: null, status: worst, reason: `${members.length} nodes`,
      layer: Math.min(...members.map((m) => m.layer)), row: members.reduce((t, m) => t + m.row, 0) / members.length,
      verdict: null, faults: [],
    })
  }
  const key = (id: string) => owner.get(id) ?? id
  const seen = new Set<string>()
  const edges: GEdge[] = []
  for (const e of g.edges) {
    const s = key(e.source)
    const t = key(e.target)
    if (s === t || seen.has(`${s}>${t}`)) continue
    seen.add(`${s}>${t}`)
    edges.push({ ...e, source: s, target: t })
  }

  const boxes = new Map<string, Box>()
  const byLayer = new Map<number, GNode[]>()
  for (const n of nodes) byLayer.set(n.layer, [...(byLayer.get(n.layer) ?? []), n])
  let maxY = 0
  for (const [layer, list] of byLayer) {
    list.sort((a, b) => a.row - b.row)
    let prev = -Infinity
    for (const n of list) {
      const y = Math.max(PAD + n.row * ROW, prev + ROW)
      prev = y
      const term = n.role !== 'node'
      const w = term ? 64 : W
      const h = term ? 26 : H
      boxes.set(n.id, { x: PAD + layer * COL + (W - w) / 2, y: y + (H - h) / 2, w, h })
      maxY = Math.max(maxY, y)
    }
  }
  const maxL = Math.max(0, ...nodes.map((n) => n.layer))
  const back = edges.some((e) => e.back) ? 34 : 0
  return { nodes, edges, boxes, groups, width: PAD * 2 + maxL * COL + W, height: maxY + H + PAD + back }
}

/** SVG path for an edge, plus where its label goes. Back edges loop underneath. */
export function edgePath(A: Box, B: Box, back: boolean) {
  if (back || B.x <= A.x) {
    const y = Math.max(A.y + A.h, B.y + B.h) + 30
    return { d: `M${A.x + A.w / 2},${A.y + A.h} C${A.x + A.w / 2},${y} ${B.x + B.w / 2},${y} ${B.x + B.w / 2},${B.y + B.h}`, mx: (A.x + B.x + A.w) / 2, my: y - 4 }
  }
  const x1 = A.x + A.w
  const y1 = A.y + A.h / 2
  const x2 = B.x
  const y2 = B.y + B.h / 2
  const c = (x2 - x1) / 2
  return { d: `M${x1},${y1} C${x1 + c},${y1} ${x2 - c},${y2} ${x2},${y2}`, mx: (x1 + x2) / 2, my: (y1 + y2) / 2 - 7 }
}

export type Badge = [GlyphName, string]

export const MARK_BADGE: Record<Mark, Badge> = {
  ran: ['check', 'ran'],
  error: ['cross', 'error'],
  restored: ['restore', 'restored'],
  pruned: ['dash', 'skipped'],
  candidate: ['diamond', 'to test'],
  pass: ['check', 'passed'],
  fail: ['cross', 'failed'],
}

export function verdictBadge(n: GNode): Badge | null {
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

