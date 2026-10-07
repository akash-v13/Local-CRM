/** Server settings and app-password help for common providers (IMAP/SMTP). */
import type { MailProvider, MailSecurity } from "../api/types";

export interface ProviderPreset {
  label: string;
  imap: { host: string; port: number; security: MailSecurity };
  smtp: { host: string; port: number; security: MailSecurity };
  help: string;
  helpUrl?: string;
}

export const PROVIDERS: Record<MailProvider, ProviderPreset> = {
  gmail: {
    label: "Gmail / Google Workspace",
    imap: { host: "imap.gmail.com", port: 993, security: "ssl" },
    smtp: { host: "smtp.gmail.com", port: 465, security: "ssl" },
    help: "Turn on 2-Step Verification for the account, then create an app password and paste it here. IMAP must be enabled in Gmail settings (Forwarding and POP/IMAP).",
    helpUrl: "https://myaccount.google.com/apppasswords",
  },
  icloud: {
    label: "iCloud Mail",
    imap: { host: "imap.mail.me.com", port: 993, security: "ssl" },
    smtp: { host: "smtp.mail.me.com", port: 587, security: "starttls" },
    help: "Create an app-specific password (Apple Account → Sign-In and Security → App-Specific Passwords). Use the full iCloud address as the username.",
    helpUrl: "https://account.apple.com",
  },
  yahoo: {
    label: "Yahoo Mail",
    imap: { host: "imap.mail.yahoo.com", port: 993, security: "ssl" },
    smtp: { host: "smtp.mail.yahoo.com", port: 465, security: "ssl" },
    help: "Generate an app password in Yahoo Account Security.",
    helpUrl: "https://login.yahoo.com/account/security",
  },
  fastmail: {
    label: "Fastmail",
    imap: { host: "imap.fastmail.com", port: 993, security: "ssl" },
    smtp: { host: "smtp.fastmail.com", port: 465, security: "ssl" },
    help: "Create an app password with IMAP and SMTP access (Settings → Privacy & Security → Manage app passwords).",
  },
  zoho: {
    label: "Zoho Mail",
    imap: { host: "imap.zoho.com", port: 993, security: "ssl" },
    smtp: { host: "smtp.zoho.com", port: 465, security: "ssl" },
    help: "Create an application-specific password in Zoho Accounts → Security. EU accounts use imap.zoho.eu / smtp.zoho.eu.",
  },
  custom: {
    label: "Other (IMAP/SMTP)",
    imap: { host: "", port: 993, security: "ssl" },
    smtp: { host: "", port: 465, security: "ssl" },
    help: "Your email host's IMAP and SMTP settings. Use an app password if the provider offers them.",
  },
};

export const SECURITY_LABELS: Record<MailSecurity, string> = {
  ssl: "SSL/TLS",
  starttls: "STARTTLS",
  none: "None (local testing only)",
};
