import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, ApiError, type DatasetMeta, type Report } from "../lib/api";
import { useStore } from "../lib/store";
import { Badge, LevelLegend, Modal, Spinner } from "../components/ui";

type Pending = { kind: "upload"; csv: File; md: File | null } | { kind: "sample" };

export default function Upload() {
  const { meta, refreshMeta, notify } = useStore();
  const nav = useNavigate();
  const [csv, setCsv] = useState<File | null>(null);
  const [md, setMd] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<{ error: string; report: Report } | null>(null);
  const [confirm, setConfirm] = useState<Pending | null>(null);
  const [showDesc, setShowDesc] = useState<string | null>(null);
  const loaded = !!meta && meta.loaded;

  async function run(p: Pending, replace: boolean) {
    setBusy(true);
    setFailed(null);
    try {
      if (p.kind === "sample") {
        await api.post("/api/dataset/sample", { replace });
      } else {
        const fd = new FormData();
        fd.append("csv", p.csv);
        if (p.md) fd.append("descriptions_md", p.md);
        fd.append("replace", String(replace));
        await api.post("/api/dataset/upload", fd);
      }
      await refreshMeta();
      setCsv(null);
      setMd(null);
      notify("Dataset loaded.");
    } catch (e) {
      if (e instanceof ApiError && e.status === 422 && e.body && typeof e.body === "object" && "report" in e.body) {
        const b = e.body as { error: string; report: Report };
        setFailed({ error: b.error, report: b.report });
      } else {
        setFailed({ error: e instanceof Error ? e.message : "Upload failed", report: { errors: [], warnings: [], notices: [] } });
      }
    } finally {
      setBusy(false);
    }
  }

  function start(p: Pending) {
    if (loaded) setConfirm(p);
    else run(p, false);
  }

  return (
    <div className="mx-auto max-w-6xl p-6">
      <div className="mb-5 flex items-end justify-between">
        <div>
          <h1 className="text-xl font-semibold">Supplier data</h1>
          <p className="text-sm text-ink-2">
            Upload a supplier risk CSV (same structure as the challenge's <code>supplier_risk_dataset.csv</code>). Your data stays in your own workspace.
          </p>
        </div>
        {loaded && (
          <button className="btn-primary" onClick={() => nav("/explore")}>
            Go to Explore →
          </button>
        )}
      </div>

      <div className="grid grid-cols-[1fr_1fr_260px] gap-4">
        <DropZone
          title="Supplier dataset"
          hint="CSV, required · max 50 MB"
          accept=".csv,text/csv"
          file={csv}
          onFile={setCsv}
          testId="drop-csv"
        />
        <DropZone
          title="Column descriptions"
          hint="Markdown, optional · used for definitions and the glossary"
          accept=".md,.markdown,text/markdown,text/plain"
          file={md}
          onFile={setMd}
          testId="drop-md"
        />
        <div className="card flex flex-col justify-between p-4">
          <div>
            <div className="text-sm font-semibold">Challenge sample</div>
            <p className="mt-1 text-xs text-ink-2">10,000 synthetic rail suppliers plus the challenge's column descriptions. One click for the jury.</p>
          </div>
          <button className="btn mt-3 justify-center" disabled={busy} onClick={() => start({ kind: "sample" })} data-testid="load-sample">
            Load the challenge sample
          </button>
        </div>
      </div>
      <div className="mt-3 flex items-center gap-3">
        <button className="btn-primary" disabled={!csv || busy} onClick={() => csv && start({ kind: "upload", csv, md })}>
          Validate and load
        </button>
        {busy && <Spinner label="Validating…" />}
        {!md && csv && <span className="text-xs text-ink-3">No descriptions file: the built-in challenge descriptions will be used, labelled as such.</span>}
      </div>

      {failed && (
        <section className="card mt-5 border-lv-high/40 p-4" role="alert">
          <h2 className="font-semibold text-lv-high">Upload not accepted</h2>
          <p className="mt-1 text-sm">{failed.error}</p>
          <ReportView report={failed.report} />
        </section>
      )}

      {loaded && meta.loaded && <CurrentDataset meta={meta} onShowDesc={async () => {
        const d = await api.get<{ text: string; source: string }>("/api/dataset/descriptions");
        setShowDesc(d.text || "(empty)");
      }} />}

      {confirm && (
        <Modal title="Replace the current dataset?" onClose={() => setConfirm(null)}>
          <p className="text-sm text-ink-2">
            This replaces <strong>{loaded && meta.loaded ? meta.file_name : ""}</strong> for your user. Your compare set and custom weights are reset. Research reports are kept.
          </p>
          <div className="mt-4 flex justify-end gap-2">
            <button className="btn" onClick={() => setConfirm(null)}>Cancel</button>
            <button
              className="btn-primary"
              data-testid="confirm-replace"
              onClick={() => {
                const p = confirm;
                setConfirm(null);
                run(p, true);
              }}
            >
              Replace dataset
            </button>
          </div>
        </Modal>
      )}
      {showDesc !== null && (
        <Modal title="Column descriptions (shown as plain text)" onClose={() => setShowDesc(null)} width={760}>
          <pre className="whitespace-pre-wrap font-sans text-sm text-ink-2">{showDesc}</pre>
        </Modal>
      )}
    </div>
  );
}

function DropZone({ title, hint, accept, file, onFile, testId }: { title: string; hint: string; accept: string; file: File | null; onFile: (f: File | null) => void; testId: string }) {
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  return (
    <div
      className={`card flex min-h-[132px] cursor-pointer flex-col items-center justify-center border-2 border-dashed p-4 text-center transition ${over ? "border-accent bg-accent-soft" : "border-line-2"}`}
      onClick={() => input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        e.preventDefault();
        setOver(false);
        const f = e.dataTransfer.files?.[0];
        if (f) onFile(f);
      }}
      data-testid={testId}
    >
      <input ref={input} type="file" accept={accept} className="hidden" onChange={(e) => onFile(e.target.files?.[0] ?? null)} />
      <div className="text-sm font-semibold">{title}</div>
      <div className="mt-1 text-xs text-ink-3">{hint}</div>
      {file ? (
        <div className="mt-3 flex items-center gap-2 text-sm">
          <span className="max-w-[260px] truncate font-medium text-accent-strong">{file.name}</span>
          <span className="num text-xs text-ink-3">{(file.size / 1024 / 1024).toFixed(1)} MB</span>
          <button
            className="btn-ghost text-xs"
            onClick={(e) => {
              e.stopPropagation();
              onFile(null);
            }}
          >
            Remove
          </button>
        </div>
      ) : (
        <div className="mt-3 text-xs text-ink-2">Drop a file here or click to choose</div>
      )}
    </div>
  );
}

