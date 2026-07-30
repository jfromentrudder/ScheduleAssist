import { NavLink, Outlet } from 'react-router-dom'

/** Chrome shared by every signed-in page. */
export function Layout() {
  return (
    <>
      <header className="app-bar">
        <span className="brand">ScheduleAssist</span>
        <nav>
          <NavLink to="/" end>
            Schedule
          </NavLink>
          <NavLink to="/account">Account</NavLink>
        </nav>
      </header>
      <main>
        <Outlet />
      </main>
    </>
  )
}
