import { useState } from 'react'
import {
  short,
  useJson,
  type DiagnosisList,
  type Info,
  type Summary,
  type Team,
  type TeamRun,
} from './api'
import {
  CommandBox,
  ErrorBanner,
  Glossary,
  Link,
  VerdictCard,
} from './parts'
import { runPath } from './route'
import { buildCommand, setText } from './terms'

function RunPicker({
  name,
  runs,
  value,
  onChange,
  disabledId,
  diagnosed,
}: {
  name: string
  runs: TeamRun[]
  value: string
  onChange: (id: string) => void
  disabledId?: string
  diagnosed: Map<string, Summary>
}) {
  return (
    <div className="picker">
      {runs.length > 0 && (
        <ul className="picker-list">
          {runs.map((run) => {
            const d = diagnosed.get(run.thread_id)
            return (
              <li key={run.thread_id}>
                <label className={value === run.thread_id ? 'picked' : undefined}>
                  <input
                    type="radio"
                    name={name}
                    checked={value === run.thread_id}
                    disabled={run.thread_id === disabledId}
                    onChange={() => onChange(run.thread_id)}
                  />
                  <code>{short(run.thread_id)}</code>
                  <span className="row-sub">{run.created_at ?? ''}</span>
                  {d && (
                    <span className="tag">
                      {d.status === 'found'
                        ? `diagnosed ${setText(d.minimal_sets)}`
                        : 'diagnosed: cannot say'}
                    </span>
                  )}
                </label>
              </li>
            )
          })}
        </ul>
      )}
      <label className="paste">
        <span>{runs.length > 0 ? 'or paste a run (thread) id' : 'Paste a run (thread) id'}</span>
        <input
          type="text"
          value={value}
          placeholder="e.g. 01a1371a-f0a7-79f2-bb6e-4b065c36df4b"
          spellCheck={false}
          onChange={(e) => onChange(e.target.value.trim())}
        />
      </label>
    </div>
  )
}

function Step({
  n,
  title,
  help,
  children,
}: {
  n: number
  title: string
  help: string
  children: React.ReactNode
}) {
  return (
    <li className="step">
      <div className="step-num" aria-hidden="true">
        {n}
      </div>
      <div className="step-body">
        <h3>
          <span className="visually-hidden">Step {n}: </span>
          {title}
        </h3>
        <p className="step-help">{help}</p>
        {children}
      </div>
    </li>
  )
}

function DiagnosisRows({ list }: { list: DiagnosisList }) {
  return (
    <ul className="diag-list">
      {list.diagnoses.map((d) => (
        <li key={d.thread_id}>
          <Link to={runPath(d.thread_id)}>
            <code>{short(d.thread_id)}</code>
            <span className="row-sub">{d.graph_id ?? ''}</span>
            <span className={`tag tag-${d.status}`}>
              {d.status === 'found'
                ? `must change ${setText(d.minimal_sets)}`
                : `cannot say${d.reason_code ? ` (${d.reason_code})` : ''}`}
            </span>
          </Link>
        </li>
      ))}
    </ul>
  )
}

