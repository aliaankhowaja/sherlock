import { useEffect, useState } from 'react'
import { getJson, isTrial, short, useJson, when, type Diagnosis, type Summary, type Team, type TeamRun } from './api'
import type { GraphView } from './model'
import Graph from './Graph'
import { Glyph } from './Kv'

/** failed run -> the known-good run its diagnosis used (read from each verdict). */
function useGoodOf(ids: string[]) {
  const key = ids.join(',')
  const [map, setMap] = useState<Record<string, string>>({})
  useEffect(() => {
    if (!key) return
    let stop = false
    Promise.all(key.split(',').map((id) => getJson<Diagnosis>(`/api/diagnoses/${id}`).catch(() => null))).then((ds) => {
      if (stop) return
      const m: Record<string, string> = {}
      for (const d of ds) {
        const g = d?.artifact.known_good_source?.thread_id
        if (d && g) m[d.summary.thread_id] = g
      }
      setMap(m)
    })
    return () => {
      stop = true
    }
  }, [key])
  return map
}

interface PickProps {
  teams: Team[]
  diagnoses: Summary[]
  team: string
  failed: string
  good: string
  onTeam: (id: string) => void
  onFailed: (id: string, suggestedGood?: string) => void
  onGood: (id: string) => void
  onNext: () => void
}

export default function Pick(p: PickProps) {
  const runs = useJson<TeamRun[]>(p.team ? `/api/runs?assistant_id=${encodeURIComponent(p.team)}&limit=100` : null)
  const graph = useJson<GraphView>(p.team ? `/api/teams/${encodeURIComponent(p.team)}/graph` : null)
  const list = (runs.data ?? []).filter((r) => !isTrial(r))
  const diagnosed = new Map(p.diagnoses.map((d) => [d.thread_id, d]))
  const goodOf = useGoodOf(list.filter((r) => diagnosed.has(r.thread_id)).map((r) => r.thread_id))
  const goodIds = new Set(Object.values(goodOf))

  const badges = (r: TeamRun) => {
    const d = diagnosed.get(r.thread_id)
    if (d) return <><span className="tag tag-fail"><Glyph name="cross" />failed</span><span className="tag"><Glyph name="check" />diagnosed</span></>
    if (goodIds.has(r.thread_id)) return <span className="tag tag-pass"><Glyph name="check" />passed</span>
    if (r.status === 'error') return <span className="tag tag-fail"><Glyph name="cross" />crashed</span>
    return <span className="tag tag-unk">not checked yet</span>
  }
  const rank = (r: TeamRun, good: boolean) => (good ? (goodIds.has(r.thread_id) ? 0 : diagnosed.has(r.thread_id) ? 2 : 1) : diagnosed.has(r.thread_id) ? 0 : goodIds.has(r.thread_id) ? 2 : 1)
  const column = (good: boolean) => (
    <fieldset className="runs">
      <legend>{good ? 'Known-good run' : 'Failed run'}</legend>
      <p className="hint">{good ? 'Same input, right answer. Sherlock copies its behaviour back one node at a time.' : 'The run that gave a wrong answer.'}</p>
      {runs.loading && <p className="muted small">Loading runs…</p>}
      {runs.error && <p className="error-line">Could not load runs: {runs.error}</p>}
      {!runs.loading && !runs.error && list.length === 0 && <p className="muted small">This team has no runs on the server yet.</p>}
      {[...list].sort((a, b) => rank(a, good) - rank(b, good)).map((r) => {
        const value = good ? p.good : p.failed
        const other = good ? p.failed : p.good
        return (
          <label key={r.thread_id} className={`run${value === r.thread_id ? ' is-on' : ''}${other === r.thread_id ? ' is-off' : ''}`}>
            <input type="radio" name={good ? 'good' : 'failed'} checked={value === r.thread_id} disabled={other === r.thread_id} onChange={() => (good ? p.onGood(r.thread_id) : p.onFailed(r.thread_id, goodOf[r.thread_id]))} />
            <span className="run-id" title={r.thread_id}>{short(r.thread_id)}</span>
            <span className="run-when">{when(r.created_at)}</span>
            <span className="run-tags">{badges(r)}</span>
          </label>
        )
      })}
    </fieldset>
  )

  return (
    <div className="screen">
      <div className="teams" role="radiogroup" aria-label="Team">
        <span className="eyebrow">Team</span>
        {p.teams.map((t) => (
          <button key={t.assistant_id} type="button" role="radio" aria-checked={p.team === t.assistant_id} className={`team${p.team === t.assistant_id ? ' is-on' : ''}`} onClick={() => p.onTeam(t.assistant_id)}>
            {t.name ?? t.graph_id}
          </button>
        ))}
      </div>
      {p.team && (
        <>
          <div className="preview">
            {graph.data ? <Graph graph={graph.data} /> : <p className="muted small">{graph.error ? `No graph: ${graph.error}` : 'Drawing the pipeline…'}</p>}
          </div>
          <div className="pick-cols">
            {column(false)}
            {column(true)}
          </div>
          <div className="actions">
            <button type="button" className="btn-primary" disabled={!p.failed} onClick={p.onNext}>Watch the failed run</button>
            {!p.failed && <span className="muted small">Pick a failed run first.</span>}
          </div>
        </>
      )}
    </div>
  )
}
