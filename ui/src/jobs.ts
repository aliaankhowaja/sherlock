import { useEffect, useState } from 'react'
import { getJson, type Info } from './api'
import type { Job } from './model'

const msg = (e: unknown) => (e instanceof Error ? e.message : String(e))

/** Poll a diagnosis job about once a second until it stops running. */
export function useJob(id: number | null) {
  const [state, setState] = useState<{ id: number; job: Job | null; error: string | null } | null>(null)
  useEffect(() => {
    if (id === null) return
    let stop = false
    let t = 0
    const tick = () =>
      getJson<Job>(`/api/jobs/${id}`)
        .then((job) => {
          if (stop) return
          setState({ id, job, error: null })
          if (job.state === 'running') t = window.setTimeout(tick, 1000)
        })
        .catch((e) => {
          if (stop) return
          setState((s) => ({ id, job: s?.id === id ? s.job : null, error: `The server stopped answering: ${msg(e)}` }))
          t = window.setTimeout(tick, 2000)
        })
    void tick()
    return () => {
      stop = true
      window.clearTimeout(t)
    }
  }, [id])
  const fresh = state && state.id === id ? state : null
  return { job: fresh?.job ?? null, error: fresh?.error ?? null }
}

/** Start a diagnosis (the run button). Resolves to the job id or throws the server's plain-words error. */
export async function startDiagnosis(info: Info, team: string, failed: string, good: string): Promise<number> {
  const res = await fetch('/api/diagnose', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Sherlock-Token': info.token ?? '' },
    body: JSON.stringify({ assistant_id: team, failed_thread_id: failed, good_thread_id: good }),
  })
  const data = await res.json().catch(() => null)
  if (!res.ok) throw new Error(typeof data?.error === 'string' ? data.error : `request failed: ${res.status}`)
  return Number(data.job_id)
}
