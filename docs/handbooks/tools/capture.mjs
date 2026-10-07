/**
 * Regenerate the handbook screenshots (docs/handbooks/images/*.png).
 *
 *   docker compose up -d
 *   cd backend && uv run python scripts/seed_demo.py --with-ai && cd ..
 *   cd docs/handbooks/tools && npm install && npx playwright install chromium
 *   node capture.mjs                       # uses the newest "Northwind Outfitters (demo …)"
 *   node capture.mjs --no-ai               # skip the screenshots that call the model
 *
 * Needs ANTHROPIC_API_KEY for the AI screenshots (about 6 drafts, ~$0.05 in total).
 * Everything shown is demo data from seed_demo.py: no real people or businesses.
 */
import { chromium } from "playwright";

const UI = process.env.UI_URL ?? "http://localhost:5173";
const API = process.env.API_URL ?? "http://localhost:8000";
const OUT = new URL("../images/", import.meta.url).pathname;
const WITH_AI = !process.argv.includes("--no-ai");

const get = async (path) => (await fetch(API + path)).json();
const tenants = (await get("/tenants")).filter((t) => t.name.startsWith("Northwind Outfitters (demo"));
if (!tenants.length) throw new Error("No demo business: run backend/scripts/seed_demo.py first.");
const tenant = tenants.at(-1);
const cases = await get(`/tenants/${tenant.id}/cases`);
// Cases come newest first: nth=0 is the most recent case for that customer.
const byName = (name, nth = 0) => cases.filter((c) => c.customer.display_name === name)[nth].case_number;
const rules = await get(`/tenants/${tenant.id}/compensation/rules`);
const connectors = await get(`/tenants/${tenant.id}/connectors`);
const queues = await get(`/tenants/${tenant.id}/queues`);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 860 }, deviceScaleFactor: 1 });
await page.addInitScript((id) => {
  localStorage.setItem("resolve.tenantId", id);
  localStorage.setItem("resolve.agentId", "agent.alex");
}, tenant.id);
const errors = [];
page.on("pageerror", (e) => errors.push(String(e)));

const card = (title) => page.locator(".card").filter({ has: page.getByRole("heading", { name: title, exact: true }) });
async function shot(name, target = page, options = {}) {
  await page.waitForLoadState("networkidle");
  // Sticky save bars would cover the middle of a full-page capture.
  if (options.fullPage) await page.addStyleTag({ content: ".sticky-actions { position: static !important; }" });
  await target.screenshot({ path: `${OUT}${name}.png`, ...options });
  console.log("✓", name);
}
async function open(path, waitFor) {
  await page.goto(UI + path);
  if (waitFor) await page.getByText(waitFor, { exact: false }).first().waitFor();
}

// ----- agents ---------------------------------------------------------------------------------
await open("/webform", "Contact");
await shot("webform");

await open("/cases", "Maya Chen");
await shot("case-list");

const maya = byName("Maya Chen");
await open(`/cases/${maya}`, "Conversation");
await shot("case-page");
await shot("case-enrichment", card("Enrichment"));
await shot("case-compensation-approved", card("Compensation"));
await shot("case-history", card("History"));

// Draft with AI (one live model call).
if (WITH_AI) {
  await page.getByRole("button", { name: /Draft with AI/ }).click();
  await page.locator(".draft-panel").waitFor({ timeout: 60000 });
  await page.locator(".composer").scrollIntoViewIfNeeded();
  await shot("case-ai-draft", page.locator(".composer"));
}

await open(`/cases/${byName("Tom Okafor")}`, "Waiting for approval");
await shot("case-compensation-pending", card("Compensation"));
await shot("case-queue", card("Queue"));
await shot("case-status", card("Status"));

await open(`/cases/${byName("Lena Fischer")}`, "Compensation");
await shot("case-compensation-none", card("Compensation"));

// ----- managers --------------------------------------------------------------------------------
await open("/ops", "Open cases");
await shot("ops-dashboard");

// Intake pipeline: the definition, the executions list, and two runs.
await open("/ops/pipeline", "Intake pipeline");
await page.locator(".flow-node").filter({ hasText: "Shipping tracker" }).click();
await shot("pipeline", page, { fullPage: true });
await page.getByRole("link", { name: "Executions" }).click();
await page.getByText("Sam Lee").first().waitFor();
await shot("pipeline-executions");
await open(`/ops/pipeline/executions/${maya}`, "Ready for an agent");
await page.locator(".flow-node").filter({ hasText: "Shop orders" }).first().click();
await shot("pipeline-execution", page, { fullPage: true });
await open(`/ops/pipeline/executions/${byName("Sam Lee")}`, "Ready for an agent");
await shot("pipeline-execution-failed", page, { fullPage: true });