function CurrentDataset({ meta, onShowDesc }: { meta: DatasetMeta; onShowDesc: () => void }) {
  const f = meta.formula;
  const cats = [...meta.categories].sort((a, b) => b.weight_pct - a.weight_pct);
  return (
    <div className="mt-6 grid grid-cols-[1.2fr_1fr] gap-4">
      <section className="card p-4">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Loaded: {meta.file_name}</h2>
          <span className="text-xs text-ink-3">{new Date(meta.uploaded_at).toLocaleString()}</span>
        </div>
        <ReportView report={meta.report} />
        <div className="mt-4 border-t border-line pt-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="font-medium">Column descriptions</span>
            <button className="btn-ghost text-xs" onClick={onShowDesc}>View</button>
          </div>
          <p className="text-xs text-ink-2">
            {meta.descriptions.source} · {meta.descriptions.terms} terms
            {meta.descriptions.builtin && <> · <Badge>built-in fallback</Badge></>}
          </p>
        </div>
        <div className="mt-4 border-t border-line pt-3">
          <div className="mb-1 text-sm font-medium">Level bands <span className="text-xs font-normal text-ink-3">({meta.band_source})</span></div>
          <LevelLegend bands={meta.bands} />
        </div>
      </section>

      <section className="card p-4" data-testid="formula">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Total Risk Index formula</h2>
          <Badge tone={f.status === "verified" ? "accent" : "warn"}>{f.label}</Badge>
        </div>
        <p className="mt-1 text-xs text-ink-2">
          Inferred from this file: non-negative least squares of Total_Risk_Index on the score columns, snapped to whole
          percent, then recomputed in integers with {f.rounding}. <strong className="num">{f.rows_matched.toLocaleString()}</strong> of{" "}
          <span className="num">{f.rows_total.toLocaleString()}</span> rows match exactly ({(f.match_share * 100).toFixed(2)}%), R² = <span className="num">{f.r2.toFixed(4)}</span>.
        </p>
        <table className="mt-3 w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-ink-3">
              <th className="py-1 font-medium">Category</th>
              <th className="py-1 text-right font-medium">Weight</th>
              <th className="py-1 text-right font-medium">NNLS fit</th>
            </tr>
          </thead>
          <tbody>
            {cats.map((c) => (
              <tr key={c.column} className="border-t border-line">
                <td className="py-1">{c.label}</td>
                <td className="num py-1 text-right font-medium">{c.weight_pct}%</td>
                <td className="num py-1 text-right text-ink-3">{f.raw_weights[c.column]?.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

function ReportView({ report }: { report: Report }) {
  const missing = Object.entries(report.missing ?? {});
  return (
    <div className="mt-3 space-y-3 text-sm" data-testid="validation-report">
      {report.rows_in_file !== undefined && (
        <div className="grid grid-cols-3 gap-2">
          <Stat label="Rows in file" value={report.rows_in_file} />
          <Stat label="Rows loaded" value={report.rows_loaded ?? 0} />
          <Stat label="Rows dropped" value={report.rows_dropped ?? 0} />
        </div>
      )}
      {report.errors.map((e) => (
        <p key={e} className="text-lv-high">✕ {e}</p>
      ))}
      {report.warnings.map((w) => (
        <p key={w} className="text-warn">⚠ {w}</p>
      ))}
      {report.notices.map((n) => (
        <p key={n} className="text-ink-2">ⓘ {n}</p>
      ))}
      {!!report.dropped?.length && (
        <div>
          <div className="label mb-1">Rows dropped and why</div>
          <table className="w-full text-sm">
            <tbody>
              {report.dropped.map((d) => (
                <tr key={d.reason} className="border-t border-line">
                  <td className="py-1">{d.reason}</td>
                  <td className="num py-1 text-right">{d.count}</td>
                  <td className="py-1 pl-3 text-xs text-ink-3">
                    e.g. {d.examples.map((x) => `row ${x.row}${x.supplierID ? ` (${x.supplierID})` : ""}`).join(", ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div>
        <div className="label mb-1">Missing values per column</div>
        {missing.length ? (
          <div className="flex flex-wrap gap-1.5">
            {missing.map(([c, n]) => (
              <Badge key={c}>{c}: <span className="num">{n}</span></Badge>
            ))}
          </div>
        ) : (
          <p className="text-xs text-ink-2">None.</p>
        )}
      </div>
      {report.score_columns && (
        <p className="text-xs text-ink-2">
          <span className="font-medium text-ink">{report.score_columns.length} score columns</span>, {report.level_columns?.length ?? 0} level columns,{" "}
          {report.optional_present?.length ?? 0} optional columns.
          {!!report.extra_columns?.length && (
            <> Extra columns (kept, not used): {report.extra_columns.join(", ")}.</>
          )}
        </p>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-md bg-canvas px-3 py-2">
      <div className="text-xs text-ink-3">{label}</div>
      <div className="num text-lg font-semibold">{value.toLocaleString()}</div>
    </div>
  );
}
