import { useState } from 'react'
import { short, useJson } from './api'
import type { GraphView, StepsView } from './model'
import HealthList from './Health'
import NodeCard from './NodeCard'
import { differing, stepFrames, stepOf } from './script'
import PipelineStage from './Stage'

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

  if (fRun.data?.health && !fRun.data.health.usable) {
    return (
      <div className="screen">
        <HealthList health={fRun.data.health} thread={failed} />
      </div>
    )
  }

  return (
    <div className="screen">
      <p className="caption">
        <b>{which === 'failed' ? 'Failed run' : 'Known-good run'}</b> <code>{short(shown.thread_id)}</code>
        <span>replayed from its recorded checkpoints</span>
        {diff.size > 0 && <span><b className="diff-key">≠</b> output differs from the known-good run</span>}
      </p>
      <PipelineStage
        key={shown.thread_id}
        graph={graph.data}
        frames={stepFrames(shown)}
        labels={shown.edges}
        diff={diff}
        relevant={new Set(shown.steps.map((s) => s.node))}
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
      {shown.health && shown.health.items.some((i) => !i.ok) && <HealthList health={shown.health} thread={shown.thread_id} />}
      {shown.note && <p className="muted small">{shown.note}</p>}
      <div className="actions">
        <button type="button" className="btn-primary" onClick={onNext}>Next: diagnose this run</button>
      </div>
    </div>
  )
}
