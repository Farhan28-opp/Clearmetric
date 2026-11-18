"use client";
import { useQueryClient } from "@tanstack/react-query";
import {
  Bookmark, BookmarkCheck, Copy, Download, FilePlus2, HelpCircle, MessageSquarePlus, MoreHorizontal, NotebookPen, PanelRightClose, PanelRightOpen,
  Pin, PinOff, SendHorizontal, Sparkles, Trash2,
} from "lucide-react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";
import { Inspector, ResultView } from "@/components/analysis/result";
import { DatasetSelect, useActiveDataset } from "@/components/datasets";
import { Badge, Button, Confirm, cx, Dialog, Empty, ErrorNote, Field, Input, Skeleton, Textarea, useToast } from "@/components/ui";
import { useWorkspace, useWsQuery } from "@/components/workspace";
import { del, download, errorMessage, patch, post } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import type { Conversation, Message, Report, Run } from "@/lib/types";

function Sidebar({ activeId, onNew }: { activeId: string | null; onNew: () => void }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [deb, setDeb] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => { const t = setTimeout(() => setDeb(q), 250); return () => clearTimeout(t); }, [q]);
  const list = useWsQuery<{ conversations: Conversation[] }>(["conversations", deb, saved], `/conversations?${saved ? "saved=true&" : ""}${deb ? `q=${encodeURIComponent(deb)}` : ""}`);
  return (
    <aside className="flex w-full flex-col gap-3 lg:w-64 lg:shrink-0" aria-label="Investigations">
      <Button variant="primary" onClick={onNew}><MessageSquarePlus className="size-4" />New analysis</Button>
      <Input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search conversations" aria-label="Search conversations" className="h-8.5 text-[13px]" />
      <div className="flex gap-1 text-[13px]" role="radiogroup" aria-label="Filter">
        {[["All", false], ["Saved", true]].map(([l, v]) => <button key={String(l)} role="radio" aria-checked={saved === v} onClick={() => setSaved(v as boolean)} className={cx("rounded px-2 py-1", saved === v ? "bg-ink text-white" : "text-ink-2 hover:bg-paper-2")}>{l as string}</button>)}
      </div>
      <ul className="max-h-[60vh] space-y-0.5 overflow-y-auto lg:max-h-[calc(100dvh-16rem)]">
        {list.isLoading && <Skeleton className="h-24" />}
        {list.data?.conversations.map((c) => (
          <li key={c.id}>
            <button onClick={() => router.push(`/app/analyst?c=${c.id}`)} aria-current={c.id === activeId}
              className={cx("w-full rounded-md px-2.5 py-2 text-left", c.id === activeId ? "bg-surface shadow-[0_0_0_1px_var(--color-line)]" : "hover:bg-paper-2")}>
              <span className="flex items-center gap-1.5 text-[13px] font-medium">{c.saved && <BookmarkCheck className="size-3.5 shrink-0 text-forest" aria-label="saved" />}<span className="truncate">{c.title}</span></span>
              <span className="block truncate text-[11.5px] text-muted">{c.dataset_name} · {timeAgo(c.updated_at)}</span>
            </button>
          </li>))}
        {list.data && !list.data.conversations.length && <li className="px-2 text-sm text-muted">{deb || saved ? "No matching investigations." : "Your investigations will appear here."}</li>}
      </ul>
    </aside>
  );
}

