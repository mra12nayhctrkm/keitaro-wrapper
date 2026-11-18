import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api, type Campaign, type Named, type OfferStats, type Stream, type StreamOffer, type StreamStats } from '../api'
import { Sparkline } from './Sparkline'
import { useMe } from '../useMe'
import { HistoryPanel } from './HistoryPanel'
import { OfferSearch } from './OfferSearch'

const STATUS_LABEL: Record<StreamOffer['status'], string> = {
  active: '',
  pending_add: 'will be added',
  pending_remove: 'will be removed',
  removed: 'removed',
}

interface Props {
  stream: Stream
  /** Keitaro stats for the selected period, if loaded. */
  stats?: StreamStats
}

export function StreamCard({ stream, stats }: Props) {
  const { canPublish } = useMe()
  const offerStats = new Map(stats?.offers.map((o) => [o.offer_id, o]))
  const queryClient = useQueryClient()
  const [offer, setOffer] = useState<Named | null>(null)
  const [showHistory, setShowHistory] = useState(false)

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
      // A push adds a history entry.
      void queryClient.invalidateQueries({ queryKey: ['history', updated.id] })
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
          <span className="muted">
            no offers{stats ? ` · ${stats.clicks} clicks` : ''}
          </span>
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
        <div className="actions">
          {stream.is_dirty && (
            <>
              <button
                className="primary"
                disabled={busy || !canPublish || stream.remote_changed_at !== null}
                title={
                  !canPublish
                    ? 'Only publishers can push to Keitaro'
                    : stream.remote_changed_at
                      ? 'Keitaro changed under your draft: review it first'
                      : undefined
                }
                onClick={() => run(() => api.push(stream.id))}
              >
                Push to Keitaro
              </button>
              <button disabled={busy} onClick={() => run(() => api.cancel(stream.id))}>
                Cancel
              </button>
            </>
          )}
          <button aria-expanded={showHistory} onClick={() => setShowHistory((v) => !v)}>
            History
          </button>
        </div>
      </header>

      {stream.remote_changed_at && (
        <div className="conflict" role="alert">
          <b>Keitaro changed while you were editing</b> (
          {new Date(stream.remote_changed_at).toLocaleString()}). Your draft was made on an older
          version: check the shares below, then confirm or cancel the draft.
          <div className="actions">
            <button disabled={busy} onClick={() => run(() => api.acknowledge(stream.id))}>
              Draft is still right
            </button>
          </div>
        </div>
      )}

      {showHistory && <HistoryPanel streamId={stream.id} busy={busy} run={run} />}

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
            <th>Stats</th>
            <th>Trends</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {stream.offers.map((o) => (
            <OfferRow key={o.id} offer={o} stats={offerStats.get(o.offer_id)} busy={busy} run={run} />
          ))}
          {stream.offers.length === 0 && (
            <tr>
              <td colSpan={5} className="muted">
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
  stats?: OfferStats
  busy: boolean
  run: (action: () => Promise<Stream>) => void
}

function OfferRow({ offer: o, stats, busy, run }: RowProps) {
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
      <td className="stats">
        {stats ? (
          <>
            <b>{stats.clicks}</b> clicks · <b>{stats.conversions}</b> conv
            <br />
            <span className="muted">
              CR {stats.cr}% · EPC {stats.epc.toFixed(2)} · rev {stats.revenue.toFixed(2)}
            </span>
          </>
        ) : (
          <span className="muted">no clicks</span>
        )}
      </td>
      <td>{stats && <Sparkline values={stats.daily_clicks} label={`Daily clicks for offer ${o.offer_id}`} />}</td>
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
