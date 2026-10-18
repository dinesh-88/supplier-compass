import { useState } from "react";
import { api } from "../lib/api";
import { useStore, type Me } from "../lib/store";

export default function Login() {
  const { setMe } = useStore();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/login", { username, password });
      setMe(await api.get<Me>("/api/me"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas p-4">
      <form onSubmit={submit} className="card w-[380px] p-7 shadow-sm">
        <div className="mb-5 flex items-center gap-2">
          <img src="/favicon.svg" alt="" className="h-8 w-8" />
          <div>
            <h1 className="text-lg font-semibold leading-tight">Supplier Compass</h1>
            <p className="text-xs text-ink-3">Smart supplier selection for trains</p>
          </div>
        </div>
        <label className="mb-3 block">
          <span className="mb-1 block text-sm font-medium">User name</span>
          <input className="input w-full" name="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        </label>
        <label className="mb-4 block">
          <span className="mb-1 block text-sm font-medium">Password</span>
          <input className="input w-full" name="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p className="mb-3 text-sm text-lv-high" role="alert">{error}</p>}
        <button className="btn-primary w-full justify-center py-2" disabled={busy || !username || !password}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
