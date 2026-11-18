import { useQuery } from '@tanstack/react-query'
import { useEffect, useId, useState } from 'react'
import { api, type Named } from '../api'

function useDebounced<T>(value: T, ms: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return debounced
}

interface Props {
  value: Named | null
  onChange: (offer: Named | null) => void
  placeholder?: string
  inputId?: string
}

/** Offer autocomplete: searches Keitaro offers by ID or name as you type. */
export function OfferSearch({ value, onChange, placeholder = 'Search offer by ID or name', inputId }: Props) {
  const [text, setText] = useState(value ? label(value) : '')
  const [open, setOpen] = useState(false)
  const [highlight, setHighlight] = useState(0)
  const query = useDebounced(text.trim(), 250)
  const listId = useId()

  // Reset the field when the parent clears the selection (e.g. after "Add").
  const [prevValue, setPrevValue] = useState(value)
  if (value !== prevValue) {
    setPrevValue(value)
    if (value === null && prevValue !== null) setText('')
  }

  const { data: offers = [], isFetching, error } = useQuery({
    queryKey: ['offers', query],
    queryFn: () => api.searchOffers(query),
    enabled: open,
    staleTime: 30_000,
  })

  const select = (offer: Named) => {
    onChange(offer)
    setText(label(offer))
    setOpen(false)
  }

  return (
    <div className="combobox">
      <input
        id={inputId}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        autoComplete="off"
        value={text}
        placeholder={placeholder}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        onChange={(e) => {
          setText(e.target.value)
          setOpen(true)
          setHighlight(0)
          if (value) onChange(null)
        }}
        onKeyDown={(e) => {
          if (!open || offers.length === 0) return
          if (e.key === 'ArrowDown') {
            e.preventDefault()
            setHighlight((h) => Math.min(h + 1, offers.length - 1))
          } else if (e.key === 'ArrowUp') {
            e.preventDefault()
            setHighlight((h) => Math.max(h - 1, 0))
          } else if (e.key === 'Enter') {
            e.preventDefault()
            select(offers[Math.min(highlight, offers.length - 1)])
          } else if (e.key === 'Escape') {
            setOpen(false)
          }
        }}
      />
      {open && (
        <ul className="combobox-list" id={listId} role="listbox">
          {error ? (
            <li className="combobox-empty">Could not load offers: {error.message}</li>
          ) : offers.length === 0 ? (
            <li className="combobox-empty">{isFetching ? 'Searching…' : 'No offers found'}</li>
          ) : (
            offers.map((offer, i) => (
              <li
                key={offer.id}
                role="option"
                aria-selected={i === highlight}
                className={i === highlight ? 'active' : undefined}
                onMouseDown={(e) => {
                  e.preventDefault()
                  select(offer)
                }}
                onMouseEnter={() => setHighlight(i)}
              >
                <span className="muted">#{offer.id}</span> {offer.name}
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  )
}

function label(offer: Named) {
  return `#${offer.id} ${offer.name}`
}
