import { useRef, useState, type ReactNode } from 'react'
import { short, useJson, type Diagnosis, type Summary } from './api'
import type { GraphView, StepsView } from './model'
import Gates from './Gates'
import Graph from './Graph'
import { Glyph } from './Kv'
import NodeCard from './NodeCard'
import { downloadHtml, downloadJson } from './share'
import { GLOSSARY, REASON_HELP, TRIAL_LABEL, plain } from './terms'

const TIP: Record<string, string> = {
  pass: 'The check passed: the answer matched what a right answer must look like.',
  fail: 'The check failed: the answer was wrong.',
  abstain: GLOSSARY[5].meaning,
  minimal: GLOSSARY[4].meaning,
  pruned: GLOSSARY[7].meaning,
  restore: GLOSSARY[2].meaning,
}

function Term({ k, children }: { k: keyof typeof TIP; children: ReactNode }) {
  return <span className="term" tabIndex={0} data-tip={TIP[k]}>{children}</span>
}

const GATE_NAME: Record<string, string> = { g0: 'clue', g1: 'LLM hint', g2: 'path check' }
const GATE_TIP: Record<string, string> = {
  g0: 'A cheap clue pointed at a node in this group; it only set the order.',
  g1: 'The optional language-model hint nominated a node in this group; it only breaks ties in the order.',
  g2: 'A suspect you named, kept because a recorded hand-off links it to the failure.',
}

const both = (set: string[]) => (set.length === 1 ? `${set[0]} alone` : `${set.slice(0, -1).join(', ')} and ${set.at(-1)} together`)

const WHY_NOT: Record<string, string> = {
  unrecorded_call: 'a trial needed a model call that was never recorded',
  cannot_test: 'no group of nodes could be tested honestly',
  budget_exhausted: 'the trial budget ran out first',
  no_known_good: 'there was no known-good run to copy from',
  no_candidates: 'no node could be given different behaviour',
  cutoff: 'no fix fits within the size limit',
  not_fixable: 'restoring every candidate still fails',
  already_passes: 'the failed run already passes its check',
  no_history: 'the run has no recorded steps',
  no_check: 'nothing says what a right answer looks like',
  path_check_failed: 'the named suspect is not on the recorded path',
  sources_disagree: 'the known-good runs disagree',
  cannot_attribute: 'a difference could not be tied to one node',
}

function headline(s: Summary): string {
  if (s.status === 'abstain') return `Cannot say: ${(s.reason_code && WHY_NOT[s.reason_code]) || 'the evidence is not conclusive'}.`
  const [first, ...rest] = s.minimal_sets
  if (!first) return 'No fix was found.'
  let text = `Restoring ${both(first)} makes the run pass`
  if (first.length === 2) text += '; neither alone does'
  else if (first.length > 2) text += '; no smaller part of them does'
  for (const r of rest) text += `; so does restoring ${both(r)}`
  return `${text}.`
}

const stepOf = (v: StepsView | null, node: string) => v?.steps.filter((s) => s.node === node).at(-1)

