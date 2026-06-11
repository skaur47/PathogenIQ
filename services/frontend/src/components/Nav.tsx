import { NavLink, useLocation } from 'react-router-dom'

const links = [
  { to: '/', label: 'Home' },
  { to: '/news', label: 'Current News' },
  { to: '/research', label: 'Research' },
  { to: '/graph', label: 'Knowledge Graph' },
  { to: '/trends', label: 'Pathogen Trends' },
  { to: '/about', label: 'About' },
  { to: '/contact', label: 'Contact' },
]

export function Nav() {
  const location = useLocation()

  return (
    <header className="fixed top-0 inset-x-0 z-40 h-16 border-b border-white/5 bg-bg/95 backdrop-blur-md">
      <div className="mx-auto max-w-7xl h-full px-6 flex items-center justify-between">
        {/* Logo */}
        <NavLink to="/" className="flex items-center gap-2.5 group">
          <div className="w-8 h-8 rounded-lg bg-accent/10 border border-accent/30 flex items-center justify-center group-hover:bg-accent/20 transition-colors">
            <span className="text-accent font-bold text-xs tracking-tight">PIQ</span>
          </div>
          <span className="font-semibold text-slate-100 text-sm tracking-wide">
            PathogenIQ
          </span>
        </NavLink>

        {/* Links */}
        <nav className="flex items-center gap-1">
          {links.map(({ to, label }) => {
            const isActive =
              to === '/' ? location.pathname === '/' : location.pathname.startsWith(to)
            return (
              <NavLink
                key={to}
                to={to}
                className={[
                  'px-3.5 py-1.5 rounded-md text-sm font-medium transition-all',
                  isActive
                    ? 'text-accent bg-accent/10'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-white/5',
                ].join(' ')}
              >
                {label}
              </NavLink>
            )
          })}
        </nav>
      </div>
    </header>
  )
}
