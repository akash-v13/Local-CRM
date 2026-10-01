import { BrowserRouter, Navigate, Route, Routes } from "react-router";

import { Layout } from "./components/Layout";
import { SessionProvider } from "./context/SessionContext";
import { CaseDetailPage } from "./pages/CaseDetailPage";
import { CaseListPage } from "./pages/CaseListPage";
import { ConnectorEditorPage } from "./pages/ops/ConnectorEditorPage";
import { ConnectorListPage } from "./pages/ops/ConnectorListPage";
import { CredentialEditorPage } from "./pages/ops/CredentialEditorPage";
import { CredentialListPage } from "./pages/ops/CredentialListPage";
import { OpsDashboardPage } from "./pages/ops/OpsDashboardPage";
import { OpsLayout } from "./pages/ops/OpsLayout";
import { QueueEditorPage } from "./pages/ops/QueueEditorPage";
import { QueueListPage } from "./pages/ops/QueueListPage";
import { ReplyTemplateEditorPage } from "./pages/ops/ReplyTemplateEditorPage";
import { ReplyTemplateListPage } from "./pages/ops/ReplyTemplateListPage";
import { SampleCaseEditorPage } from "./pages/ops/SampleCaseEditorPage";
import { SampleCaseListPage } from "./pages/ops/SampleCaseListPage";
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
 *   /ops/connectors[/new|/:id]    Operations Portal: enrichment connectors
 *   /ops/credentials[/new|/:id]   Operations Portal: credentials (auth for connectors)
 *   /ops/templates[/new|/:id]     Operations Portal: AI reply templates (+ test lab, costs)
 *   /ops/samples[/new|/:id]       Operations Portal: sample cases for the test lab
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
              <Route path="connectors" element={<ConnectorListPage />} />
              <Route path="connectors/new" element={<ConnectorEditorPage />} />
              <Route path="connectors/:connectorId" element={<ConnectorEditorPage />} />
              <Route path="credentials" element={<CredentialListPage />} />
              <Route path="credentials/new" element={<CredentialEditorPage />} />
              <Route path="credentials/:credentialId" element={<CredentialEditorPage />} />
              <Route path="templates" element={<ReplyTemplateListPage />} />
              <Route path="templates/new" element={<ReplyTemplateEditorPage />} />
              <Route path="templates/:templateId" element={<ReplyTemplateEditorPage />} />
              <Route path="samples" element={<SampleCaseListPage />} />
              <Route path="samples/new" element={<SampleCaseEditorPage />} />
              <Route path="samples/:sampleId" element={<SampleCaseEditorPage />} />
            </Route>
            <Route path="*" element={<Navigate to="/cases" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </SessionProvider>
  );
}
