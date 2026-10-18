import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { Badge, LevelChip, Spinner } from "../components/ui";

type Finding = {
  id: string;
  url: string;
  title: string;
  domain: string;
  quote: string;
  classification: "red_flag" | "neutral" | "positive";
  category: string;
  severity: string;
  summary: string;
  date: string;
  followup_of: string | null;
  single_source?: boolean;
  corroborated_by?: string[];
};
type SanctionsMatch = { status: string; score: number; matched_name: string; list: string; entry_id: string; entry_name: string; type: string; programs: string; country: string; url: string };
type Sanctions = { status: string; available: boolean; note: string; matches: SanctionsMatch[]; lists: { list: string; entries: number; downloaded_at: string; available: boolean }[] };
export type Report = {
  id: string;
  company: string;
  country: string;
  website: string;
  research_date: string;
  executive_summary: string;
  overall_level: string;
  categories: { key: string; label: string; level: string; red_flags: number; positives: number; evidence: Finding[]; queries: { query: string; results: number }[]; basis: string }[];
  searched_without_findings: { key: string; label: string; queries: string[] }[];
  sanctions: Sanctions;
  confidence: { level: string; reasons: string[] };
  verification: { kept: number; dropped_unsourced: (Finding & { reason: string })[]; rejected_during_triage: { url: string; quote: string; reason: string }[]; single_source: string[] };
  searches_used: number;
  search_budget: number;
};
type ReportSummary = { id: string; company: string; country: string; research_date: string; overall_level: string; confidence: string };

type Step =
  | { kind: "plan"; plan: { angle: string; label: string; query: string; why: string }[] }
  | { kind: "search"; angle: string; query: string; n: number; results: number; lead: string | null; error?: string }
  | { kind: "extract"; urls: string[]; ok: string[] }
  | { kind: "finding"; finding: Finding }
  | { kind: "dig"; finding_id: string; lead: string; queries: string[] }
  | { kind: "sanctions"; result: Sanctions }
  | { kind: "verify"; result: Report["verification"] }
  | { kind: "log"; message: string }
  | { kind: "error"; message: string };

const LEVELS = ["Low", "Medium", "High", "Critical"];

