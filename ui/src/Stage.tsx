import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { Frame, GraphView, HandOff, Mark } from './model'
import Graph from './Graph'
import { Icon, Now } from './Kv'

const PACE: Record<string, number> = { in: 1100, out: 1100, edge: 800 }
const SPEEDS = [0.5, 1, 2, 4]

function fold(frames: Frame[], pos: number) {
  let marks: Record<string, Mark> = {}
  const base: Record<string, Mark> = {}
  for (let i = 0; i <= pos && i < frames.length; i++) {
    const f = frames[i]
    if (f.reset) marks = { ...base }
    for (const [n, m] of Object.entries(f.mark ?? {})) {
      marks[n] = m
      if (m === 'pruned' || m === 'candidate') base[n] = m
    }
  }
  const last = (node: string, phase: Frame['phase']) => {
    for (let i = Math.min(pos, frames.length - 1); i >= 0; i--) {
      if (frames[i].node === node && frames[i].phase === phase) return frames[i]
    }
    return undefined
  }
  return { marks, last }
}

export interface StageProps {
  graph: GraphView
  frames: Frame[]
  live?: boolean
  autoplay?: boolean
  labels?: HandOff[]
  diff?: Set<string>
  relevant?: Set<string>
  detail?: (node: string) => ReactNode
  toolbar?: ReactNode
}

/** The pipeline in action: graph on top, the log and the current hand-off below, one set of player controls. */
export default function PipelineStage(p: StageProps) {
  const [pos, setPos] = useState(-1)
  const [playing, setPlaying] = useState(!!p.autoplay)
  const [speed, setSpeed] = useState(1)
  const [selected, setSelected] = useState<string | null>(null)
  const logRef = useRef<HTMLOListElement>(null)
  const end = p.frames.length - 1
  const running = playing && (pos < end || !!p.live)

  useEffect(() => {
    if (!playing || pos >= end) return
    const next = p.frames[pos + 1]
    const t = setTimeout(() => setPos((x) => x + 1), (PACE[next?.phase ?? ''] ?? 650) / speed)
    return () => clearTimeout(t)
  }, [playing, pos, end, speed, p.frames])

  // the log follows the replay; with a node picked it follows that node's latest line instead
  useEffect(() => {
    const el = logRef.current
    if (!el) return
    const mine = selected ? [...el.querySelectorAll<HTMLElement>('li.is-node')].at(-1) : undefined
    if (mine) el.scrollTop = mine.offsetTop - el.offsetTop - el.clientHeight / 2
    else el.scrollTop = el.scrollHeight
  }, [pos, selected])

  const { marks, last } = fold(p.frames, pos)
  const frame = pos >= 0 ? p.frames[pos] : null
  const play = () => {
    if (!running && pos >= end && !p.live) setPos(-1)
    setPlaying(!running)
  }

  return (
    <div className="stage">
      <div className="stage-bar" data-noshare>
        <div className="player" role="group" aria-label="Replay controls">
          <button type="button" className="btn-icon" onClick={() => { setPlaying(false); setPos(-1) }} title="Back to the start"><Icon name="reset" /><span>Reset</span></button>
          <button type="button" className="btn-play" onClick={play} aria-pressed={running}>
            <Icon name={running ? 'pause' : 'play'} />
            <span>{running ? 'Pause' : pos >= end && end >= 0 && !p.live ? 'Replay' : 'Play'}</span>
          </button>
          <button type="button" className="btn-icon" disabled={pos >= end} onClick={() => { setPlaying(false); setPos((x) => Math.min(x + 1, end)) }} title="One step forward"><Icon name="step" /><span>Step</span></button>
          <label className="speed">
            <span>Speed</span>
            <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
              {SPEEDS.map((s) => <option key={s} value={s}>{s}×</option>)}
            </select>
          </label>
        </div>
        <div className="rail" aria-hidden="true"><div style={{ width: `${end >= 0 ? ((pos + 1) / (end + 1)) * 100 : 0}%` }} /></div>
        <span className="counter">{Math.max(pos + 1, 0)} / {p.frames.length}{p.live ? ' · live' : ''}</span>
        {p.toolbar}
      </div>
      <div className="stage-graph">
        <Graph graph={p.graph} marks={marks} frame={frame} pulse={pos} labels={p.labels} diff={p.diff} relevant={p.relevant} selected={selected} onSelect={(id) => setSelected(id === selected ? null : id)} />
      </div>
      <div className="stage-lower">
        <section className="log" aria-label="Log">
          <h3 className="eyebrow">Log</h3>
          <ol ref={logRef} aria-live="polite">
            {p.frames.slice(0, pos + 1).map((f, i) => (
              <li key={i} className={`tone-${f.tone}${i === pos ? ' is-now' : ''}${selected && (f.node === selected || f.edge?.source === selected) ? ' is-node' : ''}`} onClick={() => { setPlaying(false); setPos(i) }}>
                <span className="log-t">{f.at !== undefined ? `${(f.at / 1000).toFixed(2)}s` : String(i + 1).padStart(2, '0')}</span>
                <span className="log-x">{f.text}</span>
              </li>
            ))}
            {pos < 0 && <li className="tone-muted"><span className="log-t">--</span><span className="log-x">waiting for Play</span></li>}
          </ol>
        </section>
        <section className="inspect" aria-label={selected ? `Node ${selected}` : 'Current step'}>
          {selected && p.detail ? (
            <>
              <button type="button" className="inspect-close" onClick={() => setSelected(null)} data-noshare>Back to live view</button>
              {p.detail(selected)}
            </>
          ) : (
            <>
              <h3 className="eyebrow">{frame?.node ? 'Now' : 'Status'}</h3>
              <Now frame={frame} lastOut={(n) => last(n, 'out')} lastIn={(n) => last(n, 'in')} />
            </>
          )}
        </section>
      </div>
    </div>
  )
}
