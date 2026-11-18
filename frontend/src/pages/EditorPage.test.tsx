import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { describe, expect, it } from 'vitest'
import type { Campaign, Meta } from '../api'
import { mockFetch } from '../test/utils'
import { EditorPage } from './EditorPage'

const meta: Meta = {
  keitaro_admin_url: 'https://kt.test/admin',
  campaign_prefix: 'test_x_',
  domains: [],
  groups: [],
  traffic_sources: [],
  default_domain_id: null,
  default_group_id: null,
  default_traffic_source_id: null,
}

const campaign: Campaign = {
  id: 5,
  name: 'test_x_one',
  alias: 'abc',
  fetched_at: '2026-11-18T18:00:00+00:00',
  streams: [
    { id: 1, campaign_id: 5, name: 'Geo AU → Google', type: 'regular', position: 1, has_offers: false, is_dirty: false, total_share: 0, offers: [] },
    {
      id: 2, campaign_id: 5, name: 'Offers', type: 'regular', position: 2, has_offers: true, is_dirty: false, total_share: 100,
      offers: [{ id: 9, offer_id: 18813, offer_name: 'Flexacil', share: 100, pinned: false, status: 'active', published_share: 100 }],
    },
  ],
}

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/campaigns/5']}>
        <Routes>
          <Route path="/campaigns/:id" element={<EditorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('EditorPage', () => {
  it('imports a campaign from Keitaro on the first visit', async () => {
    const fetchMock = mockFetch({
      'GET /api/meta': meta,
      'GET /api/campaigns/5': () =>
        new Response(JSON.stringify({ detail: 'Campaign 5 has not been fetched yet.' }), { status: 404 }),
      'POST /api/campaigns/5/fetch': campaign,
    })
    renderPage()

    expect(await screen.findByText('Flexacil')).toBeInTheDocument()
    expect(screen.getByText('no offers')).toBeInTheDocument()
    expect(screen.getByText('View in Keitaro ↗')).toHaveAttribute('href', 'https://kt.test/admin/#!/campaigns/5')
    const calls = fetchMock.mock.calls.map((c) => `${c[1]?.method ?? 'GET'} ${String(c[0])}`)
    expect(calls).toContain('POST /api/campaigns/5/fetch')
  })

  it('shows Keitaro errors from the import', async () => {
    mockFetch({
      'GET /api/meta': meta,
      'GET /api/campaigns/5': () => new Response(JSON.stringify({ detail: 'nope' }), { status: 404 }),
      'POST /api/campaigns/5/fetch': () =>
        new Response(JSON.stringify({ detail: 'Keitaro rejected the API key: check KEITARO_API_KEY.' }), { status: 502 }),
    })
    renderPage()
    expect(await screen.findByText(/check KEITARO_API_KEY/)).toBeInTheDocument()
  })
})
