import type { Data, Frame, HandOff, JobEvent, Mark, StepsView } from './model'
import { brief } from './model'
import { TRIAL_LABEL, setText } from './terms'

const arr = (v: unknown): string[] => (Array.isArray(v) ? v.map(String) : [])
const sid = (v: unknown) => {
  const s = String(v ?? '')
  return s.length > 12 ? `${s.slice(0, 8)}…${s.slice(-4)}` : s
}

/** A recorded run as frames: each node receives its input, produces output, hands keys on. */
export function stepFrames(v: StepsView): Frame[] {
  const out: Frame[] = []
  for (const s of v.steps) {
    if (s.node !== '__start__') {
      out.push({
        text: s.log[0] ?? `${s.node} received ${brief(s.input)}`,
        tone: 'info',
        node: s.node,
        phase: 'in',
        data: s.input,
        fresh: s.changed,
      })
    }
    out.push({
      text: s.error ? `${s.node} failed: ${s.error}` : (s.log[1] ?? s.log[0] ?? `${s.node} produced output`),
      tone: s.error ? 'bad' : s.node === '__start__' ? 'head' : 'ok',
      node: s.node,
      phase: 'out',
      data: s.output,
      error: s.error,
      mark: { [s.node]: s.error ? 'error' : 'ran' },
    })
    for (const e of v.edges.filter((e) => e.source === s.node)) out.push(edgeFrame(e))
  }
  out.push({ text: `run finished: ${brief(v.final_state, 2)}`, tone: 'head' })
  return out
}

function edgeFrame(e: HandOff): Frame {
  return {
    text: `${e.source === '__start__' ? 'run input' : e.source} → ${e.target} hands over ${e.keys.join(', ') || 'state'}`,
    tone: 'muted',
    node: e.target,
    phase: 'edge',
    edge: e,
  }
}

/** A diagnosis job's progress events as frames, so the same stage can play the trials. */
export function jobFrames(events: JobEvent[]): Frame[] {
  const out: Frame[] = []
  let budget = 0
  for (const e of events) {
    const at = e.at_ms
    const push = (f: Frame) => out.push({ at, ...f })
    switch (e.event) {
      case 'start':
        push({ text: `Diagnosis started on run ${sid(e.thread_id)}; recorded path ${arr(e.nodes_on_path).join(' → ')}`, tone: 'head' })
        break
      case 'check':
        push(e.pass
          ? { text: 'Check on the failed run: it passes, so there is nothing to diagnose', tone: 'warn' }
          : { text: `Check on the failed run: FAIL (${arr(e.failed).join('; ')})`, tone: 'bad' })
        break
      case 'sources':
        for (const s of (e.sources as Data[] | undefined) ?? []) {
          push({ text: `Known-good run ${sid(s.thread_id)}: ${String(s.why ?? '')}`, tone: s.eligible ? 'ok' : 'warn' })
        }
        break
      case 'plan': {
        budget = Number(e.max_trials ?? 0)
        const pruned = (e.pruned as Record<string, string> | undefined) ?? {}
        const mark: Record<string, Mark> = {}
        for (const n of Object.keys(pruned)) mark[n] = 'pruned'
        for (const n of arr(e.candidates)) mark[n] = 'candidate'
        push({ text: `Plan: test ${arr(e.candidates).join(', ') || 'nothing'}; skip ${Object.keys(pruned).join(', ') || 'none'}; budget ${budget} trials (testing every group would take ${String(e.exhaustive_trials ?? '?')})`, tone: 'head', mark })
        break
      }
      case 'trial_start': {
        const r = arr(e.restored)
        push({ text: `Trial ${String(e.n)} of budget ${budget || '?'}: restore ${r.join(' + ')} to known-good`, tone: 'head', reset: true, mark: Object.fromEntries(r.map((n) => [n, 'restored' as Mark])) })
        break
      }
      case 'fork':
        push({ text: `Forked the failed run at the checkpoint before ${String(e.fork_node)} (trial thread ${sid(e.fork_thread)})`, tone: 'info', node: String(e.fork_node) })
        break
      case 'resume':
        push({ text: 'Resuming downstream from the recording; replay only, no live calls', tone: 'muted' })
        break
      case 'rerun': {
        type Re = { node: string; step: number; restored: boolean; input: Data; output: Data | null; error: string | null }
        const done: Re[] = []
        for (const s of (e.steps as Re[] | undefined) ?? []) {
          // a node is fed by the nodes of the superstep before it (parallel branches share a step)
          for (const src of done.filter((d) => d.step === s.step - 1)) {
            push(edgeFrame({ source: src.node, target: s.node, keys: Object.keys(src.output ?? {}) }))
          }
          push({ text: `${s.node}${s.restored ? ' (restored)' : ''} received ${brief(s.input)}`, tone: 'info', node: s.node, phase: 'in', data: s.input, restored: s.restored })
          push({ text: s.error ? `${s.node} failed: ${s.error}` : `${s.node} produced ${brief(s.output)}`, tone: s.error ? 'bad' : 'ok', node: s.node, phase: 'out', data: s.output, error: s.error, restored: s.restored, mark: { [s.node]: s.error ? 'error' : s.restored ? 'restored' : 'ran' } })
          done.push(s)
        }
        break
      }
      case 'trial': {
        const v = String(e.verdict)
        const label = TRIAL_LABEL[e.label as keyof typeof TRIAL_LABEL] ?? String(e.label)
        const r = arr(e.restored)
        push({ text: `Trial ${String(e.n)} verdict: ${v.toUpperCase()}, ${label.toLowerCase()} (${String(e.reason)}; ${String(e.elapsed_s ?? '?')} s)`, tone: v === 'pass' ? 'ok' : v === 'fail' ? 'bad' : 'warn', mark: Object.fromEntries(r.map((n) => [n, (v === 'pass' ? 'pass' : 'fail') as Mark])) })
        break
      }
      case 'done':
        push(e.status === 'found'
          ? { text: `Done: smallest fix ${setText(e.minimal_sets as string[][])} after ${String(e.trials_used)} trial(s)`, tone: 'ok' }
          : { text: `Done: cannot say (${String(e.reason)})`, tone: 'warn' })
        break
    }
  }
  return out
}
