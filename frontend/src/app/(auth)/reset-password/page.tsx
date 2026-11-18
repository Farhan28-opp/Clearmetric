"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Button, ErrorNote, Field, Input } from "@/components/ui";
import { errorMessage, post } from "@/lib/api";

function ResetForm() {
  const token = useSearchParams().get("token") ?? "";
  const [pw, setPw] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [done, setDone] = useState(false);
  if (done) return <div role="status" className="mt-6 text-sm">Your password has been changed and other sessions were signed out. <Link href="/login" className="text-forest underline">Sign in</Link></div>;
  return (
    <form className="mt-8 space-y-4" onSubmit={async (e) => {
      e.preventDefault();
      if (pw.length < 10 || !/\d/.test(pw) || !/[A-Za-z]/.test(pw)) return setErr("Use at least 10 characters with letters and numbers");
      setBusy(true); setErr("");
      try { await post("/auth/reset-password", { token, password: pw }); setDone(true); } catch (x) { setErr(errorMessage(x)); } finally { setBusy(false); }
    }}>
      {!token && <ErrorNote>This page needs the link from your reset request.</ErrorNote>}
      {err && <ErrorNote>{err}</ErrorNote>}
      <Field label="New password" htmlFor="pw"><Input id="pw" type="password" autoComplete="new-password" value={pw} onChange={(e) => setPw(e.target.value)} /></Field>
      <Button type="submit" variant="primary" className="w-full" loading={busy} disabled={!token}>Set new password</Button>
    </form>
  );
}

export default function ResetPage() {
  return (
    <>
      <h1 className="text-3xl font-semibold tracking-[-0.015em]">Choose a new password</h1>
      <Suspense fallback={null}><ResetForm /></Suspense>
    </>
  );
}
