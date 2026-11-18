import { Link, Route, Routes } from 'react-router'
import { BulkPage } from './pages/BulkPage'
import { CampaignsPage } from './pages/CampaignsPage'
import { EditorPage } from './pages/EditorPage'
import { useMe } from './useMe'

export function App() {
  const { user, canPublish } = useMe()
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          Keitaro Wrapper
        </Link>
        <nav className="nav">
          <Link to="/">Campaigns</Link>
          <Link to="/bulk">Bulk replace</Link>
        </nav>
        {user && (
          <span className="who">
            {user} · {canPublish ? 'publisher' : 'editor'}
          </span>
        )}
      </header>
      <main>
        <Routes>
          <Route path="/" element={<CampaignsPage />} />
          <Route path="/campaigns/:id" element={<EditorPage />} />
          <Route path="/bulk" element={<BulkPage />} />
          <Route path="*" element={<p>Page not found. <Link to="/">Go home</Link></p>} />
        </Routes>
      </main>
    </>
  )
}
