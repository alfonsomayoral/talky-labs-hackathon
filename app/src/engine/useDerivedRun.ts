// Glue between the data stores and the engine (phase 1.C implements it).
// Frozen contract: views call this hook to get everything derived for the active dataset + run.
import type { DerivedRun } from '@/domain/types'

export interface DerivedRunState {
  data: DerivedRun | null
  status: 'idle' | 'loading' | 'ready' | 'error'
  error: string | null
}

export function useDerivedRun(): DerivedRunState {
  return { data: null, status: 'idle', error: null }
}
