"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";
import { Button, ErrorNote, Field, Input, Select, Textarea } from "@/components/ui";
import { errorMessage, post } from "@/lib/api";

const schema = z.object({
  name: z.string().min(1, "Enter your name").max(200),
  email: z.string().email("Enter a valid email address"),
  company: z.string().max(200).optional(),
  topic: z.enum(["sales", "support", "partnership", "privacy", "other"]),
  message: z.string().min(10, "Write at least 10 characters").max(5000),
  website: z.string().max(0).optional(),
});
type F = z.infer<typeof schema>;

export default function ContactPage() {
  const [done, setDone] = useState<null | { delivered: boolean }>(null);
  const [err, setErr] = useState("");
  const { register, handleSubmit, formState: { errors, isSubmitting } } = useForm<F>({ resolver: zodResolver(schema), defaultValues: { topic: "sales" } });
  const submit = async (v: F) => {
    setErr("");
    try {
      const r = await post<{ stored: boolean; delivered: boolean }>("/contact", v);
      setDone({ delivered: r.delivered });
    } catch (e) {
      setErr(errorMessage(e));
    }
  };
  return (
    <div className="mx-auto grid max-w-5xl gap-12 px-5 py-14 md:grid-cols-[1fr_1.3fr]">
      <div>
        <h1 className="text-4xl font-semibold tracking-[-0.02em]">Contact</h1>
        <p className="mt-3 text-ink-2">Questions about ClearMetric, data privacy or a deployment for your team.</p>
        <p className="mt-6 text-sm text-muted">Messages are stored for the ClearMetric team to review. Email delivery isn’t configured in this release, so you won’t receive an automatic confirmation email.</p>
      </div>
      {done ? (
        <div role="status" className="rounded-lg border border-forest/30 bg-surface p-6">
          <h2 className="text-lg font-semibold">Message received</h2>
          <p className="mt-2 text-sm text-ink-2">Your message has been saved. {done.delivered ? "" : "It was not emailed, because no email provider is configured; the team reads stored messages directly."}</p>
        </div>
      ) : (
        <form onSubmit={handleSubmit(submit)} className="space-y-4 rounded-lg border border-line bg-surface p-6" noValidate>
          {err && <ErrorNote>{err}</ErrorNote>}
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Name" htmlFor="name" error={errors.name?.message}><Input id="name" autoComplete="name" {...register("name")} /></Field>
            <Field label="Work email" htmlFor="email" error={errors.email?.message}><Input id="email" type="email" autoComplete="email" {...register("email")} /></Field>
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Company (optional)" htmlFor="company"><Input id="company" autoComplete="organization" {...register("company")} /></Field>
            <Field label="Topic" htmlFor="topic">
              <Select id="topic" {...register("topic")}>
                <option value="sales">Pricing and plans</option><option value="support">Product support</option>
                <option value="partnership">Partnership</option><option value="privacy">Privacy and data</option><option value="other">Something else</option>
              </Select>
            </Field>
          </div>
          <Field label="Message" htmlFor="message" error={errors.message?.message}><Textarea id="message" rows={6} {...register("message")} /></Field>
          <input type="text" tabIndex={-1} autoComplete="off" className="hidden" aria-hidden {...register("website")} />
          <Button type="submit" variant="primary" loading={isSubmitting}>Send message</Button>
        </form>
      )}
    </div>
  );
}