function AssistantMessage({ m, conv, onAsk, onClarify, onInspect, active, historical }: {
  m: Message; conv: Conversation; onAsk: (q: string) => void; onClarify: (m: Message, i: number) => void; onInspect: (r: Run) => void; active: boolean; historical: boolean;
}) {
  const { base, wid, can } = useWorkspace();
  const qc = useQueryClient();
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState(m.note);
  const p = m.payload;
  const update = async (body: Record<string, unknown>) => { await patch(`${base}/conversations/${conv.id}/messages/${m.id}`, body); qc.invalidateQueries({ queryKey: [wid, "conversation", conv.id] }); };
  return (
    <article className={cx("rounded-lg border bg-surface", active ? "border-forest/50" : "border-line", m.pinned && "ring-1 ring-brass/40")} aria-label="Answer">
      <div className="space-y-3 p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
            <Sparkles className="size-3.5 text-forest" aria-hidden />
            {p.mode === "anthropic" ? <span>Claude interpreted · computed by ClearMetric</span> : <span>Local analyst (deterministic) · computed by ClearMetric</span>}
            {m.pinned && <Badge tone="brass">pinned</Badge>}
            {historical && m.run && <Badge tone="brass">from dataset v{m.run.result.provenance.dataset.version_number} (older version)</Badge>}
          </div>
          {can("analyst") && m.kind === "answer" && (
            <div className="flex gap-0.5">
              <button onClick={() => update({ pinned: !m.pinned })} className="rounded p-1 text-muted hover:bg-paper-2 hover:text-ink" aria-label={m.pinned ? "Unpin answer" : "Pin answer"}>{m.pinned ? <PinOff className="size-4" /> : <Pin className="size-4" />}</button>
              <button onClick={() => setNoteOpen(!noteOpen)} className="rounded p-1 text-muted hover:bg-paper-2 hover:text-ink" aria-label="Add note"><NotebookPen className="size-4" /></button>
            </div>
          )}
        </div>
        {m.kind === "clarification" ? (
          <div>
            <p className="flex gap-2 text-[15px] font-medium"><HelpCircle className="mt-0.5 size-4 shrink-0 text-brass" />{m.content}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {p.clarification?.options.map((o, i) => (
                <Button key={i} size="sm" variant={p.answered === i ? "primary" : "secondary"} disabled={p.answered !== undefined || !can("analyst")} onClick={() => onClarify(m, i)} title={o.description}>{o.label}</Button>
              ))}
            </div>
            {p.answered === undefined && <p className="mt-2 text-xs text-muted">I ask rather than guess when a business term could mean more than one thing.</p>}
          </div>
        ) : (
          <p className={cx("text-[15px] leading-relaxed", m.kind === "error" && "text-rust", m.kind === "unsupported" && "text-ink-2")}>{m.content}</p>
        )}
        {p.observations && p.observations.length > 0 && (
          <div><p className="text-xs font-medium text-muted">Computed observations</p>
            <ul className="mt-1 space-y-0.5 text-sm text-ink-2">{p.observations.map((o) => <li key={o} className="flex gap-2"><span aria-hidden className="text-forest">–</span>{o}</li>)}</ul></div>
        )}
        {p.ai_explanation && (
          <div className="rounded-md border border-line bg-paper/60 p-3 text-sm"><p className="text-xs font-medium text-muted">AI-written interpretation (checked: uses only computed numbers)</p><p className="mt-1">{p.ai_explanation}</p></div>
        )}
        {p.describe && (
          <div className="overflow-x-auto rounded-md border border-line"><table className="w-full text-[13px]"><thead className="bg-paper/70 text-left"><tr><th className="px-3 py-1.5 font-medium">Column</th><th className="px-3 py-1.5 font-medium">Type</th><th className="px-3 py-1.5 font-medium">Role</th><th className="px-3 py-1.5 font-medium">Meaning</th></tr></thead>
            <tbody className="divide-y divide-line">{p.describe.columns.map((c) => <tr key={c.name}><td className="px-3 py-1.5">{c.name}</td><td className="px-3 py-1.5">{c.type}</td><td className="px-3 py-1.5">{c.role}</td><td className="px-3 py-1.5 text-muted">{c.meaning?.replace(/_/g, " ") || "—"}</td></tr>)}</tbody></table></div>
        )}
        {m.run && <ResultView run={m.run} title={undefined} compact conversationId={conv.id} onInspect={() => onInspect(m.run!)} />}
        {p.problems && <ul className="list-disc pl-5 text-sm text-ink-2">{p.problems.map((x) => <li key={x}>{x}</li>)}</ul>}
        {(p.follow_ups?.length || p.suggestions?.length) ? (
          <div className="flex flex-wrap gap-1.5 pt-1">
            <span className="text-xs text-muted">{m.kind === "answer" ? "Follow up:" : "Try:"}</span>
            {(p.follow_ups ?? p.suggestions ?? []).map((f) => <button key={f} onClick={() => onAsk(f)} disabled={!can("analyst")} className="rounded-full border border-line-2 px-2.5 py-0.5 text-[13px] text-ink-2 hover:border-forest hover:text-forest">{f}</button>)}
          </div>
        ) : null}
        {p.notes && p.notes.length > 0 && <p className="text-xs text-muted">Interpretation: {p.notes.join(" ")}</p>}
        {(noteOpen || m.note) && (
          <div className="rounded-md border border-brass/30 bg-brass-wash/40 p-2">
            {noteOpen ? (
              <div className="flex gap-2"><Textarea aria-label="Note" rows={2} value={note} onChange={(e) => setNote(e.target.value)} className="text-sm" />
                <Button size="sm" onClick={async () => { await update({ note }); setNoteOpen(false); }}>Save note</Button></div>
            ) : <p className="text-sm"><span className="font-medium">Note:</span> {m.note}</p>}
          </div>
        )}
      </div>
    </article>
  );
}

