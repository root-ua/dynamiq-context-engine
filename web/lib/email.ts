/**
 * Transactional email sender (Resend).
 *
 * Falls back to `console.log` when RESEND_API_KEY is unset — this keeps
 * local dev unblocked without requiring the API key, and makes it easy
 * to read verification / reset links from the terminal.
 *
 * All email sending happens server-side; this module is only imported
 * from route handlers and auth hooks. Never from client components.
 */

type Payload = {
  to: string;
  subject: string;
  text: string;
  html?: string;
};

export async function sendTransactional(payload: Payload): Promise<void> {
  const apiKey = process.env.RESEND_API_KEY;
  const from = process.env.EMAIL_FROM ?? "Dynamiq <noreply@getdynamiq.ai>";

  if (!apiKey) {
    // Dev fallback — print the email so the developer can click the link
    // from the terminal without configuring Resend.
    console.log(
      `\n[email.dev-fallback] to=${payload.to} subject=${payload.subject}\n${payload.text}\n`,
    );
    return;
  }

  const res = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: {
      Authorization: `Bearer ${apiKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      from,
      to: payload.to,
      subject: payload.subject,
      text: payload.text,
      html: payload.html ?? undefined,
    }),
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`resend.send failed ${res.status}: ${body}`);
  }
}

export function verificationEmail(params: {
  to: string;
  url: string;
}): Payload {
  return {
    to: params.to,
    subject: "Verify your Dynamiq account",
    text: `Welcome to Dynamiq Context Engine.

Verify your email to finish setting up your account:

${params.url}

This link expires in 1 hour. If you didn't sign up, ignore this message.`,
    html: brandedEmailHtml({
      preheader: "Verify your email to finish setting up your Dynamiq account.",
      heading: "Verify your email",
      body: "Click below to finish setting up your Dynamiq account. This link expires in one hour.",
      ctaLabel: "Verify email",
      ctaUrl: params.url,
      footer: "If you didn't sign up for Dynamiq, ignore this message.",
    }),
  };
}

export function passwordResetEmail(params: {
  to: string;
  url: string;
}): Payload {
  return {
    to: params.to,
    subject: "Reset your Dynamiq password",
    text: `We received a request to reset the password on your Dynamiq account.

Reset your password:

${params.url}

This link expires in 1 hour. If you didn't request this, ignore this message — your password is unchanged.`,
    html: brandedEmailHtml({
      preheader: "Reset the password on your Dynamiq account.",
      heading: "Reset your password",
      body: "We got a request to reset the password on your Dynamiq account. Click below to continue. This link expires in one hour.",
      ctaLabel: "Reset password",
      ctaUrl: params.url,
      footer:
        "If you didn't request this, ignore this message — your password is unchanged.",
    }),
  };
}

function brandedEmailHtml(opts: {
  preheader: string;
  heading: string;
  body: string;
  ctaLabel: string;
  ctaUrl: string;
  footer: string;
}): string {
  return `<!doctype html>
<html>
<head><meta charset="utf-8"><title>Dynamiq</title></head>
<body style="margin:0;padding:0;background:#f6f6f6;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;color:#111;">
  <div style="display:none;max-height:0;overflow:hidden;">${escapeHtml(opts.preheader)}</div>
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#f6f6f6;">
    <tr><td align="center" style="padding:32px 16px;">
      <table role="presentation" width="520" cellspacing="0" cellpadding="0" style="background:#ffffff;border-radius:12px;overflow:hidden;">
        <tr><td style="padding:24px 28px 0 28px;">
          <div style="font-size:13px;font-weight:600;letter-spacing:-0.01em;color:#0a0a0a;">Dynamiq <span style="opacity:0.55;font-weight:400;">Context Engine</span></div>
        </td></tr>
        <tr><td style="padding:20px 28px 8px 28px;">
          <h1 style="margin:0;font-size:22px;font-weight:600;letter-spacing:-0.02em;">${escapeHtml(opts.heading)}</h1>
        </td></tr>
        <tr><td style="padding:0 28px 12px 28px;">
          <p style="margin:0;font-size:15px;line-height:1.5;color:#333;">${escapeHtml(opts.body)}</p>
        </td></tr>
        <tr><td style="padding:8px 28px 24px 28px;">
          <a href="${escapeAttr(opts.ctaUrl)}" style="display:inline-block;background:#0a0a0a;color:#ffffff;text-decoration:none;padding:10px 18px;border-radius:8px;font-weight:600;font-size:14px;">${escapeHtml(opts.ctaLabel)}</a>
        </td></tr>
        <tr><td style="padding:0 28px 28px 28px;">
          <p style="margin:0;font-size:12px;color:#666;line-height:1.5;">${escapeHtml(opts.footer)}</p>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body>
</html>`;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function escapeAttr(s: string): string {
  return escapeHtml(s);
}
