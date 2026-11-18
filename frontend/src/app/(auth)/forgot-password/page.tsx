"use client";
import Link from "next/link";
import { useState } from "react";
import { Button, ErrorNote, Field, Input } from "@/components/ui";
import { errorMessage, post } from "@/lib/api";

export default function ForgotPage() {
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [res, setRes] = useState<null | { dev_reset_link: string | null }>(null);
  return (
    <>
      <h1 className="text-3xl font-semibold tracking-[-0.015em]">Reset your password</h1>
      {res ? (
        <div role="status" className="mt-6 space-y-3 text-sm text-ink-2">
          <p>If an account exists for {email}, a reset link valid for one hour has been created.</p>
          <p className="text-muted">Email delivery isn’t configured in this installation, so the link is not emailed. The server administrator can find it in the backend log.</p>
          {res.dev_reset_link && (
            <p className="rounded-md border border-brass/40 bg-brass-wash p-3">Development mode: <Link className="break-all text-forest underline" href={res.dev_reset_link.replace(/^https?:\/\/[^/]+/, "")}>open the reset link</Link></p>
          )}
        </div>
      ) : (
        <form className="mt-8 space-y-4" onSubmit={async (e) => {
          e.preventDefault();
          if (!/^\S+@\S+\.\S+$/.test(email)) return setErr("Enter a valid email address");
          setBusy(true); setErr("");
          try { setRes(await post("/auth/forgot-password", { email })); } catch (x) { setErr(errorMessage(x)); } finally { setBusy(false); }
        }}>
          <p className="text-sm text-muted">Enter your account email and we’ll create a reset link.</p>
          {err && <ErrorNote>{err}</ErrorNote>}
          <Field label="Email" htmlFor="email"><Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" /></Field>
          <Button type="submit" variant="primary" className="w-full" loading={busy}>Create reset link</Button>
        </form>
      )}
      <p className="mt-6 text-sm"><Link href="/login" className="text-forest hover:underline">Back to sign in</Link></p>
    </>
  );
}