export default function Research() {
  const [company, setCompany] = useState("");
  const [country, setCountry] = useState("");
  const [website, setWebsite] = useState("");
  const [running, setRunning] = useState(false);
  const [steps, setSteps] = useState<Step[]>([]);
  const [report, setReport] = useState<Report | null>(null);
  const [past, setPast] = useState<ReportSummary[]>([]);
  const es = useRef<EventSource | null>(null);

  const loadPast = () => api.get<ReportSummary[]>("/api/research").then(setPast).catch(() => setPast([]));
  useEffect(() => {
    loadPast();
    return () => es.current?.close();
  }, []);

  function start(e: React.FormEvent) {
    e.preventDefault();
    if (running || company.trim().length < 2) return;
    es.current?.close();
    setSteps([]);
    setReport(null);
    setRunning(true);
    const qs = new URLSearchParams({ company: company.trim(), country: country.trim(), website: website.trim() });
    const src = new EventSource(`/api/research/stream?${qs}`);
    es.current = src;
    const add = (s: Step) => setSteps((cur) => [...cur, s]);
    const on = (type: string, fn: (d: Record<string, unknown>) => void) =>
      src.addEventListener(type, (ev) => {
        const data = (ev as MessageEvent).data;
        if (typeof data === "string" && data) fn(JSON.parse(data));
      });
    on("plan", (d) => add({ kind: "plan", plan: d.plan as never }));
    on("search", (d) => add({ ...d, kind: "search" } as Step));
    on("extract", (d) => add({ kind: "extract", urls: d.urls as string[], ok: d.ok as string[] }));
    on("finding", (d) => add({ kind: "finding", finding: d.finding as Finding }));
    on("dig", (d) => add({ ...d, kind: "dig" } as Step));
    on("sanctions", (d) => add({ kind: "sanctions", result: d.result as Sanctions }));
    on("verify", (d) => add({ kind: "verify", result: d.result as never }));
    on("log", (d) => add({ kind: "log", message: String(d.message) }));
    on("error", (d) => add({ kind: "error", message: String(d.message) }));
    on("report", (d) => setReport(d.report as Report));
    on("done", () => {
      src.close();
      setRunning(false);
      loadPast();
    });
    src.onerror = () => {
      if (src.readyState === EventSource.CLOSED || src.readyState === EventSource.CONNECTING) {
        src.close();
        setRunning(false);
      }
    };
  }

  return (
    <div className="mx-auto grid max-w-[1400px] grid-cols-[340px_1fr] gap-4 p-4">
      <div className="space-y-4">
        <form onSubmit={start} className="card space-y-3 p-4">
          <div>
            <h1 className="text-lg font-semibold">Research a real company</h1>
            <p className="text-xs text-ink-3">Web research across 8 risk angles, with sanctions screening. Every link comes from a search result. At most 25 searches per run.</p>
          </div>
          <label className="block text-sm">
            <span className="mb-1 block font-medium">Company name</span>
            <input className="input w-full" value={company} onChange={(e) => setCompany(e.target.value)} placeholder="e.g. Stadler Rail" required minLength={2} maxLength={120} data-testid="research-company" />
          </label>
          <div className="grid grid-cols-2 gap-2">
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Country</span>
              <input className="input w-full" value={country} onChange={(e) => setCountry(e.target.value)} placeholder="optional" maxLength={60} />
            </label>
            <label className="block text-sm">
              <span className="mb-1 block font-medium">Website</span>
              <input className="input w-full" value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="optional" maxLength={200} />
            </label>
          </div>
          <button className="btn-primary w-full justify-center" disabled={running || company.trim().length < 2}>
            {running ? "Researching…" : "Start research"}
          </button>
        </form>

        <section className="card p-4">
          <h2 className="mb-2 text-sm font-semibold">Saved reports</h2>
          {!past.length && <p className="text-xs text-ink-3">None yet. Reports can be attached to the shortlist memo.</p>}
          <ul className="space-y-1">
            {past.map((r) => (
              <li key={r.id} className="flex items-center gap-2 text-sm">
                <button className="flex-1 truncate text-left hover:text-accent" onClick={() => api.get<Report>(`/api/research/${r.id}`).then((x) => { setReport(x); setSteps([]); })}>
                  {r.company} <span className="text-xs text-ink-3">{r.research_date}</span>
                </button>
                <LevelChip size="xs" level={r.overall_level} />
                <button
                  className="btn-ghost text-xs"
                  aria-label={`Delete report ${r.company}`}
                  onClick={async () => {
                    await api.del(`/api/research/${r.id}`);
                    if (report?.id === r.id) setReport(null);
                    loadPast();
                  }}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        </section>

        {steps.length > 0 && <Trace steps={steps} running={running} />}
      </div>

      <div className="min-w-0">
        {!report && !running && (
          <div className="card flex h-64 items-center justify-center p-6 text-center text-sm text-ink-3">
            Enter a company to start. Progress streams on the left; the report appears here.
          </div>
        )}
        {!report && running && (
          <div className="card p-6">
            <Spinner label="Running the research plan…" />
            <LiveFindings steps={steps} />
          </div>
        )}
        {report && <ReportView report={report} />}
      </div>
    </div>
  );
}

function Trace({ steps, running }: { steps: Step[]; running: boolean }) {
  const searches = steps.filter((s) => s.kind === "search").length;
  return (
    <section className="card p-4" data-testid="research-trace">
      <h2 className="mb-2 flex items-center gap-2 text-sm font-semibold">
        Research trace <span className="num text-xs font-normal text-ink-3">{searches}/25 searches</span>
        {running && <Spinner />}
      </h2>
      <ol className="max-h-[60vh] space-y-1.5 overflow-y-auto text-xs">
        {steps.map((s, i) => {
          if (s.kind === "plan")
            return (
              <li key={i}>
                <div className="font-medium text-ink">1 · Plan ({s.plan.length} angles)</div>
                <ul className="ml-3 list-disc text-ink-2">
                  {s.plan.map((p) => <li key={p.angle}><span className="font-medium">{p.label}:</span> <code className="text-[11px]">{p.query}</code></li>)}
                </ul>
              </li>
            );
          if (s.kind === "search")
            return (
              <li key={i} className={s.lead ? "ml-4 border-l-2 border-accent pl-2" : ""}>
                <span className="num text-ink-3">#{s.n}</span> {s.lead ? <>follow-up on <b>{s.lead}</b>: </> : <>search <b>{s.angle}</b>: </>}
                <code className="text-[11px]">{s.query}</code> → <span className="num">{s.results}</span> results{s.error && <span className="text-lv-high"> ({s.error})</span>}
              </li>
            );
          if (s.kind === "extract") return <li key={i} className="text-ink-3">extracted full text from {s.ok.length}/{s.urls.length} pages</li>;
          if (s.kind === "finding")
            return (
              <li key={i} className="text-ink-2">
                <ClassBadge c={s.finding.classification} /> <b>{s.finding.id}</b> {s.finding.summary}
              </li>
            );
          if (s.kind === "dig") return <li key={i} className="font-medium text-accent-strong">Dig deeper on {s.finding_id}: {s.lead}</li>;
          if (s.kind === "sanctions") return <li key={i}>Sanctions screening: <b>{s.result.status}</b></li>;
          if (s.kind === "verify")
            return (
              <li key={i}>
                Verify: kept {s.result.kept}, dropped {s.result.dropped_unsourced.length} unsourced, {s.result.rejected_during_triage.length} misquotes rejected, {s.result.single_source.length} single-source
              </li>
            );
          if (s.kind === "error") return <li key={i} className="text-lv-high">Error: {s.message}</li>;
          return <li key={i} className="text-ink-3">{s.message}</li>;
        })}
      </ol>
    </section>
  );
}

function LiveFindings({ steps }: { steps: Step[] }) {
  const f = steps.filter((s): s is Extract<Step, { kind: "finding" }> => s.kind === "finding");
  if (!f.length) return null;
  return (
    <ul className="mt-4 space-y-2 text-sm">
      {f.map((s) => (
        <li key={s.finding.id} className="flex gap-2">
          <ClassBadge c={s.finding.classification} /> <span>“{s.finding.quote}”</span>
        </li>
      ))}
    </ul>
  );
}

function ClassBadge({ c }: { c: Finding["classification"] }) {
  if (c === "red_flag") return <span className="rounded bg-lv-high px-1.5 text-[11px] font-medium text-white">red flag</span>;
  if (c === "positive") return <span className="rounded bg-accent-soft px-1.5 text-[11px] font-medium text-accent-strong">positive</span>;
  return <span className="rounded bg-canvas px-1.5 text-[11px] font-medium text-ink-2">neutral</span>;
}

export function ReportView({ report }: { report: Report }) {
  const cats = [...report.categories].sort((a, b) => LEVELS.indexOf(b.level) - LEVELS.indexOf(a.level));
  return (
    <article className="space-y-4" data-testid="research-report">
      <header className="card p-5">
        <div className="flex flex-wrap items-center gap-3">
          <h2 className="text-xl font-semibold">{report.company}</h2>
          {report.country && <span className="text-sm text-ink-3">{report.country}</span>}
          <LevelChip level={report.overall_level} />
          <Badge>Confidence: {report.confidence.level}</Badge>
          <span className="ml-auto text-xs text-ink-3">
            Research date {report.research_date} · {report.searches_used}/{report.search_budget} searches
          </span>
        </div>
        <h3 className="mt-3 text-sm font-semibold">Executive summary</h3>
        <p className="mt-1 text-sm leading-relaxed text-ink-2">{report.executive_summary}</p>
        <details className="mt-2 text-xs text-ink-3">
          <summary className="cursor-pointer">Why this confidence</summary>
          <ul className="ml-4 list-disc">{report.confidence.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        </details>
      </header>

      <section className="card p-4">
        <h3 className="mb-2 font-semibold">Sanctions screening</h3>
        <p className="text-sm">
          Status: <b>{report.sanctions.status}</b>
        </p>
        <p className="text-xs text-ink-3">{report.sanctions.note}</p>
        <p className="mt-1 text-xs text-ink-3">
          Lists: {report.sanctions.lists.map((l) => `${l.list} (${l.available ? `${l.entries.toLocaleString()} entries, ${l.downloaded_at?.slice(0, 10)}` : "unavailable"})`).join(" · ")}
        </p>
        {report.sanctions.matches.length > 0 && (
          <table className="mt-2 w-full text-sm">
            <thead>
              <tr className="text-left text-xs text-ink-3">
                <th className="py-1 font-medium">Status</th>
                <th className="py-1 font-medium">List entry</th>
                <th className="py-1 font-medium">Matched name</th>
                <th className="py-1 font-medium">Programme</th>
                <th className="py-1 text-right font-medium">Similarity</th>
              </tr>
            </thead>
            <tbody>
              {report.sanctions.matches.map((m) => (
                <tr key={m.list + m.entry_id} className="border-t border-line">
                  <td className="py-1"><Badge tone="warn">{m.status}</Badge></td>
                  <td className="py-1">
                    {m.list} #{m.entry_id}: {m.url ? <a className="text-accent underline" href={m.url} target="_blank" rel="noopener noreferrer nofollow">{m.entry_name}</a> : m.entry_name}
                    <span className="text-xs text-ink-3"> ({m.type})</span>
                  </td>
                  <td className="py-1">{m.matched_name}</td>
                  <td className="py-1 text-xs">{m.programs}</td>
                  <td className="num py-1 text-right">{m.score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="space-y-3">
        {cats.map((c) => (
          <div key={c.key} className="card p-4">
            <div className="flex items-center gap-2">
              <h3 className="font-semibold">{c.label}</h3>
              <LevelChip level={c.level} />
              <span className="text-xs text-ink-3">{c.basis}</span>
              <span className="ml-auto text-xs text-ink-3">{c.queries.length} searches</span>
            </div>
            {c.evidence.length === 0 ? (
              <p className="mt-1 text-sm text-ink-3">No findings.</p>
            ) : (
              <ul className="mt-2 space-y-2">
                {c.evidence.map((f) => (
                  <li key={f.id} className="rounded-md border border-line p-2.5 text-sm">
                    <div className="flex flex-wrap items-center gap-1.5 text-xs">
                      <b>{f.id}</b>
                      <ClassBadge c={f.classification} />
                      {f.classification === "red_flag" && <span className="text-ink-2">severity {f.severity}</span>}
                      {f.single_source ? <Badge tone="warn">single source</Badge> : <Badge tone="accent">corroborated by {f.corroborated_by?.join(", ")}</Badge>}
                      {f.followup_of && <Badge>follow-up on {f.followup_of}</Badge>}
                      {f.date && <span className="text-ink-3">{f.date}</span>}
                    </div>
                    <blockquote className="mt-1 border-l-2 border-line-2 pl-2 text-ink">“{f.quote}”</blockquote>
                    <a className="mt-1 inline-block break-all text-xs text-accent underline" href={f.url} target="_blank" rel="noopener noreferrer nofollow">
                      {f.title || f.domain} · {f.domain}
                    </a>
                  </li>
                ))}
              </ul>
            )}
          </div>
        ))}
      </section>

      <section className="card p-4 text-sm">
        <h3 className="mb-1 font-semibold">Searched without findings</h3>
        {report.searched_without_findings.length === 0 ? (
          <p className="text-ink-3">Every angle produced at least one finding.</p>
        ) : (
          <ul className="ml-4 list-disc text-ink-2">
            {report.searched_without_findings.map((s) => (
              <li key={s.key}>
                <b>{s.label}</b>: {s.queries.map((q) => <code key={q} className="mr-1 text-[11px]">{q}</code>)}
              </li>
            ))}
          </ul>
        )}
        {(report.verification.dropped_unsourced.length > 0 || report.verification.rejected_during_triage.length > 0) && (
          <details className="mt-2 text-xs text-ink-3">
            <summary className="cursor-pointer">
              Claims removed by verification ({report.verification.dropped_unsourced.length + report.verification.rejected_during_triage.length})
            </summary>
            <ul className="ml-4 list-disc">
              {[...report.verification.dropped_unsourced, ...report.verification.rejected_during_triage].map((d, i) => (
                <li key={i}>{d.reason}: “{d.quote}”</li>
              ))}
            </ul>
          </details>
        )}
      </section>
    </article>
  );
}
