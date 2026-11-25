export type TraceStatus = "ok" | "error";

export interface TraceSummary {
  trace_id: string;
  name: string;
  source: string;
  status: TraceStatus | string;
  step_count: number;
  total_in_tokens: number;
  total_out_tokens: number;
  parent_trace_id: string | null;
  forked_from_seq: number | null;
  started_at_ns: number;
}

export interface TraceListResponse {
  traces: TraceSummary[];
}

export interface ChainVerification {
  valid: boolean;
  checked_steps: number;
  corrupted_seq: number | null;
}

export interface StepPayload {
  input?: Record<string, unknown> | unknown;
  output?: Record<string, unknown> | unknown;
  error?: string | Record<string, unknown> | null;
  [key: string]: unknown;
}

export interface TraceStep {
  seq: number;
  span_id: string;
  parent_span_id: string | null;
  op_type: string;
  name: string;
  model: string | null;
  status: TraceStatus | string;
  duration_ms: number;
  input_tokens: number;
  output_tokens: number;
  payload: StepPayload;
  prev_hash: string;
  step_hash: string;
}

export interface TraceDetailResponse {
  trace: TraceSummary;
  chain_verification?: ChainVerification;
  steps: TraceStep[];
}

export type ForkMode = "stub_replay" | "live_fork";

export interface ForkRequest {
  fork_at_seq: number;
  mode: ForkMode;
  override_payload: {
    output: unknown;
  };
}

export interface ForkDiff {
  base_status: string;
  fork_status: string;
  step_count_delta: number;
  error_count_delta: number;
  changed_seqs: number[];
}

export interface ForkResponse {
  fork_trace_id: string;
  mode: ForkMode;
  tokens_burned: number;
  prefix_tokens_saved: number;
  replay_duration_ms: number;
  diff: ForkDiff;
}
