import { useEffect, useState } from "react";
import { Link, Outlet, useLocation } from "react-router-dom";
import Logo from "./Logo";

const LINKS = [
  { id: "problem", label: "The problem" },
  { id: "how", label: "How it works" },
  { id: "try", label: "Try it" },
  { id: "enterprise", label: "For enterprise" },
  { id: "faq", label: "FAQ" },
];

export default function SiteLayout() {
  const { hash } = useLocation();
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [active, setActive] = useState("");
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (hash) document.querySelector(hash)?.scrollIntoView({ behavior: "smooth" });
    else window.scrollTo(0, 0);
    setMenuOpen(false);
  }, [hash]);

  useEffect(() => {
    const onScroll = () => {
      const doc = document.documentElement;
      setScrolled(window.scrollY > 12);
      setProgress(window.scrollY / Math.max(1, doc.scrollHeight - window.innerHeight));
      const current = LINKS.filter(({ id }) => {
        const el = document.getElementById(id);
        return el && el.getBoundingClientRect().top < window.innerHeight * 0.4;
      }).pop();
      setActive(current?.id ?? "");
    };
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <div className="site">
      <header className={`site-header${scrolled ? " scrolled" : ""}${menuOpen ? " menu-open" : ""}`}>
        <div className="container site-header-inner">
          <Link to="/" aria-label="DecisionWatch home"><Logo light /></Link>
          <nav className="site-nav" aria-label="Primary">
            {LINKS.map(({ id, label }) => (
              <Link key={id} to={`/#${id}`} className={active === id ? "active" : ""} onClick={() => setMenuOpen(false)}>{label}</Link>
            ))}
          </nav>
          <div className="site-header-cta">
            <Link to="/console" className="btn btn-glow btn-sm">Open console</Link>
            <button className="burger" aria-label="Toggle menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((o) => !o)}>
              <span /><span />
            </button>
          </div>
        </div>
        <span className="scroll-progress" style={{ transform: `scaleX(${progress})` }} aria-hidden="true" />
      </header>
      <main><Outlet /></main>
      <footer className="site-footer">
        <div className="container site-footer-inner">
          <div>
            <Logo light />
            <p>Decision intelligence for procurement and supply chain teams.</p>
          </div>
          <nav className="footer-links" aria-label="Footer">
            {LINKS.map(({ id, label }) => <Link key={id} to={`/#${id}`}>{label}</Link>)}
            <Link to="/console">Console</Link>
          </nav>
        </div>
        <div className="container footer-bottom">
          © {new Date().getFullYear()} DecisionWatch. Prototype build running on synthetic data.
        </div>
      </footer>
    </div>
  );
}
