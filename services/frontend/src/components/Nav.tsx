import { useState } from 'react'
import { NavLink, useLocation } from 'react-router-dom'
import { Menu, X } from 'lucide-react'

const links = [
  { to: '/', label: 'Home' },
  { to: '/news', label: 'Current News' },
  { to: '/research', label: 'Research' },
  { to: '/graph', label: 'Knowledge Graph' },
  { to: '/trends', label: 'Pathogen Trends' },
  { to: '/about', label: 'About' },
  { to: '/contact', label: 'Contact' },
]

function PathogenLogo() {
  return (
    <svg viewBox="0 0 32 32" fill="none" className="w-7 h-7 text-accent" aria-hidden>
      <circle cx="16" cy="16" r="6" fill="currentColor" fillOpacity="0.12" stroke="currentColor" strokeWidth="1.5"/>
      <circle cx="16" cy="16" r="2.5" fill="currentColor"/>
      <line x1="16" y1="10" x2="16" y2="5.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="16" y1="22" x2="16" y2="26.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="10" y1="16" x2="5.5" y2="16" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="22" y1="16" x2="26.5" y2="16" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="20.24" y1="11.76" x2="23.54" y2="8.46" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="11.76" y1="20.24" x2="8.46" y2="23.54" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="11.76" y1="11.76" x2="8.46" y2="8.46" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
      <line x1="20.24" y1="20.24" x2="23.54" y2="23.54" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  )
}

export function Nav() {
  const location = useLocation()
  const [open, setOpen] = useState(false)

  return (
    <header className="fixed top-0 inset-x-0 z-40 h-16 border-b border-white/5 bg-bg/95 backdrop-blur-md">
      <div className="mx-auto max-w-7xl h-full px-6 flex items-center justify-between">
        {/* Logo */}
        <NavLink to="/" className="flex items-center gap-2.5" onClick={() => setOpen(false)}>
          <PathogenLogo />
          <span className="font-semibold text-slate-100 text-sm tracking-wide">PathogenIQ</span>
        </NavLink>

        {/* Desktop links */}
        <nav className="hidden md:flex items-center gap-1">
          {links.map(({ to, label }) => {
            const isActive = to === '/' ? location.pathname === '/' : location.pathname.startsWith(to)
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

        {/* Mobile hamburger */}
        <button
          className="md:hidden p-2 rounded-md text-slate-400 hover:text-white hover:bg-white/5 transition-colors"
          onClick={() => setOpen(o => !o)}
          aria-label="Toggle menu"
        >
          {open ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
        </button>
      </div>

      {/* Mobile dropdown */}
      {open && (
        <div className="md:hidden border-t border-white/5 bg-bg backdrop-blur-md">
          <nav className="px-4 py-3 flex flex-col gap-1">
            {links.map(({ to, label }) => {
              const isActive = to === '/' ? location.pathname === '/' : location.pathname.startsWith(to)
              return (
                <NavLink
                  key={to}
                  to={to}
                  onClick={() => setOpen(false)}
                  className={[
                    'px-3.5 py-2.5 rounded-md text-sm font-medium transition-all',
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
      )}
    </header>
  )
}
