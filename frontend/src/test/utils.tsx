import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import type { ReactNode } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { vi } from 'vitest'

export function renderWithProviders(ui: ReactNode, client = new QueryClient({
  defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
})) {
  return {
    client,
    ...render(
      <QueryClientProvider client={client}>
        <MemoryRouter>{ui}</MemoryRouter>
      </QueryClientProvider>,
    ),
  }
}

type Handler = (url: string, init: RequestInit) => unknown

/** Mock `fetch`: `routes` maps "METHOD /path" to a JSON body or a handler. */
export function mockFetch(routes: Record<string, unknown | Handler>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init = {}) => {
    const url = String(input)
    const key = `${init.method ?? 'GET'} ${url.split('?')[0]}`
    if (!(key in routes)) throw new Error(`Unexpected request: ${key}`)
    const route = routes[key]
    const body = typeof route === 'function' ? (route as Handler)(url, init) : route
    if (body instanceof Response) return body
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { 'Content-Type': 'application/json' },
    })
  })
}
