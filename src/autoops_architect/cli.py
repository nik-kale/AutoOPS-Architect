"""Command-line interface for AutoOps Architect."""

import json
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.syntax import Syntax
from rich.table import Table
from rich.tree import Tree

from autoops_architect.executor.engine import ExecutorConfig, WorkflowExecutor
from autoops_architect.llm.base import LLMConfig, LLMProvider
from autoops_architect.memory.backend import get_memory_backend
from autoops_architect.models.execution import ExecutionStatus
from autoops_architect.models.goal import Environment, Goal, Priority
from autoops_architect.models.workflow import WorkflowGraph
from autoops_architect.planner.architect import Architect, PlannerConfig
from autoops_architect.tools.base import create_default_registry

# Create CLI app
app = typer.Typer(
    name="autoops",
    help="AutoOps Architect - AI-powered operations workflow automation",
    add_completion=False,
)

console = Console()


def get_planner(mock: bool = False) -> Architect:
    """Get a configured Architect instance."""
    llm_config = None
    if mock:
        llm_config = LLMConfig(provider=LLMProvider.MOCK)

    config = PlannerConfig(llm_config=llm_config)
    memory = get_memory_backend()

    return Architect(config=config, memory_backend=memory)


def get_executor(dry_run: bool = False) -> WorkflowExecutor:
    """Get a configured WorkflowExecutor instance."""
    config = ExecutorConfig(dry_run=dry_run)
    registry = create_default_registry()
    return WorkflowExecutor(config=config, tool_registry=registry)


@app.command()
def plan(
    goal: str = typer.Argument(..., help="Natural language description of your goal"),
    service: Optional[list[str]] = typer.Option(
        None, "--service", "-s", help="Target service(s)"
    ),
    environment: Optional[str] = typer.Option(
        None, "--env", "-e", help="Environment (prod/staging/dev)"
    ),
    priority: Optional[str] = typer.Option(
        None, "--priority", "-p", help="Priority (critical/high/medium/low)"
    ),
    output: Optional[Path] = typer.Option(
        None, "--output", "-o", help="Output file for the workflow JSON"
    ),
    yaml_output: bool = typer.Option(
        False, "--yaml", help="Output as YAML instead of JSON"
    ),
    mock: bool = typer.Option(
        False, "--mock", help="Use mock LLM (no API calls)"
    ),
    show_mermaid: bool = typer.Option(
        False, "--mermaid", help="Show Mermaid diagram"
    ),
) -> None:
    """
    Generate a workflow plan from a natural language goal.

    Example:
        autoops plan "Investigate elevated 5xx errors for the checkout service"
    """
    console.print(Panel.fit(
        f"[bold blue]Planning workflow for:[/]\n{goal}",
        title="AutoOps Architect",
    ))

    # Parse environment
    env = Environment.UNKNOWN
    if environment:
        try:
            env = Environment(environment.lower())
        except ValueError:
            console.print(f"[yellow]Unknown environment: {environment}, using 'unknown'[/]")

    # Parse priority
    prio = Priority.UNKNOWN
    if priority:
        try:
            prio = Priority(priority.lower())
        except ValueError:
            console.print(f"[yellow]Unknown priority: {priority}, using 'unknown'[/]")

    # Create Goal object
    goal_obj = Goal(
        description=goal,
        services=list(service) if service else [],
        environment=env,
        priority=prio,
    )

    # Generate workflow
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating workflow...", total=None)

        try:
            planner = get_planner(mock=mock)
            workflow = planner.plan_sync(goal_obj)
            progress.update(task, completed=True)
        except Exception as e:
            progress.update(task, completed=True)
            console.print(f"[red]Error generating workflow: {e}[/]")
            raise typer.Exit(1)

    # Display the workflow
    console.print()
    console.print(f"[green]Generated workflow:[/] {workflow.name}")
    console.print(f"[dim]ID: {workflow.id}[/]")
    console.print(f"[dim]Nodes: {len(workflow.nodes)}, Edges: {len(workflow.edges)}[/]")

    # Show workflow tree
    console.print()
    tree = Tree("[bold]Workflow Steps[/]")
    for node in workflow.topological_sort():
        icon = "🔧" if not node.requires_human_approval else "🛑"
        tree.add(f"{icon} [{node.type.value}] {node.name}")
    console.print(tree)

    # Show Mermaid diagram if requested
    if show_mermaid:
        console.print()
        console.print("[bold]Mermaid Diagram:[/]")
        console.print(Syntax(workflow.to_mermaid(), "mermaid"))

    # Output to file or stdout
    if yaml_output:
        output_content = workflow.to_yaml()
    else:
        output_content = workflow.model_dump_json(indent=2)

    if output:
        output.write_text(output_content)
        console.print(f"\n[green]Workflow saved to:[/] {output}")
    else:
        console.print("\n[bold]Workflow JSON:[/]")
        if yaml_output:
            console.print(Syntax(output_content, "yaml"))
        else:
            console.print(Syntax(output_content, "json"))


