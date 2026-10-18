import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { MAX_COMPARE, useStore } from "../lib/store";
import { Modal } from "./ui";

/** Prompts for suppliers and adds the picks to the compare set, which the Compare, Analyses and Memo pages run on. */
export default function SupplierPicker({ title, min = 1, onClose }: { title: string; min?: number; onClose: () => void }) {
  const { data, compare, addCompare } = useStore();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [picked, setPicked] = useState<string[]>([]);
  const room = MAX_COMPARE - compare.length;
  const rows = useMemo(() => {
    if (!data) return [];
    const t = q.trim().toLowerCase();
    const out: number[] = [];
    for (let i = 0; i < data.ids.length && out.length < 200; i++) {
      if (compare.includes(data.ids[i])) continue;
      if (!t || data.ids[i].toLowerCase().includes(t) || (data.names[i] ?? "").toLowerCase().includes(t)) out.push(i);
    }
    return out;
  }, [q, data, compare]);
  const toggle = (id: string) =>
    setPicked((cur) => (cur.includes(id) ? cur.filter((x) => x !== id) : cur.length < room ? [...cur, id] : cur));
  const total = compare.length + picked.length;

  return (
    <Modal title={title} onClose={onClose} width={560}>
      <p className="mb-2 text-xs text-ink-3">
        Suppliers go into the compare set. Pick at least {min} supplier{min === 1 ? "" : "s"} (up to {MAX_COMPARE} in total).
      </p>
      <input className="input mb-2 w-full" placeholder="Search by ID or name" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
      {!data ? (
        <p className="px-3 py-2 text-sm text-ink-3">Loading suppliers…</p>
      ) : (
        <ul className="max-h-[45vh] divide-y divide-line overflow-auto rounded-md border border-line" data-testid="supplier-picker">
          {rows.map((i) => {
            const id = data.ids[i];
            const on = picked.includes(id);
            return (
              <li key={id}>
                <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-canvas">
                  <input type="checkbox" className="accent-[var(--color-accent)]" checked={on} disabled={!on && picked.length >= room} onChange={() => toggle(id)} />
                  <span className="font-medium">{id}</span>
                  <span className="truncate text-ink-2">{data.names[i]}</span>
                  <span className="num ml-auto text-xs text-ink-3">{data.index[i]?.toFixed(2)}</span>
                </label>
              </li>
            );
          })}
          {!rows.length && <li className="px-3 py-2 text-sm text-ink-3">No matching suppliers.</li>}
        </ul>
      )}
      <div className="mt-3 flex items-center gap-2">
        <button className="btn-ghost text-xs" onClick={() => nav("/explore")}>Browse in Explore instead</button>
        <span className="ml-auto text-xs text-ink-3">{total} selected</span>
        <button className="btn" onClick={onClose}>Cancel</button>
        <button
          className="btn-primary"
          disabled={!picked.length || total < min}
          onClick={() => {
            addCompare(picked);
            onClose();
          }}
          data-testid="confirm-suppliers"
        >
          Use selected
        </button>
      </div>
    </Modal>
  );
}
