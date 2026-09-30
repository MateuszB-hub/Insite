import { useEffect, useRef, useState } from 'react'
import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Home, LayoutDashboard, Route as RouteIcon, FileText, UserCircle, Search, LogOut, Menu, X } from 'lucide-react'

const navItems = [
  { label: 'Home', icon: Home, path: '/home' },
  { label: 'Find Roles', icon: Search, path: '/jobs' },
  { label: 'My Applications', icon: FileText, path: '/applications' },
  { label: 'Career Pathway', icon: RouteIcon, path: '/pathway' },
  { label: 'Future of Work', icon: LayoutDashboard, path: '/dashboard' },
  { label: 'Profile', icon: UserCircle, path: '/profile' },
]

function Logo() {
  return (
    <p className="text-2xl font-bold tracking-tight">
      <span className="text-indigo-400">In</span>site
    </p>
  )
}

/** The menu and account strip: in the sidebar on wide screens, in the slide-over on narrow ones. */
function NavContents({ onSignOut }: { onSignOut: () => void }) {
  const location = useLocation()
  const { user } = useAuth()
  return (
    <>
      <nav className="flex-1 px-3" aria-label="Main">
        {navItems.map((item) => {
          const isActive =
            location.pathname === item.path ||
            location.pathname.startsWith(item.path + '/')
          return (
            <Link
              key={item.path}
              to={item.path}
              aria-current={isActive ? 'page' : undefined}
              className={`flex items-center gap-3 px-3 py-2.5 rounded-lg mb-1 text-sm font-medium transition-colors ${
                isActive
                  ? 'bg-indigo-600 text-white'
                  : 'text-slate-300 hover:bg-slate-800 hover:text-white'
              }`}
            >
              <item.icon className="w-5 h-5" aria-hidden="true" />
              {item.label}
            </Link>
          )
        })}
      </nav>
      <div className="p-4 border-t border-slate-700">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-full bg-indigo-500 flex items-center justify-center" aria-hidden="true">
            <UserCircle className="w-4 h-4" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">
              {user?.full_name || 'Applicant'}
            </p>
            <p className="text-xs text-slate-400 truncate">{user?.email}</p>
          </div>
          <button
            type="button"
            onClick={onSignOut}
            title="Sign out"
            aria-label="Sign out"
            className="text-slate-400 hover:text-white p-1 rounded focus-visible:outline focus-visible:outline-2 focus-visible:outline-white"
          >
            <LogOut className="w-4 h-4" aria-hidden="true" />
          </button>
        </div>
      </div>
    </>
  )
}

export default function Layout() {
  const location = useLocation()
  const navigate = useNavigate()
  const { logout } = useAuth()
  // Below 1024px the sidebar took 256px of a 390px phone; there it's a menu
  // button and a slide-over instead.
  const [menuOpen, setMenuOpen] = useState(false)
  const menuButton = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLDivElement>(null)

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const closeMenu = () => {
    setMenuOpen(false)
    menuButton.current?.focus()
  }

  // Picking a page closes the menu.
  useEffect(() => { setMenuOpen(false) }, [location.pathname])

  // While open: Escape closes, focus starts inside and stays there.
  useEffect(() => {
    if (!menuOpen) return
    panel.current?.querySelector<HTMLElement>('a, button')?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeMenu()
      if (e.key !== 'Tab' || !panel.current) return
      const focusable = panel.current.querySelectorAll<HTMLElement>('a, button')
      const first = focusable[0], last = focusable[focusable.length - 1]
      if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus() }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus() }
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [menuOpen])

  return (
    <div className="min-h-screen lg:flex">
      <a href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:bg-white focus:text-indigo-800 focus:px-3 focus:py-2 focus:rounded-lg focus:shadow">
        Skip to main content
      </a>

      {/* Wide screens: the sidebar */}
      <aside className="hidden lg:flex w-64 shrink-0 bg-slate-900 text-white flex-col">
        <div className="p-6">
          <Logo />
          <p className="text-xs text-slate-400 mt-1">Career planning for any field</p>
        </div>
        <NavContents onSignOut={handleLogout} />
      </aside>

      {/* Narrow screens: a top bar and a slide-over menu */}
      <header className="lg:hidden sticky top-0 z-30 bg-slate-900 text-white flex items-center justify-between px-4 h-14">
        <Logo />
        <button
          ref={menuButton}
          type="button"
          onClick={() => setMenuOpen(true)}
          aria-label="Open menu"
          aria-expanded={menuOpen}
          aria-controls="mobile-menu"
          className="p-2 -mr-2 rounded-lg text-slate-200 hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white"
        >
          <Menu className="w-6 h-6" aria-hidden="true" />
        </button>
      </header>
      {menuOpen && (
        <div className="lg:hidden fixed inset-0 z-40">
          <button type="button" aria-label="Close menu" tabIndex={-1}
            className="absolute inset-0 bg-slate-900/60" onClick={closeMenu} />
          <div ref={panel} id="mobile-menu" role="dialog" aria-modal="true" aria-label="Menu"
            className="absolute inset-y-0 left-0 w-72 max-w-[85vw] bg-slate-900 text-white flex flex-col shadow-xl">
            <div className="p-4 flex items-center justify-between">
              <Logo />
              <button type="button" onClick={closeMenu} aria-label="Close menu"
                className="p-2 rounded-lg text-slate-200 hover:bg-slate-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-white">
                <X className="w-5 h-5" aria-hidden="true" />
              </button>
            </div>
            <NavContents onSignOut={handleLogout} />
          </div>
        </div>
      )}

      <main id="main" tabIndex={-1} className="flex-1 min-w-0 overflow-auto focus:outline-none">
        <Outlet />
      </main>
    </div>
  )
}
