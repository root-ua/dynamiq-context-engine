import Link from "next/link";

import { Logo } from "@/components/brand/Logo";

export const metadata = {
  title: "Privacy Policy",
};

/**
 * Template Privacy Policy. **Not legal advice** — review before GA.
 */
export default function PrivacyPage() {
  return (
    <main className="mx-auto max-w-2xl space-y-8 p-6 md:p-10">
      <header className="flex items-center justify-between">
        <Logo className="text-base" subtitle="Context Engine" />
        <Link
          className="text-sm text-muted-foreground underline underline-offset-4"
          href="/"
        >
          Home
        </Link>
      </header>

      <h1 className="text-3xl font-semibold tracking-tight">Privacy Policy</h1>

      <p className="text-sm text-muted-foreground">
        <strong>Draft.</strong> Covers the self-serve cloud product. Email{" "}
        <a className="underline" href="mailto:hello@getdynamiq.ai">
          hello@getdynamiq.ai
        </a>{" "}
        with questions or DSAR requests.
      </p>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">What we collect</h2>
        <ul className="list-disc space-y-2 pl-6">
          <li>
            <strong>Account data</strong>: email, name (optional), hashed
            password.
          </li>
          <li>
            <strong>Workspace content</strong>: documents, entities, edges,
            episodes, ontology definitions, attachments — everything you put
            into the product.
          </li>
          <li>
            <strong>Audit logs</strong>: who did what when. Retained as long as
            the workspace exists.
          </li>
          <li>
            <strong>Session + device</strong>: session cookies, IP address, user
            agent — standard for web apps.
          </li>
          <li>
            <strong>Product analytics</strong>: none at launch. If we add
            analytics later, we'll disclose here and make it opt-out.
          </li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Where it lives</h2>
        <ul className="list-disc space-y-2 pl-6">
          <li>
            <strong>Postgres on Render.com</strong> (US) — primary store for
            everything except attachments.
          </li>
          <li>
            <strong>S3-compatible object store</strong> — attachments. Region
            depends on the deployment.
          </li>
          <li>
            <strong>Third-party AI providers</strong> — if you use extraction or
            contradictor features, content is forwarded to Anthropic and/or
            OpenAI at time of use only. They don't retain it for training under
            their API tier terms.
          </li>
          <li>
            <strong>Transactional email</strong> — verification + password reset
            links are sent via Resend. They process the recipient address and
            the email body.
          </li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">What we don't do</h2>
        <ul className="list-disc space-y-2 pl-6">
          <li>We don't sell your data.</li>
          <li>We don't use your content to train our own models.</li>
          <li>
            We don't share your content with other customers; row-level security
            prevents cross-workspace access at the database layer.
          </li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Your rights</h2>
        <p>
          You can access, correct, export, or delete your data at any time. From
          the product: Settings → Danger zone → Delete account. For exports or
          copies of content from a workspace you don't own, email us and we'll
          coordinate with the workspace owner.
        </p>
        <p>
          If you're in the EU, UK, or California, you have specific rights under
          GDPR / UK GDPR / CCPA. Email{" "}
          <a className="underline" href="mailto:hello@getdynamiq.ai">
            hello@getdynamiq.ai
          </a>{" "}
          with your request; we'll respond within 30 days.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Retention</h2>
        <p>
          Workspace content is retained while the workspace is active. When a
          workspace is soft-deleted, hard-deletion follows within 30 days.
          Account data is retained while the account is active; on account
          deletion, identifying data is removed immediately and cascading
          records are purged within 30 days.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Sub-processors</h2>
        <ul className="list-disc space-y-2 pl-6">
          <li>Render.com — hosting + managed databases</li>
          <li>Anthropic — LLM inference (extraction, contradictor)</li>
          <li>OpenAI — embeddings (search)</li>
          <li>Resend — transactional email</li>
          <li>
            The S3-compatible bucket provider you use (AWS, Cloudflare R2,
            Backblaze, etc.)
          </li>
        </ul>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Security</h2>
        <p>
          Passwords are argon2-hashed. Long-lived agent tokens are argon2-
          hashed and can be revoked at any time. Session cookies are HttpOnly +
          SameSite=Lax (+ Secure in production). We run multi- tenant RLS so
          cross-workspace data access is impossible at the DB layer.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">Contact</h2>
        <p>
          <a className="underline" href="mailto:hello@getdynamiq.ai">
            hello@getdynamiq.ai
          </a>
        </p>
      </section>

      <p className="text-xs text-muted-foreground">Last updated: 2026-04-22</p>
    </main>
  );
}
