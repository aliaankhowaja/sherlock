import { useRef } from 'react'
import { short, useJson, type Artifact, type Diagnosis, type Trial } from './api'
import {
  CommandBox,
  ErrorBanner,
  Glossary,
  Link,
  StatusChip,
  VerdictCard,
} from './parts'
import { downloadHtml, downloadJson } from './share'
import {
  STATUS_LABEL,
  STATUS_MEANING,
  STATUS_ORDER,
  TRIAL_LABEL,
  TRIAL_MEANING,
  buildCommand,
  setText,
} from './terms'

function Judgment({ artifact }: { artifact: Artifact }) {
  const check = artifact.check
  const intake = artifact.intake
  return (
    <section className="judgment">
      <h2>Why this run counts as failed</h2>
      {check ? (
        <>
          <p>
            The check <strong>{check.pass ? 'passes' : 'fails'}</strong>:{' '}
            {check.results.filter((r) => r.pass).length} of {check.results.length} assertions
            pass. A run only passes when every assertion does.
          </p>
          <ul className="assertions">
            {check.results.map((r, i) => (
              <li key={i} className={r.pass ? 'ok' : 'bad'}>
                <span aria-hidden="true">{r.pass ? '✓' : '✗'}</span>{' '}
                <span className="visually-hidden">{r.pass ? 'pass' : 'fail'}: </span>
                <code>{r.type}</code> {r.reason}
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p>
          No check was available when this was diagnosed
          {intake?.kind === 'wrong' ? ', so the run was only marked wrong' : ''}.
        </p>
      )}
      {intake?.note && <p className="note">Note on the run: {intake.note}</p>}
    </section>
  )
}

function Timeline({ d }: { d: Diagnosis }) {
  if (d.nodes.length === 0) {
    return (
      <div className="empty">
        This diagnosis did not record which nodes the run went through, so there is nothing to
        colour. The verdict above still stands.
      </div>
    )
  }
  return (
    <ol className="node-timeline">
      {d.nodes.map((n, i) => (
        <li key={n.node} className={`node node-${n.status}`}>
          <div className="node-head">
            <span className="node-step">{i + 1}</span>
            <span className="node-name">{n.node}</span>
            <StatusChip status={n.status} />
          </div>
          <div className="node-reason">{n.reason}</div>
          {n.clues.map((c, j) => (
            <div key={j} className="node-clue">
              <span className="tag tag-clue">hint</span> {c}
            </div>
          ))}
        </li>
      ))}
    </ol>
  )
}

function Legend() {
  return (
    <dl className="legend">
      {STATUS_ORDER.map((s) => (
        <div key={s}>
          <dt>
            <StatusChip status={s} />
          </dt>
          <dd>{STATUS_MEANING[s]}</dd>
        </div>
      ))}
    </dl>
  )
}

function Evidence({ d }: { d: Diagnosis }) {
  const a = d.artifact
  const src = a.known_good_source
  const pr = a.pruning
  const red = a.trial_reduction
  const clues = (a.clues ?? []).filter((c) => c.detail)
  return (
    <section className="evidence">
      <h2>Evidence</h2>

      <h3>Known-good run used</h3>
      {src ? (
        src.kind === 'run' ? (
          <p>
            Run <code>{short(src.thread_id ?? null)}</code>
            {src.confirmed === false && ' (found automatically, not confirmed by you)'}:{' '}
            {src.why ?? 'a prior run that passes the check'}.
            {src.differing_nodes && src.differing_nodes.length > 0 && (
              <> It wrote something different in: {src.differing_nodes.join(', ')}.</>
            )}
          </p>
        ) : (
          <p>A known-good behaviour file you supplied.</p>
        )
      ) : (
        <p>
          None. Without a run that worked, Sherlock has nothing to restore from, so it cannot
          test any node.
        </p>
      )}
      {(a.other_sources ?? []).length > 0 && (
        <p>
          Other known-good runs were also searched:{' '}
          {(a.other_sources ?? [])
            .map(
              (o) =>
                `${short(o.thread_id)} ${
                  o.status === 'found' ? `agreed ${setText(o.minimal_sets)}` : 'could not say'
                }`,
            )
            .join('; ')}
          .
        </p>
      )}

      <h3>How much was tested</h3>
      {pr && pr.nodes_on_path ? (
        <p>
          The run went through {pr.nodes_on_path.length} nodes.{' '}
          {pr.candidates && pr.candidates.length > 0
            ? `${pr.candidates.length} could be tested (${pr.candidates.join(', ')}); `
            : 'None could be tested; '}
          {Object.keys(pr.pruned ?? {}).length} were skipped as unable to matter
          {pr.pruned_ratio != null && ` (${Math.round(pr.pruned_ratio * 100)}% pruned)`}.
          {red && red.exhaustive_trials > 0 && (
            <>
              {' '}
              Trying every combination would take {red.exhaustive_trials} trials; Sherlock used{' '}
              {red.trials_used}
              {red.fewer_pct > 0 && ` (${red.fewer_pct}% fewer)`}.
            </>
          )}
        </p>
      ) : (
        <p>No test plan was recorded.</p>
      )}
      {a.budget && a.budget.max_trials != null && (
        <p className="muted">
          Budget: at most {a.budget.max_trials} trials, {a.budget.max_minutes} minutes, sets of{' '}
          {a.budget.max_size} nodes. Used {a.budget.trials_used ?? 0} trials in{' '}
          {a.budget.elapsed_s ?? 0}s.
        </p>
      )}

      <h3>Hints (weaker than a trial)</h3>
      {clues.length === 0 ? (
        <p className="muted">No hints were found.</p>
      ) : (
        <ul className="clues">
          {clues.map((c, i) => (
            <li key={i}>
              <span className="tag tag-clue">hint</span> {c.detail}
            </li>
          ))}
        </ul>
      )}
      <p className="muted">
        Hints only decide which nodes to test first. They never decide a culprit.
      </p>

      {a.path_check && (
        <>
          <h3>Suspects you named</h3>
          <p>
            Kept: {(a.path_check.kept ?? []).join(', ') || 'none'}.
            {Object.entries(a.path_check.rejected ?? {}).map(([k, v]) => (
              <span key={k}>
                {' '}
                Dropped {k}: {v}.
              </span>
            ))}
          </p>
        </>
      )}

      {((a.notes ?? []).length > 0 || (a.limitations ?? []).length > 0) && (
        <>
          <h3>Limits to keep in mind</h3>
          <ul>
            {[...(a.notes ?? []), ...(a.limitations ?? [])].map((t, i) => (
              <li key={i}>{t}</li>
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

function TrialLog({ trials }: { trials: Trial[] }) {
  if (trials.length === 0) {
    return (
      <div className="empty">
        No trials ran. Sherlock stopped before testing anything, for the reason given in the
        verdict.
      </div>
    )
  }
  return (
    <div className="table-wrap">
      <table className="trials">
        <thead>
          <tr>
            <th>#</th>
            <th>Nodes restored</th>
            <th>Result</th>
            <th>Score</th>
            <th>Detail</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>
          {trials.map((t) => (
            <tr key={t.n} className={`trial-${t.label}`}>
              <td>{t.n}</td>
              <td>
                <code>{`{${t.restored.join(', ')}}`}</code>
              </td>
              <td title={TRIAL_MEANING[t.label]}>
                <span className={`tag tag-${t.label}`}>{TRIAL_LABEL[t.label]}</span>
              </td>
              <td>{t.score != null ? t.score.toFixed(2) : '–'}</td>
              <td>{t.reason}</td>
              <td>{t.elapsed_s != null ? `${t.elapsed_s}s` : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function RunPage({ threadId }: { threadId: string }) {
  const { data, error, loading } = useJson<Diagnosis>(
    `/api/diagnoses/${encodeURIComponent(threadId)}`,
  )
  const info = useJson<{ source: 'langgraph' | 'langsmith'; url: string; sherlock_dir: string }>(
    '/api/info',
  )
  const report = useRef<HTMLElement>(null)

  if (loading) return <div className="empty">Loading diagnosis…</div>
  if (error || !data) {
    const missing = (error ?? '').startsWith('no diagnosis')
    return (
      <div className="run-page">
        <Link to="/" className="back">
          ← Back to the guide
        </Link>
        {missing ? (
          <div className="empty-state">
            <h2>No diagnosis for run {short(threadId)} yet</h2>
            <p>
              Sherlock has not diagnosed this run. Run this in a terminal, then reload this page.
              The guide on the home page fills in the ids for you.
            </p>
            <CommandBox command={buildCommand(info.data, threadId, '')} />
          </div>
        ) : (
          <ErrorBanner
            message={error ?? 'Could not load the diagnosis.'}
            hint="The file under .sherlock/diagnoses may be damaged or from a newer Sherlock. Re-run the diagnosis to rewrite it."
          />
        )}
      </div>
    )
  }

  const { summary, artifact } = data
  return (
    <div className="run-page">
      <Link to="/" className="back">
        ← Back to the guide
      </Link>
      <article ref={report} id="report" className="report">
        <header className="report-head">
          <div>
            <h2>Run {short(summary.thread_id)}</h2>
            <div className="meta">
              <code>{summary.thread_id}</code>
              {summary.graph_id && <span> · team {summary.graph_id}</span>}
              {summary.created && <span> · diagnosed {summary.created}</span>}
            </div>
          </div>
          <div className="share" data-noshare>
            <button
              type="button"
              className="small-button"
              onClick={() => report.current && downloadHtml(report.current, data)}
            >
              Download read-only HTML
            </button>
            <button type="button" className="small-button" onClick={() => downloadJson(data)}>
              Download JSON
            </button>
          </div>
        </header>

        <VerdictCard summary={summary} />
        <Judgment artifact={artifact} />

        <section>
          <h2>Where each node stands</h2>
          <p className="muted">
            Colours show only what was verified by re-running the recording. A node is marked
            &quot;{STATUS_LABEL.culprit}&quot; only if restoring it fixed the run.
          </p>
          <Timeline d={data} />
          <Legend />
        </section>

        <Evidence d={data} />

        <section>
          <h2>Trial log</h2>
          <p className="muted">
            Every attempt, in order: {summary.trials_used ?? artifact.trials?.length ?? 0} trial(s).
            Hover a result for what it means.
          </p>
          <TrialLog trials={artifact.trials ?? []} />
        </section>

        <Glossary />
      </article>
    </div>
  )
}
