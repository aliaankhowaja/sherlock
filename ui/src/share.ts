import type { Diagnosis } from './api'

function download(name: string, mime: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: mime }))
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

/** The artifact exactly as the engine wrote it. */
export function downloadJson(d: Diagnosis) {
  download(
    `sherlock-${d.summary.thread_id}.json`,
    'application/json',
    JSON.stringify(d.artifact, null, 2),
  )
}

function pageCss(): string {
  return [...document.styleSheets]
    .map((sheet) => {
      try {
        return [...sheet.cssRules].map((r) => r.cssText).join('\n')
      } catch {
        return ''
      }
    })
    .join('\n')
}

/**
 * A read-only copy of the report: the page's own HTML and CSS, no script, no buttons
 * (anything marked `data-noshare` is dropped). Opens offline, cannot run or fire anything.
 */
export function shareHtml(report: HTMLElement, title: string): string {
  const copy = report.cloneNode(true) as HTMLElement
  copy.querySelectorAll('[data-noshare]').forEach((el) => el.remove())
  copy.querySelectorAll('details').forEach((el) => el.setAttribute('open', ''))
  copy.querySelectorAll('a').forEach((a) => a.removeAttribute('href'))
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;')
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<style>${pageCss()}
body { max-width: 1000px; margin: 0 auto; padding: 16px; }</style>
</head><body class="share">
<div class="share-note">Read-only export from Sherlock, ${esc(new Date().toISOString().slice(0, 10))}. This file contains no script and cannot re-run anything.</div>
${copy.outerHTML}
</body></html>
`
}

export function downloadHtml(report: HTMLElement, d: Diagnosis) {
  download(
    `sherlock-${d.summary.thread_id}.html`,
    'text/html',
    shareHtml(report, `Sherlock diagnosis ${d.summary.thread_id}`),
  )
}
