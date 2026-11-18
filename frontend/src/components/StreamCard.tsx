import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Campaign, type Named, type Stream, type StreamOffer } from '../api'
import { OfferSearch } from './OfferSearch'

const STATUS_LABEL: Record<StreamOffer['status'], string> = {
  active: '',
  pending_add: 'will be added',
  pending_remove: 'will be removed',
  removed: 'removed',
}

interface Props {
  stream: Stream
}

export function StreamCard({ stream }: Props) {
  const queryClient = useQueryClient()
  const [offer, setOffer] = useState<Named | null>(null)

  // Every edit returns the updated stream; put it straight into the campaign cache.
  const mutation = useMutation({
    mutationFn: (action: () => Promise<Stream>) => action(),
    onSuccess: (updated) => {
      queryClient.setQueryData<Campaign>(['campaign', updated.campaign_id], (campaign) =>
        campaign && {
          ...campaign,
          streams: campaign.streams.map((s) => (s.id === updated.id ? updated : s)),
        },
      )
    },
  })
  const run = (action: () => Promise<Stream>) => mutation.mutate(action)
  const busy = mutation.isPending

  if (!stream.has_offers) {
    return (
      <section className="stream" aria-label={`Stream ${stream.name}`}>
        <header className="stream-header">
          <h3>
            {stream.name} <span className="muted">#{stream.id}</span>
          </h3>
          <span className="muted">no offers</span>
        </header>
      </section>
    )
  }

  return (
    <section
      className={`stream${stream.is_dirty ? ' dirty' : ''}`}
      aria-label={`Stream ${stream.name}`}
    >
      <header className="stream-header">
        <h3>
          {stream.name} <span className="muted">#{stream.id}</span>
          {stream.is_dirty && <span className="badge warn">unpublished</span>}
        </h3>
        {stream.is_dirty && (
          <div className="actions">
            <button className="primary" disabled={busy} onClick={() => run(() => api.push(stream.id))}>
              Push to Keitaro
            </button>
            <button disabled={busy} onClick={() => run(() => api.cancel(stream.id))}>
              Cancel
            </button>
          </div>
        )}
      </header>

      {mutation.error && (
        <p className="error" role="alert">
          {mutation.error.message}
        </p>
      )}
      {stream.offers.some((o) => o.status !== 'removed') && stream.total_share !== 100 && (
        <p className="error">Shares add up to {stream.total_share}%, not 100%.</p>
      )}

      <table>
        <thead>
          <tr>
            <th>Offer</th>
            <th className="num">Share</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {stream.offers.map((o) => (
            <OfferRow key={o.id} offer={o} busy={busy} run={run} />
          ))}
          {stream.offers.length === 0 && (
            <tr>
              <td colSpan={3} className="muted">
                No offers yet
              </td>
            </tr>
          )}
        </tbody>
      </table>

      <form
        className="add-offer"
        onSubmit={(e) => {
          e.preventDefault()
          if (!offer) return
          const id = offer.id
          mutation.mutate(() => api.addOffer(stream.id, id), { onSuccess: () => setOffer(null) })
        }}
      >
        <OfferSearch value={offer} onChange={setOffer} />
        <button type="submit" disabled={!offer || busy}>
          Add
        </button>
      </form>
    </section>
  )
}

interface RowProps {
  offer: StreamOffer
  busy: boolean
  run: (action: () => Promise<Stream>) => void
}

function OfferRow({ offer: o, busy, run }: RowProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(String(o.share))
  const removed = o.status === 'removed' || o.status === 'pending_remove'

  const saveShare = () => {
    const share = Number(draft)
    setEditing(false)
    if (Number.isInteger(share) && share >= 0 && share <= 100 && share !== o.share) {
      run(() => api.updateOffer(o.id, { share }))
    }
  }

  return (
    <tr className={`offer ${o.status}`}>
      <td>
        <span className="muted">#{o.offer_id}</span> {o.offer_name || 'Unknown offer'}
        {STATUS_LABEL[o.status] && <span className={`badge ${o.status}`}>{STATUS_LABEL[o.status]}</span>}
      </td>
      <td className="num share">
        {editing ? (
          <input
            className="share-input"
            type="number"
            min={0}
            max={100}
            autoFocus
            aria-label="Share, %"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={saveShare}
            onKeyDown={(e) => {
              if (e.key === 'Enter') saveShare()
              if (e.key === 'Escape') setEditing(false)
            }}
          />
        ) : (
          <button
            className="link"
            disabled={removed || busy}
            title="Set share (pins it)"
            onClick={() => {
              setDraft(String(o.share))
              setEditing(true)
            }}
          >
            {o.share}%
          </button>
        )}
        <button
          className={`pin${o.pinned ? ' on' : ''}`}
          disabled={removed || busy}
          aria-pressed={o.pinned}
          title={o.pinned ? 'Unpin share' : 'Pin share: keep it when others change'}
          onClick={() => run(() => api.updateOffer(o.id, { pinned: !o.pinned }))}
        >
          📌
        </button>
      </td>
      <td className="actions">
        {removed ? (
          <button disabled={busy} onClick={() => run(() => api.bringBack(o.id))}>
            Bring back
          </button>
        ) : (
          <button disabled={busy} onClick={() => run(() => api.removeOffer(o.id))}>
            Remove
          </button>
        )}
      </td>
    </tr>
  )
}
