import type { Health } from './model'
import { Glyph } from './Kv'

/** The recording checklist: what is there and what is missing, instead of a hollow graph (FR-U7, FR-R9). */
export default function HealthList({ health, thread }: { health: Health; thread: string }) {
  return (
    <section className={`health${health.usable ? '' : ' is-bad'}`} aria-label="Recording health">
      <h3 className="eyebrow">{health.usable ? 'Recording health' : health.summary}</h3>
      {!health.usable && <p className="lede">Run <code>{thread.slice(0, 8)}</code> has nothing Sherlock can replay, so no graph is drawn. Here is what is missing.</p>}
      <ul>
        {health.items.map((i) => (
          <li key={i.id} className={i.ok ? 'is-ok' : 'is-missing'}>
            <Glyph name={i.ok ? 'check' : 'cross'} />
            <b>{i.label}</b>
            <span>{i.detail}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}
