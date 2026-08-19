import { Link, NavLink } from "react-router-dom";

function LogoMark() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <rect x="2.5" y="5" width="19" height="14" rx="3" />
      <path d="M10 9.5v5l4.5-2.5z" fill="currentColor" stroke="none" />
    </svg>
  );
}

export default function Header() {
  return (
    <header className="site-header">
      <div className="site-header-inner">
        <Link to="/" className="logo">
          <span className="logo-mark">
            <LogoMark />
          </span>
          Sub for Creator
        </Link>
        <nav className="site-nav" aria-label="主要導覽">
          <NavLink to="/" end className={({ isActive }) => (isActive ? "active" : undefined)}>
            首頁
          </NavLink>
          <NavLink to="/privacy" className={({ isActive }) => (isActive ? "active" : undefined)}>
            隱私權
          </NavLink>
          <NavLink to="/terms" className={({ isActive }) => (isActive ? "active" : undefined)}>
            服務條款
          </NavLink>
        </nav>
        <span className="header-spacer" />
        <a
          className="github-link"
          href="https://github.com/nashwu0117/Sub-For-Creator"
          target="_blank"
          rel="noopener noreferrer"
        >
          <svg viewBox="0 0 16 16" fill="currentColor" aria-hidden="true">
            <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
          </svg>
          <span>GitHub</span>
        </a>
      </div>
    </header>
  );
}