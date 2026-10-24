import { Navigate, Route, Routes } from "react-router-dom";
import { AsOfProvider } from "./AsOfContext";
import { WorkspaceProvider, useWorkspace } from "./WorkspaceContext";
import ConsoleLayout from "./components/ConsoleLayout";
import SiteLayout from "./components/SiteLayout";
import Assumptions from "./pages/Assumptions";
import Account from "./pages/Account";
import Agent from "./pages/Agent";
import Auth from "./pages/Auth";
import Brief from "./pages/Brief";
import Connect from "./pages/Connect";
import DecisionDetail from "./pages/DecisionDetail";
import Freshness from "./pages/Freshness";
import Integrate from "./pages/Integrate";
import Landing from "./pages/Landing";
import Metrics from "./pages/Metrics";

// A fresh AsOfProvider per workspace so the simulated (demo) and live (real data) dates never mix.
function Console() {
  const { signedIn } = useWorkspace();
  return (
    <AsOfProvider key={String(signedIn)}>
      <ConsoleLayout />
    </AsOfProvider>
  );
}

export default function App() {
  return (
    <WorkspaceProvider>
      <Routes>
      <Route element={<SiteLayout />}>
        <Route index element={<Landing />} />
        <Route path="integrate" element={<Integrate />} />
        <Route path="signup" element={<Auth mode="signup" />} />
        <Route path="login" element={<Auth mode="login" />} />
        <Route path="agent" element={<Agent />} />
      </Route>
      <Route
        path="/console"
        element={<Console />}
      >
        <Route index element={<Navigate to="brief" replace />} />
        <Route path="brief" element={<Brief />} />
        <Route path="connect" element={<Connect />} />
        <Route path="assumptions" element={<Assumptions />} />
        <Route path="decisions" element={<DecisionDetail />} />
        <Route path="decisions/:id" element={<DecisionDetail />} />
        <Route path="freshness" element={<Freshness />} />
        <Route path="metrics" element={<Metrics />} />
        <Route path="account" element={<Account />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </WorkspaceProvider>
  );
}
