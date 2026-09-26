import { Outlet, Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { Home, LayoutDashboard, Route as RouteIcon, FileText, UserCircle, Search, LogOut } from 'lucide-react'

const navItems = [
  { label: 'Home', icon: Home, path: '/home' },
  { label: 'Find Roles', icon: Search, path: '/jobs' },
  { label: 'My Applications', icon: FileText, path: '/applications' },
  { label: 'Career Pathway', icon: RouteIcon, path: '/pathway' },
  { label: 'Future of Work', icon: LayoutDashboard, path: '/dashboard' },
  { label: 'Profile', icon: UserCircle, path: '/profile' },
]


export default function Layout() {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, logout } = useAuth()

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="min-h-screen flex">
      {/* Sidebar */}
      <aside className="w-64 bg-slate-900 text-white flex flex-col">
        <div className="p-6">
          <p className="text-2xl font-bold tracking-tight">
            <span className="text-indigo-400">In</span>site
          </p>
          <p className="text-xs text-slate-400 mt-1">Career planning for any field</p>
        </div>
        <nav className="flex-1 px-3">
          {navItems.map((item) => {
            const isActive =
              location.pathname === item.path ||
              location.pathname.startsWith(item.path + '/')
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg mb-1 text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-indigo-600 text-white'
                    : 'text-slate-300 hover:bg-slate-800 hover:text-white'
                }`}
              >
                <item.icon className="w-5 h-5" />
                {item.label}
              </Link>
            )
          })}
        </nav>
        <div className="p-4 border-t border-slate-700">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-indigo-500 flex items-center justify-center">
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
              onClick={handleLogout}
              title="Sign out"
              className="text-slate-400 hover:text-white"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-auto">
        <Outlet />
      </main>
    </div>
  )
}
