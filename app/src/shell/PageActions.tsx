// Lets a page put buttons in the topbar's right slot: `<PageActions><Button…/></PageActions>`.
import { createContext, useContext, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

export const PageActionsSlotContext = createContext<HTMLElement | null>(null)

export function PageActions({ children }: { children: ReactNode }) {
  const slot = useContext(PageActionsSlotContext)
  return slot ? createPortal(children, slot) : null
}
