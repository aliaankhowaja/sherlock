import { useState } from 'react'
import type { NodeStatus, Summary } from './api'
import { navigate } from './route'
import { GLOSSARY, STATUS_LABEL, setText } from './terms'

export function ErrorBanner({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="banner banner-error" role="alert">
      <div>{message}</div>
      {hint && <div className="banner-hint">{hint}</div>}
    </div>
  )
}

export function CopyButton({ text, label = 'Copy' }: { text: string; label?: string }) {
  const [done, setDone] = useState(false)
  return (
    <button
      type="button"
      className="small-button"
      data-noshare
      onClick={() => {
        void navigator.clipboard?.writeText(text).then(() => {
          setDone(true)
          setTimeout(() => setDone(false), 1500)
        })
      }}
    >
      {done ? 'Copied' : label}
    </button>
  )
}

export function CommandBox({ command }: { command: string }) {
  return (
    <div className="command">
      <code>{command}</code>
      <CopyButton text={command} label="Copy command" />
    </div>
  )
}

const STATUS_GLYPH: Record<NodeStatus, string> = {
  culprit: '●',
  cleared: '✓',
  unverified: '○',
  abstained: '?',
}

/** Status chip: colour + glyph + words, so colour is never the only signal. */
export function StatusChip({ status }: { status: NodeStatus }) {
  return (
    <span className={`chip chip-${status}`}>
      <span aria-hidden="true">{STATUS_GLYPH[status]}</span> {STATUS_LABEL[status]}
    </span>
  )
}

/** The verdict in one plain-language card. Says no more than the diagnosis proved. */
export function VerdictCard({ summary }: { summary: Summary }) {
  if (summary.status === 'found') {
    const multi = summary.minimal_sets.length > 1
    return (
      <div className="verdict verdict-found">
        <div className="verdict-title">
          Found: {multi ? 'smallest fixes' : 'smallest fix'} {setText(summary.minimal_sets)}
        </div>
        <p>
          Putting {multi ? 'either of these groups' : 'these nodes'} back to known-good behaviour
          makes the run pass the check, and no smaller part of{' '}
          {multi ? 'them' : 'it'} does. That was tested, not guessed.
          {!summary.complete &&
            ' The search stopped early, so there may be other smallest fixes it did not reach.'}
        </p>
      </div>
    )
  }
  return (
    <div className="verdict verdict-abstain">
      <div className="verdict-title">Cannot say</div>
      <p>
        {summary.reason}
        {summary.reason_code && (
          <>
            {' '}
            <code>{summary.reason_code}</code>
          </>
        )}
      </p>
      <p className="verdict-note">
        Sherlock names no node when it cannot prove one. Nothing below is a cause.
      </p>
    </div>
  )
}

export function Glossary() {
  return (
    <section className="glossary">
      <h2>What the words mean</h2>
      <dl>
        {GLOSSARY.map((g) => (
          <div key={g.term}>
            <dt>{g.term}</dt>
            <dd>{g.meaning}</dd>
          </div>
        ))}
      </dl>
    </section>
  )
}

/** In-app link: real href (so it can be copied or opened in a tab), no page reload on click. */
export function Link({
  to,
  children,
  className,
}: {
  to: string
  children: React.ReactNode
  className?: string
}) {
  return (
    <a
      href={to}
      className={className}
      onClick={(e) => {
        if (e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return
        e.preventDefault()
        navigate(to)
      }}
    >
      {children}
    </a>
  )
}
