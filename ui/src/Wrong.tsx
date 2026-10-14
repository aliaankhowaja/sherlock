import { useState } from 'react'
import { useJson, type Info } from './api'
import { markWrong } from './jobs'

/** The "Wrong" button on a run page: says this answer is wrong (and what it should have been) by writing intake. */
export default function Wrong({ failed }: { failed: string }) {
  const info = useJson<Info>('/api/info')
  const [open, setOpen] = useState(false)
  const [expected, setExpected] = useState('')
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null)
  if (!info.data?.run?.enabled) return null
  const send = () =>
    markWrong(info.data!, failed, expected.trim())
      .then(() => setMsg({ ok: true, text: 'Recorded: this run is marked wrong.' }))
      .catch((e) => setMsg({ ok: false, text: e instanceof Error ? e.message : String(e) }))
  return (
    <span className="wrong">
      <button type="button" aria-expanded={open} onClick={() => setOpen(!open)}>Wrong</button>
      {open && (
        <>
          <input aria-label="What the answer should have been" placeholder="What it should have said (optional)" value={expected} onChange={(e) => setExpected(e.target.value)} />
          <button type="button" className="btn-primary" onClick={send}>Mark as wrong</button>
        </>
      )}
      {msg && <span role="status" className={msg.ok ? 'muted' : 'error-line'}>{msg.text}</span>}
    </span>
  )
}