function Workspace({ convId }: { convId: string }) {
  const { base, wid, can, ws } = useWorkspace();
  const qc = useQueryClient();
  const router = useRouter();
  const toast = useToast();
  const params = useSearchParams();
  const conv = useWsQuery<{ conversation: Conversation }>(["conversation", convId], `/conversations/${convId}`);
  const [text, setText] = useState("");
  const [pending, setPending] = useState<string | null>(null);
  const [err, setErr] = useState("");
  const [inspect, setInspect] = useState<Run | null>(null);
  const [panel, setPanel] = useState(true);
  const [mobileInspect, setMobileInspect] = useState(false);
  const [notes, setNotes] = useState(false);
  const [menu, setMenu] = useState(false);
  const [rename, setRename] = useState<string | null>(null);
  const [remove, setRemove] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);
  const autoAsked = useRef(false);
  const c = conv.data?.conversation;
  const sugg = useWsQuery<{ questions: string[] }>(["suggestions", c?.dataset_id], c?.dataset_id ? `/conversations/suggestions?dataset_id=${c.dataset_id}` : null);
  const refresh = () => { qc.invalidateQueries({ queryKey: [wid, "conversation", convId] }); qc.invalidateQueries({ queryKey: [wid, "conversations"] }); };

  const ask = async (q: string) => {
    if (!q.trim() || pending) return;
    setPending(q); setErr(""); setText("");
    try {
      const r = await post<{ messages: Message[] }>(`${base}/conversations/${convId}/ask`, { question: q });
      const last = r.messages[r.messages.length - 1];
      if (last.run) setInspect(last.run);
      refresh();
    } catch (e) { setErr(errorMessage(e)); setText(q); } finally { setPending(null); }
  };
  const clarify = async (m: Message, i: number) => {
    setPending(m.payload.clarification?.options[i].label ?? "…");
    try { const r = await post<{ messages: Message[] }>(`${base}/conversations/${convId}/clarify`, { message_id: m.id, option_index: i }); const last = r.messages[r.messages.length - 1]; if (last.run) setInspect(last.run); refresh(); }
    catch (e) { setErr(errorMessage(e)); } finally { setPending(null); }
  };
  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [c?.messages?.length, pending]);
  useEffect(() => {
    const q = params.get("q");
    if (q && c && !autoAsked.current && c.messages?.length === 0) { autoAsked.current = true; ask(q); router.replace(`/app/analyst?c=${convId}`, { scroll: false }); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [c?.id]);
  useEffect(() => {
    if (!inspect && c?.messages) { const lastRun = [...c.messages].reverse().find((m) => m.run)?.run; if (lastRun) setInspect(lastRun); }
  }, [c?.messages, inspect]);

  if (conv.error) return <ErrorNote>{errorMessage(conv.error)}</ErrorNote>;
  if (!c) return <Skeleton className="h-96 flex-1" />;
  const currentVersion = c.dataset_current_version_id;
  return (
    <div className="flex min-w-0 flex-1 gap-5">
      <section className="flex min-w-0 flex-1 flex-col" aria-label="Conversation">
        <header className="mb-3 flex flex-wrap items-center gap-2 border-b border-line pb-3">
          <div className="min-w-0 flex-1">
            <h1 className="truncate text-xl font-semibold">{c.title}</h1>
            <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[13px] text-muted">
              Analysing <span className="font-medium text-ink">{c.dataset_name ?? "no dataset"}</span>
              {c.messages?.find((m) => m.run)?.run?.result.provenance.dataset.is_demo && <Badge tone="brass">synthetic data</Badge>}
              <span>· mode: {ws?.ai.active_mode === "anthropic" ? `Claude (${ws.ai.model}) + deterministic engine` : "local deterministic interpreter"}</span>
            </p>
          </div>
          {can("analyst") && <Button size="sm" variant={c.saved ? "primary" : "secondary"} onClick={async () => { await patch(`${base}/conversations/${convId}`, { saved: !c.saved }); toast(c.saved ? "Removed from saved" : "Investigation saved"); refresh(); }}>
            {c.saved ? <BookmarkCheck className="size-3.5" /> : <Bookmark className="size-3.5" />}{c.saved ? "Saved" : "Save"}</Button>}
          <Button size="sm" variant="ghost" onClick={() => setNotes(!notes)} aria-expanded={notes}><NotebookPen className="size-3.5" />Notes</Button>
          <div className="relative">
            <Button size="sm" variant="ghost" onClick={() => setMenu(!menu)} aria-label="More actions" aria-expanded={menu}><MoreHorizontal className="size-4" /></Button>
            {menu && (
              <div role="menu" className="absolute right-0 top-full z-30 mt-1 w-56 rounded-md border border-line bg-surface p-1 text-sm shadow-lift" onClick={() => setMenu(false)}>
                {can("analyst") && <button role="menuitem" className="block w-full rounded px-3 py-1.5 text-left hover:bg-paper" onClick={() => setRename(c.title)}>Rename</button>}
                {can("analyst") && <button role="menuitem" className="flex w-full items-center gap-2 rounded px-3 py-1.5 text-left hover:bg-paper" onClick={async () => { const r = await post<{ conversation: Conversation }>(`${base}/conversations/${convId}/duplicate`); refresh(); router.push(`/app/analyst?c=${r.conversation.id}`); }}><Copy className="size-3.5" />Duplicate</button>}
                <button role="menuitem" className="flex w-full items-center gap-2 rounded px-3 py-1.5 text-left hover:bg-paper" onClick={() => download(`${base}/conversations/${convId}/export?format=md`)}><Download className="size-3.5" />Export as Markdown</button>
                <button role="menuitem" className="flex w-full items-center gap-2 rounded px-3 py-1.5 text-left hover:bg-paper" onClick={() => download(`${base}/conversations/${convId}/export?format=json`)}><Download className="size-3.5" />Export as JSON</button>
                {can("analyst") && <button role="menuitem" className="flex w-full items-center gap-2 rounded px-3 py-1.5 text-left hover:bg-paper" onClick={async () => { try { const r = await post<{ report: Report }>(`${base}/reports`, { title: c.title, from_conversation_id: convId }); router.push(`/app/reports/${r.report.id}`); } catch (e) { toast(errorMessage(e), "error"); } }}><FilePlus2 className="size-3.5" />Create report from this</button>}
                {can("analyst") && <button role="menuitem" className="flex w-full items-center gap-2 rounded px-3 py-1.5 text-left text-rust hover:bg-rust-wash" onClick={() => setRemove(true)}><Trash2 className="size-3.5" />Delete</button>}
              </div>
            )}
          </div>
          <Button size="sm" variant="ghost" className="hidden xl:inline-flex" onClick={() => setPanel(!panel)} aria-label={panel ? "Hide inspector" : "Show inspector"}>{panel ? <PanelRightClose className="size-4" /> : <PanelRightOpen className="size-4" />}</Button>
        </header>
        {notes && <NotesPanel conv={c} onSaved={refresh} />}
        <div className="flex-1 space-y-4 pb-4">
          {!c.messages?.length && !pending && (
            <div className="rounded-lg border border-dashed border-line-2 bg-surface/60 p-6">
              <h2 className="text-lg font-semibold">What would you like to know?</h2>
              <p className="mt-1 text-sm text-muted">Ask in plain language. Every answer comes with the calculation behind it.</p>
              <div className="mt-4 flex flex-wrap gap-2">{sugg.data?.questions.map((q) => <button key={q} onClick={() => ask(q)} disabled={!can("analyst")} className="rounded-full border border-line-2 bg-surface px-3 py-1.5 text-sm hover:border-forest hover:text-forest">{q}</button>)}</div>
            </div>
          )}
          {c.messages?.map((m) => m.role === "user" ? (
            <div key={m.id} className="flex justify-end"><p className="max-w-[80%] rounded-lg bg-ink px-3.5 py-2 text-[15px] text-white">{m.content}</p></div>
          ) : (
            <AssistantMessage key={m.id} m={m} conv={c} onAsk={ask} onClarify={clarify} onInspect={(r) => { setInspect(r); setPanel(true); if (window.innerWidth < 1280) setMobileInspect(true); }} active={!!m.run && inspect?.id === m.run.id}
              historical={!!m.run && !!currentVersion && m.run.dataset_version_id !== currentVersion} />
          ))}
          {pending && (
            <>
              <div className="flex justify-end"><p className="max-w-[80%] rounded-lg bg-ink/80 px-3.5 py-2 text-[15px] text-white">{pending}</p></div>
              <div role="status" className="rounded-lg border border-line bg-surface p-4 text-sm text-muted">Interpreting the question, validating the plan and computing…</div>
            </>
          )}
          <div ref={bottom} />
        </div>
        {err && <ErrorNote>{err}</ErrorNote>}
        {can("analyst") ? (
          <form className="sticky bottom-0 mt-2 bg-paper pb-1 pt-2" onSubmit={(e) => { e.preventDefault(); ask(text); }}>
            <div className="flex items-end gap-2 rounded-lg border border-line-2 bg-surface p-2 focus-within:border-forest">
              <label htmlFor="composer" className="sr-only">Ask a question about {c.dataset_name}</label>
              <textarea id="composer" rows={1} value={text} onChange={(e) => setText(e.target.value)} disabled={!!pending}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(text); } }}
                placeholder={`Ask about ${c.dataset_name ?? "your data"}, e.g. “Which five products generated the highest net revenue?”`}
                className="max-h-40 min-h-10 flex-1 resize-none bg-transparent px-2 py-2 text-[15px] placeholder:text-muted focus:outline-none" />
              <Button type="submit" variant="primary" disabled={!text.trim()} loading={!!pending} aria-label="Ask"><SendHorizontal className="size-4" /></Button>
            </div>
            <p className="mt-1 px-1 text-[11.5px] text-muted">Enter to ask, Shift+Enter for a new line. Follow-ups like “their”, “its” or “the second-highest” refer to the previous answer.</p>
          </form>
        ) : <p className="text-sm text-muted">Viewers can read investigations but not ask new questions.</p>}
      </section>
      {panel && (
        <aside className="hidden w-[23rem] shrink-0 xl:block" aria-label="Analysis inspector">
          <div className="sticky top-20 max-h-[calc(100dvh-6rem)] overflow-y-auto rounded-lg border border-line bg-surface">
            <header className="flex items-center justify-between border-b border-line px-4 py-3"><h2 className="text-sm font-semibold">Analysis inspector</h2><button onClick={() => setPanel(false)} aria-label="Collapse inspector" className="text-muted hover:text-ink"><PanelRightClose className="size-4" /></button></header>
            <div className="p-4">{inspect ? <Inspector run={inspect} /> : <p className="text-sm text-muted">Ask a question to see its metric, filters, records, method and query here.</p>}</div>
          </div>
        </aside>
      )}
      <Dialog open={mobileInspect && !!inspect} onClose={() => setMobileInspect(false)} title="Analysis inspector" wide>{inspect && <Inspector run={inspect} />}</Dialog>
      <Dialog open={rename !== null} onClose={() => setRename(null)} title="Rename investigation" footer={<><Button variant="ghost" onClick={() => setRename(null)}>Cancel</Button>
        <Button variant="primary" onClick={async () => { await patch(`${base}/conversations/${convId}`, { title: rename }); setRename(null); refresh(); }}>Save</Button></>}>
        <Field label="Title" htmlFor="ct"><Input id="ct" value={rename ?? ""} onChange={(e) => setRename(e.target.value)} /></Field>
      </Dialog>
      <Confirm open={remove} onClose={() => setRemove(false)} danger title="Delete investigation" confirmLabel="Delete"
        onConfirm={async () => { await del(`${base}/conversations/${convId}`); qc.invalidateQueries({ queryKey: [wid, "conversations"] }); router.push("/app/analyst"); }}>
        The questions and answers in “{c.title}” will be deleted. Report sections created from it keep their snapshots.
      </Confirm>
    </div>
  );
}

