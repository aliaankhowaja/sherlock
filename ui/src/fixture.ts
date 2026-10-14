import type { NodeStatus } from './api'
import type { Frame, GEdge, GNode, GraphView, HandOff } from './model'

/** A synthetic 40-node team (stages, parallel branches, conditional routes, a retry loop) for checking the big-graph view. */
const STAGES: [string, string[][]][] = [
  ['intake', [['parse'], ['detect_lang', 'redact_pii'], ['normalize']]],
  ['triage', [['classify', 'priority', 'sentiment'], ['route']]],
  ['kb', [['search', 'rerank_a'], ['fetch', 'rerank_b'], ['merge']]],
  ['policy', [['check_refund', 'check_sla', 'check_fraud'], ['decide']]],
  ['draft', [['outline'], ['write', 'cite'], ['tone', 'length'], ['assemble']]],
  ['review', [['grade', 'safety'], ['gate']]],
  ['final', [['format', 'translate'], ['sign'], ['send']]],
]

const CULPRIT = new Set(['kb_rerank_b', 'policy_check_sla'])
const CLEARED = new Set(['kb_merge', 'policy_decide', 'draft_write'])

export function bigGraph(): GraphView {
  const nodes: GNode[] = [{ id: '__start__', role: 'start', kind: null, status: null, reason: '', layer: 0, row: 1, verdict: null, faults: [] }]
  const edges: GEdge[] = []
  let layer = 1
  let prev = ['__start__']
  for (const [stage, cols] of STAGES) {
    for (const col of cols) {
      const ids = col.map((c) => `${stage}_${c}`)
      ids.forEach((id, row) => {
        const status: NodeStatus = CULPRIT.has(id) ? 'culprit' : CLEARED.has(id) ? 'cleared' : 'unverified'
        const pruned = status === 'unverified' && id.length % 3 !== 0 ? 'not an ancestor of the failed check' : null
        nodes.push({
          id, role: 'node', kind: id.includes('write') || id.includes('classify') || id.includes('grade') ? 'llm' : id.includes('search') || id.includes('fetch') ? 'tool' : 'deterministic',
          status, reason: status === 'culprit' ? 'in the smallest fix' : status === 'cleared' ? 'tested; not in any smallest fix' : pruned ? `not tested: ${pruned}` : 'not verified', layer, row: row + (ids.length === 1 ? 1 : ids.length === 2 ? 0.5 : 0),
          verdict: { node: id, status, reason: '', sets: status === 'culprit' ? [[...CULPRIT]] : [], clues: [], trials: status === 'unverified' ? [] : [1, 2, 3], restore: null, pruned, tested: !pruned, on_path: true },
          faults: [],
        })
      })
      for (const s of prev) for (const t of ids) edges.push({ source: s, target: t, conditional: stage === 'review' && t.endsWith('safety'), back: false })
      prev = ids
      layer += 1
    }
  }
  edges.push({ source: 'review_gate', target: 'draft_outline', conditional: true, back: true })
  nodes.push({ id: '__end__', role: 'end', kind: null, status: null, reason: '', layer, row: 1, verdict: null, faults: [] })
  for (const s of prev) edges.push({ source: s, target: '__end__', conditional: false, back: false })
  return { nodes, edges, note: null, known_good_source: null }
}

/** A replay along one route through the big graph, in the same frame shape as a recorded run. */
export function bigFrames(g: GraphView): { frames: Frame[]; labels: HandOff[] } {
  const frames: Frame[] = [{ text: 'run started with ticket="T-4411"', tone: 'head', node: '__start__', phase: 'out', data: { ticket: 'T-4411' }, mark: { __start__: 'ran' } }]
  const labels: HandOff[] = []
  const path = g.nodes.filter((n) => n.role === 'node' && !n.id.includes('rerank_a') && !n.id.includes('translate'))
  let last = '__start__'
  for (const n of path) {
    const edge = { source: last, target: n.id, keys: [`${last.split('_').pop()}_out`] }
    labels.push(edge)
    frames.push({ text: `${edge.source} → ${n.id} hands over ${edge.keys[0]}`, tone: 'muted', node: n.id, phase: 'edge', edge })
    frames.push({ text: `${n.id} received ${edge.keys[0]}`, tone: 'info', node: n.id, phase: 'in', data: { [edge.keys[0]]: 'value' }, fresh: edge.keys })
    const bad = n.id === 'policy_check_sla'
    frames.push({ text: bad ? `${n.id} failed: SLA table stale` : `${n.id} produced ${n.id.split('_').pop()}_out`, tone: bad ? 'bad' : 'ok', node: n.id, phase: 'out', data: { [`${n.id.split('_').pop()}_out`]: 'value' }, error: bad ? 'SLA table stale' : null, mark: { [n.id]: bad ? 'error' : 'ran' } })
    last = n.id
  }
  return { frames, labels }
}

export const bigGates = { nodes_total: 40, pruned_by_ancestry: 26, g0_flagged: 6, g1_nominated: 4, g2_cut: 1, g3_trials: 3, exhaustive_count: 9880 }
