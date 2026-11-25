"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { createFork, fetchTraceDetail, fetchTraces } from "@/lib/api";
import type {
  ForkMode,
  ForkResponse,
  TraceDetailResponse,
  TraceStep,
  TraceSummary,
} from "@/lib/types";

function getOpColor(opType: string): string {
  switch (opType) {
    case "invoke_agent":
      return "bg-[#38BDF8]";
    case "chat":
      return "bg-[#818CF8]";
    case "execute_tool":
      return "bg-[#F59E0B]";
    case "mcp_call":
      return "bg-[#10B981]";
    default:
      return "bg-[#64748B]";
  }
}

function getOpBadgeStyle(opType: string): string {
  switch (opType) {
    case "invoke_agent":
      return "bg-[#38BDF8]/15 text-[#38BDF8] border-[#38BDF8]/30";
    case "chat":
      return "bg-[#818CF8]/15 text-[#818CF8] border-[#818CF8]/30";
    case "execute_tool":
      return "bg-[#F59E0B]/15 text-[#F59E0B] border-[#F59E0B]/30";
    case "mcp_call":
      return "bg-[#10B981]/15 text-[#10B981] border-[#10B981]/30";
    default:
      return "bg-[#64748B]/15 text-[#94A3B8] border-[#64748B]/30";
  }
}

