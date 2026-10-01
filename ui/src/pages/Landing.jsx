import { Link } from "react-router-dom";

const STEPS = [
  {
    title: "Capture the reason",
    body: "When a planner overrides the system's recommendation, DecisionWatch reads the note and ERP context and proposes the assumptions behind it, such as “supplier will deliver by the 15th” or “stock will stay above 200 units”.",
  },
  {
    title: "Confirm in one click",
    body: "Planners review, edit or reject each proposed condition. Nothing is trusted until a person confirms it, and every edit is kept so extraction quality can be measured.",
  },
  {
    title: "Watch for change",
    body: "Forecasts, stock levels, supplier risk, lead times and price tiers keep moving. Each change is replayed against every confirmed assumption with deterministic rules, so a broken reason is caught the day it breaks.",
  },
  {
    title: "Act while it still pays",
    body: "A decision is flagged only when the estimated regret of keeping it is greater than the cost of switching. Each card shows the full arithmetic, the deadline, and Keep, Reduce, Delay or Cancel actions.",
  },
];

const PROBLEMS = [
  { tag: "Why", title: "Reasons live in heads and notes", body: "A purchase order records what was ordered, rarely the conditions that made it a good idea. Months later nobody can say what had to stay true." },
  { tag: "When", title: "The world changes silently", body: "A supplier slips, demand forecasts move, stock arrives early. Nothing in the ERP ties that change back to the decision it undermines." },
  { tag: "How much", title: "Alerts without economics create noise", body: "Flagging every change buries planners. Without a comparison of regret and switching cost, teams can't tell which reversals are worth the effort." },
];

const BENEFITS = [
  { title: "Fewer costly surprises", body: "Surface the handful of open orders whose original logic no longer holds, ranked by net benefit, before cancellation windows close." },
  { title: "Auditable by design", body: "Condition checks and flagging are deterministic. The LLM only proposes conditions and writes explanations; it never decides what gets flagged." },
  { title: "Keeps planners in control", body: "Every assumption is confirmed by a person, every recommendation shows its working, and every action is written back as an outcome." },
  { title: "Built around your ERP", body: "A connector layer reads orders, stock, supplier and forecast data. A PostgreSQL-backed connector ships today, with a SAP Business One interface mapped to OPOR/POR1, OITW, OITM and OCRD." },
  { title: "Institutional memory", body: "Reasons outlive the people who gave them. New planners inherit the logic behind open commitments instead of reverse-engineering it." },
  { title: "Measured, not assumed", body: "Track flags per week, action rate and extraction correction rate to see whether the system is earning planner trust." },
];

export default function Landing() {
  return (
    <>
      <section className="hero" id="about">
        <div className="container hero-grid">
          <div>
            <span className="eyebrow">Decision intelligence for procurement</span>
            <h1>Know the moment a purchasing decision stops making sense.</h1>
            <p className="lead">
              DecisionWatch records why your team made each procurement decision, turns those reasons into
              checkable conditions, and alerts you when reality breaks them, but only when acting is worth more than staying the course.
            </p>
            <div className="hero-actions">
              <Link to="/console" className="btn btn-primary">Open the console</Link>
              <Link to="/#how" className="btn btn-outline">See how it works</Link>
            </div>
          </div>
          <div className="hero-card" aria-hidden="true">
            <div className="hero-card-head">
              <span>Illustrative example</span>
              <span className="pill pill-danger">Assumption broken</span>
            </div>
            <p className="hero-quote">“Supplier confirmed delivery by the 15th, so we reduced the safety order.”</p>
            <div className="hero-rule"><span>Supplier lead time</span><strong>9 → 21 days</strong></div>
            <div className="hero-rule"><span>Regret of keeping</span><strong>₹1,84,000</strong></div>
            <div className="hero-rule"><span>Cost of switching</span><strong>₹42,500</strong></div>
            <div className="hero-result"><span>Recommendation</span><strong>Delay · 6 days left</strong></div>
          </div>
        </div>
      </section>

      <section className="section" id="what">
        <div className="container narrow">
          <span className="eyebrow">Who we are</span>
          <h2>A watchtower for the reasoning behind every order</h2>
          <p className="lead-dark">
            Most systems track what was decided. DecisionWatch tracks why. We sit beside your ERP, keep a living
            record of the assumptions each decision rests on, and keep checking them against the data your business already produces.
            When a reason no longer holds and the numbers justify a change, the right planner sees one ranked, explained recommendation.
          </p>
        </div>
      </section>

      <section className="section section-alt" id="problem">
        <div className="container">
          <span className="eyebrow">The problem we solve</span>
          <h2>Good decisions go bad quietly</h2>
          <p className="section-intro">
            Procurement commitments are made on assumptions about suppliers, demand and stock. When those
            assumptions fail, the ERP keeps executing the original order. By the time the loss shows up, the window to act has closed.
          </p>
          <div className="card-grid cols-3">
            {PROBLEMS.map((item) => (
              <article className="feature" key={item.title}>
                <span className="feature-tag">{item.tag}</span>
                <h3>{item.title}</h3>
                <p>{item.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section" id="how">
        <div className="container">
          <span className="eyebrow">How it works</span>
          <h2>From a planner's note to a ranked action list</h2>
          <ol className="steps">
            {STEPS.map((step, index) => (
              <li key={step.title}>
                <span className="step-num">{index + 1}</span>
                <div>
                  <h3>{step.title}</h3>
                  <p>{step.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>
      </section>

      <section className="section section-dark" id="enterprise">
        <div className="container">
          <span className="eyebrow eyebrow-light">How we help your enterprise</span>
          <h2>Protect margin and working capital without adding alert fatigue</h2>
          <div className="card-grid cols-3">
            {BENEFITS.map((item) => (
              <article className="feature feature-dark" key={item.title}>
                <h3>{item.title}</h3>
                <p>{item.body}</p>
              </article>
            ))}
          </div>
        </div>
      </section>

      <section className="section cta">
        <div className="container narrow center">
          <h2>See the morning brief on the demo dataset</h2>
          <p className="section-intro">
            Explore six months of simulated procurement history. Move the date, watch assumptions break,
            and review the arithmetic behind every recommendation.
          </p>
          <Link to="/console" className="btn btn-primary">Open the console</Link>
        </div>
      </section>
    </>
  );
}
