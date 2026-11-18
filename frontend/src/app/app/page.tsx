"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { useWorkspace } from "@/components/workspace";

export default function AppIndex() {
  const { me, ws } = useWorkspace();
  const router = useRouter();
  useEffect(() => {
    if (!me.workspaces.length || (ws && ws.onboarding && ws.onboarding.completed === false && ws.role === "owner")) router.replace("/app/onboarding");
    else router.replace("/app/overview");
  }, [me, ws, router]);
  return null;
}
