import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { inr } from "../format";

/* ---------- Content ---------- */

const STEPS = [
  {
    title: "Capture the reason",
    body: "When a planner overrides the system's recommendation, DecisionWatch reads the note and ERP context and proposes the assumptions behind it, such as “supplier will deliver by the 15th” or “stock will stay above 200 units”.",
    visual: "capture",
  },
  {
    title: "Confirm in one click",
    body: "Planners review, edit or reject each proposed condition. Nothing is trusted until a person confirms it, and every edit is kept so extraction quality can be measured.",
    visual: "confirm",
  },
  {
    title: "Watch for change",
    body: "Forecasts, stock levels, supplier risk, lead times and price tiers keep moving. Each change is replayed against every confirmed assumption with deterministic rules, so a broken reason is caught the day it breaks.",
    visual: "watch",
  },
  {
    title: "Act while it still pays",
    body: "A decision is flagged only when the estimated regret of keeping it is greater than the cost of switching. Each card shows the full arithmetic, the deadline, and Keep, Reduce, Delay or Cancel actions.",
    visual: "act",
  },
];

const PROBLEMS = [
  { icon: "note", tag: "Why", title: "Reasons live in heads and notes", body: "A purchase order records what was ordered, rarely the conditions that made it a good idea. Months later nobody can say what had to stay true." },
  { icon: "wave", tag: "When", title: "The world changes silently", body: "A supplier slips, demand forecasts move, stock arrives early. Nothing in the ERP ties that change back to the decision it undermines." },
  { icon: "bell", tag: "How much", title: "Alerts without economics create noise", body: "Flagging every change buries planners. Without a comparison of regret and switching cost, teams can't tell which reversals are worth the effort." },
];

const BENEFITS = [
  { icon: "shield", size: "wide", title: "Fewer costly surprises", body: "Surface the handful of open orders whose original logic no longer holds, ranked by net benefit, before cancellation windows close." },
  { icon: "scale", title: "Auditable by design", body: "Condition checks and flagging are deterministic. The LLM only proposes conditions and writes explanations; it never decides what gets flagged." },
  { icon: "user", title: "Planners stay in control", body: "Every assumption is confirmed by a person, every recommendation shows its working, and every action is written back as an outcome." },
  { icon: "plug", size: "wide", title: "Built around your ERP", body: "A connector layer reads orders, stock, supplier and forecast data. A PostgreSQL-backed connector ships today, with a SAP Business One interface mapped to OPOR/POR1, OITW, OITM and OCRD." },
  { icon: "book", title: "Institutional memory", body: "Reasons outlive the people who gave them. New planners inherit the logic behind open commitments instead of reverse-engineering it." },
  { icon: "chart", title: "Measured, not assumed", body: "Track flags per week, action rate and extraction correction rate to see whether the system is earning planner trust." },
];

const STACK = ["FastAPI", "PostgreSQL", "React + Vite", "SAP Business One", "Groq LLM", "Model Context Protocol", "Slack & Teams webhooks", "Alembic", "Docker Compose", "Deterministic rule engine"];

const FAQS = [
  { q: "Does the AI decide which orders get flagged?", a: "No. The LLM only proposes conditions from a planner's note and writes plain-language explanations. Whether a condition holds, and whether a decision is flagged, is computed by deterministic rules you can audit line by line." },
  { q: "What exactly triggers a flag?", a: "Two things must both be true: at least one confirmed assumption is invalid at the chosen date, and the estimated regret of keeping the decision is strictly greater than the cost of switching. Everything else stays quiet." },
  { q: "How does data get in?", a: "Load a dataset in bulk, or have your systems push changes to the event ingest API. Events are idempotent, only the assumptions watching that entity are rechecked, and late events trigger a full replay." },
  { q: "Can AI agents use it?", a: "Yes. An MCP server exposes the morning brief, decision detail, suggestions, event ingest and metrics to agents such as Claude. Write access is off unless you explicitly enable it." },
  { q: "Is this running on real company data?", a: "The demo runs on six months of synthetic procurement history so you can move the date and watch assumptions break. The connector layer is where a real ERP plugs in." },
];

