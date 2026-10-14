import './App.css'
import './shell.css'
import './stage.css'
import './graph.css'
import './panels.css'
import './screens.css'
import './verdict.css'
import Explorer from './Explorer'
import Flow from './Flow'
import { usePath } from './route'

function App() {
  const path = usePath()
  if (path === '/explore') {
    return (
      <div className="app">
        <header className="topbar">
          <a className="brand" href="/">SHERLOCK<span>fault isolation bench</span></a>
          <a className="advanced" href="/">Back to the guided flow</a>
        </header>
        <main className="main explore">
          <Explorer />
        </main>
      </div>
    )
  }
  const run = /^\/runs\/([^/]+)\/?$/.exec(path)
  const id = run ? decodeURIComponent(run[1]) : null
  return <Flow initialRun={id} />
}

export default App
