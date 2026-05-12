import Link from "next/link";
import { PiCheck } from "react-icons/pi";

import { Footer } from "@/components/app-shell/Footer";
import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";

export const metadata = {
  title: "Pricing",
};

export default function PricingPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-6 py-5">
        <Link href="/">
          <Logo className="text-base" subtitle="Context Engine" />
        </Link>
        <nav className="flex items-center gap-2">
          <Button variant="ghost" asChild>
            <Link href="/login">Sign in</Link>
          </Button>
          <Button asChild>
            <Link href="/signup">Get started</Link>
          </Button>
        </nav>
      </header>

      <section className="mx-auto w-full max-w-5xl flex-1 px-6 pb-16">
        <div className="pb-12 pt-8 text-center">
          <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
            Simple pricing
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-muted-foreground">
            Self-host is free forever. Cloud is priced per seat. Enterprise
            terms on request.
          </p>
        </div>

        <div className="grid gap-4 lg:grid-cols-3">
          <Tier
            name="Self-host"
            price="Free"
            tagline="Your hardware. Your rules."
            cta={{ label: "GitHub →", href: "https://github.com/dynamiq-ai" }}
            ctaVariant="outline"
            features={[
              "Full product, including MCP server",
              "Docker compose + render.yaml blueprint",
              "Unlimited workspaces, unlimited seats",
              "Community support",
            ]}
          />
          <Tier
            name="Cloud Pro"
            price="Design-partner pricing"
            tagline="Hosted by us. One click onboarding."
            cta={{ label: "Contact sales", href: "/contact" }}
            ctaVariant="default"
            highlight
            features={[
              "Managed Postgres + Redis + S3",
              "Daily backups, 30-day retention",
              "Priority email support",
              "99.9% uptime target",
            ]}
          />
          <Tier
            name="Enterprise"
            price="Custom"
            tagline="For teams with procurement."
            cta={{ label: "Contact sales", href: "/contact" }}
            ctaVariant="outline"
            features={[
              "SSO / SAML, SCIM",
              "Dedicated tenancy",
              "Custom data residency",
              "Security review support (SOC 2, GDPR, HIPAA)",
              "Uptime SLA + dedicated onboarding",
            ]}
          />
        </div>

        <div className="mt-16 rounded-lg border bg-card/40 p-6 text-sm text-muted-foreground">
          <p className="font-semibold text-foreground">
            Why "design-partner pricing"?
          </p>
          <p className="mt-2">
            Dynamiq Context Engine is early. Our first ~20 customers are helping
            us shape the product; in exchange, we're offering below- list
            pricing and direct access to the team. Once we're GA we'll post
            per-seat pricing here; until then, we want to learn about your
            workflow before we quote.
          </p>
        </div>
      </section>

      <Footer />
    </div>
  );
}

function Tier({
  name,
  price,
  tagline,
  features,
  cta,
  ctaVariant,
  highlight,
}: {
  name: string;
  price: string;
  tagline: string;
  features: string[];
  cta: { label: string; href: string };
  ctaVariant: "default" | "outline";
  highlight?: boolean;
}) {
  return (
    <div
      className={
        "flex flex-col rounded-lg border p-6 " +
        (highlight ? "border-brand/50 bg-brand/5" : "bg-card/60")
      }
    >
      <div className="flex items-start justify-between">
        <div>
          <div className="text-xl font-semibold tracking-tight">{name}</div>
          <p className="text-sm text-muted-foreground">{tagline}</p>
        </div>
        {highlight && (
          <span className="rounded-full bg-brand/20 px-2 py-0.5 text-xs font-medium text-brand">
            Popular
          </span>
        )}
      </div>
      <div className="mt-4 text-3xl font-semibold tracking-tight">{price}</div>

      <ul className="mt-6 flex-1 space-y-2 text-sm">
        {features.map((f) => (
          <li key={f} className="flex items-start gap-2">
            <PiCheck className="mt-0.5 h-4 w-4 shrink-0 text-brand" />
            <span>{f}</span>
          </li>
        ))}
      </ul>

      <Button className="mt-6 w-full" variant={ctaVariant} asChild>
        {cta.href.startsWith("http") ? (
          <a href={cta.href} target="_blank" rel="noopener noreferrer">
            {cta.label}
          </a>
        ) : (
          <Link href={cta.href}>{cta.label}</Link>
        )}
      </Button>
    </div>
  );
}
