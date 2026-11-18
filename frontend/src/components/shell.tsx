"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity, Bell, BookMarked, ChevronsLeft, ChevronsRight, ChevronDown, Database, FileText, LayoutGrid, Lightbulb, LogOut, Menu,
  MessageSquareText, Plus, ScanSearch, Search, Settings, X,
} from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { ReactNode, useEffect, useRef, useState } from "react";
import { Mark } from "@/components/brand";
import { cx } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { get, post } from "@/lib/api";
import { timeAgo } from "@/lib/format";

const NAV = [
  { href: "/app/overview", label: "Overview", icon: LayoutGrid },
  { href: "/app/data", label: "Data Hub", icon: Database },
  { href: "/app/metrics", label: "Metric Library", icon: BookMarked },
  { href: "/app/analyst", label: "AI Analyst", icon: MessageSquareText },
  { href: "/app/explore", label: "Explore", icon: ScanSearch },
  { href: "/app/insights", label: "Insights", icon: Lightbulb },
  { href: "/app/reports", label: "Reports", icon: FileText },
  { href: "/app/activity", label: "Activity", icon: Activity },
  { href: "/app/settings", label: "Settings", icon: Settings },
];

function useOutside(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const on = (e: MouseEvent) => ref.current && !ref.current.contains(e.target as Node) && close();
    const key = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", on);
    document.addEventListener("keydown", key);
    return () => { document.removeEventListener("mousedown", on); document.removeEventListener("keydown", key); };
  }, [open, close]);
  return ref;
}

