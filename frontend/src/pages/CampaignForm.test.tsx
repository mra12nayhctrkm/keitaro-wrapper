import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Meta } from '../api'
import { mockFetch, renderWithProviders } from '../test/utils'
import { CampaignForm } from './CampaignsPage'

const meta: Meta = {
  keitaro_admin_url: 'https://kt.test/admin',
  campaign_prefix: 'test_mkrtchyan_',
  domains: [{ id: 7, name: 'in.posdk.xyz' }],
  groups: [{ id: 3, name: 'FORTESTS' }],
  traffic_sources: [{ id: 5, name: 'FORTESTS' }],
  default_domain_id: 7,
  default_group_id: 3,
  default_traffic_source_id: 5,
}

describe('CampaignForm', () => {
  it('previews the prefixed name and submits the campaign', async () => {
    const fetchMock = mockFetch({
      'GET /api/offers': [{ id: 13, name: 'FitoMishki' }],
      'POST /api/campaigns': { id: 99, name: 'test_mkrtchyan_spring', alias: 'x', fetched_at: null, streams: [] },
    })
    renderWithProviders(<CampaignForm meta={meta} />)

    expect(screen.getByLabelText('Domain')).toHaveValue('7')
    await userEvent.type(screen.getByLabelText('Name'), 'spring')
    expect(screen.getByText('Will be created as test_mkrtchyan_spring')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('Geo'), 'AU, MX')

    const create = screen.getByText('Create')
    expect(create).toBeDisabled() // no offer yet
    await userEvent.type(screen.getByLabelText('Offer'), 'fito')
    await userEvent.click(await screen.findByText('FitoMishki'))
    await userEvent.click(create)

    await waitFor(() =>
      expect(fetchMock.mock.calls.some((c) => c[1]?.method === 'POST')).toBe(true),
    )
    const post = fetchMock.mock.calls.find((c) => c[1]?.method === 'POST')
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({
      name: 'spring',
      geo: 'AU, MX',
      offer_id: 13,
      domain_id: 7,
      group_id: 3,
      traffic_source_id: 5,
    })
  })

  it('shows validation errors from the API', async () => {
    mockFetch({
      'GET /api/offers': [{ id: 13, name: 'FitoMishki' }],
      'POST /api/campaigns': () =>
        new Response(JSON.stringify({ detail: 'Unknown country code(s): XX.' }), { status: 422 }),
    })
    renderWithProviders(<CampaignForm meta={meta} />)
    await userEvent.type(screen.getByLabelText('Name'), 'x')
    await userEvent.type(screen.getByLabelText('Geo'), 'XX')
    await userEvent.type(screen.getByLabelText('Offer'), 'fito')
    await userEvent.click(await screen.findByText('FitoMishki'))
    await userEvent.click(screen.getByText('Create'))
    expect(await screen.findByRole('alert')).toHaveTextContent('Unknown country code(s): XX.')
  })
})
