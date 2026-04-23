"""AWS CloudFormation operations via boto3."""

import boto3
import click
from botocore.exceptions import ClientError
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def _client(region: str | None = None):
    return boto3.client("cloudformation", region_name=region) if region else boto3.client("cloudformation")


def _load_template(path: str) -> str:
    with open(path) as f:
        return f.read()


def _parse_params(params: tuple[str, ...]) -> list[dict]:
    """Parse KEY=VALUE parameter pairs."""
    result = []
    for p in params:
        if "=" not in p:
            raise click.BadParameter(f"Parameter must be KEY=VALUE, got: {p}")
        k, v = p.split("=", 1)
        result.append({"ParameterKey": k, "ParameterValue": v})
    return result


def validate_template(path: str, region: str | None = None) -> bool:
    """Validate a CloudFormation template with AWS."""
    cf = _client(region)
    body = _load_template(path)
    with console.status("[bold cyan]🔍 Validating template...", spinner="dots"):
        try:
            cf.validate_template(TemplateBody=body)
        except ClientError as e:
            console.print(f"[red]✗[/red] Validation failed: {e.response['Error']['Message']}")
            return False
    console.print(f"[green]✓[/green] Template [bold]{path}[/bold] is valid.")
    return True


def create_stack(name: str, path: str, params: tuple, capabilities: tuple, region: str | None = None):
    cf = _client(region)
    body = _load_template(path)
    kwargs = dict(StackName=name, TemplateBody=body)
    if params:
        kwargs["Parameters"] = _parse_params(params)
    if capabilities:
        kwargs["Capabilities"] = list(capabilities)
    try:
        resp = cf.create_stack(**kwargs)
        console.print(f"[green]✓[/green] Stack creation initiated: [bold]{resp['StackId']}[/bold]")
        return resp
    except ClientError as e:
        console.print(f"[red]✗[/red] Create failed: {e.response['Error']['Message']}")
        return None


def update_stack(name: str, path: str, params: tuple, capabilities: tuple, region: str | None = None):
    cf = _client(region)
    body = _load_template(path)
    kwargs = dict(StackName=name, TemplateBody=body)
    if params:
        kwargs["Parameters"] = _parse_params(params)
    if capabilities:
        kwargs["Capabilities"] = list(capabilities)
    try:
        resp = cf.update_stack(**kwargs)
        console.print(f"[green]✓[/green] Stack update initiated: [bold]{resp['StackId']}[/bold]")
        return resp
    except ClientError as e:
        msg = e.response["Error"]["Message"]
        if "No updates" in msg:
            console.print("[yellow]⚠[/yellow] No updates to perform.")
        else:
            console.print(f"[red]✗[/red] Update failed: {msg}")
        return None


def delete_stack(name: str, region: str | None = None):
    cf = _client(region)
    try:
        cf.delete_stack(StackName=name)
        console.print(f"[green]✓[/green] Stack [bold]{name}[/bold] deletion initiated.")
        return True
    except ClientError as e:
        console.print(f"[red]✗[/red] Delete failed: {e.response['Error']['Message']}")
        return False


def list_stacks(status_filter: tuple, region: str | None = None):
    cf = _client(region)
    filters = list(status_filter) if status_filter else [
        "CREATE_COMPLETE", "UPDATE_COMPLETE", "CREATE_IN_PROGRESS",
        "UPDATE_IN_PROGRESS", "DELETE_IN_PROGRESS", "ROLLBACK_COMPLETE",
    ]
    with console.status("[bold cyan]📋 Fetching stacks...", spinner="dots"):
        try:
            resp = cf.list_stacks(StackStatusFilter=filters)
            stacks = resp.get("StackSummaries", [])
        except ClientError as e:
            console.print(f"[red]✗[/red] List failed: {e.response['Error']['Message']}")
            return

    if not stacks:
        console.print("[yellow]No stacks found.[/yellow]")
        return
    table = Table(title="☁️  CloudFormation Stacks", border_style="bright_blue", header_style="bold bright_cyan")
    table.add_column("Name", style="cyan")
    table.add_column("Status", style="magenta")
    table.add_column("Created", style="green")
    table.add_column("Updated", style="green")
    for s in stacks:
        status = s["StackStatus"]
        color = "green" if "COMPLETE" in status else "red" if "FAILED" in status else "yellow"
        table.add_row(
            s["StackName"],
            f"[{color}]{status}[/{color}]",
            str(s.get("CreationTime", "")),
            str(s.get("LastUpdatedTime", "")),
        )
    console.print(table)