function Sidebar({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const path = usePathname();
  return (
    <nav aria-label="Workspace" className="flex-1 space-y-0.5 px-2 py-3">
      {NAV.map(({ href, label, icon: I }) => {
        const active = path === href || path.startsWith(href + "/");
        return (
          <Link key={href} href={href} onClick={onNavigate} aria-current={active ? "page" : undefined} title={collapsed ? label : undefined}
            className={cx("relative flex items-center gap-3 rounded-md px-2.5 py-2 text-[14px] transition-colors",
              active ? "bg-surface font-medium text-ink shadow-[0_1px_0_rgb(20_32_26/0.05)]" : "text-ink-2 hover:bg-paper-2 hover:text-ink",
              collapsed && "justify-center px-0")}>
            {active && <span aria-hidden className="absolute -left-2 top-1.5 bottom-1.5 w-[3px] rounded-r bg-forest" />}
            <I className={cx("size-[18px] shrink-0", active ? "text-forest" : "text-muted")} aria-hidden />
            {!collapsed && label}
          </Link>
        );
      })}
    </nav>
  );
}

function WorkspaceSwitcher({ collapsed }: { collapsed: boolean }) {
  const { me, ws, switchTo } = useWorkspace();
  const [open, setOpen] = useState(false);
  const ref = useOutside(open, () => setOpen(false));
  if (!ws) return null;
  return (
    <div ref={ref} className="relative px-2">
      <button onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="menu"
        className={cx("flex w-full items-center gap-2 rounded-md border border-line bg-surface px-2.5 py-2 text-left text-sm hover:border-line-2", collapsed && "justify-center px-0")}>
        <span className="flex size-6 shrink-0 items-center justify-center rounded bg-forest text-xs font-semibold text-white">{ws.name.slice(0, 1).toUpperCase()}</span>
        {!collapsed && <><span className="min-w-0 flex-1"><span className="block truncate font-medium">{ws.name}</span><span className="block text-xs capitalize text-muted">{ws.role} · {ws.currency}</span></span><ChevronDown className="size-4 text-muted" /></>}
      </button>
      {open && (
        <div role="menu" className="absolute left-2 top-full z-40 mt-1 w-64 rounded-md border border-line bg-surface p-1 shadow-lift">
          {me.workspaces.map((w) => (
            <button key={w.id} role="menuitem" onClick={() => { setOpen(false); switchTo(w.id); }}
              className={cx("flex w-full items-center justify-between rounded px-2.5 py-2 text-left text-sm hover:bg-paper", w.id === ws.id && "font-medium")}>
              <span className="truncate">{w.name}</span><span className="text-xs capitalize text-muted">{w.role}</span>
            </button>
          ))}
          <Link role="menuitem" href="/app/onboarding?new=1" onClick={() => setOpen(false)} className="mt-1 flex items-center gap-2 border-t border-line px-2.5 py-2 text-sm text-forest hover:bg-paper">
            <Plus className="size-4" /> New workspace
          </Link>
        </div>
      )}
    </div>
  );
}

function GlobalSearch() {
  const { base, wid } = useWorkspace();
  const router = useRouter();
  const [q, setQ] = useState("");
  const [deb, setDeb] = useState("");
  const [open, setOpen] = useState(false);
  const ref = useOutside(open, () => setOpen(false));
  useEffect(() => { const t = setTimeout(() => setDeb(q.trim()), 220); return () => clearTimeout(t); }, [q]);
  const res = useQuery({ queryKey: [wid, "search", deb], queryFn: () => get<{ results: { type: string; id: string; title: string; subtitle: string; href: string }[] }>(`${base}/search?q=${encodeURIComponent(deb)}`), enabled: deb.length >= 2 });
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); document.getElementById("global-search")?.focus(); } };
    window.addEventListener("keydown", k);
    return () => window.removeEventListener("keydown", k);
  }, []);
  return (
    <div ref={ref} className="relative w-full max-w-md">
      <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted" aria-hidden />
      <input id="global-search" type="search" value={q} onChange={(e) => { setQ(e.target.value); setOpen(true); }} onFocus={() => setOpen(true)}
        placeholder="Search datasets, metrics, investigations, reports" aria-label="Search workspace" role="combobox" aria-expanded={open && deb.length >= 2} aria-controls="search-results"
        className="h-9 w-full rounded-md border border-line bg-surface pl-8 pr-12 text-sm placeholder:text-muted focus:border-forest focus:outline-none" />
      <kbd className="pointer-events-none absolute right-2 top-1/2 hidden -translate-y-1/2 rounded border border-line px-1 text-[11px] text-muted sm:block">⌘K</kbd>
      {open && deb.length >= 2 && (
        <div id="search-results" role="listbox" className="absolute left-0 right-0 top-full z-40 mt-1 max-h-96 overflow-y-auto rounded-md border border-line bg-surface p-1 shadow-lift">
          {res.isLoading && <p className="px-3 py-2 text-sm text-muted">Searching…</p>}
          {res.data?.results.length === 0 && <p className="px-3 py-2 text-sm text-muted">Nothing matches “{deb}”.</p>}
          {res.data?.results.map((r) => (
            <button key={r.type + r.id} role="option" aria-selected={false} onClick={() => { setOpen(false); setQ(""); router.push(r.href); }}
              className="flex w-full items-baseline justify-between gap-3 rounded px-3 py-2 text-left hover:bg-paper">
              <span className="min-w-0"><span className="block truncate text-sm">{r.title}</span><span className="block truncate text-xs text-muted">{r.subtitle}</span></span>
              <span className="text-xs capitalize text-muted">{r.type}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Notifications() {
  const { base, wid } = useWorkspace();
  const qc = useQueryClient();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const ref = useOutside(open, () => setOpen(false));
  const q = useQuery({ queryKey: [wid, "notifications"], queryFn: () => get<{ items: { id: string; kind: string; summary: string; created_at: string | null; unread: boolean; resource_type: string; resource_id: string }[]; unread: number }>(`${base}/notifications`), refetchInterval: 60_000 });
  const hrefFor = (t: string, id: string) => ({ dataset: `/app/data/${id}`, report: `/app/reports/${id}`, conversation: `/app/analyst?c=${id}`, metric: `/app/metrics?metric=${id}`, insight: "/app/insights" } as Record<string, string>)[t] ?? "/app/activity";
  return (
    <div ref={ref} className="relative">
      <button aria-label={`Notifications${q.data?.unread ? `, ${q.data.unread} unread` : ""}`} aria-expanded={open} onClick={async () => {
        setOpen(!open);
        if (!open && q.data?.unread) { await post(`${base}/notifications/read`); qc.invalidateQueries({ queryKey: [wid, "notifications"] }); }
      }} className="relative rounded-md p-2 text-ink-2 hover:bg-paper-2">
        <Bell className="size-[18px]" />
        {!!q.data?.unread && <span className="absolute right-1 top-1 flex min-w-4 items-center justify-center rounded-full bg-rust px-1 text-[10px] font-semibold leading-4 text-white">{q.data.unread}</span>}
      </button>
      {open && (
        <div className="absolute right-0 top-full z-40 mt-1 w-80 rounded-md border border-line bg-surface shadow-lift">
          <p className="border-b border-line px-3 py-2 text-sm font-medium">Notifications</p>
          <ul className="max-h-96 overflow-y-auto">
            {!q.data?.items.length && <li className="px-3 py-4 text-sm text-muted">No activity from teammates yet. New high-importance insights also appear here.</li>}
            {q.data?.items.map((n) => (
              <li key={n.id}>
                <button onClick={() => { setOpen(false); router.push(hrefFor(n.resource_type, n.resource_id)); }} className="w-full px-3 py-2.5 text-left hover:bg-paper">
                  <span className={cx("block text-sm", n.unread && "font-medium")}>{n.summary}</span>
                  {n.created_at && <span className="text-xs text-muted">{timeAgo(n.created_at)}</span>}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function UserMenu() {
  const { me } = useWorkspace();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const ref = useOutside(open, () => setOpen(false));
  const initials = me.user.full_name.split(" ").map((x) => x[0]).slice(0, 2).join("").toUpperCase();
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)} aria-expanded={open} aria-haspopup="menu" aria-label="Account menu"
        className="flex size-8 items-center justify-center rounded-full bg-ink text-xs font-semibold text-white">{initials}</button>
      {open && (
        <div role="menu" className="absolute right-0 top-full z-40 mt-1 w-60 rounded-md border border-line bg-surface p-1 shadow-lift">
          <div className="px-3 py-2"><p className="truncate text-sm font-medium">{me.user.full_name}</p><p className="truncate text-xs text-muted">{me.user.email}</p></div>
          <Link role="menuitem" href="/app/settings?tab=profile" onClick={() => setOpen(false)} className="block rounded px-3 py-2 text-sm hover:bg-paper">Profile and preferences</Link>
          <Link role="menuitem" href="/app/settings?tab=security" onClick={() => setOpen(false)} className="block rounded px-3 py-2 text-sm hover:bg-paper">Security</Link>
          <Link role="menuitem" href="/" className="block rounded px-3 py-2 text-sm hover:bg-paper">ClearMetric website</Link>
          <button role="menuitem" onClick={async () => { await post("/auth/logout"); router.replace("/login"); }}
            className="flex w-full items-center gap-2 rounded border-t border-line px-3 py-2 text-left text-sm hover:bg-paper"><LogOut className="size-4" /> Sign out</button>
        </div>
      )}
    </div>
  );
}

export function Shell({ children }: { children: ReactNode }) {
  const { ws } = useWorkspace();
  const path = usePathname();
  const router = useRouter();
  useEffect(() => { if (!ws) router.replace("/app/onboarding"); }, [ws, router]);
  const [collapsed, setCollapsed] = useState(false);
  const [mobile, setMobile] = useState(false);
  useEffect(() => { try { setCollapsed(localStorage.getItem("cm_sidebar") === "1"); } catch { /* ignore */ } }, []);
  useEffect(() => setMobile(false), [path]);
  const toggle = () => { setCollapsed((c) => { try { localStorage.setItem("cm_sidebar", c ? "0" : "1"); } catch { /* ignore */ } return !c; }); };
  return (
    <div className="flex min-h-dvh">
      <a href="#app-main" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">Skip to content</a>
      <aside className={cx("sticky top-0 hidden h-dvh print:hidden shrink-0 flex-col border-r border-line bg-paper lg:flex", collapsed ? "w-16" : "w-60")}>
        <div className={cx("flex h-14 items-center px-4", collapsed && "justify-center px-0")}>
          <Link href="/app/overview" className="flex items-center gap-2 font-semibold"><Mark />{!collapsed && "ClearMetric"}</Link>
        </div>
        <WorkspaceSwitcher collapsed={collapsed} />
        <Sidebar collapsed={collapsed} />
        <div className="border-t border-line p-2">
          {!collapsed && ws && <p className="px-2 pb-2 text-xs text-muted">Analyst mode: {ws.ai.active_mode === "anthropic" ? `Claude (${ws.ai.model})` : "local, deterministic"}</p>}
          <button onClick={toggle} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} className="flex w-full items-center justify-center gap-2 rounded-md py-1.5 text-sm text-muted hover:bg-paper-2">
            {collapsed ? <ChevronsRight className="size-4" /> : <><ChevronsLeft className="size-4" /> Collapse</>}
          </button>
        </div>
      </aside>
      {mobile && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal aria-label="Navigation">
          <div className="absolute inset-0 bg-ink/30" onClick={() => setMobile(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 flex-col bg-paper">
            <div className="flex h-14 items-center justify-between px-4">
              <span className="flex items-center gap-2 font-semibold"><Mark />ClearMetric</span>
              <button onClick={() => setMobile(false)} aria-label="Close navigation" className="p-1"><X className="size-5" /></button>
            </div>
            <WorkspaceSwitcher collapsed={false} />
            <Sidebar collapsed={false} onNavigate={() => setMobile(false)} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b print:hidden border-line bg-paper/95 px-4 backdrop-blur lg:px-6">
          <button className="rounded-md p-2 lg:hidden" onClick={() => setMobile(true)} aria-label="Open navigation"><Menu className="size-5" /></button>
          <nav aria-label="Location" className="hidden shrink-0 items-center gap-1.5 text-[13px] text-muted xl:flex">
            <span className="max-w-40 truncate">{ws?.name}</span><span aria-hidden>/</span>
            <span className="text-ink">{NAV.find((n) => path === n.href || path.startsWith(n.href + "/"))?.label ?? ""}</span>
          </nav>
          <GlobalSearch />
          <div className="ml-auto flex items-center gap-1.5">
            <Link href="/app/analyst?new=1" className="hidden items-center gap-1.5 rounded-md border border-line-2 bg-surface px-2.5 py-1.5 text-sm hover:border-ink-2 sm:flex">
              <MessageSquareText className="size-4 text-forest" /> Ask a question
            </Link>
            <Notifications />
            <UserMenu />
          </div>
        </header>
        <main id="app-main" className="min-w-0 flex-1 px-4 py-6 lg:px-8">{ws ? children : null}</main>
      </div>
    </div>
  );
}
