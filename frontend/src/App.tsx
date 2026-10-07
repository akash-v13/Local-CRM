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
import { CompensationListPage } from "./pages/ops/CompensationListPage";
import { CompensationRuleEditorPage } from "./pages/ops/CompensationRuleEditorPage";
import { MailboxEditorPage } from "./pages/ops/MailboxEditorPage";
import { MailboxListPage } from "./pages/ops/MailboxListPage";
import { PipelineExecutionPage } from "./pages/ops/PipelineExecutionPage";
import { PipelineExecutionsPage, PipelinePage } from "./pages/ops/PipelinePage";
import { PayoutsPage } from "./pages/ops/PayoutsPage";
import { ReadingPage } from "./pages/ops/ReadingPage";
import { ShopifyPage } from "./pages/ops/ShopifyPage";
import { PromptTemplateEditorPage } from "./pages/ops/PromptTemplateEditorPage";
import { PromptTemplateListPage } from "./pages/ops/PromptTemplateListPage";
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
 *   /ops/email[/new|/:id]         Operations Portal: linked email inboxes
 *   /ops/reading                  Operations Portal: what to read from customers' messages
 *   /ops/pipeline[/executions[/:caseNumber]]  Operations Portal: intake pipeline diagram + per-case runs
 *   /ops/compensation[/new|/:id]  Operations Portal: compensation rules, guardrails, backtest
 *   /ops/payouts                  Operations Portal: issuing approved compensation (Stripe, Shopify)
 *   /ops/shopify                  Operations Portal: the business's Shopify store (order lookup)
 *   /ops/templates[/<name>]       Operations Portal: Jinja prompt templates (+ preview, test lab, costs)
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
              <Route path="email" element={<MailboxListPage />} />
              <Route path="email/new" element={<MailboxEditorPage />} />
              <Route path="email/:mailboxId" element={<MailboxEditorPage />} />
              <Route path="reading" element={<ReadingPage />} />
              <Route path="payouts" element={<PayoutsPage />} />
              <Route path="shopify" element={<ShopifyPage />} />
              <Route path="pipeline" element={<PipelinePage />} />
              <Route path="pipeline/executions" element={<PipelineExecutionsPage />} />
              <Route path="pipeline/executions/:caseNumber" element={<PipelineExecutionPage />} />
              <Route path="connectors" element={<ConnectorListPage />} />
              <Route path="connectors/new" element={<ConnectorEditorPage />} />
              <Route path="connectors/:connectorId" element={<ConnectorEditorPage />} />
              <Route path="credentials" element={<CredentialListPage />} />
              <Route path="credentials/new" element={<CredentialEditorPage />} />
              <Route path="credentials/:credentialId" element={<CredentialEditorPage />} />
              <Route path="compensation" element={<CompensationListPage />} />
              <Route path="compensation/new" element={<CompensationRuleEditorPage />} />
              <Route path="compensation/:ruleId" element={<CompensationRuleEditorPage />} />
              <Route path="templates" element={<PromptTemplateListPage />} />
              <Route path="templates/*" element={<PromptTemplateEditorPage />} />
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
