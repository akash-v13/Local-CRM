/**
 * The only place the UI talks to the backend.
 *
 * Every call goes to /api/... which Vite proxies to FastAPI (see vite.config.ts).
 * Errors come back as `ApiError` carrying the backend's `detail` message, so
 * components can show the real reason (e.g. "Cannot move a case from Intake to Solved").
 */
import type {
  Case,
  CaseCreateInput,
  CaseDetail,
  CaseEvent,
  CaseFilters,
  Connector,
  ConnectorConfig,
  ConnectorTestResult,
  Credential,
  CredentialWrite,
  CompensationDecision,
  CompensationPreview,
  CompensationRule,
  CompensationRuleInput,
  CompensationSettings,
  CostProjection,
  ExecutionDetail,
  ExecutionOutcome,
  ExecutionSummary,
  PipelineDefinition,
  SimulationResult,
  Message,
  MessageCreateInput,
  ModelOption,
  CoverageRow,
  PromptPreview,
  PromptTemplate,
  PromptTemplateWrite,
  TemplateOverride,
  TemplateVariable,
  SampleCase,
  SampleCaseWrite,
  TestRun,
  TestRunCreate,
  TestRunEstimate,
  Queue,
  QueueInput,
  QueueReport,
  RoutingFields,
  RoutingPreview,
  TaxonomyType,
  Tenant,
  TokenTestResult,
  TransitionInput,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    let detail = response.statusText || `Request failed (${response.status})`;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "detail" in body) {
        detail = formatDetail((body as { detail: unknown }).detail);
      }
    } catch {
      // Body wasn't JSON; keep the status text.
    }
    throw new ApiError(response.status, detail);
  }
  return (await response.json()) as T;
}

/**
 * Backend errors carry a `detail`: a string for domain errors (404/409), or a
 * list of {loc, msg} for 422 validation errors, which we turn into readable lines
 * like "match_criteria.conditions.0: Value error, Unknown field 'x'."
 */
function formatDetail(detail: unknown): string {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        const { loc, msg } = item as { loc?: unknown[]; msg?: string };
        const where = Array.isArray(loc) ? loc.slice(1).join(".") : "";
        return where ? `${where}: ${msg}` : String(msg);
      })
      .join("\n");
  }
  return JSON.stringify(detail);
}

const post = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body) });
const patch = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PATCH", body: JSON.stringify(body) });
const put = <T>(path: string, body: unknown) =>
  request<T>(path, { method: "PUT", body: JSON.stringify(body) });

