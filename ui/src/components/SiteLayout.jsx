import { useEffect } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import Logo from "./Logo";

export default function SiteLayout() {
  const { hash } = useLocation();
  useEffect(() => {
    if (hash) document.querySelector(hash)?.scrollIntoView({ behavior: "smooth" });
    else window.scrollTo(0, 0);
  }, [hash]);

  return (
    <>
      <header className="site-header">
        <div className="container site-header-inner">
          <Link to="/" aria-label="DecisionWatch home"><Logo /></Link>
          <nav className="site-nav" aria-label="Primary">
            <Link to="/#about">About</Link>
            <Link to="/#problem">The problem</Link>
            <Link to="/#how">How it works</Link>
            <Link to="/#enterprise">For enterprise</Link>
            <Link to="/console" className="btn btn-primary btn-sm">Open console</Link>
          </nav>
        </div>
      </header>
      <main><Outlet /></main>
      <footer className="site-footer">
        <div className="container site-footer-inner">
          <Logo light />
          <p>Decision intelligence for procurement and supply chain teams.</p>
          <p className="muted-light">© {new Date().getFullYear()} DecisionWatch. Prototype build running on synthetic data.</p>
        </div>
      </footer>
    </>
  );
}