const HERO_SCENARIOS = [
  {
    quote: "“Supplier confirmed delivery by the 15th, so we reduced the safety order.”",
    rule: ["Supplier lead time", "9 → 21 days"],
    regret: 184000, switching: 42500, rec: "Delay", days: 6, status: "danger", label: "Assumption broken",
  },
  {
    quote: "“Demand forecast is flat, so a single bulk order locks in the tier-2 price.”",
    rule: ["Weekly forecast", "1,200 → 640 units"],
    regret: 96500, switching: 31000, rec: "Reduce", days: 11, status: "danger", label: "Assumption broken",
  },
  {
    quote: "“Stock will stay above 200 units until the next inbound lands.”",
    rule: ["Stock on hand", "540 units"],
    regret: 0, switching: 18000, rec: "Keep", days: null, status: "ok", label: "All assumptions hold",
  },
];

/* ---------- Small pieces ---------- */

const ICONS = {
  note: <path d="M6 3h9l5 5v13H6zM14 3v6h6M9 13h8M9 17h5" />,
  wave: <path d="M2 12c2.5-5 5-5 7.5 0s5 5 7.5 0 3.5-3 5-2M2 18h20" />,
  bell: <path d="M6 16V11a6 6 0 1 1 12 0v5l2 2H4zM10 21h4" />,
  shield: <path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6zM8.5 12l2.5 2.5 4.5-5" />,
  scale: <path d="M12 3v18M5 21h14M6 7h12M6 7l-3 7a3 3 0 0 0 6 0zM18 7l-3 7a3 3 0 0 0 6 0z" />,
  user: <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8zM4 21c1-4 4.5-6 8-6s7 2 8 6" />,
  plug: <path d="M9 2v5M15 2v5M6 7h12v4a6 6 0 0 1-12 0zM12 17v5" />,
  book: <path d="M4 4h6a3 3 0 0 1 3 3v14a2 2 0 0 0-2-2H4zM20 4h-6a3 3 0 0 0-3 3" />,
  chart: <path d="M4 20V10M10 20V4M16 20v-7M22 20H2" />,
  play: <path d="M8 5v14l11-7z" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" />,
  arrow: <path d="M5 12h14M13 6l6 6-6 6" />,
};

function Icon({ name, size = 22 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}

// Fades elements with the "reveal" class in as they scroll into view.
function useReveal() {
  useEffect(() => {
    const nodes = document.querySelectorAll(".reveal");
    if (!("IntersectionObserver" in window)) {
      nodes.forEach((node) => node.classList.add("is-visible"));
      return undefined;
    }
    const observer = new IntersectionObserver(
      (entries) => entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add("is-visible");
          observer.unobserve(entry.target);
        }
      }),
      { threshold: 0.15, rootMargin: "0px 0px -40px 0px" },
    );
    nodes.forEach((node) => observer.observe(node));
    return () => observer.disconnect();
  }, []);
}

function CountUp({ to, suffix = "", duration = 1400 }) {
  const ref = useRef(null);
  const [value, setValue] = useState(0);
  useEffect(() => {
    const node = ref.current;
    let frame;
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      observer.disconnect();
      const start = performance.now();
      const tick = (now) => {
        const t = Math.min(1, (now - start) / duration);
        setValue(Math.round(to * (1 - Math.pow(1 - t, 3))));
        if (t < 1) frame = requestAnimationFrame(tick);
      };
      frame = requestAnimationFrame(tick);
    });
    observer.observe(node);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [to, duration]);
  return <span ref={ref}>{value}{suffix}</span>;
}

// Card whose glow follows the cursor.
function Spotlight({ className = "", children, ...rest }) {
  const onMove = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    event.currentTarget.style.setProperty("--mx", `${event.clientX - rect.left}px`);
    event.currentTarget.style.setProperty("--my", `${event.clientY - rect.top}px`);
  };
  return <article className={`spot ${className}`} onMouseMove={onMove} {...rest}>{children}</article>;
}

