import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import type { Campaign, Stream } from '../api'
import { mockFetch, renderWithProviders } from '../test/utils'
import { StreamCard } from './StreamCard'

const stream: Stream = {
  id: 2,
  campaign_id: 1,
  name: 'Flow 2',
  type: 'regular',
  position: 2,
  has_offers: true,
  is_dirty: false,
  total_share: 100,
  offers: [
    { id: 10, offer_id: 11, offer_name: 'Miaflow', share: 50, pinned: false, status: 'active', published_share: 50 },
    { id: 20, offer_id: 12, offer_name: 'Oxys', share: 50, pinned: false, status: 'active', published_share: 50 },
  ],
}

function renderCard(s: Stream = stream) {
  const result = renderWithProviders(<StreamCard stream={s} />)
  const campaign: Campaign = { id: 1, name: 'c', alias: null, fetched_at: null, streams: [s] }
  result.client.setQueryData(['campaign', 1], campaign)
  return result
}

describe('StreamCard', () => {
  it('shows offers with shares and no publish buttons when clean', () => {
    renderCard()
    const rows = screen.getAllByRole('row').slice(1)
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('Miaflow')).toBeInTheDocument()
    expect(within(rows[0]).getByText('50%')).toBeInTheDocument()
    expect(screen.queryByText('Push to Keitaro')).not.toBeInTheDocument()
  })

  it('remove calls the API and puts the updated stream into the cache', async () => {
    const updated: Stream = {
      ...stream,
      is_dirty: true,
      offers: [
        { ...stream.offers[0], share: 100 },
        { ...stream.offers[1], share: 0, status: 'pending_remove' },
      ],
    }
    const fetchMock = mockFetch({ 'POST /api/stream-offers/20/remove': updated })
    const { client } = renderCard()

    await userEvent.click(screen.getAllByText('Remove')[1])

    await waitFor(() =>
      expect(client.getQueryData<Campaign>(['campaign', 1])?.streams[0].is_dirty).toBe(true),
    )
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('a dirty stream offers Push and Cancel, removed offers offer Bring back', async () => {
    const dirty: Stream = {
      ...stream,
      is_dirty: true,
      total_share: 100,
      offers: [
        { ...stream.offers[0], share: 100 },
        { ...stream.offers[1], share: 0, status: 'pending_remove' },
      ],
    }
    const fetchMock = mockFetch({
      'POST /api/streams/2/push': { ...dirty, is_dirty: false },
      'POST /api/stream-offers/20/bring-back': stream,
    })
    renderCard(dirty)

    expect(screen.getByText('unpublished')).toBeInTheDocument()
    expect(screen.getByText('will be removed')).toBeInTheDocument()
    await userEvent.click(screen.getByText('Bring back'))
    await userEvent.click(screen.getByText('Push to Keitaro'))
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    expect(fetchMock.mock.calls.map((c) => String(c[0]))).toEqual([
      '/api/stream-offers/20/bring-back',
      '/api/streams/2/push',
    ])
  })

  it('pin toggles and setting a share sends PATCH', async () => {
    const fetchMock = mockFetch({ 'PATCH /api/stream-offers/10': stream })
    renderCard()

    await userEvent.click(screen.getAllByTitle(/Pin share/)[0])
    await userEvent.click(screen.getAllByText('50%')[0])
    const input = screen.getByLabelText('Share, %')
    await userEvent.clear(input)
    await userEvent.type(input, '70{Enter}')

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2))
    const bodies = fetchMock.mock.calls.map((c) => JSON.parse(String(c[1]?.body)))
    expect(bodies).toEqual([{ pinned: true }, { share: 70 }])
  })

  it('shows API errors', async () => {
    mockFetch({
      'POST /api/stream-offers/10/remove': () =>
        new Response(JSON.stringify({ detail: 'Keitaro: boom' }), { status: 502 }),
    })
    renderCard()
    await userEvent.click(screen.getAllByText('Remove')[0])
    expect(await screen.findByRole('alert')).toHaveTextContent('Keitaro: boom')
  })

  it('adds an offer picked from the autocomplete', async () => {
    const fetchMock = mockFetch({
      'GET /api/offers': [{ id: 14, name: 'FitoMishki' }],
      'POST /api/streams/2/offers': stream,
    })
    renderCard()

    await userEvent.type(screen.getByRole('combobox'), 'fito')
    await userEvent.click(await screen.findByText('FitoMishki'))
    await userEvent.click(screen.getByText('Add'))

    await waitFor(() =>
      expect(fetchMock.mock.calls.some((c) => String(c[0]) === '/api/streams/2/offers')).toBe(true),
    )
    const add = fetchMock.mock.calls.find((c) => String(c[0]) === '/api/streams/2/offers')
    expect(JSON.parse(String(add?.[1]?.body))).toEqual({ offer_id: 14 })
  })

  it('renders streams without offers as a plain row', () => {
    renderCard({ ...stream, has_offers: false, offers: [] })
    expect(screen.getByText('no offers')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('warns when shares do not add up to 100', () => {
    renderCard({ ...stream, total_share: 90 })
    expect(screen.getByText(/Shares add up to 90%/)).toBeInTheDocument()
  })
})
