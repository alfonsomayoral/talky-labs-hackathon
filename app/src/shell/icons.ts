// lucide icons referenced by name in app/nav.ts. Unknown names fall back to a plain circle.
import {
  Activity,
  CalendarCheck,
  Circle,
  Database,
  FileText,
  Gauge,
  GitCompare,
  HandCoins,
  Inbox,
  Landmark,
  LayoutDashboard,
  Network,
  PackageCheck,
  Play,
  Receipt,
  Scale,
  Settings,
  Sparkles,
  type LucideIcon,
} from 'lucide-react'

const NAV_ICONS: Record<string, LucideIcon> = {
  Activity,
  CalendarCheck,
  Database,
  FileText,
  Gauge,
  GitCompare,
  HandCoins,
  Inbox,
  Landmark,
  LayoutDashboard,
  Network,
  PackageCheck,
  Play,
  Receipt,
  Scale,
  Settings,
  Sparkles,
}

export function navIcon(name: string): LucideIcon {
  return NAV_ICONS[name] ?? Circle
}
