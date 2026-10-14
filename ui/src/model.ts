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

export interface Health {
  usable: boolean
  summary: string
  items: { id: string; label: string; ok: boolean; detail: string }[]
}

export interface StepsView {
  health?: Health
  server_version?: string | null
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

export function value(v: unknown, max = 80, collapse = true): string {
  if (collapse && Array.isArray(v) && v.length > 1) return `[${v.length} items]`
  const s = typeof v === 'string' ? JSON.stringify(v) : JSON.stringify(v ?? null)
  return s.length > max ? `${s.slice(0, max - 1)}…` : s
}

/** Authored 10x10 stroke marks, so status never rides on a font's glyphs. */
export const GLYPHS = {
  check: 'M1.5 5.5 L4 8 L8.5 2',
  cross: 'M2 2 L8 8 M8 2 L2 8',
  bang: 'M5 1 V6.2 M5 8.4 V9',
  question: 'M3 3.6 C3 1.2 7.2 1.2 7.2 3.6 C7.2 5.2 5 5 5 6.6 M5 8.4 V9',
  dot: 'M5 2.6 A2.4 2.4 0 1 1 4.99 2.6 Z',
  ring: 'M5 1.8 A3.2 3.2 0 1 1 4.99 1.8 Z',
  dash: 'M2 5 H8',
  restore: 'M7.8 6.2 A3.2 3.2 0 1 1 6.6 2.2 M5.4 0.8 L6.8 2.3 L5.2 3.4',
  diamond: 'M5 1.2 L8.8 5 L5 8.8 L1.2 5 Z',
  arrow: 'M9 5 H1.5 M4.2 2.3 L1.5 5 L4.2 7.7',
} as const
export type GlyphName = keyof typeof GLYPHS