export default function Guide() {
  const info = useJson<Info>('/api/info')
  const teams = useJson<Team[]>('/api/teams')
  const diagnoses = useJson<DiagnosisList>('/api/diagnoses')
  const [teamChoice, setTeamChoice] = useState<string | null>(null)
  const [failed, setFailed] = useState('')
  const [good, setGood] = useState('')

  const teamId = teamChoice ?? teams.data?.[0]?.assistant_id ?? null
  const runs = useJson<TeamRun[]>(
    teamId ? `/api/runs?assistant_id=${encodeURIComponent(teamId)}&limit=100` : null,
  )

  const list = diagnoses.data
  const diagnosed = new Map((list?.diagnoses ?? []).map((d) => [d.thread_id, d]))
  const mine = failed ? diagnosed.get(failed) : undefined
  const runList = runs.data ?? []
  const command = buildCommand(info.data, failed, good)

  return (
    <div className="guide">
      <section className="intro">
        <h2>Find which agent broke a run</h2>
        <p>
          A team of agents gave a wrong answer and you want to know which agent to fix. Sherlock
          takes a failed run and a run that worked, swaps the good behaviour back in one agent
          at a time, replays the rest from the recording, and tells you the smallest group of
          agents that fixes it. If it cannot prove that, it says so instead of guessing. It never
          calls a live model.
        </p>
      </section>

      <ol className="steps">
        <Step
          n={1}
          title="Pick a team and a failed run"
          help="A team is one set of agents you built (a LangGraph graph). A failed run is one execution of it that gave a wrong answer."
        >
          {teams.error && (
            <ErrorBanner
              message={`Cannot list teams: ${teams.error}`}
              hint={`Sherlock reads runs from ${info.data?.url ?? 'the LangGraph server'}. Start your team with "sherlock-rec run langgraph dev", or paste a run id below.`}
            />
          )}
          {teams.data && teams.data.length === 0 && (
            <div className="empty">
              The server has no teams yet. Run your graph once so it records a run.
            </div>
          )}
          {teams.data && teams.data.length > 0 && (
            <label className="team-select">
              Team{' '}
              <select
                value={teamId ?? ''}
                onChange={(e) => {
                  setTeamChoice(e.target.value)
                  setFailed('')
                  setGood('')
                }}
              >
                {teams.data.map((t) => (
                  <option key={t.assistant_id} value={t.assistant_id}>
                    {t.name ?? t.graph_id}
                  </option>
                ))}
              </select>
            </label>
          )}
          {runs.error && <ErrorBanner message={`Cannot list runs: ${runs.error}`} />}
          {teamId && !runs.error && !runs.loading && runList.length === 0 && (
            <div className="empty">This team has no recorded runs yet.</div>
          )}
          <RunPicker
            name="failed"
            runs={runList}
            value={failed}
            onChange={setFailed}
            disabledId={good}
            diagnosed={diagnosed}
          />
        </Step>

        <Step
          n={2}
          title="Choose a known-good run"
          help="A run of the same team on the same input that gave a correct answer. It shows Sherlock what right behaviour looks like. A run that also failed will not work."
        >
          <RunPicker
            name="good"
            runs={runList}
            value={good}
            onChange={setGood}
            disabledId={failed}
            diagnosed={diagnosed}
          />
        </Step>

        <Step
          n={3}
          title="Run the diagnosis"
          help="Diagnosis replays recordings, so it runs in your terminal against a replay server. Sherlock does not start it from the browser, because then any web page could start commands on your machine."
        >
          <CommandBox command={command} />
          <details className="before">
            <summary>Before you run it</summary>
            <ol>
              <li>
                The failed run was recorded by starting your server as{' '}
                <code>sherlock-rec run langgraph dev</code>.
              </li>
              <li>
                Restart it as <code>sherlock-rec run --replay langgraph dev</code>. In replay mode
                nothing can reach a live model or tool, so a missing recording becomes a
                &quot;cannot say&quot; and never a guess.
              </li>
              <li>
                Put a check in <code>sherlock.yaml</code> in the folder you run the command from.
                It states what a right answer looks like. Or mark the expected answer with{' '}
                <code>sherlock-rec intake --thread-id &lt;id&gt; --expected &quot;…&quot;</code>.
              </li>
            </ol>
          </details>
        </Step>

        <Step
          n={4}
          title="Read the verdict"
          help='The result is either "found" (the smallest group of nodes that fixes the run) or "cannot say" (with the reason). Refresh after the command finishes.'
        >
          <div className="step-actions" data-noshare>
            <button type="button" className="small-button" onClick={diagnoses.reload}>
              {diagnoses.loading ? 'Loading…' : 'Refresh diagnoses'}
            </button>
          </div>
          {diagnoses.error && <ErrorBanner message={diagnoses.error} />}
          {mine && (
            <>
              <VerdictCard summary={mine} />
              <Link to={runPath(mine.thread_id)} className="primary-link">
                Open the full run page
              </Link>
            </>
          )}
          {failed && !mine && !diagnoses.loading && (
            <div className="empty">
              No diagnosis for run <code>{short(failed)}</code> yet. Run the command in step 3,
              then refresh.
            </div>
          )}
        </Step>
      </ol>

      <section className="all-diagnoses">
        <h2>All diagnoses</h2>
        {list && list.invalid.length > 0 && (
          <ErrorBanner
            message={`${list.invalid.length} file(s) in ${list.dir} are not valid diagnoses and were skipped.`}
            hint={list.invalid.map((i) => `${i.file}: ${i.error}`).join(' · ')}
          />
        )}
        {list && list.diagnoses.length === 0 && (
          <div className="empty">
            Nothing in <code>{list.dir}</code> yet. Finish the steps above to create one. To look at
            a finished example first, restart this server with{' '}
            <code>sherlock serve --sherlock-dir harness/fixtures/sherlock-demo</code> (from the
            Sherlock repository).
          </div>
        )}
        {list && list.diagnoses.length > 0 && <DiagnosisRows list={list} />}
      </section>

      <Glossary />
    </div>
  )
}
