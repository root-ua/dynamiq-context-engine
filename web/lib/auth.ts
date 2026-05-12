import { betterAuth } from "better-auth";
import { Pool } from "pg";

import {
  passwordResetEmail,
  sendTransactional,
  verificationEmail,
} from "./email";

const pool = new Pool({ connectionString: process.env.POSTGRES_URL });

const baseURL =
  process.env.BETTER_AUTH_URL ||
  process.env.NEXT_PUBLIC_BETTER_AUTH_URL ||
  "http://localhost:3000";

export const auth = betterAuth({
  database: pool,
  secret: process.env.BETTER_AUTH_SECRET!,
  baseURL,
  emailAndPassword: {
    enabled: true,
    // Real products require email verification. autoSignIn stays off
    // because we want the user to go through /verify before landing in
    // the app — clicking the verification link signs them in.
    autoSignIn: false,
    requireEmailVerification: true,
    minPasswordLength: 8,
    sendResetPassword: async ({ user, url }) => {
      await sendTransactional(passwordResetEmail({ to: user.email, url }));
    },
  },
  emailVerification: {
    sendOnSignUp: true,
    autoSignInAfterVerification: true,
    expiresIn: 60 * 60, // 1 hour
    sendVerificationEmail: async ({ user, url }) => {
      await sendTransactional(verificationEmail({ to: user.email, url }));
    },
  },
  session: {
    expiresIn: 60 * 60 * 24 * 30,
    updateAge: 60 * 60 * 24,
  },
  advanced: {
    useSecureCookies: process.env.NODE_ENV === "production",
    database: {
      // Match the uuid-typed FKs in the platform schema so BetterAuth's
      // user.id can be used as workspace_member.user_id / created_by / etc.
      generateId: "uuid",
    },
  },
  databaseHooks: {
    user: {
      create: {
        after: async (user) => {
          // Mirror BetterAuth user into app_user so FKs (workspace_member.user_id,
          // entity.created_by, etc.) can reference the same id.
          await pool.query(
            `INSERT INTO app_user (id, email, name)
             VALUES ($1, $2, $3)
             ON CONFLICT (id) DO UPDATE
               SET email = EXCLUDED.email, name = EXCLUDED.name`,
            [user.id, user.email, user.name ?? null],
          );
        },
      },
    },
  },
});

export type Auth = typeof auth;
