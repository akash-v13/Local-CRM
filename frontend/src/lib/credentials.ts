/**
 * The credential types, described once. The credential editor renders its
 * form from this, so adding a type means adding an entry here (plus the
 * backend support in app/connectors/auth.py).
 */
import type { CredentialKind } from "../api/types";

export interface ConfigField {
  name: string;
  label: string;
  hint?: string;
  type: "text" | "code" | "number" | "select" | "textarea";
  options?: { value: string; label: string }[];
  defaultValue: string;
  required?: boolean;
  /** Only show when another config field has one of these values. */
  showWhen?: { field: string; values: string[] };
}

export interface CredentialType {
  kind: CredentialKind;
  label: string;
  summary: string;
  /** True for kinds that call a token endpoint and cache the token. */
  generatesToken: boolean;
  config: ConfigField[];
  /** Fixed secret fields. null = the user names their own (token_request). */
  secrets: { name: string; label: string }[] | null;
}

export const CREDENTIAL_TYPES: CredentialType[] = [
  {
    kind: "api_key",
    label: "API key",
    summary: "A key sent in a header on every request, e.g. X-Api-Key: …",
    generatesToken: false,
    config: [{ name: "header_name", label: "Header name", type: "text", defaultValue: "X-Api-Key", required: true }],
    secrets: [{ name: "key", label: "API key" }],
  },
  {
    kind: "bearer",
    label: "Bearer token",
    summary: "A fixed token sent as Authorization: Bearer …",
    generatesToken: false,
    config: [],
    secrets: [{ name: "token", label: "Token" }],
  },
  {
    kind: "basic",
    label: "Basic auth",
    summary: "Username and password, sent as Authorization: Basic …",
    generatesToken: false,
    config: [],
    secrets: [
      { name: "username", label: "Username" },
      { name: "password", label: "Password" },
    ],
  },
  {
    kind: "oauth2_client_credentials",
    label: "OAuth 2.0 (client credentials)",
    summary:
      "Exchanges a client ID and secret for an access token at a token URL. The token is cached and refreshed automatically.",
    generatesToken: true,
    config: [
      { name: "token_url", label: "Token URL", type: "code", defaultValue: "", required: true, hint: "e.g. https://auth.example.com/oauth/token" },
      { name: "scope", label: "Scope", type: "text", defaultValue: "", hint: "Optional, space-separated." },
      { name: "audience", label: "Audience", type: "text", defaultValue: "", hint: "Optional (some providers, e.g. Auth0, need it)." },
      {
        name: "client_auth",
        label: "Send client ID/secret",
        type: "select",
        defaultValue: "body",
        options: [
          { value: "body", label: "In the request body (most common)" },
          { value: "basic_header", label: "As a Basic auth header" },
        ],
      },
    ],
    secrets: [
      { name: "client_id", label: "Client ID" },
      { name: "client_secret", label: "Client secret" },
    ],
  },
  {
    kind: "token_request",
    label: "Custom token request",
    summary:
      "For APIs with their own “generate token” endpoint. You define the request, where the token is in the response, and how to send it. Cached and refreshed automatically.",
    generatesToken: true,
    config: [
      {
        name: "method",
        label: "Method",
        type: "select",
        defaultValue: "POST",
        options: [
          { value: "POST", label: "POST" },
          { value: "GET", label: "GET" },
        ],
      },
      { name: "url", label: "Token URL", type: "code", defaultValue: "", required: true, hint: "Can use {{secret.<name>}}." },
      {
        name: "body_format",
        label: "Body format",
        type: "select",
        defaultValue: "json",
        options: [
          { value: "json", label: "JSON" },
          { value: "form", label: "Form (x-www-form-urlencoded)" },
        ],
        showWhen: { field: "method", values: ["POST"] },
      },
      {
        name: "body_template",
        label: "Body",
        type: "textarea",
        defaultValue: '{"username": "{{secret.username}}", "password": "{{secret.password}}"}',
        hint: "JSON: put {{secret.<name>}} inside quotes. Form: user={{secret.username}}&pass={{secret.password}}",
        showWhen: { field: "method", values: ["POST"] },
      },
      { name: "token_path", label: "Token is at", type: "code", defaultValue: "access_token", required: true, hint: "Path in the JSON response, e.g. data.token" },
      { name: "expires_in_path", label: "Expires-in (seconds) is at", type: "code", defaultValue: "expires_in", hint: "Optional. Leave blank if the response doesn't say." },
      { name: "default_ttl_seconds", label: "Otherwise assume it lasts (seconds)", type: "number", defaultValue: "3600" },
      { name: "header_name", label: "Send the token in header", type: "text", defaultValue: "Authorization" },
      { name: "header_prefix", label: "Header value prefix", type: "text", defaultValue: "Bearer ", hint: 'Include the trailing space, e.g. "Bearer ".' },
    ],
    secrets: null,
  },
  {
    kind: "shopify",
    label: "Shopify store",
    summary:
      "Your Shopify store, through an app you create in Shopify's Dev Dashboard. Its client ID and secret are exchanged for a 24-hour access token, refreshed automatically. Easiest from Operations → Shopify.",
    generatesToken: true,
    config: [{ name: "shop", label: "Store domain", type: "code", defaultValue: "", required: true, hint: "e.g. northwind.myshopify.com" }],
    secrets: [
      { name: "client_id", label: "Client ID" },
      { name: "client_secret", label: "Client secret" },
    ],
  },
];

export function credentialType(kind: CredentialKind): CredentialType {
  return CREDENTIAL_TYPES.find((t) => t.kind === kind) ?? CREDENTIAL_TYPES[0];
}

/** One-line description of a credential's setup, for lists. */
export function credentialDetail(kind: CredentialKind, config: Record<string, unknown>): string {
  switch (kind) {
    case "api_key":
      return `Header ${String(config.header_name ?? "")}`;
    case "oauth2_client_credentials":
      return String(config.token_url ?? "");
    case "token_request":
      return `${String(config.method ?? "POST")} ${String(config.url ?? "")}`;
    case "shopify":
      return String(config.shop ?? "");
    default:
      return "";
  }
}

/** "connector-like name" → "connector_like_name", for connector keys. */
export function slugify(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .replace(/^[^a-z]+/, "")
    .slice(0, 40);
  return slug.length >= 2 ? slug : "";
}
