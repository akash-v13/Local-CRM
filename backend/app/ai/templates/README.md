# Prompt templates

Every AI draft is built from these layers (see `_platform/system.jinja`):

| Layer | File | Who owns it | What it's for |
|---|---|---|---|
| Platform rules | `_platform/guardrails.jinja` | The platform (locked) | Safety: facts only, no undecided compensation, untrusted customer text, placeholders, plain text |
| Baseline | `base.jinja` | Each business | Tone & empathy rules **every** reply follows |
| Persona | `queue/<Queue>.jinja` → `queue/_default.jinja` | Each business | Who is speaking for this queue: tone, empathy level, formality, sign-off |
| Case type | `category/<Type>_<Category>_<Subcategory>.jinja` → `<Type>_<Category>` → `<Type>` → `category/_default.jinja` | Each business | How to answer this kind of case |
| Case facts | `_platform/case.jinja` | The platform (locked) | The user message: case facts + conversation |

`defaults/` holds the starter pack every business begins with. Businesses edit
their own copies in the Operations Portal (stored per business, versioned).

Names: each part of a category/queue name becomes PascalCase without spaces,
e.g. Complaint › Delivery › Late delivery → `category/Complaint_Delivery_LateDelivery.jinja`,
queue "High value" → `queue/HighValue.jinja`.

## Header (checks)

A template may start with a header comment; it travels with downloaded files:

```
{#---
description: Late delivery complaints
max_words: 170
must_include: sorry
must_not_include: unfortunately for you, voucher
---#}
```

## Variables (personal data already masked)

- `business.name`
- `case.number`, `case.channel`, `case.type`, `case.category`, `case.subcategory`, `case.queue`, `case.attributes.<field>`
- `customer.name`, `customer.first_name` (placeholders such as `[CUSTOMER_NAME]`, or none), `customer.tier`
- `enrichment.<connector key>.<field>`: guard with `{% if enrichment.shop_orders is defined %}`
- `decisions.compensation` (none until the compensation matrix exists)
- `thread` (list of `{from, text}`), `latest_message`

Templates run in a sandbox: no `include`/`extends`/`import` (layers are
combined automatically), and using a variable a case doesn't have stops the
draft with a clear error instead of silently rendering nothing.
