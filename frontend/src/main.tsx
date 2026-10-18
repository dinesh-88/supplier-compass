import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";
import { StoreProvider, useStore } from "./lib/store";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Upload from "./pages/Upload";
import Explore from "./pages/Explore";
import Compare from "./pages/Compare";
import Research from "./pages/Research";
import Memo from "./pages/Memo";
import { Spinner } from "./components/ui";

function Gate() {
  const { me, meta } = useStore();
  if (me === undefined) return <Centered><Spinner label="Loading…" /></Centered>;
  if (me === null) return <Login />;
  if (meta === null) return <Centered><Spinner label="Loading dataset…" /></Centered>;
  const loaded = meta.loaded;
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/upload" element={<Upload />} />
        <Route path="/explore" element={loaded ? <Explore /> : <Navigate to="/upload" replace />} />
        <Route path="/compare" element={loaded ? <Compare /> : <Navigate to="/upload" replace />} />
        <Route path="/research" element={<Research />} />
        <Route path="/memo" element={loaded ? <Memo /> : <Navigate to="/upload" replace />} />
        <Route path="*" element={<Navigate to={loaded ? "/explore" : "/upload"} replace />} />
      </Route>
    </Routes>
  );
}

function Centered({ children }: { children: React.ReactNode }) {
  return <div className="flex h-screen items-center justify-center">{children}</div>;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <StoreProvider>
        <Gate />
      </StoreProvider>
    </BrowserRouter>
  </StrictMode>,
);
