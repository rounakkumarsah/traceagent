"""OTLP HTTP/JSON trace parser with gen_ai.* and mcp.* normalization."""

from typing import Any

from traceagent.ingest.redactor import redact_secrets
from traceagent.models import StepInput, StepOpType, StepStatus, TraceCreate


def coerce_int(value: Any, default: int = 0) -> int:
    """Coerce OTLP intValue (often encoded as string in JSON) to int."""
    if value is None or isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        try:
            return int(stripped)
        except ValueError:
            try:
                return int(float(stripped))
            except ValueError:
                return default
    return default


def unwrap_otlp_value(value_obj: dict[str, Any]) -> Any:
    """Unwrap an OTLP AnyValue dictionary into a native Python value."""
    if "stringValue" in value_obj:
        return str(value_obj["stringValue"])
    if "intValue" in value_obj:
        return coerce_int(value_obj["intValue"])
    if "doubleValue" in value_obj:
        return float(value_obj["doubleValue"])
    if "boolValue" in value_obj:
        return bool(value_obj["boolValue"])
    if "arrayValue" in value_obj:
        values = value_obj["arrayValue"].get("values", [])
        return [unwrap_otlp_value(v) for v in values if isinstance(v, dict)]
    if "kvlistValue" in value_obj:
        items = value_obj["kvlistValue"].get("values", [])
        return {
            str(item["key"]): unwrap_otlp_value(item.get("value", {}))
            for item in items
            if isinstance(item, dict) and "key" in item
        }
    return None


def parse_attributes(attr_list: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Convert OTLP KeyValue list into a flat dictionary."""
    if not attr_list:
        return {}
    result: dict[str, Any] = {}
    for item in attr_list:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if not key:
            continue
        val_obj = item.get("value", {})
        if isinstance(val_obj, dict):
            result[str(key)] = unwrap_otlp_value(val_obj)
        else:
            result[str(key)] = val_obj
    return result


def _normalize_op_type(attrs: dict[str, Any]) -> StepOpType:
    """Determine normalized StepOpType from gen_ai.* and mcp.* attributes."""
    if any(k.startswith("mcp.") for k in attrs):
        return "mcp_call"

    op = str(attrs.get("gen_ai.operation.name", "")).strip().lower()
    if op == "invoke_agent":
        return "invoke_agent"
    if op in ("execute_tool", "tool"):
        return "execute_tool"
    if op == "mcp_call":
        return "mcp_call"
    return "chat"


def _normalize_status(span: dict[str, Any]) -> StepStatus:
    """Determine normalized StepStatus from OTLP span status."""
    status_obj = span.get("status")
    if not isinstance(status_obj, dict):
        return "ok"
    code = status_obj.get("code")
    if code == 2 or str(code).upper() == "STATUS_CODE_ERROR":
        return "error"
    return "ok"


def parse_otlp_traces(payload: dict[str, Any]) -> list[tuple[TraceCreate, StepInput]]:
    """Parse an OTLP ExportTraceServiceRequest JSON dict into (TraceCreate, StepInput) pairs."""
    results: list[tuple[TraceCreate, StepInput]] = []
    resource_spans = payload.get("resourceSpans")
    if not isinstance(resource_spans, list):
        return results

    for rs in resource_spans:
        if not isinstance(rs, dict):
            continue
        resource_attrs = parse_attributes(rs.get("resource", {}).get("attributes"))
        service_name = str(resource_attrs.get("service.name", "otlp-service"))

        scope_spans = rs.get("scopeSpans")
        if not isinstance(scope_spans, list):
            continue

        for ss in scope_spans:
            if not isinstance(ss, dict):
                continue
            scope_name = str(ss.get("scope", {}).get("name", ""))
            spans = ss.get("spans")
            if not isinstance(spans, list):
                continue

            for span in spans:
                if not isinstance(span, dict):
                    continue

                trace_id = str(span.get("traceId") or "").strip()
                span_id = str(span.get("spanId") or "").strip()
                if not trace_id or not span_id:
                    continue

                parent_span_id_raw = span.get("parentSpanId")
                parent_span_id = str(parent_span_id_raw).strip() if parent_span_id_raw else None
                if parent_span_id == "":
                    parent_span_id = None

                attrs = parse_attributes(span.get("attributes"))
                op_type = _normalize_op_type(attrs)
                span_name = str(span.get("name") or attrs.get("mcp.tool.name") or op_type)

                start_ns = coerce_int(span.get("startTimeUnixNano"))
                end_ns = coerce_int(span.get("endTimeUnixNano"), default=start_ns)
                duration_ms = max(0.0, (end_ns - start_ns) / 1_000_000.0)

                model_raw = attrs.get("gen_ai.request.model") or attrs.get("gen_ai.response.model")
                model = str(model_raw) if model_raw is not None else None

                input_tokens = coerce_int(
                    attrs.get("gen_ai.usage.input_tokens")
                    if "gen_ai.usage.input_tokens" in attrs
                    else attrs.get("gen_ai.usage.prompt_tokens")
                )
                output_tokens = coerce_int(
                    attrs.get("gen_ai.usage.output_tokens")
                    if "gen_ai.usage.output_tokens" in attrs
                    else attrs.get("gen_ai.usage.completion_tokens")
                )

                status = _normalize_status(span)

                raw_step_payload: dict[str, Any] = {
                    "attributes": attrs,
                    "resource": resource_attrs,
                }
                if scope_name:
                    raw_step_payload["scope"] = scope_name
                if span.get("events"):
                    raw_step_payload["events"] = span["events"]

                redacted_payload = redact_secrets(raw_step_payload)

                trace_create = TraceCreate(
                    trace_id=trace_id,
                    name=service_name if service_name != "otlp-service" else span_name,
                    source="otlp",
                    status="error" if status == "error" else "ok",
                    started_at_ns=start_ns,
                    ended_at_ns=end_ns,
                )
                step_input = StepInput(
                    span_id=span_id,
                    parent_span_id=parent_span_id,
                    op_type=op_type,
                    name=span_name,
                    model=model,
                    status=status,
                    timestamp_ns=start_ns,
                    duration_ms=duration_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    payload=redacted_payload,
                )
                results.append((trace_create, step_input))

    return results
