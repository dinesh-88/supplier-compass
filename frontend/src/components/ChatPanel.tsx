import { useEffect, useRef, useState } from "react";
import { api } from "../lib/api";
import { useStore } from "../lib/store";
import EChart from "./EChart";
import Markdown from "./Markdown";
import { Badge, Spinner } from "./ui";

type TraceEntry = { tool: string; args: Record<string, unknown>; ms: number; error?: string; sql?: string; result?: Record<string, unknown> };
type Chart = { type: string; title: string; option: Record<string, unknown>; source: Record<string, unknown> };
type Action = { type: "add_to_compare"; ids: string[] };
type Reply = { answer: string; trace: TraceEntry[]; charts: Chart[]; actions: Action[]; model: string; error: boolean };
type Msg = { role: "user"; content: string } | ({ role: "assistant"; content: string } & Partial<Reply>);

const SUGGESTIONS = [
  "Why is the Total Risk Index of SUPP_00018 so high?",
  "Which of SUPP_00012, SUPP_00450 and SUPP_00731 has the lowest financial risk?",
  "Compare SUPP_00012, SUPP_00450 and SUPP_00731",
  "Chart the number of suppliers per level",
];

export default function ChatPanel() {
  const { chat, closeChat, addCompare, notify, compare } = useStore();
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [contextIds, setContextIds] = useState<string[]>(chat.contextIds);
  const end = useRef<HTMLDivElement>(null);
  const lastNonce = useRef(-1);

  useEffect(() => {
    if (chat.nonce === lastNonce.current) return;
    lastNonce.current = chat.nonce;
    setContextIds(chat.contextIds);
    if (chat.seed) setInput(chat.seed);
  }, [chat]);

  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [msgs, busy]);

  async function send(text: string) {
    const q = text.trim();
    if (!q || busy) return;
    const next: Msg[] = [...msgs, { role: "user", content: q }];
    setMsgs(next);
    setInput("");
    setBusy(true);
    try {
      const r = await api.post<Reply>("/api/chat", {
        messages: next.map((m) => ({ role: m.role, content: m.content })),
        context_ids: contextIds,
      });
      setMsgs([...next, { role: "assistant", content: r.answer, ...r }]);
    } catch (e) {
      setMsgs([...next, { role: "assistant", content: `Request failed: ${e instanceof Error ? e.message : e}`, error: true }]);
    } finally {
      setBusy(false);
    }
  }

  return (
    <aside className="flex w-[480px] shrink-0 flex-col border-l border-line bg-surface" aria-label="Assistant" data-testid="chat-panel">
      <div className="flex items-center gap-2 border-b border-line px-4 py-3">
        <div className="flex-1">
          <div className="text-sm font-semibold">Ask the data</div>
          <div className="text-xs text-ink-3">Answers come from tool calls on your dataset; open “How I got this” to check.</div>
        </div>
        {msgs.length > 0 && <button className="btn-ghost text-xs" onClick={() => setMsgs([])}>Clear</button>}
        <button className="btn-ghost text-lg" onClick={closeChat} aria-label="Close assistant">×</button>
      </div>
      <div className="flex flex-wrap items-center gap-1 border-b border-line px-4 py-2 text-xs">
        <span className="text-ink-3">Context:</span>
        {contextIds.length ? (
          <>
            {contextIds.slice(0, 8).map((id) => <Badge key={id}>{id}</Badge>)}
            {contextIds.length > 8 && <span className="text-ink-3">+{contextIds.length - 8}</span>}
            <button className="btn-ghost text-xs" onClick={() => setContextIds([])}>clear</button>
          </>
        ) : (
          <>
            <span className="text-ink-3">none</span>
            {compare.length > 0 && <button className="btn-ghost text-xs" onClick={() => setContextIds(compare)}>use compare set ({compare.length})</button>}
          </>
        )}
      </div>
      <div className="flex-1 space-y-4 overflow-y-auto px-4 py-4">
        {msgs.length === 0 && (
          <div className="space-y-2">
            <p className="text-sm text-ink-2">Try one of these:</p>
            {SUGGESTIONS.map((s) => (
              <button key={s} className="block w-full rounded-md border border-line px-3 py-2 text-left text-sm hover:border-accent hover:bg-accent-soft" onClick={() => send(s)}>
                {s}
              </button>
            ))}
          </div>
        )}
        {msgs.map((m, i) =>
          m.role === "user" ? (
            <div key={i} className="ml-10 rounded-lg bg-accent-soft px-3 py-2 text-sm text-ink">{m.content}</div>
          ) : (
            <div key={i} className="text-sm" data-testid="chat-answer">
              <div className={m.error ? "text-lv-high" : ""}>
                <Markdown text={m.content} />
              </div>
              {m.charts?.map((c, j) => (
                <div key={j} className="mt-2 rounded-md border border-line p-2">
                  <EChart option={c.option} height={c.type === "heatmap" ? 300 : 260} ariaLabel={c.title || `${c.type} chart`} />
                </div>
              ))}
              {m.actions?.map((a, j) =>
                a.type === "add_to_compare" ? (
                  <button
                    key={j}
                    className="btn-primary mt-2"
                    data-testid="chat-add-compare"
                    onClick={() => {
                      const n = addCompare(a.ids);
                      notify(n ? `Added ${n} supplier${n > 1 ? "s" : ""} to compare.` : "Already in the compare set (or it is full).");
                    }}
                  >
                    Add {a.ids.length} to compare
                  </button>
                ) : null,
              )}
              {m.trace && <Trace trace={m.trace} model={m.model} />}
            </div>
          ),
        )}
        {busy && <Spinner label="Working…" />}
        <div ref={end} />
      </div>
      <form
        className="flex gap-2 border-t border-line p-3"
        onSubmit={(e) => {
          e.preventDefault();
          send(input);
        }}
      >
        <textarea
          className="input min-h-[42px] flex-1 resize-none"
          rows={2}
          placeholder="Ask about suppliers, scores, or the selection…"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              send(input);
            }
          }}
          aria-label="Question"
          data-testid="chat-input"
        />
        <button className="btn-primary self-end" disabled={busy || !input.trim()} data-testid="chat-send">Send</button>
      </form>
    </aside>
  );
}

