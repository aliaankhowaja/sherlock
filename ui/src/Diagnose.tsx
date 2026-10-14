import { useState } from 'react'
import { short, useJson, type Info } from './api'
import type { GraphView, Job, JobEvent } from './model'
import { startDiagnosis } from './jobs'
import { Glyph } from './Kv'
import { jobFrames } from './script'
import PipelineStage from './Stage'
import { buildCommand, setText } from './terms'

type Item = { label: string; state: 'done' | 'now' | 'bad'; at?: number }

/** The step checklist beside the live stage, straight from the job's progress events. */
function checklist(job: Job): Item[] {
  const items: Item[] = []
  const ev = (name: string) => job.events.filter((e) => e.event === name)
  const at = (e?: JobEvent) => e?.at_ms
  const s = (v: unknown) => String(v ?? '')
  const check = ev('check')[0]
  if (check) items.push({ label: check.pass ? 'The failed run already passes' : 'Confirmed the failed run fails its check', state: check.pass ? 'bad' : 'done', at: at(check) })
  if (ev('sources')[0]) items.push({ label: 'Compared with the known-good run', state: 'done', at: at(ev('sources')[0]) })
  const plan = ev('plan')[0]
  if (plan) items.push({ label: `Planned ${(plan.candidates as string[]).length} to test, ${Object.keys(plan.pruned as object).length} pruned`, state: 'done', at: at(plan) })
  for (const t of ev('trial_start')) {
    const r = (t.restored as string[]).join(' + ')
    const end = job.events.find((e) => e.event === 'trial' && e.n === t.n)
    const fork = job.events.find((e) => e.event === 'fork' && e.at_ms >= t.at_ms && (!end || e.at_ms <= end.at_ms))
    if (fork) items.push({ label: `Forked at the checkpoint before ${s(fork.fork_node)}`, state: 'done', at: at(fork) })
    items.push(end
      ? { label: `Trial ${s(t.n)}: restore ${r} → ${s(end.verdict)}`, state: end.verdict === 'pass' ? 'done' : 'bad', at: at(end) }
      : { label: `Trial ${s(t.n)}: restored ${r}, resuming downstream`, state: job.state === 'running' ? 'now' : 'bad', at: at(t) })
  }
  const done = ev('done')[0]
  if (done) items.push({ label: done.status === 'found' ? `Verdict: ${setText(done.minimal_sets as string[][])}` : 'Verdict: cannot say', state: 'done', at: at(done) })
  if (job.state === 'running' && !done && !items.some((i) => i.state === 'now')) items.push({ label: 'Working…', state: 'now' })
  if (job.state === 'failed') items.push({ label: job.error ?? 'The diagnosis stopped without a verdict', state: 'bad' })
  return items
}

const GLYPH = { done: 'check', now: 'dot', bad: 'cross' } as const

interface Props {
  info: Info | null
  infoError: string | null
  team: string
  failed: string
  good: string
  job: Job | null
  jobError: string | null
  diagnosed: boolean
  onJob: (id: number) => void
  onPick: () => void
  onVerdict: () => void
}

export default function Diagnose(p: Props) {
  const graph = useJson<GraphView>(p.team ? `/api/teams/${encodeURIComponent(p.team)}/graph` : null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const run = p.info?.run
  const command = buildCommand(p.info, p.failed, p.good)
  const otherJob = run?.running_job != null && run.running_job !== p.job?.id

  const start = () => {
    if (!p.info) return
    setBusy(true)
    setError(null)
    startDiagnosis(p.info, p.team, p.failed, p.good)
      .then(p.onJob)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false))
  }

  if (p.infoError) return <p className="error-line">Sherlock's server is not answering ({p.infoError}). Start it again with <code>sherlock serve</code> and reload.</p>
  if (!p.good) {
    return (
      <div className="screen blank">
        <p className="lede">A diagnosis needs a known-good run to copy behaviour from. None is picked.</p>
        <button type="button" className="btn-primary" onClick={p.onPick}>Pick a known-good run</button>
      </div>
    )
  }

  const launch = (
    <div className="launch">
      <div>
        <p className="lede">Sherlock forks the failed run <code>{short(p.failed)}</code>, puts chosen nodes back to how they behaved in <code>{short(p.good)}</code>, replays the rest from the recording, and checks the answer. No live model calls.</p>
        {p.diagnosed && !p.job && <p className="muted small">This run already has a verdict. Running again replaces it.</p>}
        {otherJob && <p className="error-line">Another diagnosis (job {run?.running_job}) is running. Wait for it to finish.</p>}
        {error && <p className="error-line">{error}</p>}
        {run && !run.enabled && <p className="muted small">The run button is off: this server was started without a recorded project. Run the command below in a terminal instead.</p>}
      </div>
      {run?.enabled && (
        <button type="button" className="btn-primary btn-big" disabled={busy || otherJob || p.job?.state === 'running'} onClick={start}>
          {busy ? 'Starting…' : p.job ? 'Run diagnosis again' : 'Run diagnosis'}
        </button>
      )}
      <details className="cmd" open={run ? !run.enabled : false}>
        <summary>The same diagnosis as a terminal command</summary>
        <code>{command}</code>
      </details>
    </div>
  )

  return (
    <div className="screen">
      {launch}
      {p.jobError && <p className="error-line">{p.jobError}</p>}
      {p.job && graph.data && (
        <div className="diag">
          <PipelineStage key={p.job.id} graph={graph.data} frames={jobFrames(p.job.events)} live={p.job.state === 'running'} autoplay />
          <aside className="checklist" aria-label="Diagnosis steps">
            <h3 className="eyebrow">Job {p.job.id} · {p.job.state}</h3>
            <ol>
              {checklist(p.job).map((i, n) => (
                <li key={n} className={`ck-${i.state}`}>
                  <span className="ck-g"><Glyph name={GLYPH[i.state]} /></span>
                  <span>{i.label}</span>
                  {i.at !== undefined && <span className="ck-t">{(i.at / 1000).toFixed(2)}s</span>}
                </li>
              ))}
            </ol>
            {p.job.state === 'done' && <button type="button" className="btn-primary" onClick={p.onVerdict}>Read the verdict</button>}
          </aside>
        </div>
      )}
    </div>
  )
}
