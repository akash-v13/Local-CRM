/**
 * Prompt template names, mirroring backend/app/ai/engine.py.
 *
 *   base.jinja                                   baseline: tone & empathy for every reply
 *   queue/<Queue>.jinja                          persona for a queue (voice, empathy, sign-off)
 *   category/<Type>[_<Category>[_<Sub>]].jinja   what to answer for a case type
 *
 * The most specific template that exists wins; otherwise the broader one, then _default.
 */
import type { Layer, TemplateKind } from "../api/types";

export const BASE = "base.jinja";
export const PERSONA_DEFAULT = "queue/_default.jinja";
export const CATEGORY_DEFAULT = "category/_default.jinja";

/** "Late delivery" → "LateDelivery", "High-value VIP" → "HighValueVIP". */
export function slug(text: string): string {
  return (text.match(/[A-Za-z0-9]+/g) ?? []).map((w) => w[0].toUpperCase() + w.slice(1)).join("");
}

export function personaNames(queueName: string | null | undefined): string[] {
  const s = queueName ? slug(queueName) : "";
  return s ? [`queue/${s}.jinja`, PERSONA_DEFAULT] : [PERSONA_DEFAULT];
}

export function categoryNames(type?: string, category?: string, subcategory?: string): string[] {
  const parts = [type, category, subcategory].map((p) => slug(p ?? ""));
  const names: string[] = [];
  for (const depth of [3, 2, 1]) {
    const segment = parts.slice(0, depth);
    if (segment.every(Boolean)) names.push(`category/${segment.join("_")}.jinja`);
  }
  return [...names, CATEGORY_DEFAULT];
}

const NAME = /^(base\.jinja|queue\/[A-Za-z0-9_]+\.jinja|category\/[A-Za-z0-9_]+\.jinja)$/;
export const isValidName = (name: string) => NAME.test(name);

export function kindOf(name: string): TemplateKind {
  if (name === BASE) return "base";
  return name.startsWith("queue/") ? "persona" : "category";
}

export const KIND_LABEL: Record<TemplateKind, string> = {
  base: "Baseline",
  persona: "Persona",
  category: "Case type",
};

export const LAYER_LABEL: Record<Layer, string> = {
  baseline: "Baseline",
  persona: "Persona",
  category: "Case type",
};

/** The template a new one would currently fall back to (to start from its content). */
export function fallbackFor(name: string, existing: Set<string>): string | undefined {
  const kind = kindOf(name);
  if (kind === "base") return undefined;
  if (kind === "persona") return PERSONA_DEFAULT;
  const parts = name.slice("category/".length, -".jinja".length).split("_");
  const chain = categoryNames(...(parts as [string?, string?, string?])).filter((n) => n !== name);
  return chain.find((n) => existing.has(n));
}

/** "category/Complaint_Delivery_LateDelivery.jinja" → "Complaint › Delivery › LateDelivery". */
export function displayName(name: string): string {
  if (name === BASE) return "Baseline (all replies)";
  const stem = name.replace(/^(queue|category)\//, "").replace(/\.jinja$/, "");
  if (stem === "_default") return name.startsWith("queue/") ? "Default persona" : "Default case type";
  return stem.split("_").join(" › ");
}
