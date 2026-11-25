import { Suspense } from "react";
import TraceWorkspace from "@/components/TraceWorkspace";

export default function HomePage() {
  return (
    <Suspense
      fallback={
        <div className="flex h-screen w-screen items-center justify-center bg-[#0B0F17] text-xs text-[#6B7280]">
          Loading TraceAgent...
        </div>
      }
    >
      <TraceWorkspace />
    </Suspense>
  );
}
