import { useQuery } from '@tanstack/react-query'
import { api } from './api'

/** The signed-in user and role; until known, assume publishing is allowed (the API decides). */
export function useMe() {
  const me = useQuery({ queryKey: ['me'], queryFn: api.me, staleTime: Infinity })
  return {
    user: me.data?.user ?? null,
    canPublish: me.data ? me.data.role === 'publisher' : true,
  }
}
