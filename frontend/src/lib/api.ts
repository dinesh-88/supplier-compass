export class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, message: string, body: unknown) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method, credentials: "same-origin", headers: {} };
  if (body instanceof FormData) {
    init.body = body;
  } else if (body !== undefined) {
    init.body = JSON.stringify(body);
    (init.headers as Record<string, string>)["Content-Type"] = "application/json";
  }
  const res = await fetch(url, init);
  const type = res.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const detail =
      typeof data === "object" && data && "detail" in data
        ? String((data as { detail: unknown }).detail)
        : typeof data === "object" && data && "error" in data
          ? String((data as { error: unknown }).error)
          : `Request failed (${res.status})`;
    if (res.status === 401 && url !== "/api/login") window.dispatchEvent(new Event("sc:unauthorized"));
    throw new ApiError(res.status, detail, data);
  }
  return data as T;
}

export const api = {
  get: <T>(url: string) => request<T>("GET", url),
  post: <T>(url: string, body?: unknown) => request<T>("POST", url, body),
  del: <T>(url: string) => request<T>("DELETE", url),
};

// ----------------------------------------------------------------- types

export type Band = { level: string; min: number; max: number };
export type Category = { column: string; original: string; label: string; weight_pct: number };
export type Preset = { key: string; label: string; why: string; weights: Record<string, number>; raised: string[] };

export type Formula = {
  weights: Record<string, number>;
  raw_weights: Record<string, number>;
  match_share: number;
  rows_matched: number;
  rows_total: number;
  r2: number;
  status: "verified" | "approximate";
  label: string;
  rounding: string;
};

export type DroppedReason = { reason: string; count: number; examples: { row: number; supplierID: string | null }[] };

export type Report = {
  errors: string[];
  warnings: string[];
  notices: string[];
  rows_in_file?: number;
  rows_loaded?: number;
  rows_dropped?: number;
  malformed_lines?: number;
  dropped?: DroppedReason[];
  missing?: Record<string, number>;
  columns?: string[];
  score_columns?: string[];
  level_columns?: string[];
  optional_present?: string[];
  extra_columns?: string[];
};

export type Feature = { enabled: boolean; label: string; needs: { snake: string; original: string }[] };

export type DatasetMeta = {
  loaded: true;
  file_name: string;
  uploaded_at: string;
  row_count: number;
  report: Report;
  formula: Formula;
  bands: Band[];
  band_source: string;
  features: Record<string, Feature>;
  descriptions: { source: string; builtin: boolean; terms: number };
  presets: Preset[];
  categories: Category[];
  exposure_rule?: { spend_threshold: number; index_threshold: number };
  mismatch_model?: { residual_sd: number; threshold: number; flagged: number } | null;
};

export type SuppliersData = {
  ids: string[];
  names: string[];
  index: number[];
  level: number[];
  official_rank: number[];
  scores: number[][];
  categories: Category[];
  metrics: Record<string, (number | null)[]>;
  metric_labels: Record<string, string>;
  sourcing: string[] | null;
  complexity: string[] | null;
  exposure_list: number[];
  exposure_eur: number[] | null;
  mismatch: number[];
  residual: (number | null)[];
  bands: Band[];
  features: Record<string, boolean>;
  exposure_rule?: { spend_threshold: number; index_threshold: number };
};

export type CustomIndex = {
  weights_pct: Record<string, number>;
  official: boolean;
  custom_index: number[];
  custom_rank: number[];
  rank_change: number[];
};

export type Contribution = {
  column: string;
  original: string;
  label: string;
  score: number;
  weight_pct: number;
  contribution: number;
  mean_score: number;
  points_above_average: number;
  level: string;
  percentile: number;
};

export type MismatchInfo = {
  flagged: boolean;
  label: string;
  actual_delivery: number | null;
  expected_delivery: number;
  residual: number | null;
  threshold: number;
  explanation: string;
};

export type SupplierDetail = {
  supplierID: string;
  name: string;
  total_risk_index: number;
  level: string;
  official_rank: number;
  percentile: number;
  formula_status: string;
  formula_label: string;
  approximate: boolean;
  weighted_sum: number;
  average_index: number;
  points_above_average_total: number;
  contributions: Contribution[];
  drivers: Contribution[];
  note: string;
  metrics: { column: string; original: string; value: number | null; percentile: number | null }[];
  exposure_eur?: number;
  exposure_list: boolean;
  delivery_mismatch: boolean;
  mismatch: MismatchInfo | null;
  sourcing_risk_level?: string;
  supply_chain_complexity?: string;
};

export type CompareSupplier = {
  supplierID: string;
  name: string;
  total_risk_index: number;
  level: string;
  official_rank: number;
  scores: Record<string, { score: number; level: string }>;
  custom_index?: number;
  custom_rank?: number;
  rank_change?: number;
  [metric: string]: unknown;
};

export type CompareData = {
  suppliers: CompareSupplier[];
  categories: (Category & { spread_sd: number; range: number })[];
  most_different: string[];
  custom_weights: Record<string, number> | null;
  metrics: { column: string; original: string }[];
  bands: Band[];
  formula: string;
};

export type WhyData = {
  a: string;
  b: string;
  threshold: number;
  index_a: number;
  index_b: number;
  index_gap: number;
  explained_by_listed: number;
  custom_gap?: number;
  approximate: boolean;
  note: string;
  differences: {
    column: string;
    label: string;
    score_a: number;
    score_b: number;
    difference: number;
    better: string;
    weight_pct: number;
    effect_official: number;
    weight_custom_pct?: number;
    effect_custom?: number;
  }[];
};