/* ---------- Sections ---------- */

function HeroCard() {
  const [index, setIndex] = useState(0);
  const [tilt, setTilt] = useState({ x: 0, y: 0 });
  useEffect(() => {
    const id = setInterval(() => setIndex((i) => (i + 1) % HERO_SCENARIOS.length), 4200);
    return () => clearInterval(id);
  }, []);
  const s = HERO_SCENARIOS[index];
  const onMove = (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    setTilt({
      x: ((event.clientY - rect.top) / rect.height - 0.5) * -8,
      y: ((event.clientX - rect.left) / rect.width - 0.5) * 10,
    });
  };

  return (
    <div className="hero-visual" onMouseMove={onMove} onMouseLeave={() => setTilt({ x: 0, y: 0 })}>
      <div className="hero-card" style={{ transform: `perspective(1000px) rotateX(${tilt.x}deg) rotateY(${tilt.y}deg)` }}>
        <div className="hero-card-head">
          <span className="hc-dots"><i /><i /><i /></span>
          <span>Morning brief · PO-4471</span>
          <span className={`pill pill-${s.status}`}>{s.label}</span>
        </div>
        <div key={index} className="hc-body">
          <p className="hero-quote">{s.quote}</p>
          <div className="hero-rule"><span>{s.rule[0]}</span><strong>{s.rule[1]}</strong></div>
          <div className="hero-rule"><span>Regret of keeping</span><strong>{inr(s.regret)}</strong></div>
          <div className="hero-rule"><span>Cost of switching</span><strong>{inr(s.switching)}</strong></div>
          <div className="hc-bar" aria-hidden="true">
            <span className="hc-bar-regret" style={{ width: `${Math.min(100, (s.regret / 200000) * 100)}%` }} />
            <span className="hc-bar-switch" style={{ left: `${(s.switching / 200000) * 100}%` }} />
          </div>
          <div className={`hero-result hero-result-${s.status}`}>
            <span>Recommendation</span>
            <strong>{s.rec}{s.days ? ` · ${s.days} days left` : ""}</strong>
          </div>
        </div>
        <div className="hc-pager">
          {HERO_SCENARIOS.map((_, i) => (
            <button key={i} aria-label={`Show example ${i + 1}`} className={i === index ? "on" : ""} onClick={() => setIndex(i)} />
          ))}
        </div>
      </div>
      <div className="hero-float hero-float-a"><Icon name="check" size={16} /> 3 assumptions confirmed</div>
      <div className="hero-float hero-float-b"><span className="live-dot" /> Event ingested · lead_time_days</div>
    </div>
  );
}

function StepVisual({ kind }) {
  if (kind === "capture") {
    return (
      <div className="sv">
        <div className="sv-note">“Ordering 2,400 units now because <mark>Apex Metals delivers in 9 days</mark> and <mark>stock stays above 200</mark>.”</div>
        <div className="sv-arrow"><Icon name="arrow" /></div>
        <div className="sv-chip">lead_time_days ≤ 9 <em>supplier:APEX</em></div>
        <div className="sv-chip">stock_qty &gt; 200 <em>item:SKU-118</em></div>
      </div>
    );
  }
  if (kind === "confirm") {
    return (
      <div className="sv">
        {[["lead_time_days ≤ 9", "accepted"], ["stock_qty > 200", "edited → 180"], ["price_tier = 2", "rejected"]].map(([cond, state]) => (
          <div className="sv-row" key={cond}>
            <code>{cond}</code>
            <span className={`pill ${state === "rejected" ? "pill-neutral" : state === "accepted" ? "pill-ok" : "pill-warn"}`}>{state}</span>
          </div>
        ))}
      </div>
    );
  }
  if (kind === "watch") {
    return (
      <div className="sv">
        {[["09:02", "stock_qty", "SKU-118", "412", "ok"], ["09:14", "forecast", "SKU-118", "+4%", "ok"], ["10:41", "lead_time_days", "APEX", "21", "danger"]].map(([t, f, e, v, tone]) => (
          <div className={`sv-event sv-event-${tone}`} key={t}>
            <span className="muted">{t}</span><code>{f}</code><span>{e}</span><strong>{v}</strong>
            <span className={`pill pill-${tone}`}>{tone === "ok" ? "holds" : "broken"}</span>
          </div>
        ))}
      </div>
    );
  }
  return (
    <div className="sv">
      <div className="sv-ledger">
        <div><span>Regret of keeping</span><strong>{inr(184000)}</strong></div>
        <div><span>Cost of switching</span><strong>− {inr(42500)}</strong></div>
        <div className="sv-total"><span>Net benefit of acting</span><strong>{inr(141500)}</strong></div>
      </div>
      <div className="btn-group">
        {["Keep", "Reduce", "Delay", "Cancel"].map((a) => <span key={a} className={`sv-act${a === "Delay" ? " on" : ""}`}>{a}</span>)}
      </div>
    </div>
  );
}

