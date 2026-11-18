"use client";
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { Loader2, X } from "lucide-react";
import Link from "next/link";
import {
  ButtonHTMLAttributes, createContext, forwardRef, InputHTMLAttributes, ReactNode, SelectHTMLAttributes,
  TextareaHTMLAttributes, useCallback, useContext, useEffect, useId, useRef, useState,
} from "react";

/** Class names with Tailwind conflict resolution (later utilities win, e.g. w-auto over w-full). */
export const cx = (...v: ClassValue[]) => twMerge(clsx(v));

type BtnVariant = "primary" | "secondary" | "ghost" | "danger" | "quiet";
const btn: Record<BtnVariant, string> = {
  primary: "bg-forest text-white hover:bg-forest-2 border border-forest",
  secondary: "bg-surface text-ink border border-line-2 hover:border-ink-2",
  ghost: "text-ink-2 hover:bg-paper-2 border border-transparent",
  danger: "bg-surface text-rust border border-line-2 hover:border-rust hover:bg-rust-wash",
  quiet: "text-forest hover:underline underline-offset-4 border border-transparent px-0",
};

export const Button = forwardRef<HTMLButtonElement, ButtonHTMLAttributes<HTMLButtonElement> & { variant?: BtnVariant; size?: "sm" | "md"; loading?: boolean }>(
  function Button({ variant = "secondary", size = "md", loading, className, children, disabled, ...rest }, ref) {
    return (
      <button ref={ref} disabled={disabled || loading}
        className={cx("inline-flex items-center justify-center gap-1.5 rounded-md font-medium transition-colors disabled:opacity-50 disabled:cursor-not-allowed whitespace-nowrap",
          size === "sm" ? "h-8 px-2.5 text-[13px]" : "h-9.5 px-3.5 text-sm", btn[variant], className)} {...rest}>
        {loading && <Loader2 className="size-3.5 animate-spin" aria-hidden />}
        {children}
      </button>
    );
  });

export function ButtonLink({ href, variant = "secondary", className, children }: { href: string; variant?: BtnVariant; className?: string; children: ReactNode }) {
  return (
    <Link href={href} className={cx("inline-flex items-center justify-center gap-1.5 rounded-md font-medium h-9.5 px-3.5 text-sm transition-colors", btn[variant], className)}>
      {children}
    </Link>
  );
}

const fieldBase = "w-full rounded-md border border-line-2 bg-surface px-3 text-sm text-ink placeholder:text-muted focus:border-forest focus:outline-none focus:ring-2 focus:ring-forest/20 disabled:opacity-60";

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} className={cx(fieldBase, "h-9.5", className)} {...p} />;
});
export const Textarea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...p }, ref) {
  return <textarea ref={ref} className={cx(fieldBase, "py-2 min-h-20", className)} {...p} />;
});
export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, children, ...p }, ref) {
  return <select ref={ref} className={cx(fieldBase, "h-9.5 pr-8", className)} {...p}>{children}</select>;
});

