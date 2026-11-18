"use client";
import { useQueryClient } from "@tanstack/react-query";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { Badge, Button, Confirm, ErrorNote, Field, Input, PageHeader, Panel, Select, Skeleton, Tabs, useToast } from "@/components/ui";
import { useWorkspace, useWsQuery } from "@/components/workspace";
import { del, errorMessage, get, patch, post } from "@/lib/api";
import { fmtDate } from "@/lib/format";

type Tab = "profile" | "workspace" | "business" | "members" | "security" | "privacy";
const CURRENCIES = ["USD", "EUR", "GBP", "INR", "JPY", "AUD", "CAD", "SGD", "AED", "ZAR"];
const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"];

function useSave() {
  const toast = useToast();
  const { refresh } = useWorkspace();
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const run = async (fn: () => Promise<unknown>, ok: string) => { setBusy(true); setErr(""); try { await fn(); await refresh(); toast(ok); } catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); } };
  return { busy, err, run };
}

function Profile() {
  const { me } = useWorkspace();
  const p = me.user.preferences as Record<string, unknown>;
  const [name, setName] = useState(me.user.full_name);
  const [prefs, setPrefs] = useState({ number_format: String(p.number_format ?? "compact"), default_chart: String(p.default_chart ?? "auto"), show_sql: Boolean(p.show_sql) });
  const s = useSave();
  return (
    <Panel title="Profile and preferences"><div className="max-w-xl space-y-4 p-5">
      {s.err && <ErrorNote>{s.err}</ErrorNote>}
      <Field label="Full name" htmlFor="pn"><Input id="pn" value={name} onChange={(e) => setName(e.target.value)} /></Field>
      <Field label="Email" htmlFor="pe" hint="Used to sign in and to receive workspace invitations."><Input id="pe" value={me.user.email} disabled /></Field>
      <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={prefs.show_sql} onChange={(e) => setPrefs({ ...prefs, show_sql: e.target.checked })} />Show generated queries in the analysis inspector by default</label>
      <Button variant="primary" loading={s.busy} onClick={() => s.run(() => patch("/auth/me", { full_name: name, preferences: prefs }), "Profile saved")}>Save profile</Button>
    </div></Panel>
  );
}

function WorkspaceTab({ business }: { business?: boolean }) {
  const { ws, base, can } = useWorkspace();
  const [f, setF] = useState({ name: ws!.name, industry: ws!.industry, business_type: ws!.business_type, currency: ws!.currency, timezone: ws!.timezone, fiscal_year_start_month: ws!.fiscal_year_start_month, date_format: ws!.date_format });
  const [ins, setIns] = useState({ change_threshold_pct: ws!.insight_settings?.change_threshold_pct ?? 10, concentration_threshold_pct: ws!.insight_settings?.concentration_threshold_pct ?? 40, outlier_iqr_k: ws!.insight_settings?.outlier_iqr_k ?? 3 });
  const s = useSave();
  const editable = can("admin");
  return (
    <Panel title={business ? "Business, currency and date settings" : "Workspace settings"}><div className="max-w-2xl space-y-4 p-5">
      {!editable && <p className="text-sm text-muted">Only owners and admins can change these settings.</p>}
      {s.err && <ErrorNote>{s.err}</ErrorNote>}
      {!business ? (
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Workspace name" htmlFor="wn"><Input id="wn" disabled={!editable} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} /></Field>
          <Field label="Industry" htmlFor="wi"><Input id="wi" disabled={!editable} value={f.industry} onChange={(e) => setF({ ...f, industry: e.target.value })} /></Field>
          <Field label="Business type" htmlFor="wb"><Input id="wb" disabled={!editable} value={f.business_type} onChange={(e) => setF({ ...f, business_type: e.target.value })} /></Field>
          <div className="text-sm text-muted sm:col-span-2">Created {fmtDate(ws!.created_at)}. Your role: <span className="capitalize">{ws!.role}</span>.</div>
        </div>
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label="Currency" htmlFor="wc" hint="Formats money in answers, insights and reports."><Select id="wc" disabled={!editable} value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })}>{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</Select></Field>
            <Field label="Date format" htmlFor="wd"><Select id="wd" disabled={!editable} value={f.date_format} onChange={(e) => setF({ ...f, date_format: e.target.value })}>{["YYYY-MM-DD", "DD/MM/YYYY", "MM/DD/YYYY", "DD MMM YYYY"].map((d) => <option key={d}>{d}</option>)}</Select></Field>
            <Field label="Time zone" htmlFor="wt"><Input id="wt" disabled={!editable} value={f.timezone} onChange={(e) => setF({ ...f, timezone: e.target.value })} /></Field>
            <Field label="Fiscal year starts in" htmlFor="wf"><Select id="wf" disabled={!editable} value={f.fiscal_year_start_month} onChange={(e) => setF({ ...f, fiscal_year_start_month: Number(e.target.value) })}>{MONTHS.map((m, i) => <option key={m} value={i + 1}>{m}</option>)}</Select></Field>
          </div>
          <div className="border-t border-line pt-4">
            <h3 className="text-sm font-semibold">Insight thresholds</h3>
            <div className="mt-3 grid gap-4 sm:grid-cols-3">
              <Field label="Report changes of at least (%)" htmlFor="t1"><Input id="t1" type="number" min={1} max={100} disabled={!editable} value={ins.change_threshold_pct} onChange={(e) => setIns({ ...ins, change_threshold_pct: Number(e.target.value) })} /></Field>
              <Field label="Concentration risk at (%)" htmlFor="t2"><Input id="t2" type="number" min={10} max={95} disabled={!editable} value={ins.concentration_threshold_pct} onChange={(e) => setIns({ ...ins, concentration_threshold_pct: Number(e.target.value) })} /></Field>
              <Field label="Outlier IQR multiplier" htmlFor="t3"><Input id="t3" type="number" step={0.5} min={1} max={6} disabled={!editable} value={ins.outlier_iqr_k} onChange={(e) => setIns({ ...ins, outlier_iqr_k: Number(e.target.value) })} /></Field>
            </div>
          </div>
        </>
      )}
      {editable && <Button variant="primary" loading={s.busy} onClick={() => s.run(() => patch(base, business ? { currency: f.currency, timezone: f.timezone, fiscal_year_start_month: f.fiscal_year_start_month, date_format: f.date_format, insight_settings: ins } : { name: f.name, industry: f.industry, business_type: f.business_type }), "Settings saved")}>Save settings</Button>}
    </div></Panel>
  );
}