function HowItWorks() {
  const [active, setActive] = useState(0);
  const [paused, setPaused] = useState(false);
  useEffect(() => {
    if (paused) return undefined;
    const id = setTimeout(() => setActive((a) => (a + 1) % STEPS.length), 6000);
    return () => clearTimeout(id);
  }, [active, paused]);

  return (
    <div className="how reveal" onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}>
      <ol className="how-list" role="tablist">
        {STEPS.map((step, i) => (
          <li key={step.title}>
            <button role="tab" aria-selected={i === active} className={`how-tab${i === active ? " active" : ""}`} onClick={() => setActive(i)}>
              <span className="how-num">0{i + 1}</span>
              <span className="how-text">
                <strong>{step.title}</strong>
                <span className="how-body"><span>{step.body}</span></span>
              </span>
              {i === active && <span key={`${active}-${paused}`} className={`how-progress${paused ? " paused" : ""}`} />}
            </button>
          </li>
        ))}
      </ol>
      <div className="how-stage" role="tabpanel">
        <div key={active} className="how-stage-inner">
          <span className="how-stage-label">Step 0{active + 1} · {STEPS[active].title}</span>
          <StepVisual kind={STEPS[active].visual} />
        </div>
      </div>
    </div>
  );
}

const PROMISED_LEAD = 12;
const DAILY_SHORTFALL = 14000;

function Simulator() {
  const [lead, setLead] = useState(18);
  const [switching, setSwitching] = useState(60000);
  const broken = lead > PROMISED_LEAD;
  const regret = broken ? (lead - PROMISED_LEAD) * DAILY_SHORTFALL : 0;
  const flagged = broken && regret > switching;
  const max = 300000;
  const verdict = !broken
    ? { tone: "ok", title: "Keep", text: "The assumption still holds. Nothing to review." }
    : flagged
      ? { tone: "danger", title: "Flagged for review", text: `Acting is worth ${inr(regret - switching)} more than staying the course.` }
      : { tone: "warn", title: "Watched, not flagged", text: "The reason broke, but switching would cost more than it saves. No alert noise." };

  return (
    <div className="sim reveal">
      <div className="sim-controls">
        <div className="sim-assumption">
          <span className="muted small">Confirmed assumption</span>
          <code>supplier.lead_time_days ≤ {PROMISED_LEAD}</code>
        </div>
        <label className="sim-slider">
          <span>Actual supplier lead time <strong>{lead} days</strong></span>
          <input type="range" min="5" max="35" value={lead} onChange={(e) => setLead(Number(e.target.value))} style={{ "--fill": `${((lead - 5) / 30) * 100}%` }} />
        </label>
        <label className="sim-slider">
          <span>Cost of switching <strong>{inr(switching)}</strong></span>
          <input type="range" min="10000" max="250000" step="2500" value={switching} onChange={(e) => setSwitching(Number(e.target.value))} style={{ "--fill": `${((switching - 10000) / 240000) * 100}%` }} />
        </label>
        <p className="muted small">Illustrative: each day of delay past the promise costs {inr(DAILY_SHORTFALL)} in expected shortfall.</p>
      </div>

      <div className="sim-output">
        <div className="sim-checks">
          <div className={`sim-check ${broken ? "bad" : "good"}`}>
            <span>1 · Is the assumption invalid?</span><strong>{broken ? "Yes" : "No"}</strong>
          </div>
          <div className={`sim-check ${!broken ? "idle" : regret > switching ? "bad" : "good"}`}>
            <span>2 · Is regret &gt; switching cost?</span><strong>{!broken ? "—" : regret > switching ? "Yes" : "No"}</strong>
          </div>
        </div>
        <div className="sim-bars">
          <div className="sim-bar">
            <span>Regret of keeping</span>
            <div className="sim-track"><i className="sim-fill sim-fill-regret" style={{ width: `${Math.min(100, (regret / max) * 100)}%` }} /></div>
            <strong>{inr(regret)}</strong>
          </div>
          <div className="sim-bar">
            <span>Cost of switching</span>
            <div className="sim-track"><i className="sim-fill sim-fill-switch" style={{ width: `${(switching / max) * 100}%` }} /></div>
            <strong>{inr(switching)}</strong>
          </div>
        </div>
        <div className={`sim-verdict sim-verdict-${verdict.tone}`} aria-live="polite">
          <strong>{verdict.title}</strong>
          <span>{verdict.text}</span>
        </div>
      </div>
    </div>
  );
}

