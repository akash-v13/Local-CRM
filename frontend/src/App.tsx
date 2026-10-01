import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { Layout } from "./components/Layout";
import { SessionProvider } from "./context/SessionContext";
import { CaseDetailPage } from "./pages/CaseDetailPage";
import { CaseListPage } from "./pages/CaseListPage";
import { OpsDashboardPage } from "./pages/ops/OpsDashboardPage";
import { OpsLayout } from "./pages/ops/OpsLayout";
import { QueueEditorPage } from "./pages/ops/QueueEditorPage";
import { QueueListPage } from "./pages/ops/QueueListPage";
import { WebformPage } from "./pages/WebformPage";

/**
 * Routes:
 *   /cases            agent console: case list
 *   /cases/:caseNumber  agent console: one case (case number = Unix microseconds)
 *   /webform          test customer webform
 *   /ops              Operations Portal: dashboard (reporting)
 *   /ops/queues       Operations Portal: queues in routing order
 *   /ops/queues/new   Operations Portal: create a queue
 *   /ops/queues/:id   Operations Portal: edit a queue (+ routing test)
 */
export function App() {
  return (
    <SessionProvider>
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route index element={<Navigate to="/cases" replace />} />
            <Route path="cases" element={<CaseListPage />} />
            <Route path="cases/:caseNumber" element={<CaseDetailPage />} />
            <Route path="webform" element={<WebformPage />} />
            <Route path="ops" element={<OpsLayout />}>
              <Route index element={<OpsDashboardPage />} />
              <Route path="queues" element={<QueueListPage />} />
              <Route path="queues/new" element={<QueueEditorPage />} />
              <Route path="queues/:queueId" element={<QueueEditorPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/cases" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </SessionProvider>
  );
}
