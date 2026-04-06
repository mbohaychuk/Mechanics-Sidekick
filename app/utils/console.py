# app/utils/console.py
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table
from rich import box

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
