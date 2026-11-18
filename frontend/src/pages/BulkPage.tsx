import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link } from 'react-router'
import { api, type BulkChange, type BulkOutcome, type Meta, type Named, type OfferShare } from '../api'
import { OfferSearch } from '../components/OfferSearch'
import { useMe } from '../useMe'

const key = (c: { campaign_id: number; stream_id: number }) => `${c.campaign_id}:${c.stream_id}`

export function BulkPage() {
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: Infinity })
  return (
    <section className="card">
      <h2>Replace an offer in many campaigns</h2>
      <p className="muted">
        Preview first: nothing changes until you pick streams and apply. Applying as drafts lets
        you review each stream in its editor before publishing.
      </p>
      {meta.error && <p className="error">{meta.error.message}</p>}
      {meta.data && <BulkForm meta={meta.data} />}
    </section>
  )
}

export function BulkForm({ meta }: { meta: Meta }) {
  const { canPublish } = useMe()
  const [groupId, setGroupId] = useState(meta.default_group_id ?? 0)
  // Defaults to our own prefix so we never touch someone else's campaigns by accident.
  const [nameFilter, setNameFilter] = useState(meta.campaign_prefix)
  const [from, setFrom] = useState<Named | null>(null)
  const [to, setTo] = useState<Named | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [outcomes, setOutcomes] = useState<Map<string, BulkOutcome>>(new Map())

  const preview = useMutation({
    mutationFn: () =>
      api.bulkPreview({ group_id: groupId, from_offer_id: from!.id, to_offer_id: to!.id, name_filter: nameFilter }),
    onSuccess: (data) => {
      setSelected(new Set(data.changes.map(key)))
      setOutcomes(new Map())
    },
  })
  const apply = useMutation({
    mutationFn: (publish: boolean) =>
      api.bulkApply({
        from_offer_id: from!.id,
        to_offer_id: to!.id,
        publish,
        targets: (preview.data?.changes ?? [])
          .filter((c) => selected.has(key(c)))
          .map(({ campaign_id, stream_id }) => ({ campaign_id, stream_id })),
      }),
    onSuccess: (data) => setOutcomes(new Map(data.map((o) => [key(o), o]))),
  })

  const ready = groupId > 0 && from !== null && to !== null && from.id !== to.id
  const changes = preview.data?.changes ?? []

  return (
    <>
      <form
        className="form"
        onSubmit={(e) => {
          e.preventDefault()
          if (ready) preview.mutate()
        }}
      >
        <label htmlFor="bulk-group">Group</label>
        <select id="bulk-group" value={groupId || ''} onChange={(e) => setGroupId(Number(e.target.value))}>
          <option value="" disabled>
            Choose…
          </option>
          {meta.groups.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name}
            </option>
          ))}
        </select>
        <label htmlFor="bulk-filter">Name has</label>
        <input id="bulk-filter" value={nameFilter} onChange={(e) => setNameFilter(e.target.value)} placeholder="any campaign" />
        <label htmlFor="bulk-from">Replace</label>
        <OfferSearch inputId="bulk-from" value={from} onChange={setFrom} />
        <label htmlFor="bulk-to">With</label>
        <OfferSearch inputId="bulk-to" value={to} onChange={setTo} />
        <div />
        <div>
          {from && to && from.id === to.id && <p className="error">Choose two different offers.</p>}
          <button className="primary" type="submit" disabled={!ready || preview.isPending}>
            {preview.isPending ? 'Scanning campaigns…' : 'Preview'}
          </button>
        </div>
      </form>

      {preview.error && <p className="error">{preview.error.message}</p>}
      {preview.data && (
        <div className="bulk-results">
          <p>
            Scanned {preview.data.scanned_campaigns} campaign(s), {changes.length} stream(s) use offer #{from?.id}.
          </p>
          {preview.data.errors.map((e) => (
            <p key={e} className="error">
              {e}
            </p>
          ))}
          {changes.length > 0 && (
            <>
              <table>
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        aria-label="Select all"
                        checked={selected.size === changes.length}
                        onChange={(e) => setSelected(new Set(e.target.checked ? changes.map(key) : []))}
                      />
                    </th>
                    <th>Campaign / stream</th>
                    <th>Before → after</th>
                    <th>Result</th>
                  </tr>
                </thead>
                <tbody>
                  {changes.map((c) => (
                    <ChangeRow
                      key={key(c)}
                      change={c}
                      checked={selected.has(key(c))}
                      outcome={outcomes.get(key(c))}
                      onToggle={(on) => {
                        const next = new Set(selected)
                        if (on) next.add(key(c))
                        else next.delete(key(c))
                        setSelected(next)
                      }}
                    />
                  ))}
                </tbody>
              </table>
              {apply.error && <p className="error">{apply.error.message}</p>}
              <div className="actions bulk-actions">
                <button disabled={selected.size === 0 || apply.isPending} onClick={() => apply.mutate(false)}>
                  Apply as drafts ({selected.size})
                </button>
                <button
                  className="primary"
                  disabled={selected.size === 0 || apply.isPending || !canPublish}
                  title={canPublish ? undefined : 'Only publishers can push to Keitaro'}
                  onClick={() => {
                    if (confirm(`Publish the replacement to ${selected.size} stream(s) in Keitaro?`)) apply.mutate(true)
                  }}
                >
                  Apply and publish
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </>
  )
}

function ChangeRow(props: {
  change: BulkChange
  checked: boolean
  outcome?: BulkOutcome
  onToggle: (on: boolean) => void
}) {
  const { change: c, outcome } = props
  return (
    <tr>
      <td>
        <input
          type="checkbox"
          aria-label={`Select stream ${c.stream_id}`}
          checked={props.checked}
          onChange={(e) => props.onToggle(e.target.checked)}
        />
      </td>
      <td>
        <Link to={`/campaigns/${c.campaign_id}`}>{c.campaign_name}</Link>
        <br />
        <span className="muted">
          {c.stream_name} #{c.stream_id}
        </span>
      </td>
      <td className="stats">
        {shares(c.before)} → <b>{shares(c.after)}</b>
      </td>
      <td>
        {outcome && (
          <span className={outcome.status === 'error' ? 'error' : 'badge pending_add'}>
            {outcome.status}
            {outcome.detail && `: ${outcome.detail}`}
          </span>
        )}
      </td>
    </tr>
  )
}

const shares = (list: OfferShare[]) => list.map((o) => `#${o.offer_id} ${o.share}%`).join(', ')
