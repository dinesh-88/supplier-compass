import type { SuppliersData } from "./api";
import type { Filters, Range } from "./store";

const SPEND = "purchase_order_volume_eur";
const DELIVERY = "supplier_delivery_rating";
const CONFIRM = "order_confirmation_rate";
const CHANGE = "order_change_rate";
export const METRIC_KEYS = { spend: SPEND, delivery: DELIVERY, confirmation: CONFIRM, changeRate: CHANGE } as const;

function extent(values: (number | null)[]): Range {
  let lo = Infinity;
  let hi = -Infinity;
  for (const v of values) {
    if (v === null) continue;
    if (v < lo) lo = v;
    if (v > hi) hi = v;
  }
  return lo === Infinity ? [0, 0] : [lo, hi];
}

export type Bounds = {
  spend: Range | null;
  delivery: Range | null;
  confirmation: Range | null;
  changeRate: Range | null;
  sourcing: string[];
  complexity: string[];
};

const ORDER = ["Low", "Medium", "High", "Simple", "Moderate", "Complex"];
const orderOf = (v: string) => (ORDER.includes(v) ? ORDER.indexOf(v) : ORDER.length);
const sortCats = (vals: string[]) =>
  [...new Set(vals.filter(Boolean))].sort((a, b) => orderOf(a) - orderOf(b) || a.localeCompare(b));

export function bounds(d: SuppliersData): Bounds {
  const m = d.metrics;
  const spend = m[SPEND] ? extent(m[SPEND]) : null;
  const floorTo = (r: Range | null, step: number): Range | null => (r ? [Math.floor(r[0] / step) * step, Math.ceil(r[1] / step) * step] : null);
  return {
    spend: spend ? [Math.floor(Math.log10(Math.max(1, spend[0])) * 10) / 10, Math.ceil(Math.log10(Math.max(1, spend[1])) * 10) / 10] : null,
    delivery: floorTo(m[DELIVERY] ? extent(m[DELIVERY]) : null, 1),
    confirmation: floorTo(m[CONFIRM] ? extent(m[CONFIRM]) : null, 1),
    changeRate: floorTo(m[CHANGE] ? extent(m[CHANGE]) : null, 1),
    sourcing: d.sourcing ? sortCats(d.sourcing) : [],
    complexity: d.complexity ? sortCats(d.complexity) : [],
  };
}

export function defaultFilters(d: SuppliersData, b: Bounds): Filters {
  return {
    text: "",
    index: [0, 100],
    scores: Object.fromEntries(d.categories.map((c) => [c.column, [0, 100] as Range])),
    spend: b.spend,
    delivery: b.delivery,
    confirmation: b.confirmation,
    changeRate: b.changeRate,
    sourcing: [],
    complexity: [],
    exposureOnly: false,
    mismatchOnly: false,
  };
}

export function activeFilterCount(f: Filters, def: Filters): number {
  let n = 0;
  const diff = (a: Range | null, b: Range | null) => !!a && !!b && (a[0] !== b[0] || a[1] !== b[1]);
  if (f.text.trim()) n++;
  if (diff(f.index, def.index)) n++;
  for (const k of Object.keys(f.scores)) if (diff(f.scores[k], def.scores[k])) n++;
  if (diff(f.spend, def.spend)) n++;
  if (diff(f.delivery, def.delivery)) n++;
  if (diff(f.confirmation, def.confirmation)) n++;
  if (diff(f.changeRate, def.changeRate)) n++;
  if (f.sourcing.length) n++;
  if (f.complexity.length) n++;
  if (f.exposureOnly) n++;
  if (f.mismatchOnly) n++;
  return n;
}

type Skip = "sourcing" | "complexity" | "exposure" | "mismatch" | null;