@app.command()
def run(
    workflow_file: Path = typer.Argument(..., help="Path to workflow JSON/YAML file"),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Simulate execution without running tools"
    ),
    auto_approve: bool = typer.Option(
        False, "--auto-approve", help="Automatically approve all approval requests"
    ),
) -> None:
    """
    Execute a workflow from a file.

    Example:
        autoops run workflow.json
    """
    # Load workflow
    if not workflow_file.exists():
        console.print(f"[red]Workflow file not found: {workflow_file}[/]")
        raise typer.Exit(1)

    content = workflow_file.read_text()

    try:
        if workflow_file.suffix in (".yaml", ".yml"):
            workflow = WorkflowGraph.from_yaml(content)
        else:
            data = json.loads(content)
            workflow = WorkflowGraph.model_validate(data)
    except Exception as e:
        console.print(f"[red]Error parsing workflow: {e}[/]")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold blue]Executing workflow:[/] {workflow.name}\n"
        f"[dim]ID: {workflow.id}[/]",
        title="AutoOps Architect",
    ))

    if dry_run:
        console.print("[yellow]Running in dry-run mode (no tools will be executed)[/]")

    # Create executor
    config = ExecutorConfig(dry_run=dry_run, auto_approve=auto_approve)
    executor = WorkflowExecutor(config=config, tool_registry=create_default_registry())

    # Add progress callback
    def on_status_change(node_id: str, status: ExecutionStatus, result=None):
        icon = {
            ExecutionStatus.RUNNING: "⏳",
            ExecutionStatus.SUCCESS: "✅",
            ExecutionStatus.FAILED: "❌",
            ExecutionStatus.SKIPPED: "⏭️",
            ExecutionStatus.WAITING_APPROVAL: "🛑",
        }.get(status, "❓")
        console.print(f"  {icon} {node_id}: {status.value}")

    executor.add_status_callback(on_status_change)

    # Execute
    console.print("\n[bold]Execution Progress:[/]")

    try:
        result = executor.execute_sync(workflow)
    except Exception as e:
        console.print(f"\n[red]Execution error: {e}[/]")
        raise typer.Exit(1)

    # Display results
    console.print()

    # Summary panel
    status_color = {
        ExecutionStatus.SUCCESS: "green",
        ExecutionStatus.FAILED: "red",
        ExecutionStatus.CANCELLED: "yellow",
    }.get(result.overall_status, "white")

    console.print(Panel(
        f"[{status_color}]{result.overall_status.value.upper()}[/]\n\n"
        f"Nodes: {result.success_count} succeeded, "
        f"{result.failed_count} failed, "
        f"{result.skipped_count} skipped\n"
        f"Duration: {result.duration_seconds:.2f}s" if result.duration_seconds else "",
        title="Execution Result",
    ))

    # Show detailed results
    if result.failed_count > 0:
        console.print("\n[red bold]Failed Nodes:[/]")
        for node_result in result.node_results:
            if node_result.status == ExecutionStatus.FAILED:
                console.print(f"  - {node_result.node_id}: {node_result.error_message}")

    # Save to memory
    memory = get_memory_backend()
    goal = Goal(description=workflow.goal_description)
    entry_id = memory.save_workflow_run(goal, workflow, result)
    console.print(f"\n[dim]Saved to memory: {entry_id}[/]")