function Members() {
  const { base, wid, can, me, refresh } = useWorkspace();
  const qc = useQueryClient();
  const toast = useToast();
  const m = useWsQuery<{ members: { id: string; user_id: string; name: string; email: string; role: string; joined_at: string }[]; invitations: { id: string; email: string; role: string; created_at: string }[] }>(["members"], "/members");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("analyst");
  const [err, setErr] = useState("");
  const reload = () => qc.invalidateQueries({ queryKey: [wid, "members"] });
  return (
    <div className="space-y-6">
      {me.invitations.length > 0 && (
        <Panel title="Invitations for you"><ul className="divide-y divide-line">{me.invitations.map((i) => (
          <li key={i.id} className="flex items-center gap-3 px-4 py-3 text-sm"><span className="flex-1">Join <strong>{i.workspace_name}</strong> as {i.role}</span>
            <Button size="sm" variant="primary" onClick={async () => { await post(`/invitations/${i.id}/accept`); await refresh(); toast("Joined workspace"); }}>Accept</Button>
            <Button size="sm" variant="ghost" onClick={async () => { await post(`/invitations/${i.id}/decline`); await refresh(); }}>Decline</Button></li>))}</ul></Panel>)}
      <Panel title="Members">
        <table className="w-full text-sm"><caption className="sr-only">Workspace members</caption>
          <thead className="text-left text-ink-2"><tr className="border-b border-line"><th className="px-4 py-2 font-medium">Name</th><th className="px-4 py-2 font-medium">Role</th><th className="px-4 py-2 font-medium">Joined</th><th /></tr></thead>
          <tbody className="divide-y divide-line">{m.data?.members.map((x) => (
            <tr key={x.id}><td className="px-4 py-2.5"><span className="font-medium">{x.name}</span><span className="block text-xs text-muted">{x.email}</span></td>
              <td className="px-4 py-2.5">{x.role === "owner" || !can("admin") ? <Badge>{x.role}</Badge> : (
                <Select aria-label={`Role for ${x.name}`} value={x.role} onChange={async (e) => { try { await patch(`${base}/members/${x.id}`, { role: e.target.value }); reload(); } catch (er) { toast(errorMessage(er), "error"); } }} className="h-8 w-32 text-[13px]">
                  <option value="admin">admin</option><option value="analyst">analyst</option><option value="viewer">viewer</option></Select>)}</td>
              <td className="px-4 py-2.5 text-muted">{fmtDate(x.joined_at)}</td>
              <td className="px-4 py-2.5 text-right">{x.role !== "owner" && (can("admin") || x.user_id === me.user.id) && <Button size="sm" variant="ghost" onClick={async () => { await del(`${base}/members/${x.id}`); reload(); }}>{x.user_id === me.user.id ? "Leave" : "Remove"}</Button>}</td></tr>))}</tbody>
        </table>
      </Panel>
      {can("admin") && (
        <Panel title="Invite someone"><div className="space-y-3 p-4">
          {err && <ErrorNote>{err}</ErrorNote>}
          <div className="flex flex-wrap items-end gap-2">
            <Field label="Email" htmlFor="ie"><Input id="ie" type="email" value={email} onChange={(e) => setEmail(e.target.value)} className="w-72" /></Field>
            <Field label="Role" htmlFor="ir"><Select id="ir" value={role} onChange={(e) => setRole(e.target.value)} className="w-36"><option value="admin">Admin</option><option value="analyst">Analyst</option><option value="viewer">Viewer</option></Select></Field>
            <Button variant="primary" onClick={async () => { setErr(""); try { const r = await post<{ delivery: string }>(`${base}/invitations`, { email, role }); toast(r.delivery); setEmail(""); reload(); } catch (e) { setErr(errorMessage(e)); } }}>Send invitation</Button>
          </div>
          <p className="text-xs text-muted">Email delivery isn’t configured. The person sees the invitation in Settings after signing in with this address, and must accept it. Analysts can upload and analyse; viewers can only read.</p>
          {!!m.data?.invitations.length && <ul className="divide-y divide-line rounded-md border border-line">{m.data.invitations.map((i) => <li key={i.id} className="flex items-center justify-between px-3 py-2 text-sm"><span>{i.email} <Badge>{i.role}</Badge> <span className="text-xs text-muted">pending since {fmtDate(i.created_at)}</span></span><Button size="sm" variant="ghost" onClick={async () => { await del(`${base}/invitations/${i.id}`); reload(); }}>Revoke</Button></li>)}</ul>}
        </div></Panel>)}
    </div>
  );
}

