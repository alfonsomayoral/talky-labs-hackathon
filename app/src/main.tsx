import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter } from 'react-router'
import { RouterProvider } from 'react-router/dom'
import { LucideProvider } from 'lucide-react'
import { routes } from '@/app/routes'
import { Toaster } from '@/components/Toaster/Toaster'
import '@/design/fonts'
import '@/design/global.css'

const router = createBrowserRouter(routes)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    {/* Icons: 16px, 1.5 stroke (PLAN §2.2) */}
    <LucideProvider size={16} strokeWidth={1.5}>
      <RouterProvider router={router} />
      <Toaster />
    </LucideProvider>
  </StrictMode>,
)
