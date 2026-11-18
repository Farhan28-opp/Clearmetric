"use client";
import { FileSpreadsheet, UploadCloud } from "lucide-react";
import { useRef, useState } from "react";
import { Button, cx, Dialog, ErrorNote } from "@/components/ui";
import { useWorkspace } from "@/components/workspace";
import { errorMessage, post, uploadWithProgress } from "@/lib/api";
import type { Dataset } from "@/lib/types";

export function SheetPicker({ dataset, onDone, onClose }: { dataset: Dataset | null; onDone: (d: Dataset) => void; onClose: () => void }) {
  const { base } = useWorkspace();
  const [sheet, setSheet] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  return (
    <Dialog open={!!dataset} onClose={onClose} title="Choose a sheet to import"
      footer={<><Button variant="ghost" onClick={onClose}>Later</Button><Button variant="primary" disabled={!sheet} loading={busy} onClick={async () => {
        setBusy(true); setErr("");
        try { onDone((await post<{ dataset: Dataset }>(`${base}/datasets/${dataset!.id}/import`, { sheet })).dataset); }
        catch (e) { setErr(errorMessage(e)); } finally { setBusy(false); }
      }}>Import sheet</Button></>}>
      {err && <div className="mb-3"><ErrorNote>{err}</ErrorNote></div>}
      <p className="mb-3 text-sm text-muted">{dataset?.original_filename} has several sheets. Pick the one that holds your records.</p>
      <fieldset className="space-y-2">
        <legend className="sr-only">Sheets</legend>
        {dataset?.sheets.map((s) => (
          <label key={s.name} className={cx("flex items-center justify-between gap-3 rounded-md border px-3 py-2.5 text-sm", s.empty ? "border-line opacity-60" : "cursor-pointer border-line-2 hover:border-ink-2", sheet === s.name && "border-forest bg-forest-wash")}>
            <span className="flex items-center gap-2"><input type="radio" name="sheet" value={s.name} disabled={s.empty} checked={sheet === s.name} onChange={() => setSheet(s.name)} /> {s.name}</span>
            <span className="text-xs text-muted">{s.empty ? "Empty" : `about ${Math.max(0, s.rows - 1).toLocaleString()} rows × ${s.columns} columns`}</span>
          </label>
        ))}
      </fieldset>
    </Dialog>
  );
}

export function Uploader({ onUploaded, accept = ".csv,.xlsx,.xls", compact }: { onUploaded: (d: Dataset) => void; accept?: string; compact?: boolean }) {
  const { base, can } = useWorkspace();
  const input = useRef<HTMLInputElement>(null);
  const [drag, setDrag] = useState(false);
  const [pct, setPct] = useState<number | null>(null);
  const [stage, setStage] = useState("");
  const [err, setErr] = useState("");
  const [needsSheet, setNeedsSheet] = useState<Dataset | null>(null);

  const send = async (file: File) => {
    setErr(""); setPct(0); setStage(`Uploading ${file.name}`);
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await uploadWithProgress<{ dataset: Dataset }>(`/api${base}/datasets/upload`, form, (p) => {
        setPct(p);
        if (p === 100) setStage("Processing: detecting structure, types and data quality");
      });
      if (res.dataset.status === "needs_sheet") setNeedsSheet(res.dataset);
      else onUploaded(res.dataset);
    } catch (e) {
      setErr(errorMessage(e));
    } finally {
      setPct(null); setStage("");
    }
  };
  if (!can("analyst")) return <p className="text-sm text-muted">Your role (viewer) can’t upload data.</p>;
  return (
    <div>
      <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
        onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files?.[0]; if (f) send(f); }}
        className={cx("flex flex-col items-center justify-center rounded-lg border-2 border-dashed text-center transition-colors", compact ? "px-4 py-6" : "px-6 py-10",
          drag ? "border-forest bg-forest-wash" : "border-line-2 bg-surface")}>
        {pct === null ? (
          <>
            <UploadCloud className="size-7 text-forest" aria-hidden />
            <p className="mt-2 font-medium">Drag a CSV or Excel file here</p>
            <p className="mt-1 text-sm text-muted">or</p>
            <Button className="mt-2" onClick={() => input.current?.click()}><FileSpreadsheet className="size-4" /> Choose a file</Button>
            <p className="mt-3 text-xs text-muted">.csv, .xlsx or .xls. Macros are never run.</p>
            <input ref={input} type="file" accept={accept} className="sr-only" aria-label="Choose a data file"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) send(f); e.target.value = ""; }} />
          </>
        ) : (
          <div className="w-full max-w-sm" role="status" aria-live="polite">
            <p className="text-sm font-medium">{stage}</p>
            <div className="mt-3 h-2 overflow-hidden rounded-full bg-paper-2" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
              <div className={cx("h-full rounded-full bg-forest transition-all", pct === 100 && "animate-pulse")} style={{ width: `${pct}%` }} />
            </div>
            <p className="mt-1.5 text-xs text-muted tnum">{pct < 100 ? `${pct}% uploaded` : "Upload complete"}</p>
          </div>
        )}
      </div>
      {err && <div className="mt-3"><ErrorNote>{err}</ErrorNote></div>}
      <SheetPicker dataset={needsSheet} onClose={() => setNeedsSheet(null)} onDone={(d) => { setNeedsSheet(null); onUploaded(d); }} />
    </div>
  );
}
