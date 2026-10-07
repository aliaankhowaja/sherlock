import { useCallback, useEffect, useState } from 'react'
import './App.css'

interface Team {
  assistant_id: string
  graph_id: string
  name: string | null
}

interface TeamRun {
  thread_id: string
  status: string | null
  assistant_id: string | null
  created_at: string | null
  metadata: unknown
}

interface RunEvent {
  checkpoint_id: string | null
  step: number | null
  node: string
  writes: unknown
  error: string | null
  run_id: string | null
  created_at: string | null
}

interface RunLogs {
  thread_id: string
  events: RunEvent[]
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  const data = await res.json()
  if (!res.ok) {
    throw new Error(
      typeof data?.error === 'string' ? data.error : `request failed: ${res.status}`,
    )
  }
  return data as T
}

function short(id: string | null): string {
  return id ? id.slice(0, 8) : '–'
}

function Pane({
  title,
  onRefresh,
  loading,
  children,
}: {
  title: string
  onRefresh: () => void
  loading: boolean
  children: React.ReactNode
}) {
  return (
    <section className="pane">
      <header className="pane-header">
        <h2>{title}</h2>
        <button onClick={onRefresh} disabled={loading}>
          {loading ? 'Loading…' : 'Refresh'}
        </button>
      </header>
      {children}
    </section>
  )
}

function ErrorBanner({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="banner banner-error" role="alert">
      <div>{message}</div>
      {hint && <div className="banner-hint">{hint}</div>}
    </div>
  )
}

const LANGGRAPH_HINT =
  'Is the LangGraph server running? Check the --langgraph-url passed to `sherlock serve`.'

