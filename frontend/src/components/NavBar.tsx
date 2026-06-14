import { Link, useLocation } from 'react-router-dom'

// NavBar: wordmark + nav links. Version label increments with each release.
export function NavBar() {
  const { pathname } = useLocation()

  return (
    <nav className="bg-white border-b border-gray-200 px-6 py-3 flex items-center gap-8">
      <span className="font-semibold text-gray-900 text-sm tracking-tight">
        Grow Therapy <span className="text-gray-400 font-normal">· Billing Ops</span>
        <span className="ml-2 text-xs font-normal text-gray-300">v1.0</span>
      </span>
      <div className="flex items-center gap-1">
        <NavLink href="/" active={pathname === '/'}>Dashboard</NavLink>
        <NavLink href="/claims" active={pathname.startsWith('/claims')}>Worklist</NavLink>
      </div>
    </nav>
  )
}

function NavLink({ href, active, children }: { href: string; active: boolean; children: React.ReactNode }) {
  return (
    <Link
      to={href}
      className={`px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
        active
          ? 'bg-gray-100 text-gray-900'
          : 'text-gray-500 hover:text-gray-900 hover:bg-gray-50'
      }`}
    >
      {children}
    </Link>
  )
}
