"use client";
import { Menu, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Logo } from "@/components/brand";
import { ButtonLink, cx } from "@/components/ui";

const LINKS = [["Product", "/product"], ["Features", "/features"], ["Solutions", "/solutions"], ["How it works", "/how-it-works"], ["Trust", "/trust"], ["Contact", "/contact"]];

export function SiteNav() {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => setOpen(false), [path]);
  useEffect(() => {
    fetch("/api/auth/me", { credentials: "same-origin" }).then((r) => setSignedIn(r.ok)).catch(() => {});
  }, []);
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-paper/90 backdrop-blur">
      <div className="mx-auto flex h-15 max-w-6xl items-center justify-between gap-6 px-5">
        <Logo />
        <nav aria-label="Main" className="hidden items-center gap-1 lg:flex">
          {LINKS.map(([l, h]) => (
            <Link key={h} href={h} aria-current={path === h ? "page" : undefined}
              className={cx("rounded-md px-3 py-1.5 text-sm", path === h ? "text-ink font-medium" : "text-ink-2 hover:text-ink")}>{l}</Link>
          ))}
        </nav>
        <div className="hidden items-center gap-2 lg:flex">
          {signedIn ? <ButtonLink href="/app/overview" variant="primary">Open workspace</ButtonLink> : (
            <><ButtonLink href="/login" variant="ghost">Sign in</ButtonLink><ButtonLink href="/signup" variant="primary">Start free</ButtonLink></>
          )}
        </div>
        <button className="rounded-md p-2 lg:hidden" aria-expanded={open} aria-controls="mobile-nav" aria-label="Menu" onClick={() => setOpen(!open)}>
          {open ? <X className="size-5" /> : <Menu className="size-5" />}
        </button>
      </div>
      {open && (
        <nav id="mobile-nav" aria-label="Mobile" className="border-t border-line bg-paper px-5 py-3 lg:hidden">
          {LINKS.map(([l, h]) => <Link key={h} href={h} className="block rounded px-2 py-2 text-ink-2 hover:bg-paper-2">{l}</Link>)}
          <div className="mt-2 flex gap-2 border-t border-line pt-3">
            {signedIn ? <ButtonLink href="/app/overview" variant="primary">Open workspace</ButtonLink> : (
              <><ButtonLink href="/login">Sign in</ButtonLink><ButtonLink href="/signup" variant="primary">Start free</ButtonLink></>
            )}
          </div>
        </nav>
      )}
    </header>
  );
}
