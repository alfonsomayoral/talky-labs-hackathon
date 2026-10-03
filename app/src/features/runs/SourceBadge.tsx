import type { ReactNode } from 'react'
import { BookCheck, Server, Upload } from 'lucide-react'
import { Badge } from '@/components'
import type { RunSource } from '@/domain/types'
import { RUN_SOURCE } from './taskMeta'

const SOURCE_ICON: Record<RunSource, ReactNode> = { golden: <BookCheck />, import: <Upload />, api: <Server /> }

export function SourceBadge({ source }: { source: RunSource }) {
  return (
    <Badge variant="outline" icon={SOURCE_ICON[source]} title={RUN_SOURCE[source].description}>
      {RUN_SOURCE[source].label}
    </Badge>
  )
}
