import './App.css'
import './surface.css'
import Explorer from './Explorer'
import Guide from './Guide'
import { Link } from './parts'
import { usePath } from './route'
import RunPage from './RunPage'

function App() {
  const path = usePath()
  const run = /^\/runs\/([^/]+)\/?$/.exec(path)
  let page: React.ReactNode
  if (run) {
    page = <RunPage key={run[1]} threadId={decodeURIComponent(run[1])} />
  } else if (path === '/explore') {
    page = <Explorer />
  } else {
    page = <Guide />
  }
  return (
    <div className="dashboard">
      <header className="dashboard-header">
        <h1>sherlock</h1>
        <nav className="nav" aria-label="Main">
          <Link to="/" className={path === '/' ? 'active' : undefined}>
            Diagnose a run
          </Link>
          <Link to="/explore" className={path === '/explore' ? 'active' : undefined}>
            Browse teams and runs
          </Link>
        </nav>
      </header>
      {page}
    </div>
  )
}

export default App
