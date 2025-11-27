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


# Template commands subgroup
templates_app = typer.Typer(help="Manage workflow templates")
app.add_typer(templates_app, name="templates")


@templates_app.command("list")
def templates_list(
    category: Optional[str] = typer.Option(None, "--category", "-c", help="Filter by category"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="Filter by source (builtin/project/user)"),
    show_source: bool = typer.Option(False, "--show-source", help="Show template source column"),
) -> None:
    """
    List available workflow templates.

    Templates are loaded from multiple sources:
    - builtin: Package-provided templates
    - project: .autoops/templates/ in your project
    - user: ~/.autoops/templates/

    Example:
        autoops templates list
        autoops templates list --category error_investigation
        autoops templates list --source user --show-source
    """
    from autoops_architect.templates.loader import (
        TemplateDiscovery,
        create_registry_with_file_templates,
    )

    discovery = TemplateDiscovery()

    if source:
        # Show templates from specific source only
        templates_by_source = discovery.list_templates_by_source()
        if source not in templates_by_source:
            console.print(f"[red]Unknown source: {source}. Valid: builtin, project, user[/]")
            raise typer.Exit(1)
        templates = [
            {"template": t, "source": source}
            for t in templates_by_source.get(source, [])
        ]
    else:
        # Get all templates with source info
        templates = []
        for source_name, source_templates in discovery.list_templates_by_source().items():
            for t in source_templates:
                templates.append({"template": t, "source": source_name})

    # Also include code-defined built-in templates
    from autoops_architect.templates.registry import get_builtin_templates
    code_templates = get_builtin_templates()
    code_ids = {t["template"].id for t in templates}
    for t in code_templates:
        if t.id not in code_ids:
            templates.append({"template": t, "source": "builtin-code"})

    if category:
        templates = [t for t in templates if t["template"].category == category]

    if not templates:
        console.print("[dim]No templates found.[/]")
        return

    console.print("[bold]Available Templates:[/]\n")

    table = Table(show_header=True)
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Category")
    if show_source:
        table.add_column("Source")
    table.add_column("Description", max_width=40)

    for item in templates:
        t = item["template"]
        desc = t.description[:40] + "..." if len(t.description) > 40 else t.description
        row = [t.id, t.name, t.category]
        if show_source:
            row.append(item["source"])
        row.append(desc)
        table.add_row(*row)

    console.print(table)

    # Show source info
    sources = discovery.get_template_sources()
    if sources:
        console.print("\n[dim]Template sources:[/]")
        for name, path in sources.items():
            console.print(f"  {name}: {path}")


@templates_app.command("show")
def templates_show(
    template_id: str = typer.Argument(..., help="Template ID to show"),
    show_yaml: bool = typer.Option(False, "--yaml", "-y", help="Show template YAML"),
) -> None:
    """
    Show details of a specific template.

    Example:
        autoops templates show error-rate-investigation
        autoops templates show k8s-pod-crash-investigation --yaml
    """
    from autoops_architect.templates.loader import create_registry_with_file_templates

    registry = create_registry_with_file_templates()
    template = registry.get(template_id)

    if template is None:
        console.print(f"[red]Template not found: {template_id}[/]")
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold]{template.name}[/]\n\n"
        f"{template.description}\n\n"
        f"[dim]Category:[/] {template.category}\n"
        f"[dim]Tags:[/] {', '.join(template.tags)}\n"
        f"[dim]Version:[/] {template.version}\n"
        f"[dim]Author:[/] {template.author or 'N/A'}\n"
        f"[dim]Nodes:[/] {len(template.nodes)}",
        title=f"Template: {template_id}",
    ))

    if show_yaml:
        import yaml
        template_data = template.model_dump(mode="json")
        yaml_output = yaml.dump(template_data, default_flow_style=False, sort_keys=False)
        console.print("\n[bold]Template YAML:[/]")
        console.print(Syntax(yaml_output, "yaml"))
    else:
        # Show nodes
        console.print("\n[bold]Workflow Steps:[/]")
        tree = Tree("[bold]Nodes[/]")
        for node in template.nodes:
            tree.add(f"[{node.type.value}] {node.name}")
        console.print(tree)

        # Show edges
        if template.edges:
            console.print("\n[bold]Edges:[/]")
            for edge in template.edges:
                condition = f" [dim](when: {edge.condition})[/]" if edge.condition else ""
                console.print(f"  {edge.from_node_id} -> {edge.to_node_id}{condition}")


