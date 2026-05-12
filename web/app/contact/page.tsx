"use client";

import Link from "next/link";
import { useState } from "react";

import { Footer } from "@/components/app-shell/Footer";
import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";

export default function ContactPage() {
  const { push } = useToast();
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);

  async function onSubmit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setSubmitting(true);
    const form = new FormData(e.currentTarget);
    try {
      const res = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: form.get("name"),
          email: form.get("email"),
          company: form.get("company"),
          message: form.get("message"),
        }),
      });
      if (!res.ok) throw new Error(`status ${res.status}`);
      setSent(true);
    } catch {
      push({
        title: "Couldn't send — email us directly",
        description: "hello@getdynamiq.ai",
        variant: "destructive",
      });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="mx-auto flex w-full max-w-6xl items-center justify-between gap-4 px-6 py-5">
        <Link href="/">
          <Logo className="text-base" subtitle="Context Engine" />
        </Link>
        <nav className="flex items-center gap-2">
          <Button variant="ghost" asChild>
            <Link href="/pricing">Pricing</Link>
          </Button>
          <Button variant="ghost" asChild>
            <Link href="/login">Sign in</Link>
          </Button>
        </nav>
      </header>

      <main className="mx-auto flex w-full max-w-xl flex-1 flex-col justify-center p-6">
        <Card>
          <CardHeader>
            <CardTitle>Talk to us</CardTitle>
            <CardDescription>
              Design-partner program, enterprise demos, support escalations. We
              read every message. Or email{" "}
              <a className="underline" href="mailto:hello@getdynamiq.ai">
                hello@getdynamiq.ai
              </a>{" "}
              directly.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {sent ? (
              <p className="text-sm">
                Got it — we'll be in touch within a business day.
              </p>
            ) : (
              <form onSubmit={onSubmit} className="space-y-3">
                <div className="grid gap-3 sm:grid-cols-2">
                  <div className="space-y-1">
                    <Label htmlFor="name">Name</Label>
                    <Input id="name" name="name" required />
                  </div>
                  <div className="space-y-1">
                    <Label htmlFor="company">Company (optional)</Label>
                    <Input id="company" name="company" />
                  </div>
                </div>
                <div className="space-y-1">
                  <Label htmlFor="email">Email</Label>
                  <Input id="email" name="email" type="email" required />
                </div>
                <div className="space-y-1">
                  <Label htmlFor="message">What do you want to do?</Label>
                  <Textarea id="message" name="message" rows={6} required />
                </div>
                <Button type="submit" disabled={submitting}>
                  {submitting ? "Sending…" : "Send"}
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
      </main>

      <Footer />
    </div>
  );
}
