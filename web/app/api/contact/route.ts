import { type NextRequest, NextResponse } from "next/server";

import { sendTransactional } from "@/lib/email";

export async function POST(req: NextRequest) {
  let body: Record<string, unknown>;
  try {
    body = (await req.json()) as Record<string, unknown>;
  } catch {
    return NextResponse.json({ error: "bad json" }, { status: 400 });
  }

  const asStr = (v: unknown, max: number): string =>
    typeof v === "string" ? v.slice(0, max) : "";

  const name = asStr(body.name, 200);
  const email = asStr(body.email, 200);
  const company = asStr(body.company, 200);
  const message = asStr(body.message, 5000);

  if (!email.includes("@") || message.length < 5) {
    return NextResponse.json({ error: "invalid" }, { status: 400 });
  }

  await sendTransactional({
    to: "hello@getdynamiq.ai",
    subject: `Contact: ${name || email}`,
    text: `From: ${name || "(no name)"} <${email}>\nCompany: ${company || "—"}\n\n${message}`,
  });

  return NextResponse.json({ ok: true });
}
