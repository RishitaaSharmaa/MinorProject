const inrFormat = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});

export const inr = (value) => (value === null || value === undefined ? "—" : inrFormat.format(value));
export const pct = (value) => `${(value * 100).toFixed(0)}%`;

// The synthetic dataset's simulated calendar (see data_generator/config.py).
export const DATASET_START = "2025-04-01";
export const DATASET_END = "2025-09-30";

const DAY_MS = 86_400_000;
export const dayOffset = (iso) => Math.round((Date.parse(iso) - Date.parse(DATASET_START)) / DAY_MS);
export const fromOffset = (offset) =>
  new Date(Date.parse(DATASET_START) + offset * DAY_MS).toISOString().slice(0, 10);
export const TOTAL_DAYS = dayOffset(DATASET_END);

export const formatDate = (iso) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });

// Parses a condition value typed by a planner as boolean, number, or text.
export function parseValue(text) {
  const trimmed = String(text).trim();
  if (trimmed.toLowerCase() === "true") return true;
  if (trimmed.toLowerCase() === "false") return false;
  if (trimmed !== "" && !Number.isNaN(Number(trimmed))) return Number(trimmed);
  return trimmed;
}
