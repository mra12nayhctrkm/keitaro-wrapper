import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { api, type Meta, type Named } from '../api'
import { OfferSearch } from '../components/OfferSearch'

export function CampaignsPage() {
  return (
    <div className="grid">
      <NewCampaign />
      <CampaignList />
    </div>
  )
}

function NewCampaign() {
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: Infinity })
  return (
    <section className="card">
      <h2>New campaign</h2>
      {meta.error && <p className="error">{meta.error.message}</p>}
      {meta.isPending && !meta.error && <p className="muted">Loading Keitaro settings…</p>}
      {meta.data && <CampaignForm meta={meta.data} />}
    </section>
  )
}

export function CampaignForm({ meta }: { meta: Meta }) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [geo, setGeo] = useState('')
  const [offer, setOffer] = useState<Named | null>(null)
  const [domainId, setDomainId] = useState(meta.default_domain_id ?? 0)
  const [groupId, setGroupId] = useState(meta.default_group_id ?? 0)
  const [sourceId, setSourceId] = useState(meta.default_traffic_source_id ?? 0)

  const create = useMutation({
    mutationFn: api.createCampaign,
    onSuccess: (campaign) => {
      queryClient.setQueryData(['campaign', campaign.id], campaign)
      void queryClient.invalidateQueries({ queryKey: ['campaigns'] })
      void navigate(`/campaigns/${campaign.id}`)
    },
  })

  const fullName = name.trim().startsWith(meta.campaign_prefix)
    ? name.trim()
    : `${meta.campaign_prefix}${name.trim()}`

  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault()
        if (!offer) return
        create.mutate({
          name: name.trim(),
          geo,
          offer_id: offer.id,
          domain_id: domainId || undefined,
          group_id: groupId || undefined,
          traffic_source_id: sourceId || undefined,
        })
      }}
    >
      <label htmlFor="name">Name</label>
      <div>
        <input id="name" required value={name} onChange={(e) => setName(e.target.value)} placeholder="campaign1" />
        {name.trim() && <small className="muted">Will be created as {fullName}</small>}
      </div>

      <label htmlFor="geo">Geo</label>
      <div>
        <input id="geo" required value={geo} onChange={(e) => setGeo(e.target.value)} placeholder="MX, AU, RO" />
        <small className="muted">Visitors from these countries are redirected to Google</small>
      </div>

      <label htmlFor="offer">Offer</label>
      <div>
        <OfferSearch inputId="offer" value={offer} onChange={setOffer} />
        <small className="muted">Everyone else goes to this offer</small>
      </div>

      <label htmlFor="domain">Domain</label>
      <Select id="domain" items={meta.domains} value={domainId} onChange={setDomainId} />
      <label htmlFor="group">Group</label>
      <Select id="group" items={meta.groups} value={groupId} onChange={setGroupId} />
      <label htmlFor="source">Source</label>
      <Select id="source" items={meta.traffic_sources} value={sourceId} onChange={setSourceId} />

      <div />
      <div>
        {create.error && (
          <p className="error" role="alert">
            {create.error.message}
          </p>
        )}
        <button className="primary" type="submit" disabled={!offer || create.isPending}>
          {create.isPending ? 'Creating…' : 'Create'}
        </button>
      </div>
    </form>
  )
}

function Select(props: { id: string; items: Named[]; value: number; onChange: (id: number) => void }) {
  return (
    <select id={props.id} required value={props.value || ''} onChange={(e) => props.onChange(Number(e.target.value))}>
      <option value="" disabled>
        Choose…
      </option>
      {props.items.map((item) => (
        <option key={item.id} value={item.id}>
          {item.name}
        </option>
      ))}
    </select>
  )
}

function CampaignList() {
  const [q, setQ] = useState('')
  // Load the list once and filter locally: no request to Keitaro per keystroke.
  const campaigns = useQuery({ queryKey: ['campaigns'], queryFn: () => api.listCampaigns(''), staleTime: 60_000 })
  const needle = q.trim().toLowerCase()
  const shown = campaigns.data?.filter(
    (c) => !needle || c.name.toLowerCase().includes(needle) || String(c.id) === needle,
  )

  return (
    <section className="card">
      <h2>Edit a campaign</h2>
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by name or ID" aria-label="Filter campaigns" />
      {campaigns.error && <p className="error">{campaigns.error.message}</p>}
      {campaigns.isPending && <p className="muted">Loading…</p>}
      <ul className="campaign-list">
        {shown?.slice(0, 200).map((c) => (
          <li key={c.id}>
            <Link to={`/campaigns/${c.id}`}>
              <span className="muted">#{c.id}</span> {c.name}
            </Link>
          </li>
        ))}
        {shown?.length === 0 && <li className="muted">No campaigns</li>}
      </ul>
    </section>
  )
}
