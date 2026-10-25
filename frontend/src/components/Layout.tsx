import { NavLink, Outlet } from "react-router-dom";
import { useAuth } from "../auth";

export function Layout() {
  const { user, logout } = useAuth();
  return (
    <>
      <a className="skip" href="#main">
        Skip to content
      </a>
      <header className="topbar">
        <div className="topbar-in">
          <NavLink to="/" className="brand">
            <span className="logo" aria-hidden="true">
              ◉
            </span>
            On-call Runbook Copilot
          </NavLink>
          <nav aria-label="Main">
            <NavLink to="/" end>
              Incidents
            </NavLink>
            <NavLink to="/dashboard">Dashboard</NavLink>
            <NavLink to="/runbooks">Runbooks</NavLink>
          </nav>
          {user && (
            <div className="who">
              <span>
                {user.name} <small>({user.role})</small>
              </span>
              <button type="button" className="ghost" onClick={logout}>
                Sign out
              </button>
            </div>
          )}
        </div>
      </header>
      <main id="main" className="page">
        <Outlet />
      </main>
    </>
  );
}
