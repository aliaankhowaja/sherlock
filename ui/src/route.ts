import { useSyncExternalStore } from 'react'

const EVENT = 'sherlock:navigate'

function subscribe(onChange: () => void) {
  window.addEventListener('popstate', onChange)
  window.addEventListener(EVENT, onChange)
  return () => {
    window.removeEventListener('popstate', onChange)
    window.removeEventListener(EVENT, onChange)
  }
}

/** Current pathname. The server falls back to index.html, so real paths work. */
export function usePath(): string {
  return useSyncExternalStore(subscribe, () => window.location.pathname)
}

export function navigate(path: string) {
  if (path !== window.location.pathname) {
    window.history.pushState(null, '', path)
    window.dispatchEvent(new Event(EVENT))
  }
  window.scrollTo(0, 0)
}

/** `/runs/<id>` is the one URL for a diagnosed run (FR-I5). */
export function runPath(threadId: string): string {
  return `/runs/${encodeURIComponent(threadId)}`
}
