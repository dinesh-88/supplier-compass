import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, type CustomIndex, type DatasetMeta, type SuppliersData } from "./api";

export type Me = { user: string; llm_configured: boolean; search_configured: boolean; model: string };

export type Range = [number, number];
export type Filters = {
  text: string;
  index: Range;
  scores: Record<string, Range>;
  spend: Range | null; // log10 EUR
  delivery: Range | null;
  confirmation: Range | null;
  changeRate: Range | null;
  sourcing: string[];
  complexity: string[];
  exposureOnly: boolean;
  mismatchOnly: boolean;
};

export const MAX_COMPARE = 20;

type ChatState = { open: boolean; contextIds: string[]; seed: string | null; nonce: number };

type Store = {
  me: Me | null | undefined;
  setMe: (m: Me | null) => void;
  meta: DatasetMeta | { loaded: false } | null;
  refreshMeta: () => Promise<void>;
  data: SuppliersData | null;
  weights: Record<string, number>;
  presetKey: string;
  setWeights: (w: Record<string, number>, presetKey?: string) => void;
  custom: CustomIndex | null;
  isOfficial: boolean;
  compare: string[];
  toggleCompare: (id: string) => boolean;
  addCompare: (ids: string[]) => number;
  removeCompare: (id: string) => void;
  clearCompare: () => void;
  /** Replaces the whole compare set, e.g. from the supplier picker. */
  setCompareSet: (ids: string[]) => void;
  /** True while the compare set was restored from a previous session and not yet confirmed or changed. */
  compareRestored: boolean;
  confirmCompare: () => void;
  drawerId: string | null;
  openDrawer: (id: string | null) => void;
  chat: ChatState;
  openChat: (contextIds?: string[], seed?: string) => void;
  closeChat: () => void;
  filters: Filters | null;
  setFilters: (f: Filters) => void;
  toast: string | null;
  notify: (msg: string) => void;
};

const Ctx = createContext<Store | null>(null);

export function useStore(): Store {
  const s = useContext(Ctx);
  if (!s) throw new Error("StoreProvider missing");
  return s;
}

function loadLocal<T>(key: string, fallback: T): T {
  try {
    const raw = localStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : fallback;
  } catch {
    return fallback;
  }
}
function saveLocal(key: string, value: unknown) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage unavailable */
  }
}

