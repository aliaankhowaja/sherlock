import type { Data, Frame } from './model'
import { value } from './model'

/** Key/value chips. `fresh` keys (just handed over) are flagged; `only` limits the keys shown. */
export function Kv({ data, fresh, only, diff }: { data: Data | null | undefined; fresh?: string[]; only?: string[]; diff?: Data | null }) {
  if (!data) return <p className="muted small">nothing</p>
  const keys = Object.keys(data).filter((k) => !only || only.includes(k))
  if (!keys.length) return <p className="muted small">no keys</p>
  return (
    <dl className="kv">
      {keys.map((k) => {
        const full = JSON.stringify(data[k], null, 1) ?? 'null'
        const differs = diff !== undefined && JSON.stringify(diff?.[k]) !== JSON.stringify(data[k])
        return (
          <div key={k} className={`kv-row${fresh?.includes(k) ? ' is-fresh' : ''}${differs ? ' is-diff' : ''}`}>
            <dt>
              {k}
              {fresh?.includes(k) && <span className="kv-tag">new</span>}
              {differs && <span className="kv-tag kv-tag-diff">≠ good run</span>}
            </dt>
            <dd title={full}>{value(data[k], 160)}</dd>
            {differs && diff && (
              <dd className="kv-good" title={JSON.stringify(diff[k])}>good run: {value(diff[k], 140)}</dd>
            )}
          </div>
        )
      })}
    </dl>
  )
}

/** The current moment of the replay: what flows into, through and out of the node in focus. */
export function Now({ frame, lastOut, lastIn }: { frame: Frame | null; lastOut: (node: string) => Frame | undefined; lastIn: (node: string) => Frame | undefined }) {
  if (!frame) {
    return <p className="now-empty">Press <b>Play</b> or <b>Step</b>. Each node will receive its input, produce its output, and hand it to the next node.</p>
  }
  if (frame.phase === 'edge' && frame.edge) {
    const e = frame.edge
    return (
      <div className="now">
        <h4 className="now-head"><span>{e.source}</span><span className="now-arrow">→</span><span>{e.target}</span></h4>
        <p className="now-sub">Output of {e.source} becomes input of {e.target}</p>
        <Kv data={lastOut(e.source)?.data} only={e.keys} />
      </div>
    )
  }
  if (frame.node && frame.phase) {
    const input = frame.phase === 'in' ? frame : lastIn(frame.node)
    return (
      <div className="now">
        <h4 className="now-head">
          <span>{frame.node}</span>
          {frame.restored && <span className="now-tag">restored to known-good</span>}
        </h4>
        <section className="now-io">
          <h5>Input</h5>
          <Kv data={input?.data} fresh={input?.fresh} />
        </section>
        {frame.phase === 'out' && (
          <section className="now-io now-out">
            <h5>Output</h5>
            {frame.error ? <p className="now-error">✕ {frame.error}</p> : <Kv data={frame.data} />}
          </section>
        )}
      </div>
    )
  }
  return <p className={`now-note tone-${frame.tone}`}>{frame.text}</p>
}

const ICONS: Record<string, string> = {
  play: 'M4 2 L13 8 L4 14 Z',
  pause: 'M4 2 H7 V14 H4 Z M9 2 H12 V14 H9 Z',
  step: 'M3 2 L10 8 L3 14 Z M11 2 H13 V14 H11 Z',
  reset: 'M3 2 H5 V14 H3 Z M13 2 L6 8 L13 14 Z',
}

export function Icon({ name }: { name: keyof typeof ICONS }) {
  return (
    <svg className="icon" viewBox="0 0 16 16" aria-hidden="true">
      <path d={ICONS[name]} />
    </svg>
  )
}