function Security() {
  const router = useRouter();
  const toast = useToast();
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [err, setErr] = useState("");
  const [list, setList] = useState<{ id: string; created_at: string; user_agent: string; current: boolean }[] | null>(null);
  const [delOpen, setDelOpen] = useState(false);
  const [pw, setPw] = useState("");
  const load = async () => setList((await get<{ sessions: { id: string; created_at: string; user_agent: string; current: boolean }[] }>("/auth/sessions")).sessions);
  return (
    <div className="space-y-6">
      <Panel title="Change password"><div className="max-w-md space-y-3 p-5">
        {err && <ErrorNote>{err}</ErrorNote>}
        <Field label="Current password" htmlFor="cp"><Input id="cp" type="password" autoComplete="current-password" value={cur} onChange={(e) => setCur(e.target.value)} /></Field>
        <Field label="New password" htmlFor="np" hint="At least 10 characters with letters and numbers. Other sessions are signed out."><Input id="np" type="password" autoComplete="new-password" value={nw} onChange={(e) => setNw(e.target.value)} /></Field>
        <Button variant="primary" onClick={async () => { setErr(""); try { await post("/auth/password", { current_password: cur, new_password: nw }); toast("Password changed"); setCur(""); setNw(""); } catch (e) { setErr(errorMessage(e)); } }}>Change password</Button>
      </div></Panel>
      <Panel title="Active sessions" actions={<Button size="sm" onClick={load}>Show sessions</Button>}><div className="p-4">
        {list ? <ul className="divide-y divide-line text-sm">{list.map((s) => <li key={s.id} className="py-2"><span className="block truncate">{s.user_agent || "Unknown browser"}</span><span className="text-xs text-muted">Signed in {fmtDate(s.created_at, true)}{s.current && " · this session"}</span></li>)}</ul> : <p className="text-sm text-muted">Sessions last 14 days unless you sign out.</p>}
        <Button size="sm" className="mt-3" onClick={async () => { const r = await post<{ revoked: number }>("/auth/sessions/revoke-others"); toast(`Signed out ${r.revoked} other session(s)`); load(); }}>Sign out other sessions</Button>
      </div></Panel>
      <Panel title="Delete account"><div className="space-y-3 p-5 text-sm">
        <p className="text-ink-2">Deletes your account, every workspace you own (including datasets, stored files, metrics, investigations, insights and reports) and your memberships elsewhere. This cannot be undone.</p>
        <Button variant="danger" onClick={() => setDelOpen(true)}>Delete my account</Button>
      </div></Panel>
      <Confirm open={delOpen} onClose={() => setDelOpen(false)} danger title="Delete your account?" confirmLabel="Delete account permanently"
        onConfirm={async () => { try { await post("/account/delete", { password: pw }); router.replace("/"); } catch (e) { toast(errorMessage(e), "error"); } }}>
        <p className="mb-3">Enter your password to confirm.</p><Input type="password" aria-label="Password" value={pw} onChange={(e) => setPw(e.target.value)} />
      </Confirm>
    </div>
  );
}

