"use client";
import { usePathname } from "next/navigation";
import { Mark } from "@/components/brand";
import { Shell } from "@/components/shell";
import { WorkspaceProvider } from "@/components/workspace";

function Loading() {
  return (
    <div className="flex min-h-dvh items-center justify-center" role="status" aria-label="Loading workspace">
      <Mark className="size-8 animate-pulse" />
    </div>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const bare = path.startsWith("/app/onboarding") || path === "/app";
  return (
    <WorkspaceProvider fallback={<Loading />}>
      {bare ? children : <Shell>{children}</Shell>}
    </WorkspaceProvider>
  );
}
