import type { GNode, RunStep } from './model'
import { Glyph, Kv } from './Kv'
import { STATUS_LABEL, STATUS_MEANING, plain } from './terms'

const KIND_LABEL: Record<string, string> = {
  deterministic: 'Deterministic code',
  llm: 'LLM call',
  tool: 'Tool call',
}

/** Everything known about one node: what it is, what it got and gave, and what the verdict says about it. */
export default function NodeCard({ node, step, good, checkFailed }: { node: GNode | undefined; step?: RunStep; good?: RunStep; checkFailed?: boolean }) {
  if (!node) return <p className="muted">Unknown node.</p>
  const v = node.verdict
  return (
    <div className="card">
      <h4 className="card-head">
        {node.id}
        <span className="chip-kind">{node.kind ? KIND_LABEL[node.kind] : 'kind not recorded'}</span>
      </h4>
      {node.status && (
        <div className={`card-verdict st-${node.status}`}>
          <b>{v?.pruned ? 'Not tested (pruned)' : STATUS_LABEL[node.status]}</b>
          <p>{plain(node.reason) || STATUS_MEANING[node.status]}</p>
          {!!v?.trials.length && <p>Trials that restored it: {v.trials.map((n) => `#${n}`).join(', ')}.</p>}
        </div>
      )}
      <dl className="facts">
        {node.faults.length > 0 && (
          <>
            <dt>Fault flags</dt>
            <dd>{node.faults.map((f) => <code key={f}>{f}</code>)}</dd>
          </>
        )}
        {v?.restore != null && (
          <>
            <dt>Restored from</dt>
            <dd><code>{JSON.stringify(v.restore)}</code></dd>
          </>
        )}
        {!!v?.clues.length && (
          <>
            <dt>Clues</dt>
            <dd>
              <ul>{v.clues.map((c) => <li key={c}>{plain(c)}</li>)}</ul>
            </dd>
          </>
        )}
        {step?.input_from.length ? (
          <>
            <dt>Input came from</dt>
            <dd>{step.input_from.map((s) => `${s.node === '__start__' ? 'run input' : s.node} (${s.keys.join(', ')})`).join('; ')}</dd>
          </>
        ) : null}
      </dl>
      {step && !step.error && good && JSON.stringify(good.output) !== JSON.stringify(step.output) && (
        <p className="ok-differs"><b>Ran ok, output differs.</b> It finished without an error, but its output is not what the known-good run produced. A green span is not a right answer.</p>
      )}
      {step && !step.error && checkFailed && !(good && JSON.stringify(good.output) !== JSON.stringify(step.output)) && (
        <p className="ok-differs"><b>Ran ok; the check failed downstream.</b> This node finished without an error and matches the known-good run, but the final answer still failed its check.</p>
      )}
      {step ? (
        <>
          <h5>Input in the failed run</h5>
          <Kv data={step.input} fresh={step.changed} />
          <h5>Output in the failed run</h5>
          {step.error ? <p className="now-error"><Glyph name="cross" />{step.error}</p> : <Kv data={step.output} diff={good ? good.output : undefined} />}
        </>
      ) : (
        <p className="muted small">This node did not run in the recorded failed run.</p>
      )}
    </div>
  )
}
