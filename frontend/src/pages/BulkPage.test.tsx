import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import type { Meta } from '../api'
import { mockFetch, renderWithProviders } from '../test/utils'
import { BulkForm } from './BulkPage'

const meta: Meta = {
  keitaro_admin_url: 'https://kt.test/admin',
  campaign_prefix: 'test_x_',
  domains: [],
  groups: [{ id: 3, name: 'FORTESTS' }],
  traffic_sources: [],
  default_domain_id: null,
  default_group_id: 3,
  default_traffic_source_id: null,
}

const preview = {
  scanned_campaigns: 2,
  errors: [],
  changes: [
    { campaign_id: 1, campaign_name: 'test_x_a', stream_id: 10, stream_name: 'Offers', before: [{ offer_id: 11, share: 100 }], after: [{ offer_id: 14, share: 100 }] },
    { campaign_id: 2, campaign_name: 'test_x_b', stream_id: 20, stream_name: 'Offers', before: [{ offer_id: 11, share: 50 }, { offer_id: 12, share: 50 }], after: [{ offer_id: 12, share: 50 }, { offer_id: 14, share: 50 }] },
  ],
}

async function pick(label: string, query: string, option: string) {
  await userEvent.type(screen.getByLabelText(label), query)
  await userEvent.click(await screen.findByText(option))
}

describe('BulkForm', () => {
  it('previews, lets you deselect, and applies only the chosen streams', async () => {
    const fetchMock = mockFetch({
      'GET /api/offers': (url: string) =>
        url.includes('q=a') ? [{ id: 11, name: 'Alpha' }] : [{ id: 14, name: 'Omega' }],
      'POST /api/bulk/replace-offer/preview': preview,
      'POST /api/bulk/replace-offer/apply': [
        { campaign_id: 2, stream_id: 20, status: 'drafted', detail: '' },
      ],
    })
    renderWithProviders(<BulkForm meta={meta} />)

    expect(screen.getByLabelText('Name has')).toHaveValue('test_x_') // safe default
    await pick('Replace', 'a', 'Alpha')
    await pick('With', 'o', 'Omega')
    await userEvent.click(screen.getByText('Preview'))

    expect(await screen.findByText(/Scanned 2 campaign\(s\), 2 stream\(s\)/)).toBeInTheDocument()
    expect(screen.getByText(/#11 50%, #12 50% →/)).toBeInTheDocument()
    expect(screen.getByText('#12 50%, #14 50%')).toBeInTheDocument()
    await userEvent.click(screen.getByLabelText('Select stream 10'))
    await userEvent.click(screen.getByText('Apply as drafts (1)'))

    expect(await screen.findByText('drafted')).toBeInTheDocument()
    const apply = fetchMock.mock.calls.find((c) => String(c[0]) === '/api/bulk/replace-offer/apply')
    expect(JSON.parse(String(apply?.[1]?.body))).toEqual({
      from_offer_id: 11,
      to_offer_id: 14,
      publish: false,
      targets: [{ campaign_id: 2, stream_id: 20 }],
    })
    const sent = fetchMock.mock.calls.find((c) => String(c[0]) === '/api/bulk/replace-offer/preview')
    expect(JSON.parse(String(sent?.[1]?.body))).toMatchObject({ group_id: 3, name_filter: 'test_x_' })
  })

  it('asks before publishing', async () => {
    const fetchMock = mockFetch({
      'GET /api/offers': (url: string) =>
        url.includes('q=a') ? [{ id: 11, name: 'Alpha' }] : [{ id: 14, name: 'Omega' }],
      'POST /api/bulk/replace-offer/preview': preview,
    })
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
    renderWithProviders(<BulkForm meta={meta} />)
    await pick('Replace', 'a', 'Alpha')
    await pick('With', 'o', 'Omega')
    await userEvent.click(screen.getByText('Preview'))
    await userEvent.click(await screen.findByText('Apply and publish'))
    expect(confirm).toHaveBeenCalledWith('Publish the replacement to 2 stream(s) in Keitaro?')
    await waitFor(() =>
      expect(fetchMock.mock.calls.some((c) => String(c[0]).includes('/apply'))).toBe(false),
    )
  })
})