export function StoreProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  const [meta, setMeta] = useState<DatasetMeta | { loaded: false } | null>(null);
  const [data, setData] = useState<SuppliersData | null>(null);
  const [weights, setWeightsState] = useState<Record<string, number>>({});
  const [presetKey, setPresetKey] = useState("official");
  const [custom, setCustom] = useState<CustomIndex | null>(null);
  const [compare, setCompareState] = useState<string[]>([]);
  const [compareRestored, setCompareRestored] = useState(false);
  // Any change by the user counts as confirming the set.
  const setCompare = useCallback((next: string[] | ((cur: string[]) => string[])) => {
    setCompareState(next);
    setCompareRestored(false);
  }, []);
  const [drawerId, setDrawerId] = useState<string | null>(null);
  const [chat, setChat] = useState<ChatState>({ open: false, contextIds: [], seed: null, nonce: 0 });
  const [filters, setFilters] = useState<Filters | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<number | undefined>(undefined);
  const hydratedKey = useRef<string | null>(null);

  useEffect(() => {
    api
      .get<Me>("/api/me")
      .then(setMe)
      .catch(() => setMe(null));
  }, []);

  const refreshMeta = useCallback(async () => {
    const m = await api.get<DatasetMeta | { loaded: false }>("/api/dataset");
    if (m.loaded) {
      // Set meta together with the restored compare set, so pages never mount with an empty set that then fills in.
      const d = await api.get<SuppliersData>("/api/suppliers").catch((e) => {
        setMeta(m);
        throw e;
      });
      setMeta(m);
      setData(d);
      const key = `sc:${me?.user}:${m.uploaded_at}`;
      const saved = loadLocal<{ weights?: Record<string, number>; presetKey?: string; compare?: string[] }>(key, {});
      const valid = saved.weights && Object.keys(m.formula.weights).every((c) => typeof saved.weights![c] === "number");
      setWeightsState(valid ? saved.weights! : m.formula.weights);
      setPresetKey(valid ? (saved.presetKey ?? "custom") : "official");
      setCustom(null);
      setFilters(null);
      const ids = new Set(d.ids);
      const restored = (saved.compare ?? []).filter((id) => ids.has(id));
      setCompareState(restored);
      setCompareRestored(restored.length > 0);
      hydratedKey.current = key;
    } else {
      setMeta(m);
      hydratedKey.current = null;
      setData(null);
      setCompare([]);
    }
  }, [me?.user]);

  useEffect(() => {
    if (me) refreshMeta().catch(() => setMeta({ loaded: false }));
    else {
      setMeta(null);
      setData(null);
    }
  }, [me, refreshMeta]);

  useEffect(() => {
    // Only after this dataset's saved state has been restored, so a reload never overwrites it.
    if (!meta || !meta.loaded || !me) return;
    const key = `sc:${me.user}:${meta.uploaded_at}`;
    if (hydratedKey.current === key) saveLocal(key, { compare, weights, presetKey });
  }, [compare, weights, presetKey, meta, me]);

  const isOfficial = useMemo(() => {
    if (!meta || !meta.loaded || !Object.keys(weights).length) return true;
    const off = meta.formula.weights;
    const total = Object.values(weights).reduce((a, b) => a + b, 0) || 1;
    return Object.keys(off).every((k) => Math.abs(((weights[k] ?? 0) / total) * 100 - off[k]) < 0.01);
  }, [weights, meta]);

  // Custom index from the backend, debounced while sliders move.
  useEffect(() => {
    if (!meta || !meta.loaded || isOfficial) {
      setCustom(null);
      return;
    }
    const t = window.setTimeout(() => {
      api
        .post<CustomIndex>("/api/custom-index", { weights })
        .then(setCustom)
        .catch(() => setCustom(null));
    }, 250);
    return () => window.clearTimeout(t);
  }, [weights, isOfficial, meta]);

  const notify = useCallback((msg: string) => {
    setToast(msg);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 3200);
  }, []);

  const compareRef = useRef<string[]>([]);
  compareRef.current = compare;

  const toggleCompare = useCallback(
    (id: string) => {
      const cur = compareRef.current;
      if (cur.includes(id)) {
        setCompare(cur.filter((x) => x !== id));
        return true;
      }
      if (cur.length >= MAX_COMPARE) {
        notify(`The compare set is full (${MAX_COMPARE} suppliers).`);
        return false;
      }
      setCompare([...cur, id]);
      return true;
    },
    [notify],
  );

  const addCompare = useCallback((ids: string[]) => {
    const next = [...compareRef.current];
    let added = 0;
    for (const id of ids) {
      if (next.includes(id)) continue;
      if (next.length >= MAX_COMPARE) break;
      next.push(id);
      added++;
    }
    compareRef.current = next;
    setCompare(next);
    return added;
  }, []);

  const value: Store = {
    me,
    setMe,
    meta,
    refreshMeta,
    data,
    weights,
    presetKey,
    setWeights: (w, key) => {
      setWeightsState(w);
      setPresetKey(key ?? "custom");
    },
    custom,
    isOfficial,
    compare,
    toggleCompare,
    addCompare,
    removeCompare: (id) => setCompare((c) => c.filter((x) => x !== id)),
    clearCompare: () => setCompare([]),
    setCompareSet: (ids) => setCompare(ids.slice(0, MAX_COMPARE)),
    compareRestored,
    confirmCompare: () => setCompareRestored(false),
    drawerId,
    openDrawer: setDrawerId,
    chat,
    openChat: (contextIds = [], seed) =>
      setChat((c) => ({ open: true, contextIds, seed: seed ?? null, nonce: c.nonce + 1 })),
    closeChat: () => setChat((c) => ({ ...c, open: false })),
    filters,
    setFilters,
    toast,
    notify,
  };
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
