// Dev-only Vite middleware that serves local dataset folders under /__data/<id>/…
// and run bundles under /__runs/<id>/… (phase 1.B implements it).
import type { Plugin } from 'vite'

export interface KalmoraDataOptions {
  /** `dev:../../participant/phase_dev,test:../../participant-2/phase_test` */
  datasets?: string
  /** Folder that contains run bundles, e.g. `../runs`. */
  runs?: string
}

export function kalmoraData(_options: KalmoraDataOptions = {}): Plugin {
  return { name: 'kalmora-data', apply: 'serve' }
}
