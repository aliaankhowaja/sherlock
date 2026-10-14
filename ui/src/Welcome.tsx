import type { Summary } from './api'
import Demo from './Demo'
import Verdict from './Verdict'

/** First screen (FR-U9, NFR-12): an already-solved two-cause failure. No signup, no API key. */
export default function Welcome({ diagnoses, onStart }: { diagnoses: Summary[]; onStart: () => void }) {
  const live = diagnoses.find((d) => d.status === 'found' && d.minimal_sets.some((s) => s.length === 2))
  return (
    <div className="screen welcome">
      <div className="welcome-head">
        <div>
          <p className="eyebrow">{live ? 'A two-cause failure, already diagnosed' : 'Example: a failure with two causes'}</p>
          <p className="lede">Two nodes were broken at once. Fixing either alone still gave a wrong answer, so Sherlock tested them together.</p>
        </div>
        <button type="button" className="btn-primary" onClick={onStart}>Try your own run →</button>
      </div>
      {live ? <Verdict failed={live.thread_id} onDiagnose={onStart} onReplay={onStart} /> : <Demo />}
    </div>
  )
}