function Trace({ trace, model }: { trace: TraceEntry[]; model?: string }) {
  return (
    <details className="mt-2 rounded-md border border-line bg-canvas text-xs" data-testid="how-i-got-this">
      <summary className="cursor-pointer select-none px-3 py-1.5 font-medium text-ink-2">
        How I got this · {trace.length} tool call{trace.length === 1 ? "" : "s"} · {model}
      </summary>
      <div className="space-y-3 border-t border-line px-3 py-2">
        {trace.length === 0 && <p className="text-ink-3">No tools were called.</p>}
        {trace.map((t, i) => (
          <div key={i}>
            <div className="font-medium">
              {i + 1}. <code>{t.tool}</code> <span className="text-ink-3">{t.ms} ms</span>
            </div>
            <pre className="mt-0.5 overflow-x-auto whitespace-pre-wrap rounded bg-surface p-1.5 font-mono text-[11px] text-ink-2">{JSON.stringify(t.args)}</pre>
            {t.sql && <pre className="mt-1 overflow-x-auto whitespace-pre-wrap rounded bg-surface p-1.5 font-mono text-[11px] text-accent-strong">{t.sql}</pre>}
            {t.error ? <p className="mt-1 text-lv-high">Error: {t.error}</p> : <ResultView result={t.result} />}
          </div>
        ))}
      </div>
    </details>
  );
}

function ResultView({ result }: { result?: Record<string, unknown> }) {
  if (!result) return null;
  const cols = result.columns as string[] | undefined;
  const rows = result.rows as unknown[] | undefined;
  if (cols && Array.isArray(rows) && rows.length) {
    const asArray = Array.isArray(rows[0]);
    return (
      <div className="mt-1 max-h-56 overflow-auto rounded border border-line bg-surface">
        <table className="w-full text-[11px]">
          <thead className="sticky top-0 bg-surface">
            <tr>
              {(asArray ? cols : ["supplierID", ...cols]).map((c) => <th key={c} className="border-b border-line px-1.5 py-0.5 text-left font-medium">{c}</th>)}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                {(asArray ? (r as unknown[]) : [(r as Record<string, unknown>).supplierID, ...cols.map((c) => (r as Record<string, unknown>)[c])]).map((v, j) => (
                  <td key={j} className="num border-b border-line px-1.5 py-0.5">{fmt(v)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {!!result.rows_truncated && <p className="px-1.5 py-0.5 text-ink-3">(first rows shown)</p>}
      </div>
    );
  }
  return (
    <pre className="mt-1 max-h-56 overflow-auto whitespace-pre-wrap rounded bg-surface p-1.5 font-mono text-[11px] text-ink-2">{JSON.stringify(result, null, 1)}</pre>
  );
}

const fmt = (v: unknown) => (v === null || v === undefined ? "–" : typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(2)) : String(v));
