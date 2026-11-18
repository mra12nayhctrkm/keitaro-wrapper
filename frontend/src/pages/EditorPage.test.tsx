import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
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
    { id: 1, campaign_id: 5, name: 'Geo AU → Google', type: 'regular', position: 1, has_offers: false, is_dirty: false, remote_changed_at: null, total_share: 0, offers: [] },
    {
      id: 2, campaign_id: 5, name: 'Offers', type: 'regular', position: 2, has_offers: true, is_dirty: false, remote_changed_at: null, total_share: 100,
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
      'GET /api/campaigns/5/stats': {
        period: '7d',
        days: ['2026-11-17', '2026-11-18'],
        streams: [
          { stream_id: 1, clicks: 8, conversions: 0, revenue: 0, cr: 0, epc: 0, offers: [] },
          {
            stream_id: 2, clicks: 40, conversions: 2, revenue: 10, cr: 5, epc: 0.25,
            offers: [{ offer_id: 18813, clicks: 40, conversions: 2, revenue: 10, cr: 5, epc: 0.25, daily_clicks: [10, 30], daily_conversions: [0, 2] }],
          },
        ],
      },
    })
    renderPage()

    expect(await screen.findByText('Flexacil')).toBeInTheDocument()
    expect(screen.getByText(/^no offers/)).toBeInTheDocument()
    expect(screen.getByText('View in Keitaro ↗')).toHaveAttribute('href', 'https://kt.test/admin/#!/campaigns/5')
    const calls = fetchMock.mock.calls.map((c) => `${c[1]?.method ?? 'GET'} ${String(c[0])}`)
    expect(calls).toContain('POST /api/campaigns/5/fetch')

    // Stats and trend for the offer, stream totals for the redirect stream.
    expect(await screen.findByText('40')).toBeInTheDocument()
    expect(screen.getByText(/CR 5% · EPC 0.25 · rev 10.00/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: 'Daily clicks for offer 18813: 10, 30' })).toBeInTheDocument()
    expect(screen.getByText('no offers · 8 clicks')).toBeInTheDocument()

    await userEvent.selectOptions(screen.getByLabelText('Stats period'), '30d')
    await waitFor(() =>
      expect(fetchMock.mock.calls.map((c) => String(c[0]))).toContain('/api/campaigns/5/stats?period=30d'),
    )
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