export function Field({ label, error, hint, children, htmlFor }: { label: string; error?: string; hint?: string; children: ReactNode; htmlFor?: string }) {
  return (
    <div className="space-y-1.5">
      <label htmlFor={htmlFor} className="block text-[13px] font-medium text-ink-2">{label}</label>
      {children}
      {error ? <p role="alert" className="text-xs text-rust">{error}</p> : hint ? <p className="text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

export function Badge({ tone = "neutral", children, className }: { tone?: "neutral" | "forest" | "rust" | "brass" | "slate"; children: ReactNode; className?: string }) {
  const t = { neutral: "bg-paper-2 text-ink-2", forest: "bg-forest-wash text-forest-2", rust: "bg-rust-wash text-rust", brass: "bg-brass-wash text-brass", slate: "bg-[#e1e9f3] text-slate" }[tone];
  return <span className={cx("inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[11.5px] font-medium leading-none", t, className)}>{children}</span>;
}

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <span role="status" className="inline-flex items-center gap-2 text-sm text-muted"><Loader2 className="size-4 animate-spin" aria-hidden />{label}</span>;
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cx("skeleton", className)} aria-hidden />;
}

export function Empty({ icon, title, children, action }: { icon?: ReactNode; title: string; children?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-start gap-3 rounded-lg border border-dashed border-line-2 bg-surface/60 p-8">
      {icon && <div className="text-forest">{icon}</div>}
      <div>
        <h3 className="text-base font-semibold">{title}</h3>
        {children && <div className="mt-1 max-w-prose text-sm text-muted">{children}</div>}
      </div>
      {action}
    </div>
  );
}

export function ErrorNote({ children }: { children: ReactNode }) {
  return <div role="alert" className="rounded-md border border-rust/30 bg-rust-wash px-3 py-2 text-sm text-rust">{children}</div>;
}

export function Panel({ className, children, title, actions, as: As = "section" }: { className?: string; children: ReactNode; title?: ReactNode; actions?: ReactNode; as?: "section" | "div" }) {
  return (
    <As className={cx("rounded-lg border border-line bg-surface", className)}>
      {(title || actions) && (
        <header className="flex items-center justify-between gap-3 border-b border-line px-4 py-3">
          {typeof title === "string" ? <h2 className="text-sm font-semibold">{title}</h2> : title}
          {actions && <div className="flex items-center gap-2">{actions}</div>}
        </header>
      )}
      {children}
    </As>
  );
}

export function Tabs<T extends string>({ value, onChange, items, className }: { value: T; onChange: (v: T) => void; items: { value: T; label: string; count?: number }[]; className?: string }) {
  return (
    <div role="tablist" className={cx("flex gap-1 border-b border-line overflow-x-auto", className)}>
      {items.map((it) => (
        <button key={it.value} role="tab" aria-selected={value === it.value} onClick={() => onChange(it.value)}
          className={cx("relative -mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm transition-colors",
            value === it.value ? "border-forest font-medium text-ink" : "border-transparent text-muted hover:text-ink")}>
          {it.label}{it.count !== undefined && <span className="ml-1.5 text-xs text-muted tnum">{it.count}</span>}
        </button>
      ))}
    </div>
  );
}

export function Dialog({ open, onClose, title, children, footer, wide }: { open: boolean; onClose: () => void; title: string; children: ReactNode; footer?: ReactNode; wide?: boolean }) {
  const ref = useRef<HTMLDialogElement>(null);
  const id = useId();
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} aria-labelledby={id} onClose={onClose} onCancel={onClose}
      className={cx("m-auto w-[calc(100%-2rem)] rounded-lg border border-line bg-surface p-0 text-ink shadow-lift", wide ? "max-w-3xl" : "max-w-lg")}>
      {open && (
        <div className="flex max-h-[85vh] flex-col">
          <header className="flex items-center justify-between border-b border-line px-5 py-3.5">
            <h2 id={id} className="text-base font-semibold">{title}</h2>
            <button onClick={onClose} aria-label="Close" className="rounded p-1 text-muted hover:bg-paper-2 hover:text-ink"><X className="size-4" /></button>
          </header>
          <div className="overflow-y-auto px-5 py-4">{children}</div>
          {footer && <footer className="flex justify-end gap-2 border-t border-line px-5 py-3">{footer}</footer>}
        </div>
      )}
    </dialog>
  );
}

export function Confirm({ open, onClose, onConfirm, title, children, confirmLabel, danger, loading }: {
  open: boolean; onClose: () => void; onConfirm: () => void; title: string; children: ReactNode; confirmLabel: string; danger?: boolean; loading?: boolean;
}) {
  return (
    <Dialog open={open} onClose={onClose} title={title}
      footer={<><Button variant="ghost" onClick={onClose}>Cancel</Button><Button variant={danger ? "danger" : "primary"} loading={loading} onClick={onConfirm}>{confirmLabel}</Button></>}>
      <div className="text-sm text-ink-2">{children}</div>
    </Dialog>
  );
}

/* ---------------------------------------------------------------- toasts (live region) */
type Toast = { id: number; tone: "ok" | "error"; text: string };
const ToastCtx = createContext<(text: string, tone?: "ok" | "error") => void>(() => {});
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((text: string, tone: "ok" | "error" = "ok") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, tone, text }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), 4200);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
        {items.map((t) => (
          <div key={t.id} role={t.tone === "error" ? "alert" : "status"}
            className={cx("pointer-events-auto rounded-md border px-3.5 py-2.5 text-sm shadow-lift", t.tone === "error" ? "border-rust/40 bg-rust-wash text-rust" : "border-forest/30 bg-surface text-ink")}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  );
}
export const useToast = () => useContext(ToastCtx);

export function Tip({ text, children }: { text: string; children: ReactNode }) {
  return (
    <span className="group relative inline-flex">
      {children}
      <span role="tooltip" className="pointer-events-none absolute bottom-full left-1/2 z-40 mb-1.5 hidden w-max max-w-64 -translate-x-1/2 rounded-md bg-ink px-2 py-1 text-xs text-white group-hover:block group-focus-within:block">
        {text}
      </span>
    </span>
  );
}

export function PageHeader({ title, description, actions, crumbs }: { title: string; description?: ReactNode; actions?: ReactNode; crumbs?: { href?: string; label: string }[] }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        {crumbs && (
          <nav aria-label="Breadcrumb" className="mb-1.5 flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
            {crumbs.map((c, i) => (
              <span key={i} className="flex items-center gap-1.5">
                {i > 0 && <span aria-hidden>/</span>}
                {c.href ? <Link href={c.href} className="hover:text-ink">{c.label}</Link> : <span aria-current="page">{c.label}</span>}
              </span>
            ))}
          </nav>
        )}
        <h1 className="text-[26px] font-semibold leading-tight tracking-[-0.01em]">{title}</h1>
        {description && <p className="mt-1 max-w-2xl text-sm text-muted">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}