function Privacy() {
  const { ws, base, can, me } = useWorkspace();
  const router = useRouter();
  const s = useSave();
  const [delOpen, setDelOpen] = useState(false);
  const ai = ws!.ai;
  return (
    <div className="space-y-6">
      <Panel title="External AI"><div className="max-w-2xl space-y-3 p-5 text-sm">
        <p>Active analyst for this workspace: <strong>{ai.active_mode === "anthropic" ? `Claude (${ai.model})` : "local deterministic interpreter"}</strong>.</p>
        <p className="text-ink-2">{ai.provider_configured ? `The server administrator has configured Claude (${ai.model}).` : "No external AI provider is configured on this server, so everything runs locally regardless of this setting."}</p>
        <p className="text-ink-2">When enabled, Claude receives the question, column names and types, roles, distinct-value counts, metric definitions, the latest date in the data and the previous question’s plan. It may also receive aggregated results (up to 30 rows) to write an explanation. Raw records and lists of column values are never sent.</p>
        <label className="flex items-center gap-2"><input type="checkbox" disabled={!can("admin") || !ai.provider_configured || s.busy} checked={ws!.external_ai_enabled}
          onChange={(e) => s.run(() => patch(base, { external_ai_enabled: e.target.checked }), e.target.checked ? "External AI enabled" : "External AI disabled")} />Allow this workspace to use the external AI provider</label>
        {!can("admin") && <p className="text-xs text-muted">Only owners and admins can change this.</p>}
      </div></Panel>
      <Panel title="Your data"><div className="max-w-2xl space-y-2 p-5 text-sm text-ink-2">
        <p>Uploads are stored on this ClearMetric server: originals under generated names, and analytical copies as Parquet files. Delete a dataset in the Data Hub to remove its files.</p>
        <p>Signed in as {me.user.email}. Read the full <a href="/trust" className="text-forest underline">trust and privacy page</a>.</p>
      </div></Panel>
      {ws!.role === "owner" && <Panel title="Delete workspace"><div className="space-y-3 p-5 text-sm">
        <p className="text-ink-2">Permanently deletes “{ws!.name}” with all datasets, stored files, metrics, investigations, insights and reports.</p>
        <Button variant="danger" onClick={() => setDelOpen(true)}>Delete workspace</Button></div></Panel>}
      <Confirm open={delOpen} onClose={() => setDelOpen(false)} danger title="Delete workspace?" confirmLabel="Delete workspace" onConfirm={async () => { await del(base); try { localStorage.removeItem("cm_workspace"); } catch { /* ignore */ } router.replace("/app"); window.location.reload(); }}>
        Everything in “{ws!.name}” will be deleted, including stored files. This cannot be undone.
      </Confirm>
    </div>
  );
}

function Settings() {
  const params = useSearchParams();
  const router = useRouter();
  const tab = (params.get("tab") as Tab) || "profile";
  const { ws } = useWorkspace();
  if (!ws) return <Skeleton className="h-96" />;
  return (
    <div className="mx-auto max-w-5xl">
      <PageHeader title="Settings" description={`Your profile and the settings for ${ws.name}.`} />
      <Tabs value={tab} onChange={(t) => router.replace(`/app/settings?tab=${t}`, { scroll: false })} className="mb-6" items={[
        { value: "profile", label: "Profile" }, { value: "workspace", label: "Workspace" }, { value: "business", label: "Business and formats" },
        { value: "members", label: "Members" }, { value: "security", label: "Security" }, { value: "privacy", label: "Data privacy" }]} />
      {tab === "profile" && <Profile />}
      {tab === "workspace" && <WorkspaceTab key="w" />}
      {tab === "business" && <WorkspaceTab key="b" business />}
      {tab === "members" && <Members />}
      {tab === "security" && <Security />}
      {tab === "privacy" && <Privacy />}
    </div>
  );
}

export default function SettingsPage() {
  return <Suspense fallback={<Skeleton className="h-96" />}><Settings /></Suspense>;
}