function Faq() {
  const [open, setOpen] = useState(0);
  return (
    <div className="faq reveal">
      {FAQS.map((item, i) => (
        <div key={item.q} className={`faq-item${open === i ? " open" : ""}`}>
          <button className="faq-q" aria-expanded={open === i} onClick={() => setOpen(open === i ? -1 : i)}>
            {item.q}<span className="faq-plus" aria-hidden="true" />
          </button>
          <div className="faq-a"><div><p>{item.a}</p></div></div>
        </div>
      ))}
    </div>
  );
}

function VideoModal({ onClose }) {
  useEffect(() => {
    const onKey = (event) => event.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { document.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [onClose]);
  return (
    <div className="modal" role="dialog" aria-modal="true" aria-label="Architecture walkthrough" onClick={onClose}>
      <div className="modal-box" onClick={(e) => e.stopPropagation()}>
        <button className="modal-close" onClick={onClose} aria-label="Close video">×</button>
        <video src="/decisionwatch-architecture.mp4" controls autoPlay playsInline />
      </div>
    </div>
  );
}

/* ---------- Page ---------- */

export default function Landing() {
  useReveal();
  const [video, setVideo] = useState(false);

  return (
    <div className="lp">
      <section className="hero" id="about">
        <div className="hero-bg" aria-hidden="true"><span className="orb orb-1" /><span className="orb orb-2" /><span className="grid-bg" /></div>
        <div className="container hero-grid">
          <div className="hero-copy">
            <span className="badge"><span className="badge-new">New</span> Live event ingest + MCP server for AI agents</span>
            <h1>Know the moment a purchasing decision <span className="grad-text">stops making sense.</span></h1>
            <p className="lead">
              DecisionWatch records why your team made each procurement decision, turns those reasons into
              checkable conditions, and alerts you when reality breaks them, but only when acting is worth more than staying the course.
            </p>
            <div className="hero-actions">
              <Link to="/console" className="btn btn-glow">Open the console <Icon name="arrow" size={18} /></Link>
              <button className="btn btn-glass" onClick={() => setVideo(true)}><span className="play"><Icon name="play" size={14} /></span> Watch the architecture</button>
            </div>
            <dl className="hero-stats">
              <div><dt>Months of replayable history</dt><dd><CountUp to={6} /></dd></div>
              <div><dt>Actions per flag</dt><dd><CountUp to={4} /></dd></div>
              <div><dt>Flags decided by the LLM</dt><dd><CountUp to={0} /></dd></div>
            </dl>
          </div>
          <HeroCard />
        </div>
      </section>

      <section className="marquee" aria-label="Built with">
        <div className="marquee-track">
          {[...STACK, ...STACK].map((item, i) => <span key={i} aria-hidden={i >= STACK.length}>{item}</span>)}
        </div>
      </section>

      <section className="section" id="what">
        <div className="container narrow center reveal">
          <span className="eyebrow">Who we are</span>
          <h2>A watchtower for the <span className="grad-text">reasoning</span> behind every order</h2>
          <p className="lead-dark">
            Most systems track what was decided. DecisionWatch tracks why. We sit beside your ERP, keep a living
            record of the assumptions each decision rests on, and keep checking them against the data your business already produces.
          </p>
        </div>
      </section>

      <section className="section" id="problem">
        <div className="container">
          <div className="section-head reveal">
            <span className="eyebrow">The problem we solve</span>
            <h2>Good decisions go bad quietly</h2>
            <p className="section-intro">
              Procurement commitments are made on assumptions about suppliers, demand and stock. When those
              assumptions fail, the ERP keeps executing the original order. By the time the loss shows up, the window to act has closed.
            </p>
          </div>
          <div className="card-grid cols-3">
            {PROBLEMS.map((item, i) => (
              <Spotlight className="reveal" style={{ "--delay": `${i * 90}ms` }} key={item.title}>
                <span className="spot-icon"><Icon name={item.icon} /></span>
                <span className="feature-tag">{item.tag}</span>
                <h3>{item.title}</h3>
                <p>{item.body}</p>
              </Spotlight>
            ))}
          </div>
        </div>
      </section>

      <section className="section" id="how">
        <div className="container">
          <div className="section-head reveal">
            <span className="eyebrow">How it works</span>
            <h2>From a planner's note to a ranked action list</h2>
          </div>
          <HowItWorks />
        </div>
      </section>

      <section className="section" id="try">
        <div className="container">
          <div className="section-head center reveal">
            <span className="eyebrow">Try the rule</span>
            <h2>One rule. No alert fatigue.</h2>
            <p className="section-intro">
              A decision is flagged only when a confirmed reason is broken <em>and</em> the regret of keeping it beats the cost of
              switching. Drag the sliders and watch the verdict change.
            </p>
          </div>
          <Simulator />
        </div>
      </section>

      <section className="section" id="enterprise">
        <div className="container">
          <div className="section-head reveal">
            <span className="eyebrow">How we help your enterprise</span>
            <h2>Protect margin and working capital without adding alert fatigue</h2>
          </div>
          <div className="bento">
            {BENEFITS.map((item, i) => (
              <Spotlight className={`reveal${item.size ? ` bento-${item.size}` : ""}`} style={{ "--delay": `${(i % 3) * 90}ms` }} key={item.title}>
                <span className="spot-icon"><Icon name={item.icon} /></span>
                <h3>{item.title}</h3>
                <p>{item.body}</p>
              </Spotlight>
            ))}
          </div>
        </div>
      </section>

      <section className="section" id="faq">
        <div className="container faq-grid">
          <div className="reveal">
            <span className="eyebrow">Questions</span>
            <h2>Straight answers</h2>
            <p className="section-intro">How DecisionWatch decides, what it trusts, and where people stay in the loop.</p>
          </div>
          <Faq />
        </div>
      </section>

      <section className="section cta-wrap">
        <div className="container">
          <div className="cta reveal">
            <span className="orb orb-3" aria-hidden="true" />
            <h2>See the morning brief on the demo dataset</h2>
            <p className="section-intro">
              Explore six months of simulated procurement history. Move the date, watch assumptions break,
              and review the arithmetic behind every recommendation.
            </p>
            <div className="hero-actions center-actions">
              <Link to="/console" className="btn btn-glow">Open the console <Icon name="arrow" size={18} /></Link>
              <button className="btn btn-glass" onClick={() => setVideo(true)}>Watch the architecture</button>
            </div>
          </div>
        </div>
      </section>

      {video && <VideoModal onClose={() => setVideo(false)} />}
    </div>
  );
}
