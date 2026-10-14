import { useCallback, useEffect, useState } from 'react'

export interface Team {
  assistant_id: string
  graph_id: string
  name: string | null
}

export interface TeamRun {
  thread_id: string
  status: string | null
  assistant_id: string | null
  created_at: string | null
  metadata: unknown
}

export interface RunEvent {
  checkpoint_id: string | null
  step: number | null
  node: string
  writes: unknown
  error: string | null
  run_id: string | null
  created_at: string | null
}

export interface RunLogs {
  thread_id: string
  events: RunEvent[]
}

export interface Info {
  source: 'langgraph' | 'langsmith'
  url: string
  sherlock_dir: string
  token?: string
  run?: { enabled: boolean; project: string | null; program: string | null; running_job: number | null }
}

/** Verified status of one node. The server computes it; the UI never upgrades it. */
export type NodeStatus = 'culprit' | 'cleared' | 'unverified' | 'abstained'

export interface NodeVerdict {
  node: string
  status: NodeStatus
  reason: string
  sets: string[][]
  clues: string[]
}

export interface Summary {
  thread_id: string
  graph_id: string | null
  created: string | null
  status: 'found' | 'abstain'
  reason_code: string | null
  reason: string
  minimal_sets: string[][]
  complete: boolean
  trials_used: number | null
  fewer_pct: number | null
}

export interface AssertionResult {
  type: string
  pass: boolean
  score: number
  reason: string
}

export interface CheckReport {
  pass: boolean
  results: AssertionResult[]
}

export interface Trial {
  n: number
  restored: string[]
  verdict: string
  label: 'fixes' | 'partly_helps' | 'does_not_help' | 'cannot_say'
  score: number | null
  reason: string
  elapsed_s?: number
  cassette_miss?: boolean
  gate?: string
}

export interface Clue {
  kind: string
  node: string | null
  detail: string
  strength?: string
}

export interface Source {
  kind: string
  thread_id?: string
  confirmed?: boolean
  eligible?: boolean
  why?: string
  differing_nodes?: string[]
  same_output_nodes?: string[]
}

export interface Artifact {
  created?: string
  check?: CheckReport | null
  trials?: Trial[]
  clues?: Clue[]
  notes?: string[]
  limitations?: string[]
  unverified_sets?: string[][]
  counts?: Record<string, number>
  budget?: {
    max_trials?: number
    max_minutes?: number
    max_size?: number
    trials_used?: number
    elapsed_s?: number
  }
  pruning?: {
    nodes_on_path?: string[]
    candidates?: string[]
    pruned?: Record<string, string>
    pruned_ratio?: number
    exhaustive_trials?: number
    limitation?: string
  }
  trial_reduction?: { exhaustive_trials: number; trials_used: number; fewer_pct: number } | null
  known_good_source?: Source | null
  sources_considered?: Source[]
  other_sources?: { thread_id: string; status: string; minimal_sets: string[][]; reason_code: string | null }[]
  path_check?: { kept?: string[]; rejected?: Record<string, string> } | null
  intake?: { kind?: string; note?: string; expected?: string } | null
  gates?: GateSummary
  gate_summary?: GateSummary
}

/** Per-gate counts (additive artifact field; any of them may be missing). */
export interface GateSummary {
  nodes_total?: number
  pruned_by_ancestry?: number
  g0_flagged?: number
  g1_nominated?: number
  g2_cut?: number
  g3_trials?: number
  exhaustive_count?: number
}

export interface Diagnosis {
  summary: Summary
  nodes: NodeVerdict[]
  artifact: Artifact
}

export interface DiagnosisList {
  dir: string
  diagnoses: Summary[]
  invalid: { file: string; error: string }[]
}

export async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  const data = await res.json().catch(() => null)
  if (!res.ok) {
    throw new Error(
      typeof data?.error === 'string' ? data.error : `request failed: ${res.status}`,
    )
  }
  return data as T
}

/** Threads Sherlock forks while testing a node set are its own trials, not runs of the user's team. */
export function isTrial(run: { metadata: unknown }): boolean {
  const m = run.metadata as { sherlock_fork_of?: unknown } | null
  return !!m && typeof m === 'object' && 'sherlock_fork_of' in m
}

/** "2026-10-13T22:23:16.240887+00:00" -> "2026-10-13 22:23 UTC". */
export function when(iso: string | null | undefined): string {
  const m = iso && /^(\d{4}-\d\d-\d\d)T(\d\d:\d\d)/.exec(iso)
  return m ? `${m[1]} ${m[2]}${/(Z|[+-]00:00)$/.test(iso) ? ' UTC' : ''}` : (iso ?? '')
}

export function short(id: string | null): string {
  return id ? (id.length > 12 ? `${id.slice(0, 8)}…${id.slice(-4)}` : id) : '–'
}

interface Loaded<T> {
  url: string
  data: T | null
  error: string | null
}

/** Fetch `url` (null = do nothing). `reload` re-fetches; `loading` is derived, not stored. */
export function useJson<T>(url: string | null) {
  const [state, setState] = useState<Loaded<T> | null>(null)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    if (!url) return
    let cancelled = false
    getJson<T>(url)
      .then((data) => !cancelled && setState({ url, data, error: null }))
      .catch(
        (e) =>
          !cancelled &&
          setState({
            url,
            data: null,
            error: e instanceof Error ? e.message : String(e),
          }),
      )
    return () => {
      cancelled = true
    }
  }, [url, tick])

  const reload = useCallback(() => setTick((t) => t + 1), [])
  const fresh = state && state.url === url ? state : null
  return {
    data: fresh?.data ?? null,
    error: fresh?.error ?? null,
    loading: url !== null && fresh === null,
    reload,
  }
}
