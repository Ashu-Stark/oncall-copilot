import type { ReactNode } from "react";
import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { Layout } from "./components/Layout";
import { Dashboard } from "./pages/Dashboard";
import { Inbox } from "./pages/Inbox";
import { IncidentPage } from "./pages/IncidentPage";
import { Login } from "./pages/Login";
import { Postmortem } from "./pages/Postmortem";
import { RunbookEditor } from "./pages/RunbookEditor";
import { Runbooks } from "./pages/Runbooks";

function Private({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth();
  if (!ready) return <p className="muted page">Loading…</p>;
  return user ? <>{children}</> : <Navigate to="/login" replace />;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <Private>
            <Layout />
          </Private>
        }
      >
        <Route index element={<Inbox />} />
        <Route path="incidents/:id" element={<IncidentPage />} />
        <Route path="incidents/:id/postmortem" element={<Postmortem />} />
        <Route path="dashboard" element={<Dashboard />} />
        <Route path="runbooks" element={<Runbooks />} />
        <Route path="runbooks/new" element={<RunbookEditor />} />
        <Route path="runbooks/:id" element={<RunbookEditor />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
