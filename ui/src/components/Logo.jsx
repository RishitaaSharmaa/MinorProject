// Eye (watching) with a checkmark pupil (a verified decision).
export default function Logo({ light = false }) {
  return (
    <span className={`logo${light ? " logo-light" : ""}`}>
      <svg width="30" height="30" viewBox="0 0 28 28" aria-hidden="true">
        <defs>
          <linearGradient id="dw-logo-grad" x1="0" y1="0" x2="28" y2="28" gradientUnits="userSpaceOnUse">
            <stop offset="0" stopColor="#6366f1" />
            <stop offset="1" stopColor="#06b6d4" />
          </linearGradient>
        </defs>
        <rect width="28" height="28" rx="8" fill="url(#dw-logo-grad)" />
        <path d="M3.5 14C6.6 9.2 10.2 7 14 7s7.4 2.2 10.5 7c-3.1 4.8-6.7 7-10.5 7S6.6 18.8 3.5 14Z" fill="none" stroke="#fff" strokeWidth="1.8" strokeLinejoin="round" />
        <circle cx="14" cy="14" r="4.2" fill="#fff" />
        <path d="m12 14.1 1.4 1.4 2.7-2.9" fill="none" stroke="#4f46e5" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      DecisionWatch
    </span>
  );
}
