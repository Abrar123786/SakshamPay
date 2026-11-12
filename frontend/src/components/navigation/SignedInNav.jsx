import { Menu, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { NavLink, useLocation } from 'react-router'

import { useAuth } from '../../context/authContext'
import { cx } from '../../utils/cx'
import Button from '../ui/Button'
import { SIGNED_IN_NAV_ITEMS } from './navItems'

const MENU_ID = 'signed-in-menu'

function desktopLinkClass({ isActive }) {
  return cx(
    'inline-flex h-9 items-center rounded-md px-3 text-sm font-medium transition-colors',
    isActive ? 'bg-brand-soft text-brand' : 'text-ink-muted hover:bg-surface-muted hover:text-ink',
  )
}

function menuLinkClass({ isActive }) {
  return cx(
    'flex h-11 items-center rounded-md px-3 text-base font-medium transition-colors',
    isActive ? 'bg-brand-soft text-brand' : 'text-ink hover:bg-surface-muted',
  )
}

/**
 * Header navigation for signed-in users.
 *
 * From 640px: the links inline, then Sign out. Below 640px: a "Menu" disclosure
 * button that opens a panel with the same links and Sign out. The panel closes on
 * Escape (focus returns to the button), on a click outside, and after navigating.
 * The active link carries aria-current="page" (set by NavLink).
 */
export default function SignedInNav() {
  const { user, logout } = useAuth()
  const location = useLocation()
  const [openOnPath, setOpenOnPath] = useState(null)
  const open = openOnPath === location.pathname // navigating elsewhere closes the menu
  const buttonRef = useRef(null)
  const containerRef = useRef(null)

  function close({ returnFocus = false } = {}) {
    setOpenOnPath(null)
    if (returnFocus) buttonRef.current?.focus()
  }

  useEffect(() => {
    if (!open) return undefined
    const onPointerDown = (event) => {
      if (!containerRef.current?.contains(event.target)) setOpenOnPath(null)
    }
    document.addEventListener('pointerdown', onPointerDown)
    return () => document.removeEventListener('pointerdown', onPointerDown)
  }, [open])

  return (
    <>
      <div className="hidden items-center gap-1 sm:flex">
        <nav aria-label="Main">
          <ul className="flex items-center gap-1">
            {SIGNED_IN_NAV_ITEMS.map((item) => (
              <li key={item.to}>
                <NavLink to={item.to} end={item.end} className={desktopLinkClass}>
                  {item.label}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
        <span className="ml-2">
          <Button variant="secondary" size="sm" onClick={logout}>
            Sign out
          </Button>
        </span>
      </div>

      <div
        ref={containerRef}
        className="sm:hidden"
        onKeyDown={(event) => {
          if (event.key === 'Escape' && open) {
            event.stopPropagation()
            close({ returnFocus: true })
          }
        }}
      >
        <Button
          ref={buttonRef}
          variant="ghost"
          size="sm"
          leadingIcon={open ? X : Menu}
          aria-expanded={open}
          aria-controls={MENU_ID}
          onClick={() => setOpenOnPath(open ? null : location.pathname)}
        >
          Menu
        </Button>

        {open && (
          <div id={MENU_ID} className="absolute inset-x-0 top-full z-20 border-b border-line bg-surface-raised shadow-md">
            <nav aria-label="Main" className="px-4 pt-3">
              <ul className="space-y-1">
                {SIGNED_IN_NAV_ITEMS.map((item) => (
                  <li key={item.to}>
                    <NavLink to={item.to} end={item.end} className={menuLinkClass}>
                      {item.label}
                    </NavLink>
                  </li>
                ))}
              </ul>
            </nav>
            <div className="mt-3 border-t border-line px-4 py-3">
              {user?.email && <p className="mb-3 truncate px-3 text-sm text-ink-muted">Signed in as {user.email}</p>}
              <Button variant="secondary" fullWidth onClick={logout}>
                Sign out
              </Button>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