@templates_app.command("use")
def templates_use(
    template_id: str = typer.Argument(..., help="Template ID to use"),
    goal: str = typer.Option(..., "--goal", "-g", help="Goal description"),
    service: Optional[str] = typer.Option(None, "--service", "-s", help="Target service"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Output file"),
    run_workflow: bool = typer.Option(False, "--run", "-r", help="Execute the workflow after creating"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Dry run execution"),
) -> None:
    """
    Create a workflow from a template.

    Example:
        autoops templates use error-rate-investigation -g "Check checkout errors" -s checkout-api
        autoops templates use k8s-pod-crash-investigation -g "Pod crashes" -s my-pod --run
    """
    from autoops_architect.templates.loader import create_registry_with_file_templates

    registry = create_registry_with_file_templates()
    template = registry.get(template_id)

    if template is None:
        console.print(f"[red]Template not found: {template_id}[/]")
        raise typer.Exit(1)

    # Create goal
    goal_obj = Goal(
        description=goal,
        services=[service] if service else [],
    )

    # Instantiate workflow
    workflow = template.instantiate(
        goal_description=goal,
        service=service,
    )

    console.print(f"[green]Created workflow from template:[/] {template.name}")
    console.print(f"[dim]ID: {workflow.id}[/]")
    console.print(f"[dim]Nodes: {len(workflow.nodes)}[/]")

    # Show steps
    console.print("\n[bold]Workflow Steps:[/]")
    for i, node in enumerate(workflow.topological_sort(), 1):
        console.print(f"  {i}. {node.name}")

    # Save to file if requested
    if output:
        output.write_text(workflow.model_dump_json(indent=2))
        console.print(f"\n[green]Saved to:[/] {output}")

    # Run if requested
    if run_workflow:
        console.print("\n[bold]Executing workflow...[/]")
        executor = get_executor(dry_run=dry_run)

        def on_status(node_id: str, status: ExecutionStatus, result=None):
            icon = "✅" if status == ExecutionStatus.SUCCESS else (
                "❌" if status == ExecutionStatus.FAILED else "⏳"
            )
            if status in (ExecutionStatus.SUCCESS, ExecutionStatus.FAILED):
                console.print(f"  {icon} {node_id}")

        executor.add_status_callback(on_status)
        result = executor.execute_sync(workflow)

        if result.overall_status == ExecutionStatus.SUCCESS:
            console.print("\n[green bold]Workflow completed successfully![/]")
        else:
            console.print(f"\n[red bold]Workflow {result.overall_status.value}[/]")

        # Save to memory
        memory = get_memory_backend()
        entry_id = memory.save_workflow_run(goal_obj, workflow, result)
        console.print(f"[dim]Memory entry: {entry_id}[/]")


@templates_app.command("init")
def templates_init(
    location: str = typer.Option("project", "--location", "-l", help="Where to create: project or user"),
) -> None:
    """
    Initialize a templates directory.

    Creates the templates directory structure for custom templates.

    Example:
        autoops templates init
        autoops templates init --location user
    """
    from autoops_architect.templates.loader import (
        get_project_templates_dir,
        get_user_templates_dir,
    )

    if location == "user":
        templates_dir = get_user_templates_dir()
    else:
        # Create .autoops/templates in current directory
        templates_dir = Path.cwd() / ".autoops" / "templates"
        templates_dir.mkdir(parents=True, exist_ok=True)

    console.print(f"[green]Templates directory created:[/] {templates_dir}")

    # Create a sample template file
    sample_template = templates_dir / "sample-investigation.yaml"
    if not sample_template.exists():
        sample_content = """# Sample Investigation Template
# Customize this template for your team's needs

id: sample-investigation
name: Sample Investigation
description: A sample template to customize
category: general
tags:
  - sample
  - template

author: your-team
version: "1.0"

parameters:
  service: "{{service}}"
  duration: "1h"

nodes:
  - id: collect-logs
    name: "Collect logs for {{service}}"
    description: "Gather relevant logs"
    type: log_collection
    tool: log_collector
    params:
      service: "{{service}}"
      duration: "{{duration}}"

  - id: analyze
    name: "Analyze collected data"
    description: "Analyze the gathered data"
    type: analysis
    tool: analysis
    params:
      analysis_type: "general"

  - id: summary
    name: "Generate summary"
    description: "Create investigation summary"
    type: summary
    tool: summary
    params:
      format: "markdown"

edges:
  - from_node_id: collect-logs
    to_node_id: analyze
  - from_node_id: analyze
    to_node_id: summary
"""
        sample_template.write_text(sample_content)
        console.print(f"[green]Sample template created:[/] {sample_template}")

    console.print("\n[dim]Add your custom YAML templates to this directory.[/]")


@templates_app.command("export")
def templates_export(
    template_id: str = typer.Argument(..., help="Template ID to export"),
    output: Path = typer.Option(..., "--output", "-o", help="Output file path"),
    format: str = typer.Option("yaml", "--format", "-f", help="Output format: yaml or json"),
) -> None:
    """
    Export a template to a file.

    Export existing templates to customize or share.

    Example:
        autoops templates export error-rate-investigation -o my-template.yaml
    """
    from autoops_architect.templates.loader import (
        TemplateLoader,
        create_registry_with_file_templates,
    )

    registry = create_registry_with_file_templates()
    template = registry.get(template_id)

    if template is None:
        console.print(f"[red]Template not found: {template_id}[/]")
        raise typer.Exit(1)

    TemplateLoader.save_template(template, output, format=format)
    console.print(f"[green]Template exported to:[/] {output}")


@templates_app.command("validate")
def templates_validate(
    template_file: Path = typer.Argument(..., help="Template file to validate"),
) -> None:
    """
    Validate a template file.

    Check that a YAML/JSON template file is valid.

    Example:
        autoops templates validate my-template.yaml
    """
    from autoops_architect.templates.loader import TemplateLoader

    if not template_file.exists():
        console.print(f"[red]File not found: {template_file}[/]")
        raise typer.Exit(1)

    try:
        template = TemplateLoader.load_from_file(template_file)
        console.print(f"[green]Valid template:[/] {template.name}")
        console.print(f"  ID: {template.id}")
        console.print(f"  Category: {template.category}")
        console.print(f"  Nodes: {len(template.nodes)}")
        console.print(f"  Edges: {len(template.edges)}")

        # Basic validation
        node_ids = {n.id for n in template.nodes}
        issues = []

        for edge in template.edges:
            if edge.from_node_id not in node_ids:
                issues.append(f"Edge references unknown node: {edge.from_node_id}")
            if edge.to_node_id not in node_ids:
                issues.append(f"Edge references unknown node: {edge.to_node_id}")

        if issues:
            console.print("\n[yellow]Warnings:[/]")
            for issue in issues:
                console.print(f"  - {issue}")
        else:
            console.print("\n[green]No issues found.[/]")

    except Exception as e:
        console.print(f"[red]Validation failed: {e}[/]")
        raise typer.Exit(1)


@templates_app.command("categories")
def templates_categories() -> None:
    """
    List all template categories.

    Example:
        autoops templates categories
    """
    from autoops_architect.templates.loader import create_registry_with_file_templates

    registry = create_registry_with_file_templates()
    templates = registry.list()

    categories = {}
    for t in templates:
        if t.category not in categories:
            categories[t.category] = 0
        categories[t.category] += 1

    console.print("[bold]Template Categories:[/]\n")

    for category, count in sorted(categories.items()):
        console.print(f"  {category}: {count} template(s)")


# Memory commands subgroup
memory_app = typer.Typer(help="Manage workflow memory")
app.add_typer(memory_app, name="memory")


@memory_app.command("list")
def memory_list(
    limit: int = typer.Option(20, "--limit", "-n", help="Number of entries to show"),
) -> None:
    """
    List memory entries.

    Example:
        autoops memory list --limit 10
    """
    memory = get_memory_backend()
    entries = memory.list_entries(limit=limit)

    if not entries:
        console.print("[dim]No memory entries found.[/]")
        return

    console.print(f"[bold]Memory Entries ({len(entries)}):[/]\n")

    table = Table(show_header=True)
    table.add_column("ID", style="dim")
    table.add_column("Goal", max_width=35)
    table.add_column("Status")
    table.add_column("Nodes")
    table.add_column("Date")

    for entry in entries:
        status_style = "green" if entry.outcome_status == "success" else "red"
        table.add_row(
            entry.id[:12],
            entry.goal_description[:35] + ("..." if len(entry.goal_description) > 35 else ""),
            f"[{status_style}]{entry.outcome_status}[/]",
            f"{entry.success_count}/{entry.node_count}",
            entry.created_at.strftime("%Y-%m-%d %H:%M"),
        )

    console.print(table)


@memory_app.command("show")
def memory_show(
    entry_id: str = typer.Argument(..., help="Memory entry ID"),
) -> None:
    """
    Show details of a memory entry.

    Example:
        autoops memory show mem-abc123
    """
    memory = get_memory_backend()

    # Search for partial ID match
    entries = memory.list_entries(limit=100)
    entry = None
    for e in entries:
        if e.id.startswith(entry_id) or entry_id in e.id:
            entry = e
            break

    if entry is None:
        console.print(f"[red]Memory entry not found: {entry_id}[/]")
        raise typer.Exit(1)

    status_color = "green" if entry.outcome_status == "success" else "red"

    console.print(Panel(
        f"[bold]Goal:[/] {entry.goal_description}\n\n"
        f"[bold]Status:[/] [{status_color}]{entry.outcome_status}[/]\n"
        f"[bold]Workflow ID:[/] {entry.workflow_id}\n"
        f"[bold]Services:[/] {', '.join(entry.services) if entry.services else 'N/A'}\n"
        f"[bold]Nodes:[/] {entry.success_count} succeeded / {entry.node_count} total\n"
        f"[bold]Duration:[/] {entry.duration_seconds:.2f}s" if entry.duration_seconds else ""
        f"\n[bold]Created:[/] {entry.created_at.strftime('%Y-%m-%d %H:%M:%S')}",
        title=f"Memory Entry: {entry.id}",
    ))

    if entry.outcome_summary:
        console.print(f"\n[bold]Summary:[/]\n{entry.outcome_summary}")


@memory_app.command("delete")
def memory_delete(
    entry_id: str = typer.Argument(..., help="Memory entry ID to delete"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """
    Delete a memory entry.

    Example:
        autoops memory delete mem-abc123
    """
    memory = get_memory_backend()

    if not force:
        confirm = typer.confirm(f"Delete memory entry {entry_id}?")
        if not confirm:
            console.print("[dim]Cancelled.[/]")
            return

    deleted = memory.delete_entry(entry_id)

    if deleted:
        console.print(f"[green]Deleted memory entry: {entry_id}[/]")
    else:
        console.print(f"[red]Memory entry not found: {entry_id}[/]")


@memory_app.command("search")
def memory_search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-n", help="Max results"),
    semantic: bool = typer.Option(False, "--semantic", "-s", help="Use semantic similarity search"),
) -> None:
    """
    Search memory entries.

    Use --semantic for smarter natural language search that understands
    similar concepts (e.g., "slow API" matches "latency issues").

    Example:
        autoops memory search "5xx errors checkout"
        autoops memory search "slow database queries" --semantic
    """
    memory = get_memory_backend()

    if semantic:
        entries = memory.semantic_search(query=query, limit=limit)
        search_type = "Semantic"
    else:
        keywords = query.split()
        entries = memory.search(keywords=keywords, limit=limit)
        search_type = "Keyword"

    if not entries:
        console.print(f"[dim]No results for: {query}[/]")
        return

    console.print(f"[bold]{search_type} search results for:[/] {query}\n")

    for entry in entries:
        status_color = "green" if entry.outcome_status == "success" else "red"
        console.print(f"[dim]{entry.id[:12]}[/] [{status_color}]{entry.outcome_status}[/]")
        console.print(f"  {entry.goal_description[:60]}...")
        console.print(f"  [dim]Relevance: {entry.relevance_score:.0%}[/]")
        console.print()


@memory_app.command("clear")
def memory_clear(
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
) -> None:
    """
    Clear all memory entries.

    Example:
        autoops memory clear --force
    """
    if not force:
        confirm = typer.confirm("Delete ALL memory entries? This cannot be undone.")
        if not confirm:
            console.print("[dim]Cancelled.[/]")
            return

    memory = get_memory_backend()
    entries = memory.list_entries(limit=1000)
    count = 0

    for entry in entries:
        if memory.delete_entry(entry.id):
            count += 1

    console.print(f"[green]Deleted {count} memory entries.[/]")


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="Host to bind to"),
    port: int = typer.Option(8000, "--port", "-p", help="Port to bind to"),
    reload: bool = typer.Option(False, "--reload", "-r", help="Enable auto-reload for development"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Enable debug mode"),
) -> None:
    """
    Start the web UI server.

    This launches a FastAPI application that provides a web interface
    for creating, reviewing, and executing workflows.

    Example:
        autoops serve
        autoops serve --port 3000 --reload
    """
    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]Web dependencies not installed.[/]\n"
            "Install with: pip install autoops-architect[web]"
        )
        raise typer.Exit(1)

    console.print(Panel.fit(
        f"[bold blue]Starting AutoOps Architect Web UI[/]\n\n"
        f"Server: http://{host}:{port}\n"
        f"API Docs: http://{host}:{port}/docs\n"
        f"Debug: {'enabled' if debug else 'disabled'}",
        title="AutoOps Architect",
    ))

    uvicorn.run(
        "autoops_architect.api.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="debug" if debug else "info",
    )


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
