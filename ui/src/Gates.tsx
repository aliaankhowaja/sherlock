import type { GateSummary } from './api'

/** "How the gates narrowed it down": each gate's count, left to right, only for the numbers the artifact has. */
export default function Gates({ g }: { g: GateSummary }) {
  const steps: { n: number; label: string; why: string }[] = []
  const has = (v: unknown): v is number => typeof v === 'number'
  if (has(g.nodes_total)) steps.push({ n: g.nodes_total, label: 'nodes in the team', why: 'Every node the graph declares.' })
  if (has(g.nodes_total) && has(g.pruned_by_ancestry)) {
    steps.push({ n: g.nodes_total - g.pruned_by_ancestry, label: 'could reach the output', why: `${g.pruned_by_ancestry} nodes dropped: nothing they wrote can reach the failed answer.` })
  }
  if (has(g.g0_flagged)) steps.push({ n: g.g0_flagged, label: 'flagged by clues', why: 'Cheap signals: an error, an empty or malformed output, or a different output from the known-good run. Clues order the search; they prove nothing.' })
  if (has(g.g1_nominated)) steps.push({ n: g.g1_nominated, label: 'nominated', why: 'Suspects put forward for testing.' })
  if (has(g.g1_nominated) && has(g.g2_cut)) steps.push({ n: g.g1_nominated - g.g2_cut, label: 'on the recorded path', why: `${g.g2_cut} suspect(s) cut: no recorded hand-off links them to the failure.` })
  if (has(g.g3_trials)) steps.push({ n: g.g3_trials, label: g.g3_trials === 1 ? 'replay trial' : 'replay trials', why: 'Restore-and-replay trials: the only step that proves anything.' })
  if (!steps.length) return null
  return (
    <figure className="gates" aria-label="How the gates narrowed it down">
      <figcaption>How the search narrowed it down</figcaption>
      <ol>
        {steps.map((s, i) => (
          <li key={i} title={s.why}>
            <b>{s.n.toLocaleString()}</b>
            <span>{s.label}</span>
          </li>
        ))}
      </ol>
      {has(g.exhaustive_count) && <p className="gates-note">Testing every group of nodes would take {g.exhaustive_count.toLocaleString()} trials.</p>}
    </figure>
  )
}
