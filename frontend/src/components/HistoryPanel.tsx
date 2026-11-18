import { useQuery } from '@tanstack/react-query'
import { api, type SnapshotOffer, type Stream } from '../api'

interface Props {
  streamId: number
  busy: boolean
  run: (action: () => Promise<Stream>) => void
}

/** Past "Push to Keitaro" runs of a stream; any of them can be loaded back as a draft. */
export function HistoryPanel({ streamId, busy, run }: Props) {
  const history = useQuery({ queryKey: ['history', streamId], queryFn: () => api.history(streamId) })

  if (history.error) return <p className="error">{history.error.message}</p>
  if (history.isPending) return <p className="muted">Loading history…</p>
  if (history.data.length === 0) return <p className="muted">Nothing has been published from here yet.</p>

  return (
    <ol className="history" aria-label="Publish history">
      {history.data.map((entry) => (
        <li key={entry.id}>
          <div className="history-head">
            <span>
              {new Date(entry.created_at).toLocaleString()}
              {entry.actor && <span className="muted"> · {entry.actor}</span>}
            </span>
            <span className="actions">
              <button
                disabled={busy}
                title="Load the state from before this push as a draft"
                onClick={() => run(() => api.restore(streamId, entry.id, 'before'))}
              >
                Undo
              </button>
              <button
                disabled={busy}
                title="Load the result of this push as a draft"
                onClick={() => run(() => api.restore(streamId, entry.id))}
              >
                Restore
              </button>
            </span>
          </div>
          <Offers label="before" offers={entry.before} />
          <Offers label="after" offers={entry.after} />
        </li>
      ))}
    </ol>
  )
}

function Offers({ label, offers }: { label: string; offers: SnapshotOffer[] }) {
  return (
    <div className="history-offers">
      <span className="muted">{label}:</span>{' '}
      {offers.length === 0
        ? 'no offers'
        : offers.map((o) => `#${o.offer_id} ${o.share}%${o.state === 'disabled' ? ' (disabled)' : ''}`).join(', ')}
    </div>
  )
}
