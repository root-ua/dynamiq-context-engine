"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Logo } from "@/components/brand/Logo";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useToast } from "@/components/ui/toast";
import { authClient } from "@/lib/auth-client";

export default function SignupPage() {
  const router = useRouter();
  const { push } = useToast();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    const { error } = await authClient.signUp.email({ name, email, password });
    setSubmitting(false);
    if (error) {
      push({
        title: "Sign up failed",
        description: error.message,
        variant: "destructive",
      });
      return;
    }
    // BetterAuth is configured with requireEmailVerification: true +
    // sendOnSignUp: true. The user needs to click the link in their
    // email before they can sign in.
    void router.push(`/verify?email=${encodeURIComponent(email)}`);
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-md space-y-6">
        <div className="flex justify-center">
          <Logo className="text-base" subtitle="Context Engine" />
        </div>
        <Card className="w-full">
          <CardHeader>
            <CardTitle>Create account</CardTitle>
            <CardDescription>
              One ontology for you and your agents. Bi-temporal. Self-hosted.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <form onSubmit={onSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <Label htmlFor="name">Name</Label>
                <Input
                  id="name"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  autoComplete="email"
                  required
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  autoComplete="new-password"
                  minLength={8}
                  required
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
                <p className="text-xs text-muted-foreground">
                  At least 8 characters.
                </p>
              </div>
              <Button type="submit" disabled={submitting} className="w-full">
                {submitting ? "Creating…" : "Create account"}
              </Button>
              <p className="text-center text-sm text-muted-foreground">
                Already have one?{" "}
                <Link className="underline underline-offset-4" href="/login">
                  Sign in
                </Link>
              </p>
            </form>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
