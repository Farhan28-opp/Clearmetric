import Link from "next/link";
import { Mark } from "@/components/brand";

export default function NotFound() {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 px-6 text-center">
      <Mark className="size-10" />
      <h1 className="text-2xl font-semibold">This page doesn’t exist</h1>
      <p className="max-w-sm text-muted">The link may be out of date, or the item may have been deleted.</p>
      <div className="flex gap-3"><Link href="/" className="text-forest underline underline-offset-4">ClearMetric home</Link><Link href="/app" className="text-forest underline underline-offset-4">Your workspace</Link></div>
    </main>
  );
}
