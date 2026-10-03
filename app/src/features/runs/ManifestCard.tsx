// manifest.json of a run: models, tokens, cost, runtime, agent version and policies hash.
import { Amount, Card, KeyValue, Mono } from '@/components'
import type { RunManifest } from '@/domain/types'
import { formatDateTime, formatDuration, formatNumber } from '@/lib/format'
import s from './ManifestCard.module.css'

const usd = (v: number | undefined) => (v == null ? null : <Amount cents={Math.round(v * 100)} currency="USD" />)

export function ManifestCard({ manifest: m }: { manifest: RunManifest }) {
  const models = m.models ?? []
  const totalCost = m.cost_usd_total ?? (models.length ? models.reduce((n, x) => n + (x.cost_usd ?? 0), 0) : undefined)
  return (
    <Card title="Manifiesto" description={<Mono muted>{m.run_id}</Mono>}>
      <div className={s.body}>
        <KeyValue
          columns={2}
          labelWidth={120}
          items={[
            { label: 'Coste total', value: usd(totalCost) },
            { label: 'Duración', value: m.runtime_s != null ? formatDuration(m.runtime_s * 1000) : null },
            { label: 'Inicio', value: m.started_at ? formatDateTime(m.started_at) : null },
            { label: 'Fin', value: m.finished_at ? formatDateTime(m.finished_at) : null },
            { label: 'Versión del agente', value: m.agent_version ? <Mono>{m.agent_version}</Mono> : null },
            {
              label: 'Políticas (sha256)',
              value: m.policies_sha256 ? (
                <Mono title={m.policies_sha256}>{m.policies_sha256.length > 16 ? `${m.policies_sha256.slice(0, 16)}…` : m.policies_sha256}</Mono>
              ) : null,
            },
            { label: 'Correcciones humanas', value: m.human_overrides != null ? formatNumber(m.human_overrides) : null },
            { label: 'Dataset', value: m.dataset ? `${m.dataset}${m.month ? ` · ${m.month}` : ''}` : null },
          ]}
        />
        {models.length > 0 && (
          <table className={s.table}>
            <thead>
              <tr>
                <th>Modelo</th>
                <th className={s.num}>Llamadas</th>
                <th className={s.num}>Tokens de entrada</th>
                <th className={s.num}>Tokens de salida</th>
                <th className={s.num}>Coste</th>
              </tr>
            </thead>
            <tbody>
              {models.map((x) => (
                <tr key={`${x.provider}/${x.name}`}>
                  <td>
                    <Mono>{x.name}</Mono> <span className={s.provider}>{x.provider}</span>
                  </td>
                  <td className={s.num}>{formatNumber(x.calls)}</td>
                  <td className={s.num}>{formatNumber(x.input_tokens)}</td>
                  <td className={s.num}>{formatNumber(x.output_tokens)}</td>
                  <td className={s.num}>{usd(x.cost_usd)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  )
}
