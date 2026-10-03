// Shell-only UI state: which global overlays are open.
import { create } from 'zustand'

interface ShellUiState {
  paletteOpen: boolean
  helpOpen: boolean
  setPaletteOpen: (open: boolean) => void
  togglePalette: () => void
  setHelpOpen: (open: boolean) => void
}

export const useShellUi = create<ShellUiState>((set) => ({
  paletteOpen: false,
  helpOpen: false,
  setPaletteOpen: (paletteOpen) => set({ paletteOpen }),
  togglePalette: () => set((s) => ({ paletteOpen: !s.paletteOpen, helpOpen: false })),
  setHelpOpen: (helpOpen) => set({ helpOpen }),
}))
