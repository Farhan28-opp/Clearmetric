"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button, ErrorNote, Field, Input } from "@/components/ui";
import { errorMessage, post } from "@/lib/api";

const schema = z.object({ email: z.string().email("Enter a valid email address"), password: z.string().min(1, "Enter your password") });

export default function LoginPage() {
  const router = useRouter();
  const [err, setErr] = useState("");
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });
  return (
    <>
      <h1 className="text-3xl font-semibold tracking-[-0.015em]">Sign in</h1>
      <p className="mt-2 text-sm text-muted">Welcome back. Pick up where you left off.</p>
      <form className="mt-8 space-y-4" noValidate onSubmit={handleSubmit(async (v) => {
        setErr("");
        try {
          await post("/auth/login", v);
          router.push("/app");
        } catch (e) {
          setErr(errorMessage(e));
        }
      })}>
        {err && <ErrorNote>{err}</ErrorNote>}
        <Field label="Email" htmlFor="email" error={errors.email?.message}><Input id="email" type="email" autoComplete="email" autoFocus {...register("email")} /></Field>
        <Field label="Password" htmlFor="password" error={errors.password?.message}><Input id="password" type="password" autoComplete="current-password" {...register("password")} /></Field>
        <div className="flex justify-end"><Link href="/forgot-password" className="text-sm text-forest hover:underline">Forgot password?</Link></div>
        <Button type="submit" variant="primary" className="w-full" loading={isSubmitting}>Sign in</Button>
      </form>
      <p className="mt-6 text-sm text-muted">New to ClearMetric? <Link href="/signup" className="text-forest hover:underline">Create an account</Link></p>
    </>
  );
}
