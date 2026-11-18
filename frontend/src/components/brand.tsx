import Link from "next/link";

/** ClearMetric mark: a measured bar meeting a check line — a figure that has been verified. */
export function Mark({ className = "size-6" }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <rect x="1" y="1" width="22" height="22" rx="5" fill="#14201a" />
      <rect x="5" y="12" width="3" height="7" rx="1" fill="#8fc2ab" />
      <rect x="10.5" y="8" width="3" height="11" rx="1" fill="#8fc2ab" />
      <path d="M15.5 9.5l2 2 3.5-4.5" fill="none" stroke="#fbfbf8" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function Logo({ href = "/", tone = "ink" }: { href?: string; tone?: "ink" | "light" }) {
  return (
    <Link href={href} className={`inline-flex items-center gap-2 font-semibold tracking-[-0.01em] ${tone === "light" ? "text-white" : "text-ink"}`}>
      <Mark />
      <span className="text-[17px]">ClearMetric</span>
    </Link>
  );
}