export const api = {
  listTenants: () => request<Tenant[]>("/tenants"),
  createTenant: (name: string) => post<Tenant>("/tenants", { name }),
  listCategories: (tenantId: string) => request<TaxonomyType[]>(`/tenants/${tenantId}/categories`),

  createCase: (tenantId: string, input: CaseCreateInput) =>
    post<Case>(`/tenants/${tenantId}/cases`, input),
  listCases: (tenantId: string, filters: CaseFilters = {}) => {
    const params = new URLSearchParams();
    if (filters.status) params.set("status", filters.status);
    if (filters.queueId) params.set("queue_id", filters.queueId);
    if (filters.unrouted) params.set("unrouted", "true");
    const query = params.size ? `?${params}` : "";
    return request<Case[]>(`/tenants/${tenantId}/cases${query}`);
  },
  getCase: (tenantId: string, caseNumber: number) =>
    request<CaseDetail>(`/tenants/${tenantId}/cases/${caseNumber}`),
  listEvents: (tenantId: string, caseNumber: number) =>
    request<CaseEvent[]>(`/tenants/${tenantId}/cases/${caseNumber}/events`),

  addMessage: (tenantId: string, caseNumber: number, input: MessageCreateInput) =>
    post<Message>(`/tenants/${tenantId}/cases/${caseNumber}/messages`, input),
  transition: (tenantId: string, caseNumber: number, input: TransitionInput) =>
    post<Case>(`/tenants/${tenantId}/cases/${caseNumber}/transitions`, input),
  routeCase: (tenantId: string, caseNumber: number, actorId: string) =>
    post<Case>(`/tenants/${tenantId}/cases/${caseNumber}/route`, {
      actor_type: "human",
      actor_id: actorId,
    }),
  rerouteCase: (
    tenantId: string,
    caseNumber: number,
    input: { queue_id: string; actor_id: string; reason?: string },
  ) => post<Case>(`/tenants/${tenantId}/cases/${caseNumber}/reroute`, input),

  // Operations Portal
  listQueues: (tenantId: string) => request<Queue[]>(`/tenants/${tenantId}/queues`),
  getQueue: (tenantId: string, queueId: string) =>
    request<Queue>(`/tenants/${tenantId}/queues/${queueId}`),
  createQueue: (tenantId: string, input: QueueInput) =>
    post<Queue>(`/tenants/${tenantId}/queues`, input),
  updateQueue: (tenantId: string, queueId: string, input: Partial<QueueInput>) =>
    patch<Queue>(`/tenants/${tenantId}/queues/${queueId}`, input),
  routingFields: (tenantId: string) =>
    request<RoutingFields>(`/tenants/${tenantId}/routing/fields`),
  previewRouting: (
    tenantId: string,
    input: { case_number: number; draft?: QueueInput; draft_queue_id?: string },
  ) => post<RoutingPreview>(`/tenants/${tenantId}/routing/preview`, input),
  queueReport: (tenantId: string) => request<QueueReport>(`/tenants/${tenantId}/reports/queues`),

  // Enrichment
  enrichCase: (tenantId: string, caseNumber: number, actorId: string) =>
    post<Case>(`/tenants/${tenantId}/cases/${caseNumber}/enrich`, { actor_id: actorId }),
  listConnectors: (tenantId: string) => request<Connector[]>(`/tenants/${tenantId}/connectors`),
  getConnector: (tenantId: string, id: string) =>
    request<Connector>(`/tenants/${tenantId}/connectors/${id}`),
  createConnector: (tenantId: string, input: ConnectorConfig) =>
    post<Connector>(`/tenants/${tenantId}/connectors`, input),
  replaceConnector: (tenantId: string, id: string, input: ConnectorConfig) =>
    put<Connector>(`/tenants/${tenantId}/connectors/${id}`, input),
  testConnector: (tenantId: string, caseNumber: number, draft: ConnectorConfig) =>
    post<ConnectorTestResult>(`/tenants/${tenantId}/connectors/test`, {
      case_number: caseNumber,
      draft,
    }),
  listCredentials: (tenantId: string) => request<Credential[]>(`/tenants/${tenantId}/credentials`),
  getCredential: (tenantId: string, id: string) =>
    request<Credential>(`/tenants/${tenantId}/credentials/${id}`),
  createCredential: (tenantId: string, input: CredentialWrite) =>
    post<Credential>(`/tenants/${tenantId}/credentials`, input),
  replaceCredential: (tenantId: string, id: string, input: CredentialWrite) =>
    put<Credential>(`/tenants/${tenantId}/credentials/${id}`, input),
  testCredential: (tenantId: string, id: string) =>
    post<TokenTestResult>(`/tenants/${tenantId}/credentials/${id}/test`, {}),

  // Intake pipeline
  pipeline: (tenantId: string) => request<PipelineDefinition>(`/tenants/${tenantId}/pipeline`),
  pipelineExecutions: (tenantId: string, outcome?: ExecutionOutcome) =>
    request<ExecutionSummary[]>(`/tenants/${tenantId}/pipeline/executions${outcome ? `?outcome=${outcome}` : ""}`),
  pipelineExecution: (tenantId: string, caseNumber: number) =>
    request<ExecutionDetail>(`/tenants/${tenantId}/pipeline/executions/${caseNumber}`),

  // Compensation matrix
  listCompensationRules: (tenantId: string) =>
    request<CompensationRule[]>(`/tenants/${tenantId}/compensation/rules`),
  getCompensationRule: (tenantId: string, id: string) =>
    request<CompensationRule>(`/tenants/${tenantId}/compensation/rules/${id}`),
  createCompensationRule: (tenantId: string, input: CompensationRuleInput) =>
    post<CompensationRule>(`/tenants/${tenantId}/compensation/rules`, input),
  replaceCompensationRule: (tenantId: string, id: string, input: CompensationRuleInput) =>
    put<CompensationRule>(`/tenants/${tenantId}/compensation/rules/${id}`, input),
  compensationSettings: (tenantId: string) =>
    request<CompensationSettings>(`/tenants/${tenantId}/compensation/settings`),
  saveCompensationSettings: (tenantId: string, input: CompensationSettings) =>
    put<CompensationSettings>(`/tenants/${tenantId}/compensation/settings`, input),
  previewCompensation: (
    tenantId: string,
    input: { case_number: number; draft?: CompensationRuleInput | null; draft_rule_id?: string },
  ) => post<CompensationPreview>(`/tenants/${tenantId}/compensation/preview`, input),
  simulateCompensation: (
    tenantId: string,
    input: { days: number; draft?: CompensationRuleInput | null; draft_rule_id?: string },
  ) => post<SimulationResult>(`/tenants/${tenantId}/compensation/simulate`, input),
  decideCompensation: (tenantId: string, caseNumber: number, actorId: string) =>
    post<CompensationDecision>(`/tenants/${tenantId}/cases/${caseNumber}/compensation/decide`, { actor_id: actorId }),
  reviewCompensation: (tenantId: string, caseNumber: number, approve: boolean, actorId: string, note?: string) =>
    post<CompensationDecision>(
      `/tenants/${tenantId}/cases/${caseNumber}/compensation/${approve ? "approve" : "reject"}`,
      { actor_id: actorId, note: note || null },
    ),

  // AI reply drafting
  aiModels: () => request<ModelOption[]>("/ai/models"),
  draftReply: (tenantId: string, caseNumber: number, actorId: string) =>
    post<Message>(`/tenants/${tenantId}/cases/${caseNumber}/drafts`, { actor_id: actorId }),
  // Prompt templates. Names contain a slash (queue/…, category/…) and are used in the path as is.
  listPromptTemplates: (tenantId: string) =>
    request<PromptTemplate[]>(`/tenants/${tenantId}/prompt-templates`),
  getPromptTemplate: (tenantId: string, name: string) =>
    request<PromptTemplate>(`/tenants/${tenantId}/prompt-templates/${name}`),
  savePromptTemplate: (tenantId: string, name: string, input: PromptTemplateWrite, actorId: string) =>
    put<PromptTemplate>(`/tenants/${tenantId}/prompt-templates/${name}?actor_id=${encodeURIComponent(actorId)}`, input),
  importPromptTemplate: (tenantId: string, name: string, content: string, actorId: string) =>
    post<PromptTemplate>(`/tenants/${tenantId}/prompt-templates/import?actor_id=${encodeURIComponent(actorId)}`, { name, content }),
  /** URL for downloading the template as a .jinja file (header included). */
  promptTemplateDownloadUrl: (tenantId: string, name: string) =>
    `/api/tenants/${tenantId}/prompt-templates/${name}/download`,
  previewPrompt: (
    tenantId: string,
    input: { case_number?: number; sample_id?: string; override?: TemplateOverride | null },
  ) => post<PromptPreview>(`/tenants/${tenantId}/prompt-templates/preview`, input),
  templateCoverage: (tenantId: string) =>
    request<CoverageRow[]>(`/tenants/${tenantId}/prompt-templates/coverage`),
  templateVariables: (tenantId: string) =>
    request<TemplateVariable[]>(`/tenants/${tenantId}/prompt-templates/variables`),
  platformRules: async (tenantId: string) => {
    const response = await fetch(`/api/tenants/${tenantId}/prompt-templates/platform`);
    if (!response.ok) throw new ApiError(response.status, response.statusText);
    return response.text();
  },
  costProjection: (tenantId: string, name: string, monthlyVolume: number) =>
    request<CostProjection>(`/tenants/${tenantId}/prompt-templates/${name}/projection?monthly_volume=${monthlyVolume}`),
  listSampleCases: (tenantId: string) => request<SampleCase[]>(`/tenants/${tenantId}/sample-cases`),
  createSampleCase: (tenantId: string, input: SampleCaseWrite) =>
    post<SampleCase>(`/tenants/${tenantId}/sample-cases`, input),
  updateSampleCase: (tenantId: string, id: string, input: SampleCaseWrite) =>
    put<SampleCase>(`/tenants/${tenantId}/sample-cases/${id}`, input),
  estimateTest: (tenantId: string, input: TestRunCreate) =>
    post<TestRunEstimate>(`/tenants/${tenantId}/template-tests/estimate`, input),
  startTest: (tenantId: string, input: TestRunCreate) =>
    post<TestRun>(`/tenants/${tenantId}/template-tests`, input),
  getTest: (tenantId: string, id: string) => request<TestRun>(`/tenants/${tenantId}/template-tests/${id}`),
  recentTests: (tenantId: string, templateName: string) =>
    request<TestRun[]>(`/tenants/${tenantId}/template-tests?template_name=${encodeURIComponent(templateName)}`),
};

export type Api = typeof api;

/** Human-readable message for any thrown value. */
export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error);
}
