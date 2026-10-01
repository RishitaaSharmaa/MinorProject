import { Navigate, Route, Routes } from "react-router-dom";
import { AsOfProvider } from "./AsOfContext";
import ConsoleLayout from "./components/ConsoleLayout";
import SiteLayout from "./components/SiteLayout";
import Assumptions from "./pages/Assumptions";
import Brief from "./pages/Brief";
import DecisionDetail from "./pages/DecisionDetail";
import Landing from "./pages/Landing";
import Metrics from "./pages/Metrics";

export default function App() {
  return (
    <Routes>
      <Route element={<SiteLayout />}>
        <Route index element={<Landing />} />
      </Route>
      <Route
        path="/console"
        element={
          <AsOfProvider>
            <ConsoleLayout />
          </AsOfProvider>
        }
      >
        <Route index element={<Navigate to="brief" replace />} />
        <Route path="brief" element={<Brief />} />
        <Route path="assumptions" element={<Assumptions />} />
        <Route path="decisions" element={<DecisionDetail />} />
        <Route path="decisions/:id" element={<DecisionDetail />} />
        <Route path="metrics" element={<Metrics />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