function NotesPanel({ conv, onSaved }: { conv: Conversation; onSaved: () => void }) {
  const { base, can } = useWorkspace();
  const toast = useToast();
  const [notes, setNotes] = useState(conv.notes);
  const [findings, setFindings] = useState<string[]>(conv.findings ?? []);
  const [f, setF] = useState("");
  return (
    <div className="mb-4 grid gap-3 rounded-lg border border-line bg-surface p-4 md:grid-cols-2">
      <Field label="Investigation notes" htmlFor="nn"><Textarea id="nn" rows={4} value={notes} onChange={(e) => setNotes(e.target.value)} disabled={!can("analyst")} /></Field>
      <div>
        <p className="text-[13px] font-medium text-ink-2">Findings</p>
        <ul className="mt-1.5 space-y-1 text-sm">{findings.map((x, i) => <li key={i} className="flex justify-between gap-2"><span>– {x}</span>{can("analyst") && <button className="text-xs text-muted hover:text-rust" onClick={() => setFindings(findings.filter((_, j) => j !== i))}>remove</button>}</li>)}</ul>
        {can("analyst") && <div className="mt-2 flex gap-2"><Input aria-label="New finding" value={f} onChange={(e) => setF(e.target.value)} className="h-8 text-sm" placeholder="Add a finding" /><Button size="sm" onClick={() => { if (f.trim()) { setFindings([...findings, f.trim()]); setF(""); } }}>Add</Button></div>}
      </div>
      {can("analyst") && <div className="md:col-span-2"><Button size="sm" variant="primary" onClick={async () => { await patch(`${base}/conversations/${conv.id}`, { notes, findings }); toast("Notes saved"); onSaved(); }}>Save notes</Button></div>}
    </div>
  );
}

