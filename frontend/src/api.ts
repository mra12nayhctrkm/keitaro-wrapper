export type OfferStatus = 'active' | 'pending_add' | 'pending_remove' | 'removed'

export interface Named {
  id: number
  name: string
}

export interface StreamOffer {
  id: number
  offer_id: number
  offer_name: string
  share: number
  pinned: boolean
  status: OfferStatus
  published_share: number | null
}

export interface Stream {
  id: number
  campaign_id: number
  name: string
  type: string
  position: number
  has_offers: boolean
  is_dirty: boolean
  total_share: number
  offers: StreamOffer[]
}

export interface Campaign {
  id: number
  name: string
  alias: string | null
  fetched_at: string | null
  streams: Stream[]
}

export interface KeitaroCampaign {
  id: number
  name: string
  alias: string | null
  state: string | null
}

export interface Meta {
  keitaro_admin_url: string
  campaign_prefix: string
  domains: Named[]
  groups: Named[]
  traffic_sources: Named[]
  default_domain_id: number | null
  default_group_id: number | null
  default_traffic_source_id: number | null
}

export interface CampaignCreate {
  name: string
  geo: string
  offer_id: number
  domain_id?: number
  group_id?: number
  traffic_source_id?: number
}

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const response = await fetch(url, {
    method,
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`
    try {
      const data: unknown = await response.json()
      message = errorMessage(data) ?? message
    } catch {
      // not JSON: keep the status line
    }
    throw new ApiError(response.status, message)
  }
  return (await response.json()) as T
}

/** FastAPI returns `detail` as a string, or a list of validation errors. */
function errorMessage(data: unknown): string | undefined {
  if (typeof data !== 'object' || data === null || !('detail' in data)) return undefined
  const { detail } = data as { detail: unknown }
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map((d: { loc?: unknown[]; msg?: string }) => `${(d.loc ?? []).slice(1).join('.')}: ${d.msg}`)
      .join('; ')
  }
  return undefined
}

export const api = {
  meta: () => request<Meta>('GET', '/api/meta'),
  searchOffers: (q: string) =>
    request<Named[]>('GET', `/api/offers?${new URLSearchParams({ q, limit: '15' })}`),
  listCampaigns: (q: string) =>
    request<KeitaroCampaign[]>('GET', `/api/campaigns?${new URLSearchParams({ q })}`),
  createCampaign: (body: CampaignCreate) => request<Campaign>('POST', '/api/campaigns', body),
  getCampaign: (id: number) => request<Campaign>('GET', `/api/campaigns/${id}`),
  fetchCampaign: (id: number) => request<Campaign>('POST', `/api/campaigns/${id}/fetch`),
  addOffer: (streamId: number, offerId: number) =>
    request<Stream>('POST', `/api/streams/${streamId}/offers`, { offer_id: offerId }),
  push: (streamId: number) => request<Stream>('POST', `/api/streams/${streamId}/push`),
  cancel: (streamId: number) => request<Stream>('POST', `/api/streams/${streamId}/cancel`),
  removeOffer: (linkId: number) => request<Stream>('POST', `/api/stream-offers/${linkId}/remove`),
  bringBack: (linkId: number) =>
    request<Stream>('POST', `/api/stream-offers/${linkId}/bring-back`),
  updateOffer: (linkId: number, patch: { pinned?: boolean; share?: number }) =>
    request<Stream>('PATCH', `/api/stream-offers/${linkId}`, patch),
}