function App() {
  const [teams, setTeams] = useState<Team[]>([])
  const [teamsLoading, setTeamsLoading] = useState(false)
  const [teamsError, setTeamsError] = useState<string | null>(null)
  const [selectedTeam, setSelectedTeam] = useState<Team | null>(null)

  const [runs, setRuns] = useState<TeamRun[]>([])
  const [runsLoading, setRunsLoading] = useState(false)
  const [runsError, setRunsError] = useState<string | null>(null)
  const [selectedThread, setSelectedThread] = useState<string | null>(null)

  const [logs, setLogs] = useState<RunLogs | null>(null)
  const [logsLoading, setLogsLoading] = useState(false)
  const [logsError, setLogsError] = useState<string | null>(null)
  const [runFilter, setRunFilter] = useState<string>('all')
  const [limit, setLimit] = useState<number>(50)

  const fetchRuns = useCallback(async (team: Team) => {
    setRunsLoading(true)
    setRunsError(null)
    try {
      const data = await getJson<TeamRun[]>(
        `/api/runs?assistant_id=${encodeURIComponent(team.assistant_id)}&limit=100`,
      )
      setRuns(data)
    } catch (e) {
      setRunsError(e instanceof Error ? e.message : String(e))
      setRuns([])
    } finally {
      setRunsLoading(false)
    }
  }, [])

  const fetchLogs = useCallback(
    async (threadId: string, logLimit: number) => {
      setLogsLoading(true)
      setLogsError(null)
      try {
        const data = await getJson<RunLogs>(
          `/api/logs?thread_id=${encodeURIComponent(threadId)}&limit=${logLimit}`,
        )
        setLogs(data)
        setRunFilter('all')
      } catch (e) {
        setLogsError(e instanceof Error ? e.message : String(e))
        setLogs(null)
      } finally {
        setLogsLoading(false)
      }
    },
    [],
  )

  const selectTeam = useCallback(
    (team: Team) => {
      setSelectedTeam(team)
      setSelectedThread(null)
      setLogs(null)
      setLogsError(null)
      setRunFilter('all')
      void fetchRuns(team)
    },
    [fetchRuns],
  )

  const selectThread = useCallback(
    (threadId: string, logLimit: number) => {
      setSelectedThread(threadId)
      void fetchLogs(threadId, logLimit)
    },
    [fetchLogs],
  )

  const loadTeams = useCallback(async () => {
    setTeamsLoading(true)
    setTeamsError(null)
    try {
      const data = await getJson<Team[]>('/api/teams')
      setTeams(data)
      const first = data[0] ?? null
      if (first) {
        selectTeam(first)
      } else {
        setSelectedTeam(null)
        setRuns([])
      }
    } catch (e) {
      setTeamsError(e instanceof Error ? e.message : String(e))
      setTeams([])
    } finally {
      setTeamsLoading(false)
    }
  }, [selectTeam])

  // Initial dashboard load on mount. This is the only effect that sets
  // state; all subsequent loads are driven by click/change handlers.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- mount-only initial fetch
    void loadTeams()
  }, [loadTeams])

  const runIds = [
    ...new Set(
      (logs?.events ?? []).flatMap((e) => (e.run_id ? [e.run_id] : [])),
    ),
  ]
  const visibleEvents = (logs?.events ?? []).filter(
    (e) => runFilter === 'all' || e.run_id === runFilter,
  )
  const errorCount = visibleEvents.filter((e) => e.error).length

  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>sherlock</h1>
        <p>LangGraph team debugger: teams → runs → per-node logs.</p>
      </header>

      <div className="panes">
        <Pane
          title="Teams"
          onRefresh={loadTeams}
          loading={teamsLoading}
        >
          {teamsError && (
            <ErrorBanner message={teamsError} hint={LANGGRAPH_HINT} />
          )}
          {!teamsError && teams.length === 0 && !teamsLoading && (
            <div className="empty">No teams found.</div>
          )}
          <ul className="list">
            {teams.map((team) => (
              <li key={team.assistant_id}>
                <button
                  className={
                    selectedTeam?.assistant_id === team.assistant_id
                      ? 'selected'
                      : undefined
                  }
                  onClick={() => selectTeam(team)}
                >
                  <span className="row-title">
                    {team.name ?? team.graph_id}
                  </span>
                  <span className="row-sub">{team.graph_id}</span>
                </button>
              </li>
            ))}
          </ul>
        </Pane>

        <Pane
          title={selectedTeam ? `Runs · ${selectedTeam.graph_id}` : 'Runs'}
          onRefresh={() => {
            if (selectedTeam) {
              void fetchRuns(selectedTeam)
            }
          }}
          loading={runsLoading}
        >
          {runsError && (
            <ErrorBanner message={runsError} hint={LANGGRAPH_HINT} />
          )}
          {!runsError && !runsLoading && selectedTeam && runs.length === 0 && (
            <div className="empty">No runs for this team yet.</div>
          )}
          {!selectedTeam && (
            <div className="empty">Select a team first.</div>
          )}
          <ul className="list">
            {runs.map((run) => (
              <li key={run.thread_id}>
                <button
                  className={
                    selectedThread === run.thread_id ? 'selected' : undefined
                  }
                  onClick={() => selectThread(run.thread_id, limit)}
                >
                  <span className="row-title">
                    <code>{short(run.thread_id)}</code>
                    {run.status && (
                      <span className={`status status-${run.status}`}>
                        {run.status}
                      </span>
                    )}
                  </span>
                  <span className="row-sub">{run.created_at ?? ''}</span>
                </button>
              </li>
            ))}
          </ul>
        </Pane>

        <Pane
          title={
            selectedThread
              ? `Logs · ${short(selectedThread)}`
              : 'Logs'
          }
          onRefresh={() => {
            if (selectedThread) {
              void fetchLogs(selectedThread, limit)
            }
          }}
          loading={logsLoading}
        >
          {logsError && (
            <ErrorBanner message={logsError} hint={LANGGRAPH_HINT} />
          )}
          {!logsError && !logsLoading && selectedThread && logs && (
            <>
              <div className="logs-toolbar">
                <label>
                  Run{' '}
                  <select
                    value={runFilter}
                    onChange={(e) => setRunFilter(e.target.value)}
                  >
                    <option value="all">all ({logs.events.length})</option>
                    {runIds.map((id) => (
                      <option key={id} value={id}>
                        {short(id)}
                      </option>
                    ))}
                  </select>
                </label>
                <label>
                  Limit{' '}
                  <select
                    value={limit}
                    onChange={(e) => {
                      const next = Number(e.target.value)
                      setLimit(next)
                      if (selectedThread) {
                        void fetchLogs(selectedThread, next)
                      }
                    }}
                  >
                    {[10, 50, 100, 200].map((n) => (
                      <option key={n} value={n}>
                        {n}
                      </option>
                    ))}
                  </select>
                </label>
                {errorCount > 0 && (
                  <span className="error-count">
                    {errorCount} error{errorCount === 1 ? '' : 's'}
                  </span>
                )}
              </div>
              {visibleEvents.length === 0 && (
                <div className="empty">
                  No checkpoints{runFilter === 'all' ? '' : ' for this run'} yet.
                </div>
              )}
              <ol className="timeline">
                {visibleEvents.map((event, i) => (
                  <li
                    key={`${event.checkpoint_id ?? i}-${event.node}`}
                    className={event.error ? 'event event-error' : 'event'}
                  >
                    <div className="event-head">
                      <span className="event-step">
                        step {event.step ?? '–'}
                      </span>
                      <span className="event-node">{event.node}</span>
                      <code title={event.run_id ?? ''}>
                        {short(event.run_id)}
                      </code>
                    </div>
                    {event.error && (
                      <div className="event-error-msg">{event.error}</div>
                    )}
                    {event.writes != null && (
                      <details>
                        <summary>writes</summary>
                        <pre>{JSON.stringify(event.writes, null, 2)}</pre>
                      </details>
                    )}
                  </li>
                ))}
              </ol>
            </>
          )}
          {!logsError && !logsLoading && !selectedThread && (
            <div className="empty">Select a run to inspect its logs.</div>
          )}
        </Pane>
      </div>
    </div>
  )
}

export default App