export default function Verdict({ failed, onDiagnose, onReplay }: { failed: string; onDiagnose: () => void; onReplay: () => void }) {
  const id = encodeURIComponent(failed)
  const diag = useJson<Diagnosis>(failed ? `/api/diagnoses/${id}` : null)
  const graph = useJson<GraphView>(failed ? `/api/diagnoses/${id}/graph` : null)
  const good = diag.data?.artifact.known_good_source?.thread_id ?? ''
  const fRun = useJson<StepsView>(failed ? `/api/runs/${id}/steps` : null)
  const gRun = useJson<StepsView>(good ? `/api/runs/${encodeURIComponent(good)}/steps` : null)
  const [sel, setSel] = useState<string | null>(null)
  const report = useRef<HTMLDivElement>(null)

  if (diag.error) {
    return (
      <div className="screen blank">
        <p className="lede">{/404|no diagnosis|not found/i.test(diag.error) ? `Run ${short(failed)} has no verdict yet.` : `Could not read the verdict: ${diag.error}`}</p>
        <button type="button" className="btn-primary" onClick={onDiagnose}>Go to Diagnose</button>
      </div>
    )
  }
  if (!diag.data || !graph.data) return <p className="muted">Loading the verdict…</p>
  const d = diag.data
  const s = d.summary
  const trials = d.artifact.trials ?? []
  const exhaustive = d.artifact.trial_reduction?.exhaustive_trials

  return (
    <div className="screen" ref={report}>
      <header className={`verdict v-${s.status}`}>
        <h2 className="headline">{headline(s)}</h2>
        <p className="verdict-sub">
          {s.trials_used ?? trials.length} <Term k="restore">restore-and-replay</Term> trials{exhaustive ? ` instead of ${exhaustive} for every group` : ''}
          {' · '}known-good run <code>{short(good || null)}</code>
          {' · '}{s.status === 'abstain' ? <Term k="abstain">no node is named</Term> : s.complete ? <>each set is <Term k="minimal">minimal</Term> and the search was complete</> : 'the search stopped early, so other fixes may exist'}
        </p>
        {s.status === 'abstain' && (
          <>
            {s.reason_code && REASON_HELP[s.reason_code] && <p className="lede verdict-help">{REASON_HELP[s.reason_code]}</p>}
            <p className="verdict-why">Engine reason: {plain(s.reason)}</p>
          </>
        )}
      </header>
      {(d.artifact.gates ?? d.artifact.gate_summary) && <Gates g={(d.artifact.gates ?? d.artifact.gate_summary)!} />}
      <div className="verdict-graph">
        <Graph graph={graph.data} verdict selected={sel} onSelect={(n) => setSel(n === sel ? null : n)} />
        <ul className="legend" aria-label="Legend">
          <li className="st-culprit"><Glyph name="bang" />must change</li>
          <li className="st-cleared"><Glyph name="check" />not needed</li>
          <li className="st-unverified"><Glyph name="dash" /><Term k="pruned">not tested</Term></li>
          <li className="st-unverified"><Glyph name="ring" />not verified</li>
          <li className="st-abstained"><Glyph name="question" />cannot say</li>
        </ul>
      </div>
      <div className="verdict-lower">
        <section>
          <h3 className="eyebrow">Trial log</h3>
          <table className="trials">
            <thead><tr><th>#</th><th>Restored</th><th>Result</th><th>Why</th><th>Time</th></tr></thead>
            <tbody>
              {trials.map((t) => (
                <tr key={t.n} className={`tr-${t.verdict}`}>
                  <td>{t.n}</td>
                  <td>{t.restored.join(' + ')}{t.gates?.filter((g) => g !== 'g3').map((g) => <span key={g} className="tag gate-tag" title={GATE_TIP[g] ?? g}>{GATE_NAME[g] ?? g}</span>)}</td>
                  <td><Term k={t.verdict === 'pass' ? 'pass' : t.verdict === 'fail' ? 'fail' : 'abstain'}><Glyph name={t.verdict === 'pass' ? 'check' : t.verdict === 'fail' ? 'cross' : 'question'} />{TRIAL_LABEL[t.label] ?? t.verdict}</Term></td>
                  <td>{plain(t.reason)}</td>
                  <td>{t.elapsed_s !== undefined ? `${t.elapsed_s.toFixed(1)} s` : ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="actions" data-noshare>
            <button type="button" onClick={() => report.current && downloadHtml(report.current, d)}>Download report (HTML)</button>
            <button type="button" onClick={() => downloadJson(d)}>Download artifact (JSON)</button>
            <button type="button" onClick={onReplay}>Replay the failed run</button>
          </div>
        </section>
        <section className="inspect">
          <h3 className="eyebrow">Evidence</h3>
          {sel ? <NodeCard node={graph.data.nodes.find((n) => n.id === sel)} step={stepOf(fRun.data, sel)} good={stepOf(gRun.data, sel)} /> : <p className="muted">Click a node in the graph to see why it has its status, the trials that touched it, and its input and output.</p>}
        </section>
      </div>
    </div>
  )
}