function formatJson(value: unknown): string {
  if (value === undefined) return "null";
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

export default function TraceWorkspace() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTraceId = searchParams.get("trace");

  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [tracesLoading, setTracesLoading] = useState<boolean>(true);
  const [tracesError, setTracesError] = useState<string | null>(null);

  const [detail, setDetail] = useState<TraceDetailResponse | null>(null);
  const [detailLoading, setDetailLoading] = useState<boolean>(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const [selectedSeq, setSelectedSeq] = useState<number | null>(null);
  const [jsonText, setJsonText] = useState<string>("{}");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [forkMode, setForkMode] = useState<ForkMode>("stub_replay");
  const [forkSubmitting, setForkSubmitting] = useState<boolean>(false);
  const [forkError, setForkError] = useState<string | null>(null);
  const [forkResult, setForkResult] = useState<ForkResponse | null>(null);

  const loadTraces = useCallback(async () => {
    setTracesLoading(true);
    setTracesError(null);
    try {
      const data = await fetchTraces();
      setTraces(data.traces);
      return data.traces;
    } catch (err) {
      setTracesError(err instanceof Error ? err.message : "Failed to load traces");
      return [];
    } finally {
      setTracesLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadTraces().then((list) => {
      if (!activeTraceId && list.length > 0) {
        router.replace(`/?trace=${encodeURIComponent(list[0].trace_id)}`);
      }
    });
  }, [activeTraceId, loadTraces, router]);

  useEffect(() => {
    if (!activeTraceId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    setForkResult(null);
    setForkError(null);

    void fetchTraceDetail(activeTraceId)
      .then((data) => {
        if (cancelled) return;
        setDetail(data);
        if (data.steps.length > 0) {
          const errorStep = data.steps.find((s) => s.status === "error");
          const initialStep = errorStep ?? data.steps[0];
          setSelectedSeq(initialStep.seq);
          const initialOutput =
            initialStep.payload?.output !== undefined
              ? initialStep.payload.output
              : {};
          setJsonText(formatJson(initialOutput));
          setJsonError(null);
        } else {
          setSelectedSeq(null);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setDetailError(
          err instanceof Error ? err.message : "Failed to load trace detail"
        );
      })
      .finally(() => {
        if (!cancelled) setDetailLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [activeTraceId]);

  const selectedStep: TraceStep | null = useMemo(() => {
    if (!detail || selectedSeq === null) return null;
    return detail.steps.find((s) => s.seq === selectedSeq) ?? null;
  }, [detail, selectedSeq]);

  const handleSelectTrace = (traceId: string) => {
    router.push(`/?trace=${encodeURIComponent(traceId)}`);
  };

  const handleSelectStep = (step: TraceStep) => {
    setSelectedSeq(step.seq);
    const outVal = step.payload?.output !== undefined ? step.payload.output : {};
    setJsonText(formatJson(outVal));
    setJsonError(null);
    setForkError(null);
    setForkResult(null);
  };

  const handleJsonChange = (value: string) => {
    setJsonText(value);
    try {
      JSON.parse(value);
      setJsonError(null);
    } catch (err) {
      setJsonError(err instanceof Error ? err.message : "Invalid JSON");
    }
  };

  const handleForkSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!detail || selectedStep === null || jsonError) return;

    let parsedOutput: unknown;
    try {
      parsedOutput = JSON.parse(jsonText);
    } catch (err) {
      setJsonError(err instanceof Error ? err.message : "Invalid JSON");
      return;
    }

    setForkSubmitting(true);
    setForkError(null);
    try {
      const res = await createFork(detail.trace.trace_id, {
        fork_at_seq: selectedStep.seq,
        mode: forkMode,
        override_payload: {
          output: parsedOutput,
        },
      });
      setForkResult(res);
      await loadTraces();
    } catch (err) {
      setForkError(err instanceof Error ? err.message : "Fork failed");
    } finally {
      setForkSubmitting(false);
    }
  };

  const maxDurationMs = useMemo(() => {
    if (!detail || detail.steps.length === 0) return 1;
    return Math.max(
      1,
      ...detail.steps.map((s) => (s.duration_ms > 0 ? s.duration_ms : 0))
    );
  }, [detail]);

  const totalDurationMs = useMemo(() => {
    if (!detail) return 0;
    return detail.steps.reduce((acc, s) => acc + (s.duration_ms || 0), 0);
  }, [detail]);

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-[#0B0F17] text-[#F9FAFB]">
      {/* Panel 1 — Left Sidebar (260px): Trace Explorer */}
      <aside className="flex w-[260px] shrink-0 flex-col border-r border-[#1F2937] bg-[#111827]">
        <div className="flex items-center justify-between border-b border-[#1F2937] px-4 py-3">
          <div className="flex items-center gap-2">
            <span className="h-2.5 w-2.5 rounded-sm bg-[#38BDF8]" />
            <span className="text-sm font-semibold tracking-tight text-[#F9FAFB]">
              TraceAgent
            </span>
          </div>
          <button
            type="button"
            onClick={() => void loadTraces()}
            className="rounded border border-[#1F2937] bg-[#0B0F17] px-2 py-0.5 text-[11px] font-medium text-[#9CA3AF] hover:border-[#38BDF8]/50 hover:text-[#F9FAFB]"
          >
            Refresh
          </button>
        </div>

        <div className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-[#6B7280]">
          Trace Explorer ({traces.length})
        </div>

        <div className="flex-1 overflow-y-auto px-2 pb-4">
          {tracesLoading && traces.length === 0 ? (
            <div className="px-2 py-4 text-xs text-[#6B7280]">Loading traces...</div>
          ) : tracesError ? (
            <div className="rounded border border-[#EF4444]/40 bg-[#EF4444]/10 p-2 text-xs text-[#EF4444]">
              {tracesError}
            </div>
          ) : traces.length === 0 ? (
            <div className="px-2 py-4 text-xs text-[#6B7280]">
              No traces recorded yet.
            </div>
          ) : (
            <ul className="space-y-1">
              {traces.map((t) => {
                const isActive = t.trace_id === activeTraceId;
                const isError = t.status === "error";
                return (
                  <li key={t.trace_id}>
                    <button
                      type="button"
                      onClick={() => handleSelectTrace(t.trace_id)}
                      className={`w-full rounded border px-2.5 py-2 text-left transition-colors ${
                        isActive
                          ? "border-[#38BDF8]/60 bg-[#0B0F17]"
                          : "border-transparent bg-transparent hover:border-[#1F2937] hover:bg-[#0B0F17]/60"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-1.5">
                        <div className="flex min-w-0 items-center gap-2">
                          <span
                            className={`h-2 w-2 shrink-0 rounded-full ${
                              isError ? "bg-[#EF4444]" : "bg-[#22C55E]"
                            }`}
                          />
                          <span className="truncate text-xs font-medium text-[#F9FAFB]">
                            {t.name}
                          </span>
                        </div>
                        {t.parent_trace_id !== null && (
                          <span className="shrink-0 rounded border border-[#38BDF8]/40 bg-[#38BDF8]/10 px-1 py-0.5 font-mono text-[9px] font-semibold text-[#38BDF8]">
                            FORK
                          </span>
                        )}
                      </div>
                      <div className="mt-1 truncate font-mono text-[10px] text-[#6B7280]">
                        {t.trace_id.slice(0, 22)}
                      </div>
                      <div className="mt-1.5 flex items-center justify-between font-mono text-[10px] text-[#9CA3AF]">
                        <span>{t.step_count} steps</span>
                        <span>
                          {t.total_in_tokens} / {t.total_out_tokens} tok
                        </span>
                      </div>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </aside>

      {/* Panel 2 — Center Canvas (Flexible): Waterfall Flamegraph & Audit Header */}
      <main className="flex min-w-0 flex-1 flex-col bg-[#0B0F17]">
        {detailLoading ? (
          <div className="flex flex-1 items-center justify-center text-xs text-[#6B7280]">
            Loading trace waterfall...
          </div>
        ) : detailError ? (
          <div className="m-6 rounded border border-[#EF4444]/40 bg-[#EF4444]/10 p-4 text-xs text-[#EF4444]">
            {detailError}
          </div>
        ) : !detail ? (
          <div className="flex flex-1 items-center justify-center text-xs text-[#6B7280]">
            Select a trace from the left sidebar to inspect its execution.
          </div>
        ) : (
          <>
            {/* Top Audit Bar */}
            <header className="flex flex-wrap items-center justify-between gap-4 border-b border-[#1F2937] bg-[#111827] px-5 py-3">
              <div className="min-w-0">
                <div className="flex items-center gap-2.5">
                  <h1 className="truncate text-sm font-semibold text-[#F9FAFB]">
                    {detail.trace.name}
                  </h1>
                  {detail.trace.parent_trace_id && (
                    <span className="rounded border border-[#38BDF8]/40 bg-[#38BDF8]/10 px-1.5 py-0.5 font-mono text-[10px] text-[#38BDF8]">
                      forked from seq {detail.trace.forked_from_seq}
                    </span>
                  )}
                </div>
                <div className="mt-0.5 font-mono text-[11px] text-[#6B7280]">
                  {detail.trace.trace_id}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-4">
                {/* SHA-256 Chain Badge */}
                {detail.chain_verification ? (
                  detail.chain_verification.valid ? (
                    <span className="rounded border border-[#22C55E]/40 bg-[#22C55E]/10 px-2.5 py-1 font-mono text-[11px] font-semibold text-[#22C55E]">
                      SHA-256 CHAIN: VALID
                    </span>
                  ) : (
                    <span className="rounded border border-[#EF4444]/50 bg-[#EF4444]/15 px-2.5 py-1 font-mono text-[11px] font-semibold text-[#EF4444]">
                      TAMPERED AT SEQ {detail.chain_verification.corrupted_seq ?? "?"}
                    </span>
                  )
                ) : (
                  <span className="rounded border border-[#1F2937] bg-[#0B0F17] px-2.5 py-1 font-mono text-[11px] text-[#9CA3AF]">
                    SHA-256 CHAIN: UNVERIFIED
                  </span>
                )}

                <div className="flex items-center gap-4 font-mono text-xs text-[#9CA3AF]">
                  <div>
                    <span className="text-[#6B7280]">STEPS </span>
                    <span className="text-[#F9FAFB]">{detail.steps.length}</span>
                  </div>
                  <div>
                    <span className="text-[#6B7280]">DUR </span>
                    <span className="text-[#F9FAFB]">
                      {totalDurationMs.toFixed(1)} ms
                    </span>
                  </div>
                  <div>
                    <span className="text-[#6B7280]">TOKENS </span>
                    <span className="text-[#F9FAFB]">
                      {detail.trace.total_in_tokens + detail.trace.total_out_tokens}
                    </span>
                  </div>
                </div>
              </div>
            </header>

            {/* Step Waterfall List */}
            <div className="flex-1 overflow-y-auto p-5">
              <div className="mb-3 flex items-center justify-between text-[11px] font-semibold uppercase tracking-wider text-[#6B7280]">
                <span>Step Execution Waterfall</span>
                <span>Duration (proportional)</span>
              </div>

              <div className="space-y-2">
                {detail.steps.map((step) => {
                  const isSelected = step.seq === selectedSeq;
                  const isError = step.status === "error";
                  const widthPct = Math.max(
                    4,
                    Math.min(100, (step.duration_ms / maxDurationMs) * 100)
                  );

                  return (
                    <button
                      key={step.seq}
                      type="button"
                      onClick={() => handleSelectStep(step)}
                      className={`w-full rounded border p-3 text-left transition-colors ${
                        isSelected
                          ? "border-[#38BDF8] bg-[#111827]"
                          : isError
                          ? "border-[#EF4444]/60 bg-[#111827]/80 hover:border-[#EF4444]"
                          : "border-[#1F2937] bg-[#111827]/60 hover:border-[#374151]"
                      }`}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="flex min-w-0 items-center gap-2.5">
                          <span className="font-mono text-xs font-semibold text-[#9CA3AF]">
                            #{step.seq}
                          </span>
                          <span
                            className={`rounded border px-1.5 py-0.5 font-mono text-[10px] font-medium ${getOpBadgeStyle(
                              step.op_type
                            )}`}
                          >
                            {step.op_type}
                          </span>
                          <span className="truncate text-xs font-medium text-[#F9FAFB]">
                            {step.name}
                          </span>
                          {isError && (
                            <span className="rounded bg-[#EF4444]/20 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-[#EF4444]">
                              ERROR
                            </span>
                          )}
                        </div>

                        <div className="flex shrink-0 items-center gap-3 font-mono text-[11px] text-[#9CA3AF]">
                          <span>
                            {step.input_tokens}/{step.output_tokens} tok
                          </span>
                          <span className="w-20 text-right text-[#F9FAFB]">
                            {step.duration_ms.toFixed(1)} ms
                          </span>
                        </div>
                      </div>

                      {/* Proportional Waterfall Bar */}
                      <div className="mt-2.5 h-2 w-full overflow-hidden rounded-sm bg-[#0B0F17]">
                        <div
                          className={`h-full rounded-sm ${
                            isError ? "bg-[#EF4444]" : getOpColor(step.op_type)
                          }`}
                          style={{ width: `${widthPct}%` }}
                        />
                      </div>
                    </button>
                  );
                })}
              </div>
            </div>
          </>
        )}
      </main>

      {/* Panel 3 — Right Drawer (420px): Step Inspector & Time-Travel Forker */}
      <aside className="flex w-[420px] shrink-0 flex-col border-l border-[#1F2937] bg-[#111827]">
        <div className="border-b border-[#1F2937] px-4 py-3">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-[#9CA3AF]">
            Step Inspector &amp; Time-Travel Forker
          </h2>
        </div>

        {!selectedStep || !detail ? (
          <div className="flex flex-1 items-center justify-center p-4 text-xs text-[#6B7280]">
            Select a step in the waterfall to inspect payloads or fork.
          </div>
        ) : (
          <div className="flex-1 overflow-y-auto p-4 space-y-4">
            {/* Step Metadata */}
            <div className="rounded border border-[#1F2937] bg-[#0B0F17] p-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs font-semibold text-[#38BDF8]">
                  SEQ #{selectedStep.seq} — {selectedStep.op_type}
                </span>
                <span
                  className={`font-mono text-[11px] font-semibold ${
                    selectedStep.status === "error"
                      ? "text-[#EF4444]"
                      : "text-[#22C55E]"
                  }`}
                >
                  {selectedStep.status.toUpperCase()}
                </span>
              </div>
              <div className="mt-1 text-xs font-medium text-[#F9FAFB]">
                {selectedStep.name}
              </div>
              <div className="mt-2 space-y-1 font-mono text-[10px] text-[#6B7280]">
                <div className="truncate">
                  <span className="text-[#9CA3AF]">prev_hash: </span>
                  {selectedStep.prev_hash}
                </div>
                <div className="truncate">
                  <span className="text-[#9CA3AF]">step_hash: </span>
                  {selectedStep.step_hash}
                </div>
              </div>
            </div>

            {/* Error block if present */}
            {selectedStep.payload?.error && (
              <div>
                <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[#EF4444]">
                  Error
                </div>
                <pre className="max-h-32 overflow-auto rounded border border-[#EF4444]/40 bg-[#EF4444]/10 p-2.5 font-mono text-[11px] text-[#EF4444]">
                  {typeof selectedStep.payload.error === "string"
                    ? selectedStep.payload.error
                    : formatJson(selectedStep.payload.error)}
                </pre>
              </div>
            )}

            {/* Input */}
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[#6B7280]">
                Input
              </div>
              <pre className="max-h-36 overflow-auto rounded border border-[#1F2937] bg-[#0B0F17] p-2.5 font-mono text-[11px] text-[#D1D5DB]">
                {formatJson(selectedStep.payload?.input ?? {})}
              </pre>
            </div>

            {/* Output */}
            <div>
              <div className="mb-1 text-[11px] font-semibold uppercase tracking-wider text-[#6B7280]">
                Recorded Output
              </div>
              <pre className="max-h-36 overflow-auto rounded border border-[#1F2937] bg-[#0B0F17] p-2.5 font-mono text-[11px] text-[#D1D5DB]">
                {formatJson(selectedStep.payload?.output ?? {})}
              </pre>
            </div>

            {/* Edit & Fork Action Block */}
            <form
              onSubmit={(e) => void handleForkSubmit(e)}
              className="space-y-3 border-t border-[#1F2937] pt-4"
            >
              <div className="flex items-center justify-between">
                <label
                  htmlFor="fork-json-editor"
                  className="text-[11px] font-semibold uppercase tracking-wider text-[#38BDF8]"
                >
                  Edit Output &amp; Fork at Seq #{selectedStep.seq}
                </label>
                {jsonError ? (
                  <span className="font-mono text-[10px] text-[#EF4444]">
                    Invalid JSON
                  </span>
                ) : (
                  <span className="font-mono text-[10px] text-[#22C55E]">
                    Valid JSON
                  </span>
                )}
              </div>

              <textarea
                id="fork-json-editor"
                value={jsonText}
                onChange={(e) => handleJsonChange(e.target.value)}
                rows={6}
                spellCheck={false}
                className={`w-full rounded border bg-[#0B0F17] p-2.5 font-mono text-[11px] text-[#F9FAFB] focus:outline-none ${
                  jsonError
                    ? "border-[#EF4444] focus:border-[#EF4444]"
                    : "border-[#1F2937] focus:border-[#38BDF8]"
                }`}
              />
              {jsonError && (
                <div className="font-mono text-[10px] text-[#EF4444]">
                  {jsonError}
                </div>
              )}

              {/* Strict 2-Mode Selector */}
              <div className="space-y-1.5">
                <div className="text-[11px] font-semibold uppercase tracking-wider text-[#6B7280]">
                  Replay Mode
                </div>
                <label className="flex cursor-pointer items-center gap-2 rounded border border-[#1F2937] bg-[#0B0F17] px-2.5 py-2 text-xs hover:border-[#374151]">
                  <input
                    type="radio"
                    name="forkMode"
                    value="stub_replay"
                    checked={forkMode === "stub_replay"}
                    onChange={() => setForkMode("stub_replay")}
                    className="accent-[#38BDF8]"
                  />
                  <span>Deterministic Stub Replay ($0.00 — tests code/parsers)</span>
                </label>
                <label className="flex cursor-pointer items-center gap-2 rounded border border-[#1F2937] bg-[#0B0F17] px-2.5 py-2 text-xs hover:border-[#374151]">
                  <input
                    type="radio"
                    name="forkMode"
                    value="live_fork"
                    checked={forkMode === "live_fork"}
                    onChange={() => setForkMode("live_fork")}
                    className="accent-[#38BDF8]"
                  />
                  <span>Live Fork from Step N (saves prefix tokens)</span>
                </label>
              </div>

              <button
                type="submit"
                disabled={Boolean(jsonError) || forkSubmitting}
                className="w-full rounded bg-[#38BDF8] px-3 py-2 text-xs font-semibold text-[#0B0F17] transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
              >
                {forkSubmitting
                  ? "Forking Trace..."
                  : `Fork & Replay from Seq #${selectedStep.seq}`}
              </button>

              {forkError && (
                <div className="rounded border border-[#EF4444]/40 bg-[#EF4444]/10 p-2 text-xs text-[#EF4444]">
                  {forkError}
                </div>
              )}

              {forkResult && (
                <div className="space-y-2 rounded border border-[#22C55E]/40 bg-[#22C55E]/10 p-3">
                  <div className="text-xs font-semibold text-[#22C55E]">
                    Base vs. Fork Diff Summary
                  </div>
                  <div className="grid grid-cols-2 gap-1.5 font-mono text-[11px] text-[#D1D5DB]">
                    <div>error_count_delta:</div>
                    <div className="text-right text-[#F9FAFB]">
                      {forkResult.diff.error_count_delta}
                    </div>
                    <div>tokens_burned:</div>
                    <div className="text-right text-[#F9FAFB]">
                      {forkResult.tokens_burned}
                    </div>
                    <div>prefix_tokens_saved:</div>
                    <div className="text-right text-[#F9FAFB]">
                      {forkResult.prefix_tokens_saved}
                    </div>
                    <div>replay_duration_ms:</div>
                    <div className="text-right text-[#F9FAFB]">
                      {forkResult.replay_duration_ms.toFixed(2)} ms
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleSelectTrace(forkResult.fork_trace_id)}
                    className="mt-1 w-full rounded border border-[#38BDF8] bg-[#38BDF8]/15 px-2.5 py-1.5 text-xs font-semibold text-[#38BDF8] hover:bg-[#38BDF8]/25"
                  >
                    Open Fork Trace ({forkResult.fork_trace_id})
                  </button>
                </div>
              )}
            </form>
          </div>
        )}
      </aside>
    </div>
  );
}