@app.command("plan-and-run")
def plan_and_run(
    goal: str = typer.Argument(..., help="Natural language description of your goal"),
    service: Optional[list[str]] = typer.Option(
        None, "--service", "-s", help="Target service(s)"
    ),
    environment: Optional[str] = typer.Option(
        None, "--env", "-e", help="Environment (prod/staging/dev)"
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Simulate execution"
    ),
    mock: bool = typer.Option(
        False, "--mock", help="Use mock LLM"
    ),
) -> None:
    """
    Plan and execute a workflow in one step.

    Example:
        autoops plan-and-run "Check why login API is slow" --service auth-api
    """
    console.print(Panel.fit(
        f"[bold blue]Goal:[/] {goal}",
        title="AutoOps Architect - Plan & Run",
    ))

    # Parse environment
    env = Environment.UNKNOWN
    if environment:
        try:
            env = Environment(environment.lower())
        except ValueError:
            pass

    # Create Goal
    goal_obj = Goal(
        description=goal,
        services=list(service) if service else [],
        environment=env,
    )

    # Plan
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Generating workflow...", total=None)

        try:
            planner = get_planner(mock=mock)
            memory = get_memory_backend()
            workflow = planner.plan_sync(goal_obj)
            progress.update(task, completed=True)
        except Exception as e:
            progress.update(task, completed=True)
            console.print(f"[red]Error: {e}[/]")
            raise typer.Exit(1)

    console.print(f"\n[green]Generated:[/] {workflow.name} ({len(workflow.nodes)} steps)")

    # Show steps
    console.print("\n[bold]Planned Steps:[/]")
    for i, node in enumerate(workflow.topological_sort(), 1):
        console.print(f"  {i}. {node.name}")

    console.print()

    if dry_run:
        console.print("[yellow]Dry-run mode: simulating execution[/]")

    # Execute
    console.print("[bold]Executing...[/]")
    executor = get_executor(dry_run=dry_run)

    def on_status(node_id: str, status: ExecutionStatus, result=None):
        icon = "✅" if status == ExecutionStatus.SUCCESS else (
            "❌" if status == ExecutionStatus.FAILED else "⏳"
        )
        if status in (ExecutionStatus.SUCCESS, ExecutionStatus.FAILED):
            console.print(f"  {icon} {node_id}")

    executor.add_status_callback(on_status)

    result = executor.execute_sync(workflow)

    # Summary
    console.print()
    if result.overall_status == ExecutionStatus.SUCCESS:
        console.print("[green bold]Workflow completed successfully![/]")
    else:
        console.print(f"[red bold]Workflow {result.overall_status.value}[/]")

    # Save
    entry_id = memory.save_workflow_run(goal_obj, workflow, result)
    console.print(f"[dim]Memory entry: {entry_id}[/]")


@app.command()
def history(
    limit: int = typer.Option(10, "--limit", "-n", help="Number of entries to show"),
    search: Optional[str] = typer.Option(None, "--search", "-q", help="Search keywords"),
) -> None:
    """
    Show workflow execution history.

    Example:
        autoops history --search "5xx errors"
    """
    memory = get_memory_backend()

    if search:
        keywords = search.split()
        entries = memory.search(keywords=keywords, limit=limit)
        console.print(f"[bold]Search results for:[/] {search}\n")
    else:
        entries = memory.list_entries(limit=limit)
        console.print("[bold]Recent workflow runs:[/]\n")

    if not entries:
        console.print("[dim]No entries found.[/]")
        return

    # Create table
    table = Table(show_header=True)
    table.add_column("ID", style="dim")
    table.add_column("Goal", max_width=40)
    table.add_column("Status")
    table.add_column("Nodes")
    table.add_column("Date")

    for entry in entries:
        status_style = "green" if entry.outcome_status == "success" else "red"
        table.add_row(
            entry.id[:12],
            entry.goal_description[:40] + ("..." if len(entry.goal_description) > 40 else ""),
            f"[{status_style}]{entry.outcome_status}[/]",
            f"{entry.success_count}/{entry.node_count}",
            entry.created_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)


@app.command()
def tools(
    show_disabled: bool = typer.Option(False, "--all", "-a", help="Show disabled tools"),
) -> None:
    """
    List available tools.

    Example:
        autoops tools --all
    """
    registry = create_default_registry()
    info = registry.get_tool_info()

    console.print("[bold]Available Tools:[/]\n")

    table = Table(show_header=True)
    table.add_column("ID")
    table.add_column("Description")
    table.add_column("Status")

    for tool in info:
        if not show_disabled and not tool["enabled"]:
            continue

        status = "[green]enabled[/]" if tool["enabled"] else "[dim]disabled[/]"
        table.add_row(tool["id"], tool["description"][:50], status)

    console.print(table)


@app.command()
def validate(
    workflow_file: Path = typer.Argument(..., help="Path to workflow file"),
) -> None:
    """
    Validate a workflow file.

    Example:
        autoops validate workflow.json
    """
    if not workflow_file.exists():
        console.print(f"[red]File not found: {workflow_file}[/]")
        raise typer.Exit(1)

    content = workflow_file.read_text()

    try:
        if workflow_file.suffix in (".yaml", ".yml"):
            workflow = WorkflowGraph.from_yaml(content)
        else:
            data = json.loads(content)
            workflow = WorkflowGraph.model_validate(data)

        console.print(f"[green]Valid workflow:[/] {workflow.name}")
        console.print(f"  Nodes: {len(workflow.nodes)}")
        console.print(f"  Edges: {len(workflow.edges)}")

        # Check with planner
        planner = get_planner(mock=True)
        issues = planner.validate_workflow(workflow)

        if issues:
            console.print("\n[yellow]Warnings:[/]")
            for issue in issues:
                console.print(f"  - {issue}")
        else:
            console.print("\n[green]No issues found.[/]")

    except Exception as e:
        console.print(f"[red]Validation failed: {e}[/]")
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show version information."""
    from autoops_architect import __version__

    console.print(f"AutoOps Architect v{__version__}")


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
