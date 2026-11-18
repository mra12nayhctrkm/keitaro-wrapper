import { Link, Route, Routes } from 'react-router'
import { CampaignsPage } from './pages/CampaignsPage'
import { EditorPage } from './pages/EditorPage'

export function App() {
  return (
    <>
      <header className="topbar">
        <Link to="/" className="brand">
          Keitaro Wrapper
        </Link>
      </header>
      <main>
        <Routes>
          <Route path="/" element={<CampaignsPage />} />
          <Route path="/campaigns/:id" element={<EditorPage />} />
          <Route path="*" element={<p>Page not found. <Link to="/">Go home</Link></p>} />
        </Routes>
      </main>
    </>
  )
}
