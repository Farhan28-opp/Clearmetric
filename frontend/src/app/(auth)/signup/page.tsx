"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button, ErrorNote, Field, Input } from "@/components/ui";
import { errorMessage, post } from "@/lib/api";

const schema = z.object({
  full_name: z.string().min(1, "Enter your name").max(200),
  email: z.string().email("Enter a valid email address"),
  password: z.string().min(10, "Use at least 10 characters").regex(/[A-Za-z]/, "Include a letter").regex(/\d/, "Include a number"),
});

export default function SignupPage() {
  const router = useRouter();
  const [err, setErr] = useState("");
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<z.infer<typeof schema>>({ resolver: zodResolver(schema) });
  return (
    <>
      <h1 className="text-3xl font-semibold tracking-[-0.015em]">Create your account</h1>
      <p className="mt-2 text-sm text-muted">Next, you’ll set up a workspace for your business and choose some data.</p>
      <form className="mt-8 space-y-4" noValidate onSubmit={handleSubmit(async (v) => {
        setErr("");
        try {
          await post("/auth/signup", v);
          router.push("/app/onboarding");
        } catch (e) {
          setErr(errorMessage(e));
        }
      })}>
        {err && <ErrorNote>{err}</ErrorNote>}
        <Field label="Full name" htmlFor="full_name" error={errors.full_name?.message}><Input id="full_name" autoComplete="name" autoFocus {...register("full_name")} /></Field>
        <Field label="Work email" htmlFor="email" error={errors.email?.message}><Input id="email" type="email" autoComplete="email" {...register("email")} /></Field>
        <Field label="Password" htmlFor="password" error={errors.password?.message} hint="At least 10 characters with letters and numbers.">
          <Input id="password" type="password" autoComplete="new-password" {...register("password")} />
        </Field>
        <Button type="submit" variant="primary" className="w-full" loading={isSubmitting}>Create account</Button>
      </form>
      <p className="mt-6 text-sm text-muted">Already have an account? <Link href="/login" className="text-forest hover:underline">Sign in</Link></p>
    </>
  );
}
