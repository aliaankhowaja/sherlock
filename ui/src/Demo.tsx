import type { NodeStatus } from './api'
import Graph from './Graph'
import Judgment from './Judgment'
import type { GNode, GraphView } from './model'

/** The seeded two-cause case (vendor_brief; harness/fixtures/sherlock-demo): shown when the server has no verdict of its own. */
const CHAIN: [string, NodeStatus][] = [
  ['router', 'cleared'],
  ['retriever', 'culprit'],
  ['extractor', 'culprit'],
  ['writer', 'cleared'],
  ['reviewer', 'cleared'],
]

const node = (id: string, role: GNode['role'], layer: number, status: NodeStatus | null): GNode => ({
  id, role, kind: null, status, reason: status === 'culprit' ? 'in the smallest fix' : status ? 'tested; not in any smallest fix' : '', layer, row: 0,
  verdict: null, faults: [],
})

const NAMES = ['__start__', ...CHAIN.map(([id]) => id), '__end__']

const GRAPH: GraphView = {
  nodes: [node('__start__', 'start', 0, null), ...CHAIN.map(([id, s], i) => node(id, 'node', i + 1, s)), node('__end__', 'end', CHAIN.length + 1, null)],
  edges: NAMES.slice(1).map((target, i) => ({ source: NAMES[i], target, conditional: false, back: false })),
  note: null,
  known_good_source: null,
}

const CHECK = {
  pass: false,
  results: [
    { type: 'contains', pass: false, score: 0, reason: "output does not contain 'ISO 27001'" },
    { type: 'not-contains', pass: false, score: 0, reason: "expected the opposite: output contains 'SOC 2'" },
    { type: 'contains', pass: true, score: 1, reason: "output contains 'Data region: EU'" },
  ],
}

export default function Demo() {
  return (
    <section className="demo">
      <header className="verdict v-found">
        <h2 className="headline">Restoring retriever and extractor together makes the run pass; neither alone does.</h2>
        <p className="verdict-sub">3 restore-and-replay trials instead of 31 for every group · each set is minimal and the search was complete</p>
      </header>
      <Judgment check={CHECK} run={null} />
      <div className="verdict-graph">
        <Graph graph={GRAPH} verdict selected={null} onSelect={() => undefined} />
      </div>
    </section>
  )
}
