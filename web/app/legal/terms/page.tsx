import Link from "next/link";

import { Logo } from "@/components/brand/Logo";

export const metadata = {
  title: "Terms of Service",
};

/**
 * Template Terms of Service. Early-stage SaaS language. **Not legal
 * advice** — a real lawyer should review before GA.
 */
export default function TermsPage() {
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

      <h1 className="text-3xl font-semibold tracking-tight">
        Terms of Service
      </h1>

      <p className="text-sm text-muted-foreground">
        <strong>Draft.</strong> These terms are a starting point for an
        early-stage design-partner relationship. Email{" "}
        <a className="underline" href="mailto:hello@getdynamiq.ai">
          hello@getdynamiq.ai
        </a>{" "}
        if you need a custom MSA.
      </p>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">1. Account</h2>
        <p>
          You need a valid email to sign up. You are responsible for keeping
          your credentials secret and for activity that happens under your
          account. You must be at least 18 years old to use Dynamiq Context
          Engine ("the Service").
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">2. Acceptable use</h2>
        <p>
          Don't use the Service to break the law, violate anyone's rights, or
          attack our infrastructure. Don't upload content you don't have the
          right to process. Don't attempt to exfiltrate other customers' data or
          bypass our tenancy isolation.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">3. Your data</h2>
        <p>
          You own the content you upload. You grant us a narrow license to
          process it solely to deliver the Service (store it, serve it back to
          you, pass it to AI providers you've configured). We don't use your
          content to train models. We don't sell your data to third parties.
        </p>
        <p>
          You can export or delete your data at any time from Settings → Danger
          zone. Hard-deletion happens within 30 days of the soft-delete request.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">4. AI providers</h2>
        <p>
          When you use features that call third-party AI providers (Anthropic,
          OpenAI) using our keys, your content is transmitted to those providers
          subject to their terms. If you want to use your own keys or self-host,
          talk to us.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">5. Availability</h2>
        <p>
          We aim for high availability but don't guarantee specific uptime SLAs
          on the self-serve plan. Enterprise plans can include an SLA — contact
          sales.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">6. Payment</h2>
        <p>
          Paid plans are billed in advance. Fees are non-refundable except where
          required by law. You can cancel any time; cancellation stops future
          renewals but does not entitle you to a refund for the current period.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">7. Termination</h2>
        <p>
          You can close your account at any time. We can suspend or terminate
          your account for material breach of these terms, with notice where
          practical.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">8. Liability</h2>
        <p>
          The Service is provided "as is". To the maximum extent permitted by
          law, we disclaim warranties of merchantability, fitness for a
          particular purpose, and non-infringement. Our aggregate liability is
          capped at the fees you paid us in the 12 months preceding the claim.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">9. Changes</h2>
        <p>
          We may update these terms. Material changes will be announced at least
          30 days in advance by email to the account owner. Continued use after
          the effective date constitutes acceptance.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">10. Governing law</h2>
        <p>
          These terms are governed by the laws of the State of Delaware, USA,
          without regard to conflict-of-laws rules.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-xl font-semibold">11. Contact</h2>
        <p>
          Email{" "}
          <a className="underline" href="mailto:hello@getdynamiq.ai">
            hello@getdynamiq.ai
          </a>{" "}
          for legal notices and support.
        </p>
      </section>

      <p className="text-xs text-muted-foreground">Last updated: 2026-04-22</p>
    </main>
  );
}
