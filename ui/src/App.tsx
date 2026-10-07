import { useEffect, useState } from 'react'
import './App.css'

function App() {
  const [apiStatus, setApiStatus] = useState<string>('checking…')

  // Same-origin: the UI is served by the api crate, so no base URL config needed.
  useEffect(() => {
    fetch('/api/health')
      .then((res) => res.json())
      .then((data) => setApiStatus(data.status ?? 'unknown'))
      .catch(() => setApiStatus('unreachable'))
  }, [])

  return (
    <>
      <div>murgi</div>
      <div>api: {apiStatus}</div>
    </>
  )
}

export default App
