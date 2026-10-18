import { useEffect, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../lib/store";
import Markdown from "../components/Markdown";
import { weightsLabel } from "../components/WeightsBar";
import SupplierPicker from "../components/SupplierPicker";
import { Badge, LevelChip, Spinner } from "../components/ui";

type ReportSummary = { id: string; company: string; research_date: string; overall_level: string; confidence: string };
type MemoResult = { markdown: string; prose: { source: string; removed: string[] } };

export default function Memo() {
  const { compare, weights, isOfficial, presetKey, meta, notify } = useStore();
  const presets = meta && meta.loaded ? meta.presets : [];
  const presetName = isOfficial ? "Official index" : weightsLabel(presetKey, presets);
  const presetWhy = presets.find((p) => p.key === presetKey)?.why ?? "";
  // The memo needs a shortlist: prompt for one as soon as the tab opens with none selected.
  const [picking, setPicking] = useState(() => !compare.length);
  const [title, setTitle] = useState("Supplier shortlist memo");
  const [rationale, setRationale] = useState(presetWhy);
  const [reports, setReports] = useState<ReportSummary[]>([]);
  const [attach, setAttach] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [memo, setMemo] = useState<MemoResult | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    api.get<ReportSummary[]>("/api/research").then(setReports).catch(() => setReports([]));
  }, []);
  useEffect(() => setRationale(presetWhy), [presetWhy]);

  async function generate() {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.post<MemoResult>("/api/memo", {
        ids: compare,
        weights: isOfficial ? null : weights,
        preset_label: presetName,
        rationale,
        research_ids: attach,
        title,
      });
      setMemo(r);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed");
    } finally {
      setBusy(false);
    }
  }

  const fileBase = title.replace(/[^A-Za-z0-9_-]+/g, "-").replace(/^-|-$/g, "") || "shortlist-memo";

  function downloadMd() {
    if (!memo) return;
    const blob = new Blob([memo.markdown], { type: "text/markdown;charset=utf-8" });
    save(blob, `${fileBase}.md`);
  }

  async function downloadPdf() {
    if (!memo) return;
    const res = await fetch("/api/memo/pdf", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ markdown: memo.markdown, filename: fileBase }),
    });
    if (!res.ok) {
      notify("PDF export failed.");
      return;
    }
    save(await res.blob(), `${fileBase}.pdf`);
  }

  if (!compare.length)
    return (
      <div className="mx-auto max-w-xl p-10 text-center">
        <h1 className="text-xl font-semibold">No shortlist yet</h1>
        <p className="mt-2 text-sm text-ink-2">The memo is built from your compare set. Select the suppliers to shortlist first.</p>
        <button className="btn-primary mt-4" onClick={() => setPicking(true)}>Select suppliers</button>
        {picking && <SupplierPicker title="Select suppliers for the memo" onClose={() => setPicking(false)} />}
      </div>
    );

  return (
    <div className="mx-auto grid max-w-[1300px] grid-cols-[360px_1fr] gap-4 p-4">
      {picking && <SupplierPicker title="Add suppliers to the memo" onClose={() => setPicking(false)} />}
      <aside className="card h-fit space-y-4 p-4">
        <div>
          <h1 className="text-lg font-semibold">Shortlist memo</h1>
          <p className="text-xs text-ink-3">The assistant writes the prose; every table and number is filled in from the data, and prose sentences with numbers not found in the data are removed.</p>
        </div>
        <label className="block text-sm">
          <span className="mb-1 block font-medium">Title</span>
          <input className="input w-full" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={120} />
        </label>
        <div className="text-sm">
          <div className="mb-1 flex items-center justify-between font-medium">
            Shortlist ({compare.length})
            <button className="btn-ghost text-xs" onClick={() => setPicking(true)}>Add suppliers</button>
          </div>
          <div className="flex flex-wrap gap-1">{compare.map((id) => <Badge key={id}>{id}</Badge>)}</div>
        </div>
        <div className="text-sm">
          <div className="mb-1 font-medium">Weights: {presetName}</div>
          <textarea className="input w-full" rows={4} value={rationale} onChange={(e) => setRationale(e.target.value)} placeholder="Why these weights? (goes into the memo)" maxLength={2000} />
          <p className="text-xs text-ink-3">Change weights on the Explore page.</p>
        </div>
        <div className="text-sm">
          <div className="mb-1 font-medium">Attach research reports</div>
          {!reports.length && <p className="text-xs text-ink-3">No reports yet. Run one on the Research page.</p>}
          {reports.map((r) => (
            <label key={r.id} className="flex items-center gap-2 py-0.5">
              <input type="checkbox" className="accent-[var(--color-accent)]" checked={attach.includes(r.id)} onChange={() => setAttach((a) => (a.includes(r.id) ? a.filter((x) => x !== r.id) : [...a, r.id]))} />
              <span className="flex-1 truncate">{r.company}</span>
              <LevelChip size="xs" level={r.overall_level} />
                          </label>
          ))}
        </div>
        <button className="btn-primary w-full justify-center" onClick={generate} disabled={busy} data-testid="memo-generate">
          {busy ? "Writing…" : memo ? "Regenerate memo" : "Generate memo"}
        </button>
        {err && <p className="text-sm text-lv-high">{err}</p>}
      </aside>

      <section className="card min-h-[400px] p-6">
        {busy && <Spinner label="Writing the memo…" />}
        {!busy && !memo && <p className="text-sm text-ink-3">The memo preview appears here.</p>}
        {memo && !busy && (
          <>
            <div className="mb-4 flex items-center gap-2 border-b border-line pb-3">
              <span className="text-xs text-ink-3">
                Prose by {memo.prose.source}
                {memo.prose.removed.length > 0 && ` · ${memo.prose.removed.length} sentence(s) removed by the number check`}
              </span>
              <button className="btn ml-auto" onClick={downloadMd} data-testid="memo-md">Download Markdown</button>
              <button className="btn-primary" onClick={downloadPdf} data-testid="memo-pdf">Download PDF</button>
            </div>
            <div className="text-[14px] leading-relaxed" data-testid="memo-preview">
              <Markdown text={memo.markdown} />
            </div>
          </>
        )}
      </section>
    </div>
  );
}

function save(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
