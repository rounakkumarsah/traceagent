"""CLI entrypoint for TraceAgent."""

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console

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
