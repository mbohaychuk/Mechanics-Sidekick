# app/utils/console.py
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich import box

from app.rag.loop_state import LoopTraceEntry

console = Console()


def print_success(message: str) -> None:
    console.print(f"[bold green]✓[/bold green] {message}")


def print_error(message: str) -> None:
    console.print(f"[bold red]✗[/bold red] {message}")


def print_vehicle(vehicle) -> None:
    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("Field", style="dim")
    table.add_column("Value")
    table.add_row("ID", str(vehicle.id))
    table.add_row("Year", str(vehicle.year))
    table.add_row("Make", vehicle.make)
    table.add_row("Model", vehicle.model)
    table.add_row("Engine", vehicle.engine)
    if vehicle.vin:
        table.add_row("VIN", vehicle.vin)
    if vehicle.notes:
        table.add_row("Notes", vehicle.notes)
    console.print(Panel(table, title=f"Vehicle #{vehicle.id}", border_style="blue"))


def print_job(job) -> None:
    table = Table(box=box.SIMPLE, show_header=False)
    table.add_column("Field", style="dim")
    table.add_column("Value")
    table.add_row("ID", str(job.id))
    table.add_row("Title", job.title)
    table.add_row("Status", job.status)
    if job.description:
        table.add_row("Description", job.description)
    console.print(Panel(table, title=f"Job #{job.id}", border_style="cyan"))


def print_answer(answer: str, sources: list[dict]) -> None:
    console.print()
    console.print(Panel(escape(answer), title="[bold]Answer[/bold]", border_style="green"))
    if sources:
        console.print("[bold dim]Sources:[/bold dim]")
        for i, src in enumerate(sources, start=1):
            page = f", page {src['page']}" if src.get("page") else ""
            console.print(f"  {i}. {src['filename']}{page}")
    console.print()


def print_loop_step_retrieval(entry: LoopTraceEntry, max_iterations: int) -> None:
    iter_label = f"[{entry.iteration + 1}/{max_iterations + 1}]"
    quoted = f'"{entry.query}"'
    console.print(f"[bold cyan]{iter_label}[/bold cyan] Retrieving for {quoted}")
    arrow = "→"
    console.print(
        f"      Hybrid: {entry.candidate_count} {arrow} reranked: {entry.reranked_count} "
        f"{arrow} graded: {entry.relevant_count} relevant"
    )
    if entry.rejected_reasons:
        breakdown = ", ".join(
            f"{count} {reason}" for reason, count in entry.rejected_reasons.items()
        )
        rejected = sum(entry.rejected_reasons.values())
        console.print(f"      [dim]({rejected} rejected: {breakdown})[/dim]")


def print_loop_step_rewrite(entry: LoopTraceEntry) -> None:
    if entry.rewritten_query:
        cycle = "↻"
        console.print(f'[yellow]{cycle}[/yellow] Query rewritten: "{entry.rewritten_query}"')
        if entry.rewrite_rationale:
            console.print(f"  [dim]{entry.rewrite_rationale}[/dim]")


def print_loop_step_generation(chunk_count: int, model: str) -> None:
    pen = "✎"
    console.print(f"[cyan]{pen}[/cyan] Generating answer with {chunk_count} chunks ([dim]{model}[/dim])")


def print_loop_step_groundedness(passed: bool, unsupported: list[str] | None) -> None:
    if passed:
        console.print("[green]✓[/green] Groundedness check: PASS")
    else:
        console.print("[red]✗[/red] Groundedness check: FAIL")
        if unsupported:
            for claim in unsupported:
                console.print(f"  [red]·[/red] [dim]{claim}[/dim]")


def print_loop_refusal(searched_queries: int, total_examined: int, breakdown: dict[str, int]) -> None:
    console.print()
    console.print("[bold red]✗[/bold red] Could not answer from manuals.")
    console.print(f"  Searched {searched_queries} query variant(s); examined {total_examined} chunks.")
    if breakdown:
        for reason, count in breakdown.items():
            console.print(f"  - {count} {reason}")
    console.print()