function Studio() {
  const params = useSearchParams();
  const router = useRouter();
  const { base, can } = useWorkspace();
  const toast = useToast();
  const convId = params.get("c");
  const { id: dsId, choose, datasets } = useActiveDataset(params.get("dataset"));
  const [creating, setCreating] = useState(false);
  const started = useRef(false);
  const create = async () => {
    if (!dsId) return toast("Add a dataset first", "error");
    setCreating(true);
    try {
      const r = await post<{ conversation: Conversation }>(`${base}/conversations`, { dataset_id: dsId });
      const q = params.get("q");
      router.replace(`/app/analyst?c=${r.conversation.id}${q ? `&q=${encodeURIComponent(q)}` : ""}`);
    } catch (e) { toast(errorMessage(e), "error"); } finally { setCreating(false); }
  };
  useEffect(() => {
    if (params.get("new") === "1" && dsId && !started.current && can("analyst")) { started.current = true; create(); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dsId, params]);
  return (
    <div className="mx-auto flex max-w-[1500px] flex-col gap-5 lg:flex-row">
      <div className="space-y-3">
        <Sidebar activeId={convId} onNew={create} />
        <div className="rounded-md border border-line bg-surface p-3 lg:w-64">
          <p className="mb-2 text-xs font-medium text-muted">Dataset for new analyses</p>
          <DatasetSelect value={dsId} onChange={choose} datasets={datasets} label="" />
          <ul className="mt-2 space-y-0.5 text-xs text-muted">{datasets.filter((d) => d.status === "ready").slice(0, 4).map((d) => <li key={d.id} className="truncate">{d.name} · {d.row_count?.toLocaleString()} rows</li>)}</ul>
        </div>
      </div>
      {convId ? <Workspace key={convId} convId={convId} /> : (
        <div className="flex-1">
          <Empty icon={<Sparkles className="size-6" />} title="Start an investigation" action={<Button variant="primary" loading={creating} onClick={create} disabled={!dsId || !can("analyst")}>New analysis</Button>}>
            {dsId ? "Ask questions about your data in plain language. Each answer shows the metric, filters, records and query used, and follow-ups build on earlier results." : "Add a dataset in the Data Hub first."}
          </Empty>
        </div>
      )}
    </div>
  );
}

export default function AnalystPage() {
  return <Suspense fallback={<Skeleton className="h-96" />}><Studio /></Suspense>;
}
