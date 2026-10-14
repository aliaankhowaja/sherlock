import type { AssertionResult, Artifact } from './api'
import type { StepsView } from './model'

const FLIP: [RegExp, string][] = [
  [/^output does not contain /, 'output contains '],
  [/^output contains /, 'output does not contain '],
]
const OPPOSITE = 'expected the opposite: '

/** Expected vs actual for one failed assertion. Uses `expected`/`actual` when the artifact has them, else reads the reason. */
function sides(r: AssertionResult): { expected: string; actual: string } {
  if (r.expected !== undefined && r.actual !== undefined) return { expected: r.expected, actual: r.actual }
  const actual = r.reason.startsWith(OPPOSITE) ? r.reason.slice(OPPOSITE.length) : r.reason
  const hit = FLIP.find(([re]) => re.test(actual))
  return { expected: hit ? actual.replace(hit[0], hit[1]) : `${r.type} check passes`, actual }
}

const text = (v: unknown) => (typeof v === 'string' ? v : JSON.stringify(v, null, 1))

/** The judgment strip: the check the failed run did not pass, expected beside actual (FR-U2). */
export default function Judgment({ check, run }: { check: Artifact['check']; run: StepsView | null }) {
  if (!check) return null
  const failed = check.results.filter((r) => !r.pass)
  const out = run && (run.final_state.final_output ?? run.final_state.output ?? run.final_state)
  return (
    <section className={`judgment ${check.pass ? 'is-pass' : 'is-fail'}`} aria-label="Failed check">
      <h3 className="eyebrow">{check.pass ? 'The check passes' : `Failed check (${failed.length} of ${check.results.length})`}</h3>
      {failed.length > 0 && (
        <table className="judge-table">
          <thead><tr><th>Expected</th><th>Actual</th></tr></thead>
          <tbody>
            {failed.map((r, i) => {
              const s = sides(r)
              return <tr key={i}><td>{s.expected}</td><td>{s.actual}</td></tr>
            })}
          </tbody>
        </table>
      )}
      {!check.pass && out != null && <details><summary>The run's final output</summary><pre>{text(out)}</pre></details>}
    </section>
  )
}
