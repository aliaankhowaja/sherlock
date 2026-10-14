import type { NodeStatus, NodeVerdict } from './api'

export type Kind = 'deterministic' | 'llm' | 'tool' | null
export type Data = Record<string, unknown>

export interface HandOff {
  source: string
  target: string
  keys: string[]
}

export interface RunStep {
  index: number
  step: number
  node: string
  kind: Kind
  input: Data
  changed: string[]
  input_from: { node: string; keys: string[] }[]
  output: Data | null
  error: string | null
  duration_ms: number | null
  log: string[]
}

export interface StepsView {
  thread_id: string
  graph_id: string | null
  note: string | null
  final_state: Data
  steps: RunStep[]
  edges: HandOff[]
}

export interface GVerdict extends NodeVerdict {
  trials: number[]
  restore: unknown
  pruned: string | null
  tested: boolean
  on_path: boolean
}

export interface GNode {
  id: string
  role: 'start' | 'end' | 'node'
  kind: Kind
  status: NodeStatus | null
  reason: string
  layer: number
  row: number
  verdict: GVerdict | null
  faults: string[]
}

export interface GEdge {
  source: string
  target: string
  conditional: boolean
  back: boolean
}

export interface GraphView {
  nodes: GNode[]
  edges: GEdge[]
  note: string | null
  known_good_source: string | null
}

export type JobEvent = { event: string; at_ms: number } & Record<string, unknown>

export interface Job {
  id: number
  graph_id: string | null
  failed: string
  good: string
  command: string
  state: 'running' | 'done' | 'failed'
  events: JobEvent[]
  log: string[]
  exit_code: number | null
  error: string | null
  artifact_id: string | null
}

/** What a node looks like at one moment of the replay. */
export type Mark = 'ran' | 'error' | 'restored' | 'pruned' | 'candidate' | 'pass' | 'fail'
export type Tone = 'head' | 'info' | 'ok' | 'bad' | 'warn' | 'muted'

/** One moment of the replay: a log line, and what the stage shows while it is the latest. */
export interface Frame {
  text: string
  tone: Tone
  at?: number
  node?: string
  phase?: 'in' | 'out' | 'edge'
  data?: Data | null
  fresh?: string[]
  error?: string | null
  edge?: HandOff
  restored?: boolean
  mark?: Record<string, Mark>
  reset?: boolean
}

/** `k=v` summary in the same style as the server log lines. */
export function brief(d: Data | null | undefined, max = 3): string {
  if (!d) return 'nothing'
  const keys = Object.keys(d)
  const parts = keys.slice(0, max).map((k) => `${k}=${value(d[k], 36)}`)
  if (keys.length > max) parts.push(`+${keys.length - max} more`)
  return parts.join(', ') || 'nothing'
}

export function value(v: unknown, max = 80): string {
  if (Array.isArray(v) && v.length > 1) return `[${v.length} items]`
  const s = typeof v === 'string' ? JSON.stringify(v) : JSON.stringify(v ?? null)
  return s.length > max ? `${s.slice(0, max - 1)}…` : s
}
