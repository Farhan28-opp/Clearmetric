"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { createContext, ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { ApiError, get } from "@/lib/api";
import type { Me, Role, Workspace } from "@/lib/types";

type Ctx = {
  me: Me;
  ws: Workspace | null;
  wid: string | null;
  base: string;
  can: (role: Role) => boolean;
  switchTo: (id: string) => void;
  refresh: () => Promise<void>;
};
const WorkspaceCtx = createContext<Ctx | null>(null);
const RANK: Record<Role, number> = { viewer: 0, analyst: 1, admin: 2, owner: 3 };
const KEY = "cm_workspace";

export function WorkspaceProvider({ children, fallback }: { children: ReactNode; fallback: ReactNode }) {
  const router = useRouter();
  const qc = useQueryClient();
  const meQ = useQuery({ queryKey: ["me"], queryFn: () => get<Me>("/auth/me"), retry: false });
  const [wid, setWid] = useState<string | null>(null);

  useEffect(() => {
    if (meQ.error instanceof ApiError && meQ.error.status === 401) router.replace("/login");
  }, [meQ.error, router]);

  useEffect(() => {
    const me = meQ.data;
    if (!me) return;
    const ids = me.workspaces.map((w) => w.id);
    let stored: string | null = null;
    try { stored = localStorage.getItem(KEY); } catch { /* storage unavailable */ }
    const pick = [stored, me.user.last_workspace_id, ids[0]].find((x) => x && ids.includes(x)) ?? null;
    setWid((cur) => (cur && ids.includes(cur) ? cur : pick));
  }, [meQ.data]);

  const wsQ = useQuery({ queryKey: ["ws", wid], queryFn: () => get<{ workspace: Workspace }>(`/workspaces/${wid}`), enabled: !!wid });

  const switchTo = useCallback((id: string) => {
    try { localStorage.setItem(KEY, id); } catch { /* ignore */ }
    setWid(id);
    qc.removeQueries({ predicate: (q) => !["me"].includes(q.queryKey[0] as string) });
    router.push("/app/overview");
  }, [qc, router]);

  const value = useMemo<Ctx | null>(() => {
    if (!meQ.data) return null;
    const ws = wsQ.data?.workspace ?? null;
    return {
      me: meQ.data, ws, wid, base: wid ? `/workspaces/${wid}` : "",
      can: (r: Role) => !!ws && RANK[ws.role] >= RANK[r],
      switchTo,
      refresh: async () => { await qc.invalidateQueries({ queryKey: ["me"] }); await qc.invalidateQueries({ queryKey: ["ws"] }); },
    };
  }, [meQ.data, wsQ.data, wid, switchTo, qc]);

  const resolving = !!meQ.data && meQ.data.workspaces.length > 0 && (!wid || !value?.ws);
  if (!value || resolving) return <>{fallback}</>;
  return <WorkspaceCtx.Provider value={value}>{children}</WorkspaceCtx.Provider>;
}

export function useWorkspace(): Ctx {
  const c = useContext(WorkspaceCtx);
  if (!c) throw new Error("useWorkspace outside provider");
  return c;
}

/** Hook for workspace-scoped queries: key and path are both relative to the current workspace. */
export function useWsQuery<T>(key: unknown[], path: string | null, opts: { enabled?: boolean; refetchInterval?: number | false } = {}) {
  const { wid, base } = useWorkspace();
  return useQuery<T>({
    queryKey: [wid, ...key],
    queryFn: () => get<T>(`${base}${path}`),
    enabled: !!wid && path !== null && (opts.enabled ?? true),
    refetchInterval: opts.refetchInterval,
  });
}
