"""CLI entrypoint for TraceAgent."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
import uvicorn
from rich.console import Console
from rich.table import Table

from traceagent.demo.seed_demo import seed_demo_trace
from traceagent.ingest.mcp_tap import run_mcp_tap
from traceagent.replay.ci_gate import InvalidTraceFileError, evaluate_ci_gate
from traceagent.server.app import create_app
from traceagent.storage.sqlite_ledger import SQLiteLedger

app = typer.Typer(
    name="traceagent",
    help="Forensic-grade observability and replay ledger for AI agents.",
    no_args_is_help=True,
)
console = Console()


@app.callback()
def main() -> None:
    """TraceAgent CLI."""


@app.command()
def verify(
    trace_id: Annotated[
        str | None,
        typer.Argument(help="Trace ID to verify. Omit when using --all."),
    ] = None,
    all_traces: Annotated[
        bool,
        typer.Option("--all", help="Verify all traces in the ledger."),
    ] = False,
    db: Annotated[
        Path,
        typer.Option("--db", help="Path to SQLite ledger database."),
    ] = Path("traceagent.db"),
) -> None:
    """Verify the SHA-256 hash chain integrity of one or all traces."""
    if not all_traces and trace_id is None:
        console.print("[red]Error:[/red] Provide a <trace_id> or pass --all.")
        raise typer.Exit(code=1)

    if not db.exists():
        console.print(f"[red]Error:[/red] Database not found: {db}")
        raise typer.Exit(code=1)

    ledger = SQLiteLedger(db)

    async def _run() -> int:
        if all_traces:
            trace_ids = await ledger.list_trace_ids()
            if not trace_ids:
                console.print("[yellow]No traces found in ledger.[/yellow]")
                return 0
        else:
            assert trace_id is not None
            trace_ids = [trace_id]

        exit_code = 0
        for tid in trace_ids:
            result = await ledger.verify_trace(tid)
            if result.valid:
                console.print(
                    f"[green]VALID[/green] trace={result.trace_id} "
                    f"checked_steps={result.checked_steps}"
                )
            else:
                console.print(
                    f"[red]TAMPERED[/red] trace={result.trace_id} "
                    f"corrupted_seq={result.corrupted_seq} "
                    f"reason={result.reason}"
                )
                exit_code = 1
        return exit_code

    code = asyncio.run(_run())
    raise typer.Exit(code=code)


@app.command()
def serve(
    host: Annotated[
        str,
        typer.Option("--host", help="Host interface to bind."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", help="Port to listen on."),
    ] = 8000,
    db: Annotated[
        Path,
        typer.Option("--db", help="Path to SQLite ledger database."),
    ] = Path("traceagent.db"),
) -> None:
    """Start the TraceAgent OTLP receiver and API server."""
    fastapi_app = create_app(db)
    uvicorn.run(fastapi_app, host=host, port=port)


@app.command(context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
def wrap(
    cmd: Annotated[
        list[str],
        typer.Argument(help="Command and arguments to wrap (use `-- <cmd...>`)."),
    ],
    db: Annotated[
        Path,
        typer.Option("--db", help="Path to SQLite ledger database."),
    ] = Path("traceagent.db"),
    trace_id: Annotated[
        str | None,
        typer.Option("--trace-id", help="Optional trace ID for the wrapped session."),
    ] = None,
) -> None:
    """Wrap an MCP stdio server, proxying stdio transparently and recording calls."""
    code = run_mcp_tap(cmd=cmd, db_path=db, trace_id=trace_id)
    raise typer.Exit(code=code)


@app.command()
def check(
    golden: Annotated[
        Path,
        typer.Option("--golden", help="Path to golden baseline JSONL trace."),
    ],
    candidate: Annotated[
        Path,
        typer.Option("--candidate", help="Path to candidate JSONL trace."),
    ],
    max_token_increase_pct: Annotated[
        float,
        typer.Option(
            "--max-token-increase-pct",
            help="Maximum allowed token increase percentage.",
        ),
    ] = 15.0,
    max_step_increase: Annotated[
        int,
        typer.Option(
            "--max-step-increase",
            help="Maximum allowed step count increase.",
        ),
    ] = 2,
) -> None:
    """Run CI golden-trace regression gate against a candidate JSONL trace."""
    try:
        result = evaluate_ci_gate(
            golden_path=golden,
            candidate_path=candidate,
            max_token_increase_pct=max_token_increase_pct,
            max_step_increase=max_step_increase,
        )
    except InvalidTraceFileError as exc:
        console.print(f"[red]Invalid input:[/red] {exc}")
        raise typer.Exit(code=2) from exc

    if result.passed:
        console.print(
            f"[green]PASS[/green] steps={result.candidate_steps} "
            f"(golden={result.golden_steps}), "
            f"tokens={result.candidate_tokens} (golden={result.golden_tokens}), "
            f"errors={result.candidate_errors}"
        )
        raise typer.Exit(code=0)

    table = Table(title="CI Golden-Trace Regression Detected")
    table.add_column("Rule", style="red")
    table.add_column("Golden")
    table.add_column("Candidate")
    table.add_column("Offending Seq")
    for failure in result.failures:
        table.add_row(
            failure.rule,
            failure.golden_value,
            failure.candidate_value,
            failure.offending_seq,
        )
    console.print(table)
    raise typer.Exit(code=1)


@app.command()
def demo(
    host: Annotated[
        str,
        typer.Option("--host", help="Host interface to bind."),
    ] = "127.0.0.1",
    port: Annotated[
        int,
        typer.Option("--port", help="Port to listen on."),
    ] = 8000,
    db: Annotated[
        Path,
        typer.Option("--db", help="Path to SQLite ledger database."),
    ] = Path("traceagent.db"),
) -> None:
    """Seed the 7-step offline demo trace and start the TraceAgent API server."""
    ledger = SQLiteLedger(db)

    async def _seed() -> str:
        await ledger.init_schema()
        return await seed_demo_trace(ledger)

    trace_id = asyncio.run(_seed())
    console.print(
        f"[green]Seeded demo trace:[/green] {trace_id} "
        f"(crashing at Seq 6). Starting server at http://{host}:{port}"
    )
    fastapi_app = create_app(db)
    uvicorn.run(fastapi_app, host=host, port=port)


if __name__ == "__main__":
    app()
