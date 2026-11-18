import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Link, useParams } from 'react-router-dom'
import { ApiError, api } from '../api'
import { StreamCard } from '../components/StreamCard'

export function EditorPage() {
  const id = Number(useParams().id)
  const queryClient = useQueryClient()
  const meta = useQuery({ queryKey: ['meta'], queryFn: api.meta, staleTime: Infinity })

  const campaign = useQuery({
    queryKey: ['campaign', id],
    queryFn: () => api.getCampaign(id),
    retry: (count, error) => !(error instanceof ApiError && error.status === 404) && count < 2,
  })

  const fetchStreams = useMutation({
    mutationFn: () => api.fetchCampaign(id),
    onSuccess: (data) => queryClient.setQueryData(['campaign', id], data),
  })

  // First visit: the campaign is not in our DB yet, import it from Keitaro.
  const notFetched = campaign.error instanceof ApiError && campaign.error.status === 404
  const { mutate, isIdle } = fetchStreams
  useEffect(() => {
    if (notFetched && isIdle) mutate()
  }, [notFetched, isIdle, mutate])

  const data = campaign.data
  const dirty = data?.streams.some((s) => s.is_dirty)

  return (
    <div>
      <nav className="breadcrumbs">
        <Link to="/">Campaigns</Link> / {data?.name ?? `#${id}`}
      </nav>

      <div className="toolbar">
        <button
          disabled={fetchStreams.isPending}
          onClick={() => {
            if (!dirty || confirm('Unpublished changes stay as drafts. Fetch anyway?')) fetchStreams.mutate()
          }}
        >
          {fetchStreams.isPending ? 'Fetching…' : 'Fetch streams from Keitaro'}
        </button>
        {meta.data && (
          <a className="button" href={`${meta.data.keitaro_admin_url}/#!/campaigns/${id}`} target="_blank" rel="noreferrer">
            View in Keitaro ↗
          </a>
        )}
        {data?.fetched_at && <span className="muted">Last fetched {new Date(data.fetched_at).toLocaleString()}</span>}
      </div>

      {fetchStreams.error && <p className="error">{fetchStreams.error.message}</p>}
      {campaign.error && !notFetched && <p className="error">{campaign.error.message}</p>}
      {(campaign.isPending || (notFetched && !fetchStreams.error)) && <p className="muted">Loading…</p>}

      {data && (
        <>
          <h1>
            {data.name} <span className="muted">#{data.id}</span>
          </h1>
          {data.streams.length === 0 && <p className="muted">This campaign has no streams.</p>}
          {data.streams.map((stream) => (
            <StreamCard key={stream.id} stream={stream} />
          ))}
        </>
      )}
    </div>
  )
}
