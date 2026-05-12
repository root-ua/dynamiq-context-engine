"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";

import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { useToast } from "@/components/ui/toast";
import { authClient } from "@/lib/auth-client";

/**
 * Post-signup landing. Tells the user to check their inbox, and offers
 * a "resend" button. The actual verification link opens a BetterAuth
 * endpoint that signs the user in directly on success — this page is
 * only shown to users who still need to verify.
 */
export default function VerifyPage() {
  const search = useSearchParams();
  const email = search.get("email") ?? "";
  const { push } = useToast();
  const [sending, setSending] = useState(false);

  async function resend() {
    if (!email) return;
    setSending(true);
    try {
      await authClient.sendVerificationEmail({ email });
      push({ title: "Verification email sent", description: email });
    } catch (err) {
      push({
        title: "Couldn't resend",
        description: err instanceof Error ? err.message : String(err),
        variant: "destructive",
      });
    } finally {
      setSending(false);
    }
  }

  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-md space-y-6">
        <div className="flex justify-center">
          <Logo className="text-base" subtitle="Context Engine" />
        </div>
        <Card>
          <CardHeader>
            <CardTitle>Check your inbox</CardTitle>
            <CardDescription>
              {email ? (
                <>
                  We sent a verification link to{" "}
                  <span className="font-medium text-foreground">{email}</span>.
                </>
              ) : (
                "We sent you a verification link."
              )}{" "}
              Click it to finish setting up your account.
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            <p className="text-sm text-muted-foreground">
              The link expires in one hour. If you don't see it, check your spam
              folder.
            </p>
            <div className="flex gap-2">
              <Button
                variant="outline"
                onClick={resend}
                disabled={sending || !email}
              >
                {sending ? "Sending…" : "Resend email"}
              </Button>
              <Button variant="ghost" asChild>
                <Link href="/login">Back to sign in</Link>
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </main>
  );
}