/** Row test; `skip` leaves one facet out so its options can show live counts. */
function makeTest(d: SuppliersData, f: Filters, def: Filters, skip: Skip) {
  const text = f.text.trim().toLowerCase();
  const scoreTests: [number, number, number][] = [];
  d.categories.forEach((c, k) => {
    const r = f.scores[c.column];
    if (r && (r[0] > 0 || r[1] < 100)) scoreTests.push([k, r[0], r[1]]);
  });
  const rangeTest = (key: keyof typeof METRIC_KEYS, r: Range | null, base: Range | null, log = false) => {
    const arr = d.metrics[METRIC_KEYS[key]];
    if (!arr || !r || !base || (r[0] === base[0] && r[1] === base[1])) return null;
    const lo = log ? Math.pow(10, r[0]) : r[0];
    const hi = log ? Math.pow(10, r[1]) : r[1];
    return (i: number) => {
      const v = arr[i];
      return v !== null && v >= lo - 1e-9 && v <= hi + 1e-9;
    };
  };
  const metricTests = [
    rangeTest("spend", f.spend, def.spend, true),
    rangeTest("delivery", f.delivery, def.delivery),
    rangeTest("confirmation", f.confirmation, def.confirmation),
    rangeTest("changeRate", f.changeRate, def.changeRate),
  ].filter(Boolean) as ((i: number) => boolean)[];
  const sourcing = skip !== "sourcing" && f.sourcing.length && d.sourcing ? new Set(f.sourcing) : null;
  const complexity = skip !== "complexity" && f.complexity.length && d.complexity ? new Set(f.complexity) : null;
  const exposure = skip !== "exposure" && f.exposureOnly;
  const mismatch = skip !== "mismatch" && f.mismatchOnly;
  const [ilo, ihi] = f.index;
  return (i: number) => {
    const idx = d.index[i];
    if (idx < ilo || idx > ihi) return false;
    if (exposure && !d.exposure_list[i]) return false;
    if (mismatch && !d.mismatch[i]) return false;
    if (sourcing && !sourcing.has(d.sourcing![i])) return false;
    if (complexity && !complexity.has(d.complexity![i])) return false;
    const s = d.scores[i];
    for (const [k, lo, hi] of scoreTests) if (s[k] < lo || s[k] > hi) return false;
    for (const t of metricTests) if (!t(i)) return false;
    if (text && !d.ids[i].toLowerCase().includes(text) && !d.names[i].toLowerCase().includes(text)) return false;
    return true;
  };
}

export type FilterResult = {
  matches: Uint8Array;
  indices: number[];
  facetCounts: {
    sourcing: Record<string, number>;
    complexity: Record<string, number>;
    exposure: number;
    mismatch: number;
  };
};

export function applyFilters(d: SuppliersData, f: Filters, def: Filters): FilterResult {
  const n = d.ids.length;
  const test = makeTest(d, f, def, null);
  const matches = new Uint8Array(n);
  const indices: number[] = [];
  for (let i = 0; i < n; i++) {
    if (test(i)) {
      matches[i] = 1;
      indices.push(i);
    }
  }
  const counts = (skip: Exclude<Skip, null>, key: (i: number) => string | null) => {
    const t = makeTest(d, f, def, skip);
    const out: Record<string, number> = {};
    for (let i = 0; i < n; i++) {
      if (!t(i)) continue;
      const k = key(i);
      if (k !== null) out[k] = (out[k] ?? 0) + 1;
    }
    return out;
  };
  return {
    matches,
    indices,
    facetCounts: {
      sourcing: d.sourcing ? counts("sourcing", (i) => d.sourcing![i]) : {},
      complexity: d.complexity ? counts("complexity", (i) => d.complexity![i]) : {},
      exposure: counts("exposure", (i) => (d.exposure_list[i] ? "y" : null)).y ?? 0,
      mismatch: counts("mismatch", (i) => (d.mismatch[i] ? "y" : null)).y ?? 0,
    },
  };
}

export function median(values: number[]): number | null {
  if (!values.length) return null;
  const s = [...values].sort((a, b) => a - b);
  const m = s.length >> 1;
  return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
}
