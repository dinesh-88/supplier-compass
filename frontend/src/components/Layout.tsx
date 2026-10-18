import { NavLink, Outlet } from "react-router-dom";
import { api } from "../lib/api";
import { useStore } from "../lib/store";
import SupplierDrawer from "./SupplierDrawer";
import ChatPanel from "./ChatPanel";
import { Badge } from "./ui";

export default function Layout() {
  const { me, setMe, meta, compare, openChat, chat, drawerId, toast } = useStore();
  const loaded = !!meta && meta.loaded;

  const link = ({ isActive }: { isActive: boolean }) =>
    `rounded-md px-3 py-1.5 text-sm font-medium ${isActive ? "bg-accent-soft text-accent-strong" : "text-ink-2 hover:bg-canvas hover:text-ink"}`;

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-14 shrink-0 items-center gap-4 border-b border-line bg-surface px-4">
        <div className="flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="h-6 w-6" />
          <span className="text-[15px] font-semibold tracking-tight">Supplier Compass</span>
        </div>
        <nav className="flex items-center gap-1" aria-label="Main">
          {loaded && (
            <>
              <NavLink to="/explore" className={link}>Explore</NavLink>
              <NavLink to="/compare" className={link}>
                Compare <span className="num ml-1 rounded bg-canvas px-1.5 text-xs text-ink-2" data-testid="compare-count">{compare.length}</span>
              </NavLink>
            </>
          )}
          <NavLink to="/research" className={link}>Research</NavLink>
          {loaded && <NavLink to="/memo" className={link}>Memo</NavLink>}
          <NavLink to="/upload" className={link}>Data</NavLink>
        </nav>
        <div className="ml-auto flex items-center gap-3">
          {loaded && meta.loaded && (
            <span className="hidden max-w-[260px] truncate text-xs text-ink-3 lg:inline" title={meta.file_name}>
              {meta.file_name} · <span className="num">{meta.row_count.toLocaleString()}</span> suppliers
            </span>
          )}
          {me && !me.llm_configured && <Badge tone="warn" title="Set LLM_API_KEY: chat and memo prose are unavailable">LLM not configured</Badge>}
          {me && !me.search_configured && <Badge tone="warn" title="Set TAVILY_API_KEY: company research is unavailable">Search not configured</Badge>}
          {loaded && (
            <button className="btn-primary" onClick={() => openChat(compare)} aria-pressed={chat.open}>
              Ask
            </button>
          )}
          <span className="text-sm text-ink-2">{me?.user}</span>
          <button
            className="btn-ghost"
            onClick={async () => {
              await api.post("/api/logout");
              setMe(null);
            }}
          >
            Log out
          </button>
        </div>
      </header>
      <div className="relative flex min-h-0 flex-1">
        <main className="min-w-0 flex-1 overflow-auto">
          <Outlet />
        </main>
        {chat.open && loaded && <ChatPanel />}
      </div>
      {drawerId && loaded && <SupplierDrawer />}
      {toast && (
        <div role="status" className="fixed bottom-5 left-1/2 z-[60] -translate-x-1/2 rounded-md bg-ink px-4 py-2 text-sm text-white shadow-lg">
          {toast}
        </div>
      )}
    </div>
  );
}
