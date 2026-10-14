import { useState } from 'react'
import { short, useJson } from './api'
import type { GraphView, RunStep, StepsView } from './model'
import NodeCard from './NodeCard'
import { stepFrames } from './script'
import PipelineStage from './Stage'

const stepOf = (v: StepsView | null, node: string): RunStep | undefined => v?.steps.filter((s) => s.node === node).at(-1)

/** Nodes whose output in the failed run differs from the known-good run. */
function differing(a: StepsView | null, b: StepsView | null): Set<string> {
  const out = new Set<string>()
  if (!a || !b) return out
  for (const s of a.steps) {
    if (s.node === '__start__') continue
    const g = stepOf(b, s.node)
    if (!g || JSON.stringify(g.output) !== JSON.stringify(s.output)) out.add(s.node)
  }
  return out
}

export default function Replay({ team, failed, good, onNext }: { team: string; failed: string; good: string; onNext: () => void }) {
  const [which, setWhich] = useState<'failed' | 'good'>('failed')
  const graph = useJson<GraphView>(team ? `/api/teams/${encodeURIComponent(team)}/graph` : null)
  const fRun = useJson<StepsView>(failed ? `/api/runs/${encodeURIComponent(failed)}/steps` : null)
  const gRun = useJson<StepsView>(good ? `/api/runs/${encodeURIComponent(good)}/steps` : null)
  const shown = which === 'good' && gRun.data ? gRun.data : fRun.data
  const diff = differing(fRun.data, gRun.data)
  const error = graph.error ?? fRun.error ?? (which === 'good' ? gRun.error : null)

  if (error) return <p className="error-line">Could not load the run: {error}</p>
  if (!graph.data || !shown) return <p className="muted">Loading the recorded run…</p>

  return (
    <div className="screen">
      <p className="lede">
        {which === 'failed' ? 'The failed run' : 'The known-good run'} <code>{short(shown.thread_id)}</code>, replayed from its checkpoints.
        Watch each node take its input, produce its output, and hand it on.
        {diff.size > 0 && <> Nodes marked <b>≠</b> wrote something different from the known-good run.</>}
      </p>
      <PipelineStage
        key={shown.thread_id}
        graph={graph.data}
        frames={stepFrames(shown)}
        labels={shown.edges}
        diff={diff}
        detail={(n) => <NodeCard node={graph.data?.nodes.find((x) => x.id === n)} step={stepOf(shown, n)} good={which === 'failed' ? stepOf(gRun.data, n) : undefined} />}
        toolbar={
          good ? (
            <div className="seg" role="radiogroup" aria-label="Which run">
              <button type="button" role="radio" aria-checked={which === 'failed'} className={which === 'failed' ? 'is-on' : ''} onClick={() => setWhich('failed')}>Failed run</button>
              <button type="button" role="radio" aria-checked={which === 'good'} className={which === 'good' ? 'is-on' : ''} onClick={() => setWhich('good')}>Known-good run</button>
            </div>
          ) : null
        }
      />
      {shown.note && <p className="muted small">{shown.note}</p>}
      <div className="actions">
        <button type="button" className="btn-primary" onClick={onNext}>Next: diagnose this run</button>
      </div>
    </div>
  )
}
