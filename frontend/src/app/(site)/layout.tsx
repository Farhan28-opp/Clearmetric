import Link from "next/link";
import { Logo } from "@/components/brand";
import { SiteNav } from "./site-nav";

const FOOT = [
  { title: "Product", links: [["Product tour", "/product"], ["Features", "/features"], ["How it works", "/how-it-works"]] },
  { title: "Use cases", links: [["Retail", "/solutions#retail"], ["E-commerce", "/solutions#ecommerce"], ["Sales operations", "/solutions#sales-ops"]] },
  { title: "Company", links: [["Trust and privacy", "/trust"], ["Contact", "/contact"], ["Sign in", "/login"]] },
];

export default function SiteLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">Skip to content</a>
      <SiteNav />
      <main id="main" className="flex-1">{children}</main>
      <footer className="border-t border-line bg-paper-2/60">
        <div className="mx-auto grid max-w-6xl gap-10 px-5 py-12 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
          <div className="max-w-xs space-y-3">
            <Logo />
            <p className="text-sm text-muted">Your AI business analyst. Answers from your own data, each with the calculation behind it.</p>
          </div>
          {FOOT.map((col) => (
            <div key={col.title}>
              <h2 className="text-sm font-semibold">{col.title}</h2>
              <ul className="mt-3 space-y-2 text-sm text-muted">
                {col.links.map(([label, href]) => <li key={href}><Link className="hover:text-ink" href={href}>{label}</Link></li>)}
              </ul>
            </div>
          ))}
        </div>
        <div className="mx-auto max-w-6xl px-5 pb-8 text-xs text-muted">© {new Date().getFullYear()} ClearMetric. Built for small businesses that want to understand their numbers.</div>
      </footer>
    </div>
  );
}
