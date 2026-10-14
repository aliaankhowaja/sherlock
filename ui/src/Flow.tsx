import { useState } from 'react'
import { short, useJson, type Diagnosis, type DiagnosisList, type Info, type Team } from './api'
import Diagnose from './Diagnose'
import { Glyph } from './Kv'
import type { Job } from './model'
import { useJob } from './jobs'
import Pick from './Pick'
import Replay from './Replay'
import { runPath } from './route'
import Verdict from './Verdict'
import Welcome from './Welcome'

type Step = 1 | 2 | 3 | 4
const STEPS: { n: Step; label: string }[] = [
  { n: 1, label: 'Pick runs' },
  { n: 2, label: 'Pipeline & replay' },
  { n: 3, label: 'Diagnose' },
  { n: 4, label: 'Verdict' },
]

/** The guided flow: pick, watch, diagnose, read. `/runs/:id` opens straight on the verdict. */
export default function Flow({ initialRun }: { initialRun: string | null }) {
  const info = useJson<Info>('/api/info')
  const teams = useJson<Team[]>('/api/teams')
  const diags = useJson<DiagnosisList>('/api/diagnoses')
  const opened = useJson<Diagnosis>(initialRun ? `/api/diagnoses/${encodeURIComponent(initialRun)}` : null)
  const jobs = useJson<Job[]>('/api/jobs')
  const [pick, setPick] = useState<{ team?: string; failed?: string; good?: string }>({})
  const [step, setStepRaw] = useState<Step>(initialRun ? 4 : 1)
  const [jobId, setJobId] = useState<number | null>(null)
  const [started, setStarted] = useState(false)
  const landing = step === 1 && !started && !initialRun && !pick.failed

  const graphId = opened.data?.summary.graph_id
  const team = pick.team ?? teams.data?.find((t) => t.graph_id === graphId)?.assistant_id ?? ''
  const failed = pick.failed ?? initialRun ?? ''
  const good = pick.good ?? opened.data?.artifact.known_good_source?.thread_id ?? ''
  const pastJob = jobs.data?.find((j) => j.failed === failed)?.id ?? null
  const { job, error: jobError } = useJob(jobId ?? pastJob)
  const diagnosed = new Set((diags.data?.diagnoses ?? []).map((d) => d.thread_id))

  const setStep = (n: Step) => {
    window.history.replaceState(null, '', n === 4 && failed ? runPath(failed) : '/')
    if (n === 4) diags.reload()
    setStepRaw(n)
  }
  const reachable = (n: Step) => n === 1 || (n === 2 && !!failed) || (n === 3 && !!failed) || (n === 4 && !!failed)

  const next = (): string => {
    if (info.error || teams.error) return `Sherlock cannot reach its server (${info.error ?? teams.error}). Restart sherlock serve, then reload.`
    switch (step) {
      case 1:
        if (landing) return 'This is a finished example: a failure with two causes. Press Try your own run to diagnose yours.'
        if (!team) return 'Pick the team whose run went wrong.'
        if (!failed) return 'Pick the failed run: the run that gave a wrong answer.'
        if (!good) return 'Pick a known-good run: same input, right answer. Then press Watch the failed run.'
        return 'Both runs picked. Next: press Watch the failed run.'
      case 2:
        return `You are watching run ${short(failed)} replay. Press Play or Step; click any node to inspect it. Next: Diagnose.`
      case 3:
        if (!job) return 'Press Run diagnosis. Sherlock will restore nodes from the good run and replay the rest.'
        if (job.state === 'running') return `Diagnosing now: ${job.events.filter((e) => e.event === 'trial').length} trial(s) finished. Watch the log.`
        if (job.state === 'failed') return `The diagnosis stopped: ${job.error ?? 'no verdict'}. Check the log, then run it again.`
        return 'Diagnosis finished. Next: press Read the verdict.'
      case 4:
        return 'This is what the trials proved, and no more. Click a node for its evidence, or download the report.'
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <a className="brand" href="/" onClick={(e) => { e.preventDefault(); setPick({}); setJobId(null); setStarted(false); setStep(1) }}>
          SHERLOCK<span>fault isolation bench</span>
        </a>
        <ol className="stepper">
          {STEPS.map((s) => (
            <li key={s.n} className={s.n === step ? 'is-now' : s.n < step ? 'is-done' : ''}>
              <button type="button" disabled={!reachable(s.n)} aria-current={s.n === step ? 'step' : undefined} onClick={() => setStep(s.n)}>
                <span className="step-n">{s.n < step ? <Glyph name="check" /> : s.n}</span>
                {s.label}
              </button>
            </li>
          ))}
        </ol>
        <a className="advanced" href="/explore">Advanced</a>
      </header>
      <p className="nextline" role="status"><span>Next</span>{next()}</p>
      <main className="main">
        {landing && <Welcome diagnoses={diags.data?.diagnoses ?? []} onStart={() => setStarted(true)} />}
        {step === 1 && !landing && (
          <Pick
            teams={teams.data ?? []}
            diagnoses={diags.data?.diagnoses ?? []}
            team={team}
            failed={failed}
            good={good}
            onTeam={(id) => setPick({ team: id, failed: '', good: '' })}
            onFailed={(id, g) => setPick({ team, failed: id, good: g ?? (good === id ? '' : good) })}
            onGood={(id) => setPick({ team, failed, good: id })}
            onNext={() => setStep(2)}
          />
        )}
        {step === 2 && <Replay team={team} failed={failed} good={good} onNext={() => setStep(3)} />}
        {step === 3 && (
          <Diagnose info={info.data} infoError={info.error} team={team} failed={failed} good={good} job={job} jobError={jobError} diagnosed={diagnosed.has(failed)}
            onJob={(id) => { setJobId(id); info.reload() }} onPick={() => setStep(1)} onVerdict={() => setStep(4)} />
        )}
        {step === 4 && <Verdict key={`${failed}-${job?.id ?? 0}-${job?.state}`} failed={failed} onDiagnose={() => setStep(3)} onReplay={() => setStep(2)} />}
      </main>
    </div>
  )
}
