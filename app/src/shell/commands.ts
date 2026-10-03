// ⌘K command registry. The shell ships navigation commands; features add providers
// (e.g. entity search in phase 4) with `registerCommandProvider`.
import type { ReactNode } from 'react'
import type { NavigateFunction } from 'react-router'

export interface CommandContext {
  navigate: NavigateFunction
  /** Opens the item peek panel (`?item=`) on the current page. */
  openItem: (itemId: string) => void
}

export interface Command {
  /** Unique across providers, e.g. `doc:API004128`. */
  id: string
  label: string
  /** Group heading in the palette. Default «Resultados». */
  group?: string
  /** Right-aligned secondary text (entity type, company, amount). */
  hint?: string
  icon?: ReactNode
  /** Extra search terms for the built-in filter (ids, synonyms). */
  keywords?: string[]
  /** Shown as keys, e.g. `['G', 'R']`. */
  shortcut?: string[]
  run: (ctx: CommandContext) => void
}

/**
 * Called on every query change (also with `''` when the palette opens).
 * Return already-filtered results; the palette shows them as they come, newest query wins.
 */
export type CommandProvider = (query: string) => Command[] | Promise<Command[]>

const providers = new Set<CommandProvider>()
const listeners = new Set<() => void>()
let version = 0

function emit() {
  version++
  for (const l of listeners) l()
}

/** Adds a provider; returns the function that removes it. */
export function registerCommandProvider(provider: CommandProvider): () => void {
  providers.add(provider)
  emit()
  return () => {
    if (providers.delete(provider)) emit()
  }
}

export function getCommandProviders(): CommandProvider[] {
  return [...providers]
}

export function subscribeCommandProviders(listener: () => void): () => void {
  listeners.add(listener)
  return () => {
    listeners.delete(listener)
  }
}

export function getCommandProvidersVersion(): number {
  return version
}