await open("/ops/queues", "Priority customers");
await shot("queues");
const delivery = queues.find((q) => q.name === "Delivery issues");
await open(`/ops/queues/${delivery.id}`, "Receives cases where");
await page.getByLabel("Case to test").selectOption(String(maya));
await page.getByRole("button", { name: "Run test" }).click();
await page.locator(".preview-winner").waitFor();
await shot("queue-editor", page, { fullPage: true });

await open("/ops/connectors", "Shop orders");
await shot("connectors");
const shop = connectors.find((c) => c.key === "shop_orders");
await open(`/ops/connectors/${shop.id}`, "Basics");
await page.getByLabel("Case to test with").selectOption(String(maya));
await page.getByRole("button", { name: "Send test request" }).click();
await page.getByText("179.04").first().waitFor();
await shot("connector-editor", page, { fullPage: true });

await open("/ops/credentials", "Shop API (OAuth)");
await shot("credentials");

await open("/ops/compensation", "Our fault and very late");
await page.getByRole("button", { name: "Run backtest" }).click();
await page.locator(".simulation .stat-row").waitFor();
await shot("compensation-rules", page, { fullPage: true });
const refund = rules.find((r) => r.name.startsWith("Our fault"));
await open(`/ops/compensation/${refund.id}`, "Customer gets");
await page.getByLabel("Case to test").selectOption(String(maya));
await page.getByRole("button", { name: "Run test" }).first().click();
await page.locator(".preview-winner").waitFor();
await shot("compensation-editor", page, { fullPage: true });

await open("/ops/templates", "Platform rules");
await shot("templates", page, { fullPage: true });
await open("/ops/templates/queue/PriorityCustomers.jinja", "Template (Jinja)");
await page.getByLabel("Preview with").selectOption(`case:${maya}`);
await page.getByRole("button", { name: "Preview", exact: true }).click();
await page.locator(".preview-layers").waitFor();
await shot("template-editor", page, { fullPage: true });

// Test lab: Haiku vs Sonnet on the two samples, 1 run each (4 live model calls).
if (WITH_AI) {
await open("/ops/templates/category/Complaint_Delivery_LateDelivery.jinja", "Test lab");
const lab = page.locator(".lab-card").first();
await lab.getByLabel("Runs per input").selectOption("1").catch(() => {});
await lab.locator("select").filter({ hasText: "1" }).last().selectOption("1");
await lab.getByRole("button", { name: "Run test" }).click();
await lab.locator(".compare-table").waitFor({ timeout: 120000 });
await page.waitForFunction(() => !document.querySelector(".lab-run button")?.textContent?.includes("Running"), null, { timeout: 120000 });
await shot("test-lab", lab);
await shot("cost-projection", page.locator(".lab-card").nth(1));
}

// Email channel: the inbox, its settings, and an email case answered by email.
await open("/ops/email", "Support inbox");
await shot("email-inboxes");
const boxes = await get(`/tenants/${tenant.id}/mailboxes`);
await open(`/ops/email/${boxes[0].id}`, "What to import");
await shot("email-inbox-editor", page, { fullPage: true });
const priya = byName("Priya Patel");
await open(`/cases/${priya}`, "Conversation");
if (!(await page.getByText(/✓ Emailed to priya/).count())) {
  await page.getByPlaceholder("Write a message…").fill(
    "Hi Priya,\n\nI'm sorry your gift is late. I've asked the carrier to prioritise it and I'll update you as soon as it moves.\n\nBest regards,\nNorthwind Support");
  await page.getByRole("button", { name: "Send", exact: true }).click();
  for (let i = 0; i < 20 && !(await page.getByText(/✓ Emailed to priya/).count()); i++) {
    await page.waitForTimeout(1000);
    await page.reload();
  }
}
await page.getByText(/✓ Emailed to priya/).waitFor();
await shot("email-case", card("Conversation"));

await open("/ops/samples", "Late gift");
await shot("samples");

// ----- developers ----------------------------------------------------------------------------
await page.goto(`${API}/docs`);
await page.getByText("compensation", { exact: false }).first().waitFor();
await shot("api-docs");

console.log(errors.length ? `page errors:\n${errors.join("\n")}` : "✓ no page errors");
await browser.close();
