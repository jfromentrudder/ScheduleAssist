import { useCallback, useEffect, useRef, useState } from 'react'
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'

import { useAuth } from './auth/useAuth'

/** Chrome shared by every signed-in page.
 *
 * The schedule is the app, so it keeps its place in the bar. Everything about
 * the account behind it — who you are, how it behaves, leaving — collapses into
 * one menu, which stops the bar growing a new link every time a settings page
 * is added. */
export function Layout() {
  const { signOut } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const [open, setOpen] = useState(false)
  const [leaving, setLeaving] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const buttonRef = useRef<HTMLButtonElement>(null)

  const close = useCallback(() => setOpen(false), [])

  // Navigating is a decision already made; leaving the menu hanging over the
  // new page reads as a bug.
  useEffect(close, [location.pathname, close])

  useEffect(() => {
    if (!open) return

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return
      close()
      // Dismissing with the keyboard should leave focus somewhere useful,
      // rather than on an element that no longer exists.
      buttonRef.current?.focus()
    }
    const onPointerDown = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) close()
    }

    document.addEventListener('keydown', onKeyDown)
    document.addEventListener('mousedown', onPointerDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.removeEventListener('mousedown', onPointerDown)
    }
  }, [open, close])

  async function handleSignOut() {
    setLeaving(true)
    await signOut()
    navigate('/signin', { replace: true })
  }

  return (
    <>
      <header className="app-bar">
        <span className="brand">ScheduleAssist</span>
        <nav>
          <NavLink to="/" end>
            Schedule
          </NavLink>

          <div className="menu" ref={menuRef}>
            <button
              ref={buttonRef}
              type="button"
              className="icon-button menu-button"
              aria-label="Account menu"
              // A disclosure rather than an ARIA menu: role="menu" would
              // promise arrow-key navigation and managed focus, and a panel of
              // ordinary links that only answers to Tab is more usable than a
              // half-kept promise of the real pattern.
              aria-haspopup="true"
              aria-expanded={open}
              onClick={() => setOpen((was) => !was)}
            >
              {/* Three bars, drawn rather than typed: the ☰ glyph is missing
                  from enough fonts to render as a box. */}
              <span className="menu-bars" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
            </button>

            {open && (
              <div className="menu-panel">
                {/* Closed explicitly as well as on navigation: choosing the
                    page you are already on changes no route, so nothing else
                    would dismiss the panel. */}
                <NavLink to="/account" className="menu-item" onClick={close}>
                  Account
                </NavLink>
                <NavLink to="/settings" className="menu-item" onClick={close}>
                  Settings
                </NavLink>
                <hr />
                <button
                  type="button"
                  className="menu-item"
                  disabled={leaving}
                  onClick={() => void handleSignOut()}
                >
                  {leaving ? 'Signing out…' : 'Sign out'}
                </button>
              </div>
            )}
          </div>
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
    </>
  )
}