def describe_stack(name: str, region: str | None = None):
    cf = _client(region)
    with console.status(f"[bold cyan]🔍 Describing stack [bold]{name}[/bold]...", spinner="dots"):
        try:
            resp = cf.describe_stacks(StackName=name)
            stack = resp["Stacks"][0]
        except ClientError as e:
            console.print(f"[red]✗[/red] Describe failed: {e.response['Error']['Message']}")
            return None

    status = stack["StackStatus"]
    color = "green" if "COMPLETE" in status else "red" if "FAILED" in status else "yellow"

    lines = [
        f"[bold]Status:[/bold]   [{color}]{status}[/{color}]",
        f"[bold]Created:[/bold]  {stack.get('CreationTime', 'N/A')}",
        f"[bold]Updated:[/bold]  {stack.get('LastUpdatedTime', 'N/A')}",
    ]
    if stack.get("Outputs"):
        lines.append("\n[bold]Outputs:[/bold]")
        for o in stack["Outputs"]:
            lines.append(f"  [cyan]{o['OutputKey']}[/cyan]: {o['OutputValue']}")
    if stack.get("Parameters"):
        lines.append("\n[bold]Parameters:[/bold]")
        for p in stack["Parameters"]:
            lines.append(f"  [cyan]{p['ParameterKey']}[/cyan]: {p['ParameterValue']}")

    panel = Panel(
        "\n".join(lines),
        title=f"[bold cyan]☁️  {stack['StackName']}[/bold cyan]",
        border_style="bright_blue",
        padding=(1, 2),
    )
    console.print(panel)
    return stack


def wait_for_stack(name: str, operation: str = "create", region: str | None = None):
    """Wait for a stack operation to complete with animated spinner."""
    cf = _client(region)
    waiter_name = f"stack_{operation}_complete"
    try:
        waiter = cf.get_waiter(waiter_name)
        emoji = "🚀" if operation == "create" else "🔄" if operation == "update" else "🗑️"
        with console.status(
            f"[bold cyan]{emoji} Waiting for stack {operation} to complete...",
            spinner="dots12",
        ):
            waiter.wait(StackName=name, WaiterConfig={"Delay": 10, "MaxAttempts": 120})
        console.print(f"[green]✓[/green] Stack {operation} complete.")
        return True
    except Exception as e:
        console.print(f"[red]✗[/red] Wait failed: {e}")
        return False


def deploy_stack(name: str, path: str, params: tuple, capabilities: tuple, region: str | None = None):
    """Create or update a stack (upsert), then wait for completion."""
    cf = _client(region)
    with console.status(f"[bold cyan]🔍 Checking if stack [bold]{name}[/bold] exists...", spinner="dots"):
        try:
            cf.describe_stacks(StackName=name)
            exists = True
        except ClientError:
            exists = False

    if exists:
        console.print(f"  [cyan]↻[/cyan] Stack [bold]{name}[/bold] exists — updating...")
        result = update_stack(name, path, params, capabilities, region)
        if result:
            wait_for_stack(name, "update", region)
    else:
        console.print(f"  [cyan]✦[/cyan] Creating new stack [bold]{name}[/bold]...")
        result = create_stack(name, path, params, capabilities, region)
        if result:
            wait_for_stack(name, "create", region)


def get_stack_template(name: str, region: str | None = None) -> str | None:
    """Fetch the template from a running stack (like rain cat)."""
    cf = _client(region)
    try:
        resp = cf.get_template(StackName=name, TemplateStage="Processed")
        body = resp["TemplateBody"]
        # boto3 may return dict or string depending on format
        if isinstance(body, dict):
            import json
            return json.dumps(body, indent=2)
        return body
    except ClientError as e:
        console.print(f"[red]✗[/red] Failed to get template: {e.response['Error']['Message']}")
        return None


def get_stack_events(name: str, limit: int = 50, region: str | None = None):
    """Show stack events (like rain logs)."""
    cf = _client(region)
    try:
        resp = cf.describe_stack_events(StackName=name)
        events = resp.get("StackEvents", [])[:limit]
        if not events:
            console.print("[yellow]No events found.[/yellow]")
            return
        table = Table(title=f"Events for {name}")
        table.add_column("Timestamp", style="dim")
        table.add_column("Resource", style="cyan")
        table.add_column("Type", style="blue")
        table.add_column("Status", style="magenta")
        table.add_column("Reason", style="red")
        for e in events:
            status = e.get("ResourceStatus", "")
            style = "green" if "COMPLETE" in status else "red" if "FAILED" in status else "yellow"
            table.add_row(
                str(e.get("Timestamp", "")),
                e.get("LogicalResourceId", ""),
                e.get("ResourceType", ""),
                f"[{style}]{status}[/{style}]",
                e.get("ResourceStatusReason", ""),
            )
        console.print(table)
    except ClientError as e:
        console.print(f"[red]✗[/red] Logs failed: {e.response['Error']['Message']}")


def get_account_info(region: str | None = None):
    """Show current AWS account/region info (like rain info)."""
    import boto3
    with console.status("[bold cyan]🔑 Fetching account info...", spinner="dots"):
        sts = boto3.client("sts", region_name=region) if region else boto3.client("sts")
        try:
            identity = sts.get_caller_identity()
            session = boto3.session.Session()
        except Exception as e:
            console.print(f"[red]✗[/red] Failed to get info: {e}")
            return

    panel = Panel(
        f"[bold]Account:[/bold]  [cyan]{identity['Account']}[/cyan]\n"
        f"[bold]ARN:[/bold]      [cyan]{identity['Arn']}[/cyan]\n"
        f"[bold]Region:[/bold]   [cyan]{region or session.region_name or 'not set'}[/cyan]",
        title="[bold cyan]🔑 AWS Identity[/bold cyan]",
        border_style="bright_blue",
        padding=(1, 2),
    )
    console.print(panel)
