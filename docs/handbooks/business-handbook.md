# Business User Handbook

**For:** customer care agents, team leads and operations managers using Local CRM day to day. No technical knowledge needed.

**How to read it:**
- Read **sections 1–3** first.
- **Agents:** then read **Part A**.
- **Managers** who set up queues, rules and AI: also read **Part B**.
- **Part C** has step-by-step recipes for common jobs.

Every screenshot uses a made-up demo shop called *Northwind Outfitters*. Ask whoever runs your installation to load it: [Demo data](#demo-data).

---

## Contents

1. [What the platform does](#1-what-the-platform-does)
2. [Getting started](#2-getting-started)
3. [Words you'll see](#3-words-youll-see)

**Part A: Working cases (agents)**

- [A1. The case list](#a1-the-case-list)
- [A2. A case, top to bottom](#a2-a-case-top-to-bottom)
- [A3. Replying, notes and status](#a3-replying-notes-and-status)
- [A4. Drafting a reply with AI](#a4-drafting-a-reply-with-ai)
- [A5. Compensation on a case](#a5-compensation-on-a-case)
- [A6. Moving a case to another queue](#a6-moving-a-case-to-another-queue)
- [A7. Order and shipping data (enrichment)](#a7-order-and-shipping-data-enrichment)
- [A8. Creating test cases](#a8-creating-test-cases)

**Part B: Setting things up (managers)**

- [B1. Dashboard](#b1-dashboard)
- [B2. Queues and routing](#b2-queues-and-routing)
- [B3. Connectors and credentials](#b3-connectors-and-credentials)
- [B4. Compensation rules](#b4-compensation-rules)
- [B5. How AI replies are written (prompt templates)](#b5-how-ai-replies-are-written-prompt-templates)
- [B6. Testing AI before you change anything](#b6-testing-ai-before-you-change-anything)

**Part C: Recipes and reference**

- [C1. Recipes](#c1-recipes)
- [C2. Case statuses](#c2-case-statuses)
- [C3. Questions and troubleshooting](#c3-questions-and-troubleshooting)
- [C4. What's not built yet](#c4-whats-not-built-yet)

---

## 1. What the platform does

Local CRM takes in customer cases and prepares them for your team:

1. **Gathers the facts.** It looks up the customer's order and shipping data in your own systems.
2. **Routes the case.** It sends the case to the right queue.
3. **Decides compensation.** Your rules decide what the customer is owed.
4. **Drafts a reply.** AI writes a draft for an agent to review.

```mermaid
flowchart LR
    Customer([Customer writes in]) --> Facts[Order & shipping data<br/>looked up automatically]
    Facts --> Queue[Sent to the right queue]
    Queue --> Comp[Compensation decided<br/>by your rules]
    Comp --> Agent[Agent opens the case]
    Agent -- "✨ Draft with AI" --> Draft[AI draft]
    Draft --> Agent
    Agent -- review, edit, send --> Reply([Reply to customer])
```

**Three promises the platform keeps:**
- **The AI never decides money.** Compensation comes from rules your managers write. The AI only mentions compensation once it's approved.
- **A person reviews every AI draft.** Nothing is sent to a customer automatically.
- **Everything is recorded.** Every status change, move, decision and draft appears in the case's **History**, with who did it and why.

---

## 2. Getting started

1. **Open the app.** Use the address your administrator gave you. Locally it's **http://localhost:5173**.
2. **Pick your business** in the drop-down at the top right.
3. **Check "Acting as".** It should show your name (e.g. `agent.alex`), because every action is recorded under this name.

> **Temporary:** there's no sign-in yet. The business picker and "Acting as" box stand in for logging in. Sign-in comes later.

**The top bar has three areas:**

| Area | For |
|---|---|
| **Agent console** | Agents: the case list and individual cases |
| **Operations** | Managers: dashboard, queues, connectors, credentials, compensation, prompt templates, sample cases |
| **Test webform** | Anyone: create a case the way a customer would |

---

## 3. Words you'll see

| Word | Meaning |
|---|---|
| **Case** | One customer issue, with its whole conversation. |
| **Case number** | A case's ID, e.g. `1791221037860354`. It's the time the case was created, so higher numbers are newer. |
| **Category** | What the case is about, in three levels: *Type › Category › Subcategory* (e.g. Complaint › Delivery › Late delivery). The customer picks it on the webform. |
| **Queue** | A line of cases waiting for a team, e.g. *Delivery issues*. Each case is in one queue. |
| **Status** | Where the case is in its life: *Queued*, *Assigned to agent*, *Solved*… (see [C2](#c2-case-statuses)). |
| **Enrichment** | Data looked up automatically from your systems, e.g. order total and days late. |
| **Connector** | A saved lookup into one of your systems (e.g. "Shop orders"). Managers set these up. |
| **Compensation** | What the customer gets: refund, store credit, voucher, replacement, points, or nothing. |
| **Prompt template** | The written instructions that tell the AI how to write replies. |
| **Draft** | An AI-written reply that hasn't been sent. You always review it first. |

---

# Part A: Working cases (agents)

## A1. The case list

**Agent console** lists the business's cases, newest first.

![The case list](images/case-list.png)

- **Filter** by queue (drop-down) or by status (the buttons).
- **Click a case number** to open the case.
- **Refresh** reloads the list.
- **New test case** opens the test webform (see [A8](#a8-creating-test-cases)).

## A2. A case, top to bottom

![A case](images/case-page.png)

The header shows:
- **Case number and status**
- **Category, queue and channel**
- **When the case was opened**

**Left side, the conversation:**
- **Customer messages** are grey.
- **Your replies** are on the right.
- **Internal notes** are yellow and never shown to the customer.
- **AI drafts** have a dashed border and are labelled *AI draft · not sent*.

**Right side, everything you need to decide:**

| Card | What it tells you |
|---|---|
| **Customer** | Name, email, loyalty tier |
| **Case** | Category, assignee, extra details from the form (e.g. order number) |
| **Enrichment** | Order and shipping data looked up automatically ([A7](#a7-order-and-shipping-data-enrichment)) |
| **Queue** | The case's queue, and buttons to move it ([A6](#a6-moving-a-case-to-another-queue)) |
| **Compensation** | What the customer is owed and why ([A5](#a5-compensation-on-a-case)) |
| **Status** | Buttons for the next allowed steps ([A3](#a3-replying-notes-and-status)) |
| **History** | Everything that has happened, oldest first |

![History](images/case-history.png)

## A3. Replying, notes and status

The reply box under the conversation has three tabs:

| Tab | What it does |
|---|---|
| **Reply to customer** | Sends your message to the customer. For now, sending is *simulated*: the reply is saved on the case but not emailed. |
| **Internal note** | Saves a note only your team can see. |
| **Simulate customer reply** | Testing only: pretends the customer wrote back. |

**Send & mark solved** sends your reply and closes out the case in one step.

**The Status card** only offers the moves that are allowed from the case's current status, so you can't put a case in an impossible state.

![Status buttons](images/case-status.png)

- **Assign to me** takes ownership of the case.
- **Request approval** is for when a manager must sign off.
- **Wait on customer** is for when you've asked the customer something.
- **Mark solved** is for when the customer has their answer.

You can add a **reason** before clicking any of these. It appears in the History.

If the customer replies to a **Solved** or **Waiting on customer** case, it goes back to **Queued** automatically, in the same queue. **Closed** cases don't accept replies.

## A4. Drafting a reply with AI

**✨ Draft with AI** in the reply box writes a draft from the whole conversation, the case details and the enrichment data. It takes a few seconds.

![An AI draft](images/case-ai-draft.png)

**What you see:**
- **The draft text** is in the reply box. **Edit it freely** before you send.
- **The panel underneath** shows:
  - **Model, cost and time:** e.g. *Claude Sonnet 5 · $0.0054 · 3.9s*.
  - **Checks:** green ✓ means the draft followed a rule (word limit, required phrases, banned phrases). A red ✗ means it didn't, so fix it before sending.
  - **Warnings (⚠):** things to double-check, such as a promised timeline that isn't in the case data, a refund offer nobody approved, or contact details that weren't in the case.
  - **Needs your attention:** the AI thinks a person should handle this one (legal threats, safety, refund demands nobody has decided, …).
  - **Templates:** which instructions wrote the draft ([B5](#b5-how-ai-replies-are-written-prompt-templates)).
  - **Based on:** the facts the AI used.

**Good to know:**
- **Nothing is sent automatically.** You review, edit, then click **Send**.
- **Personal data is hidden from the AI.** The customer's name and contact details are swapped for placeholders before the AI sees them, then put back in the draft.
- **Compensation:** the AI only mentions compensation once it's **approved** on the case. While approval is pending, it won't offer anything.
- **Edits are tracked.** The platform records whether you changed the draft. This is how the team measures draft quality.
- **If the button is greyed out or shows an error:**
  - AI may be switched off for this case's queue.
  - Or your installation has no AI key yet.

  Ask your manager.

## A5. Compensation on a case

When a case is routed, your business's **compensation rules** decide what the customer is owed. The **Compensation** card shows the result:

| Approved automatically | Waiting for approval | No compensation |
|---|---|---|
| ![Approved](images/case-compensation-approved.png) | ![Waiting for approval](images/case-compensation-pending.png) | ![None](images/case-compensation-none.png) |

**What the card shows:**
- **The decision:** e.g. *Refund of USD 89.52*, and how the amount was worked out (*50% of order total 179.04*).
- **The rule** that decided it, and the conditions that matched.
- **Why it needs approval**, if it does. For example:
  - the customer was compensated recently (*Repeat claim*)
  - the amount is above the queue's limit
  - the rule always needs approval
- **Past compensation** for this customer.

**Your options:**
- **Approve:** the compensation is confirmed, and AI drafts will mention it.
- **Reject:** type a reason first, then click Reject. Nothing is offered.
- **Decide again:** re-runs the rules, e.g. after order data arrived or the rules changed. Not possible once a decision has been approved or rejected.

> Approving records the decision. **Paying** the customer isn't automated yet (see [C4](#c4-whats-not-built-yet)).

## A6. Moving a case to another queue

![Queue card](images/case-queue.png)

- **Run routing again:** sends the case through the queue rules again, e.g. after a manager changed them.
- **Move to queue…:** pick a queue, add a reason, and move the case.
  - The case is then **pinned**: automatic routing won't move it back.
  - Use this when the customer picked the wrong category.

## A7. Order and shipping data (enrichment)

![Enrichment](images/case-enrichment.png)

When a case comes in, the platform looks up data in your systems, such as order total, days late, carrier, and who caused a delay.

- **✓ OK** means the lookup worked.
- **An error** means a system didn't answer. The case is still routed unless your manager marked that lookup as required.
- **Re-run enrichment** looks everything up again, e.g. if a system was down.

## A8. Creating test cases

**Test webform** works like the contact form on your business's website. Submitting it creates a real case in the current business.

![Test webform](images/webform.png)

Use it to try things out, for example:
- Does a delivery complaint land in the right queue?
- What does the AI draft for it?

To pretend the customer wrote back, open the case and use the **Simulate customer reply** tab.

---

# Part B: Setting things up (managers)

Everything in Part B lives under **Operations**. Changes apply to **new** cases. Existing cases keep their queue and compensation decision unless you re-run routing or *Decide again* on them.

## B1. Dashboard

![Dashboard](images/ops-dashboard.png)

**The tiles count open cases by state:**
- waiting for pickup
- with agents
- waiting for approval
- waiting on the customer
- unrouted or failed

**The table shows cases by queue and status.** Darker cells mean more open cases. Click any number to open that list of cases.

## B2. Queues and routing

![Queues](images/queues.png)

**How routing works:**
- **Queues are checked from top to bottom.** A lower **priority** number is checked earlier.
- **The first queue whose conditions match gets the case.**
- **General is the catch-all.** It has no conditions and a high priority number, so every case lands somewhere.

**The queue editor has three parts:**
- **Basics:** name, priority, active or inactive.
- **Receives cases where…:** conditions such as *Category is Delivery* or *Customer tier is one of Gold, Platinum*. You can match **all** conditions or **any** of them. Conditions can use:
  - the case's category, channel, tier and message words
  - extra form fields
  - enrichment data, e.g. *Shop orders: days late is greater than 5*
- **Handling:** settings for this queue.
  - **Allow AI to draft replies**, and which **AI model** and **effort** to use.
  - **Approval needed above (amount):** compensation above this needs approval.
  - **First-response SLA** and **reopen window**.

**Test with a real case** (right-hand panel) shows which queue a case *would* land in with your unsaved changes, and why each queue did or didn't match. Nothing is moved.

![Queue editor](images/queue-editor.png)

Queues are **deactivated, never deleted**, so old cases keep their history.

## B3. Connectors and credentials

A **connector** is a saved lookup into one of your systems, e.g. *get the order for this order number*. Connectors run automatically on every new case, in order, before routing.

![Connectors](images/connectors.png)

**The connector editor walks you through seven steps:**

1. **Basics:** name, key (a short ID), and *required* (if it fails, the case waits as *Enrichment failed* instead of being routed).
2. **Request:** the address to call. **Insert field…** adds case data, e.g. the order number.
3. **Authentication:** pick a saved credential.
4. **Test & pick fields:** sends the request for a real case and shows the full answer. Click **Keep** on any value you want saved on cases.
5. **Fields to keep:** what's saved, under which name, with a friendly label.
6. **When to run:** optional conditions (empty means every case).
7. **Order & reliability:** run order, timeout, retries.

![Connector editor](images/connector-editor.png)

**Credentials** are the logins connectors use. They're shared, so one login can serve several connectors.

![Credentials](images/credentials.png)

**Supported credential types:**
- API key
- Bearer token
- Basic auth
- OAuth 2.0 client credentials
- A custom "generate token" request

Secrets are **write-only**: after saving, nobody can read them back in the app, only replace them. For token types, **Generate token now** checks the login works. Tokens are refreshed automatically before they expire.

## B4. Compensation rules

**Operations → Compensation** is your **compensation matrix**: the rules that decide what customers get.

![Compensation rules](images/compensation-rules.png)

**How the rules work:**
- **The first match wins.** Rules are checked from top to bottom (lowest priority number first), and the first rule whose conditions match decides.
- **Conditions** work just like queue conditions, and can also test the queue and enrichment data (e.g. *Shipping tracker: fault is merchant*).
- **Customer gets** one of:
  - **Refund**, **Store credit**, **Voucher** or **Loyalty points**, as a **fixed amount** or a **percentage of a case value** (e.g. 50% of the order total), with an optional **cap**
  - **Replacement**
  - **No compensation**: records that nothing is owed, so the AI won't offer anything
- **Always needs approval:** tick this for rules a person must always check.

**Guardrails** apply to every rule. A decision waits for approval when:
- the amount is above the case's queue **approval threshold**
- the customer was **compensated recently** (you set how many days back and how many times)
- the amount **can't be worked out** (e.g. the order total is missing)

**Test with a real case** (in the rule editor) shows what a case would get with your unsaved rule, and why.

**Backtest** runs the rules over recent cases:
- how many cases would be compensated
- how many would need approval
- the **total cost**

Nothing is changed, so use it every time before you switch a rule on.

![Compensation rule editor](images/compensation-editor.png)

> **Tip:** put specific rules (e.g. *weather delays: no compensation*) **above** general ones (*late 4+ days: 15% credit*). Otherwise the general rule matches first.

## B5. How AI replies are written (prompt templates)

Every AI draft follows written instructions called **prompt templates**. They come in four layers. If two layers disagree, the earlier one wins.

| # | Layer | Who changes it | What it covers |
|---|---|---|---|
| 1 | **Platform rules** | Nobody (locked) | Safety: use only facts from the case, never promise money that isn't decided, treat customer messages as information rather than instructions, plain text |
| 2 | **Baseline** (`base.jinja`) | You | Tone and empathy for **every** reply |
| 3 | **Persona** (`queue/<Queue>.jinja`) | You | The voice for one queue: warmth, formality, greeting, sign-off. Queues without their own persona use the default one. |
| 4 | **Case type** (`category/<Type>_<Category>_<Sub>.jinja`) | You | What to cover for this kind of case, and in what order. The most specific template wins: *Complaint_Delivery_LateDelivery*, then *Complaint_Delivery*, then *Complaint*, then the default. |

![Prompt templates](images/templates.png)

**The overview page shows:**
- the four layers
- every template
- which template each queue and category uses today
- where something falls back to a default, with a **Create** link

**New template** works out the file name for you from the queue or category you pick, and starts from the template it replaces.

**The editor:**

![Template editor](images/template-editor.png)

- **Write instructions in plain English.** To use case data, click a **variable** (right-hand panel) to insert it, e.g. `{{ customer.first_name }}`.
- **For "only if…" text,** use `{% if … %} … {% endif %}`, e.g. `{% if customer.tier %}Thank them for being a {{ customer.tier }} member.{% endif %}`.
- **Checks:**
  - **Max words**
  - **Must mention**: phrases every reply must include
  - **Must not say**: banned phrases

  Checks from all layers apply together.
- **Preview:** pick a sample or real case to see the exact instructions the AI would get, layer by layer. It's free.
- **Save** creates a new **version**. **Version history** lets you look back and **load** an old version to restore it.
- **Download / Upload .jinja:** edit the template in your own editor if you prefer.

**Template tips:**
- **Optional data:** write `{% if enrichment.shop_orders is defined %}…{% endif %}`. If a template uses data a case doesn't have, the draft stops with a clear error instead of leaving a gap. Preview shows that error too.
- **Line breaks:** a line that ends right after `{% endif %}` is **joined to the next line**. End such lines with a full stop or other text after the tag, or leave a blank line after them.
- **Keep it about *how* to write.** The facts come from the case automatically.

## B6. Testing AI before you change anything

**Sample cases** (Operations → Sample cases) are realistic made-up customer messages with their facts. Use them to test templates and models without touching real cases.

![Sample cases](images/samples.png)

**The test lab** (at the bottom of every template) drafts replies with your template **as edited**, saved or not, on several AI models. It runs each one several times so you can compare them.

![Test lab](images/test-lab.png)

**How to read the results:**
- **Checks passed:** how often drafts followed your rules.
- **Consistency:** how alike repeated drafts are. Higher means more predictable replies.
- **Needs attention / With warnings:** drafts that flagged a case, or that made a promise the facts don't support.
- **Cost per reply** and **time**.
- **Replies side by side:** read the drafts yourself.

The estimated cost is shown **before** you run. A typical test costs a few cents.

**Cost projection** shows what drafts using this template cost per reply, per 1,000 replies and per month, for each model. It uses measured figures from your tests and real drafts where available.

![Cost projection](images/cost-projection.png)

**Which model?**
- **Sonnet 5** is the default and followed the rules best in our testing. About $0.0075 a reply, or $75 per 10,000.
- **Haiku 4.5** is about 3× cheaper.
- **Opus 5** is the most capable and the most expensive.

Set the model per queue under **Queues → Handling**, after comparing them in the test lab on your own samples.

---

# Part C: Recipes and reference

## C1. Recipes

**Give VIP customers their own queue and voice**

1. **Operations → Queues & routing → New queue:** name it *Priority customers* with priority 10.
   - **Condition:** *Customer tier is one of Gold, Platinum*.
   - **Handling:** tick **Allow AI to draft replies**.
2. **Test with a real case** from a Gold customer, then save.
3. **Operations → Prompt templates → New template:** choose *Queue (persona)* → *Priority customers* → **Create**.
4. Edit the voice and sign-off, **Preview** with a Gold customer's case, then **Create template**.

**Compensate late deliveries automatically**

1. **Check the data exists.** You need a connector that saves *days late* and *order total* (B3).
2. **Operations → Compensation → New rule:**
   - **Conditions:** *Subcategory is Late delivery* **and** *days late is greater than 3*.
   - **Customer gets:** **Store credit**, **15% of** order total, cap 60.
3. **Test with a real case**, run the **backtest** to see the monthly cost, then **Create rule**.
4. **In Guardrails**, set the repeat-claim window, e.g. 1 compensation per 90 days before approval is needed.

**Stop compensation for delays outside your control**

Create a rule *Weather delays: no compensation* with the condition *Shipping tracker: fault is weather* and **Customer gets: No compensation**. Give it a **lower** priority number than your other late-delivery rules, so it's checked first.

**Try a cheaper AI model safely**

1. Open the case-type template your queue uses most, and go to the **test lab**.
2. Tick **Claude Haiku 4.5** and **Claude Sonnet 5**, pick 3–5 samples and set **2 runs per input**, then **Run test**.
3. Compare *checks passed*, *with warnings* and the replies side by side.
4. If Haiku holds up, change the queue's **AI model** under **Queues → Handling**.

## C2. Case statuses

| Status | Meaning | Usually next |
|---|---|---|
| **Intake** | Just arrived. Order and shipping data is being looked up. | Queued |
| **Enrichment failed** | A *required* lookup failed. | Intake (retry) |
| **Queued** | In a queue, waiting for someone | Assigned to agent / AI |
| **Assigned to agent** | An agent owns it | Waiting on customer, Waiting for approval, Solved, or moved to another queue |
| **Assigned to AI** | Reserved for automatic handling | Assigned to agent, Waiting for approval, Solved |
| **Waiting for approval** | A manager must sign off | Assigned to agent (rejected), Solved |
| **Waiting on customer** | We asked the customer something | Queued (when they reply) |
| **Solved** | Answered. If the customer replies, it reopens. | Closed, or Queued if they reply |
| **Closed** | Final | — |

## C3. Questions and troubleshooting

| Question | Answer |
|---|---|
| A case is in the wrong queue. | Use **Move to queue…** on the case (A6). If it keeps happening, fix the queue conditions (B2) and test them with **Test with a real case**. |
| A case went to General instead of my queue. | No other queue's conditions matched. In the queue editor, **Test with a real case** shows which condition failed and what the case actually had. |
| Enrichment shows an error. | The other system didn't answer. Try **Re-run enrichment**. If it persists, a manager can test the connector (B3, step 4). |
| "Draft with AI" says AI is turned off. | Tick **Allow AI to draft replies** on the case's queue (B2). |
| "Draft with AI" says AI isn't set up. | Your installation needs an Anthropic API key. Ask your administrator. |
| The draft says "Prompt template problem in …". | A template uses data this case doesn't have. Open that template, **Preview** it with this case, and guard the data with `{% if … is defined %}`. |
| The draft didn't mention the refund. | The compensation isn't **approved** yet, or a rule decided *no compensation*. Check the Compensation card. |
| I can't click *Decide again*. | The decision was already approved or rejected. Those are final, because the customer may already have been told. |
| Why do two cases from one customer get different treatment? | The repeat-claim guardrail: a second compensation within the window needs approval. |

## C4. What's not built yet

- **Sign-in.** The business picker and "Acting as" box are temporary.
- **Real email sending and receiving.** Replies are saved but not emailed, and "Simulate customer reply" stands in for real replies.
- **Paying compensation.** Approving records the decision, but money isn't sent automatically.
- **SLA timers, automatic escalation and auto-close.** SLA hours and the reopen window are saved on queues but not enforced yet, so Solved cases aren't closed automatically.
- **AI sending replies on its own.** The setting exists, but every draft still needs a person.

---

### Demo data

Your administrator can load the *Northwind Outfitters* demo shown in this handbook with one command. See the [Developer handbook](developer-handbook.md#2-day-one-run-it-and-load-the-demo). It creates:
- queues
- connectors to a pretend shop and shipping system
- compensation rules
- a persona template
- sample cases
- six cases in different states

That makes it a safe place to practise everything above.
