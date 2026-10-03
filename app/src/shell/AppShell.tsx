// Placeholder shell — phase 1.A replaces it (sidebar, topbar, PeekHost, ⌘K).
import { NavLink, Outlet } from 'react-router'
import { NAV } from '@/app/nav'

export default function AppShell() {
  return (
    <div style={{ display: 'flex', minHeight: '100vh' }}>
      <nav style={{ width: 232 }}>
        {NAV.flatMap((s) => s.entries).map((e) => (
          <div key={e.to}>
            <NavLink to={e.to}>{e.label}</NavLink>
          </div>
        ))}
      </nav>
      <main style={{ flex: 1 }}>
        <Outlet />
      </main>
    </div>
  )
}
