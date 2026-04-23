"""CLI entry point for cfn-tool."""

import sys

import click
from botocore.exceptions import ClientError
from rich.console import Console

from cfn_tool import aws

console = Console()

CAPABILITIES = ["CAPABILITY_IAM", "CAPABILITY_NAMED_IAM", "CAPABILITY_AUTO_EXPAND"]


@click.group()
@click.version_option(package_name="cfn-tool")
def cli():
    """cfn — A simple CLI to manage AWS CloudFormation stacks."""


@cli.command("completions")
@click.argument("shell", type=click.Choice(["bash", "zsh", "fish"]), default="zsh")
def completions(shell):
    """Generate shell completion script and install it."""
    import os
    import subprocess

    env_var = f"_{cli.name.upper()}_COMPLETE"
    source_type = {"bash": "bash_source", "zsh": "zsh_source", "fish": "fish_source"}[shell]

    # Generate the completion script
    env = os.environ.copy()
    env[env_var] = source_type
    result = subprocess.run(
        [sys.executable, "-m", "cfn_tool.cli"],
        env=env, capture_output=True, text=True,
    )
    script = result.stdout

    if not script.strip():
        # Fallback: use click's shell_complete module directly
        from click.shell_completion import get_completion_class
        comp_cls = get_completion_class(shell)
        if comp_cls:
            comp = comp_cls(cli, {}, cli.name, f"_{cli.name.upper()}_COMPLETE")
            script = comp.source()

    if not script.strip():
        console.print(f"[red]✗[/red] Failed to generate completion script for {shell}")
        sys.exit(1)

    # Determine install location
    home = os.path.expanduser("~")
    if shell == "zsh":
        comp_dir = os.path.join(home, ".zfunc")
        os.makedirs(comp_dir, exist_ok=True)
        comp_file = os.path.join(comp_dir, "_cfn")
        with open(comp_file, "w") as f:
            f.write(script)
        # Ensure .zshrc has fpath and compinit
        zshrc = os.path.join(home, ".zshrc")
        zshrc_content = ""
        if os.path.exists(zshrc):
            with open(zshrc) as f:
                zshrc_content = f.read()
        lines_to_add = []
        if ".zfunc" not in zshrc_content:
            lines_to_add.append('fpath=(~/.zfunc $fpath)')
        if "compinit" not in zshrc_content:
            lines_to_add.append('autoload -Uz compinit && compinit')
        if lines_to_add:
            with open(zshrc, "a") as f:
                f.write("\n# cfn-tool completions\n")
                for line in lines_to_add:
                    f.write(line + "\n")
        console.print(f"[green]✓[/green] Zsh completions installed to {comp_file}")
        console.print("  Run [bold]source ~/.zshrc[/bold] or open a new terminal.")

    elif shell == "bash":
        comp_dir = os.path.join(home, ".bash_completions")
        os.makedirs(comp_dir, exist_ok=True)
        comp_file = os.path.join(comp_dir, "cfn.bash")
        with open(comp_file, "w") as f:
            f.write(script)
        bashrc = os.path.join(home, ".bashrc")
        source_line = f"source {comp_file}"
        bashrc_content = ""
        if os.path.exists(bashrc):
            with open(bashrc) as f:
                bashrc_content = f.read()
        if source_line not in bashrc_content:
            with open(bashrc, "a") as f:
                f.write(f"\n# cfn-tool completions\n{source_line}\n")
        console.print(f"[green]✓[/green] Bash completions installed to {comp_file}")
        console.print("  Run [bold]source ~/.bashrc[/bold] or open a new terminal.")

    elif shell == "fish":
        comp_dir = os.path.join(home, ".config", "fish", "completions")
        os.makedirs(comp_dir, exist_ok=True)
        comp_file = os.path.join(comp_dir, "cfn.fish")
        with open(comp_file, "w") as f:
            f.write(script)
        console.print(f"[green]✓[/green] Fish completions installed to {comp_file}")


@cli.command()
@click.argument("template", type=click.Path(exists=True))
def lint(template):
    """Lint a CloudFormation template using cfn-lint."""
    try:
        import cfnlint
        from cfnlint import decode, runner
    except ImportError:
        console.print("[red]cfn-lint is not installed. Run: pip install cfn-lint[/red]")
        sys.exit(1)

    from cfnlint.config import ConfigMixIn
    from cfnlint.runner import Runner

    args = ConfigMixIn(["--template", template])
    r = Runner(args)
    matches = list(r.run())

    if not matches:
        console.print(f"[green]✓[/green] No lint issues found in [bold]{template}[/bold]")
        sys.exit(0)

    for m in matches:
        level = "red" if m.rule.severity == "error" else "yellow"
        console.print(f"[{level}]{m.rule.severity.upper()}[/{level}] {m.filename}:{m.linenumber} — {m.message}")

    sys.exit(1 if any(m.rule.severity == "error" for m in matches) else 0)


@cli.command()
@click.argument("template", type=click.Path(exists=True))
@click.option("--region", "-r", help="AWS region")
def validate(template, region):
    """Validate a template against the AWS CloudFormation API."""
    ok = aws.validate_template(template, region)
    sys.exit(0 if ok else 1)


@cli.command()
@click.argument("stack-name")
@click.argument("template", type=click.Path(exists=True))
@click.option("--param", "-p", multiple=True, help="Parameters as KEY=VALUE")
@click.option("--capability", "-c", multiple=True, type=click.Choice(CAPABILITIES), help="IAM capabilities")
@click.option("--region", "-r", help="AWS region")
def create(stack_name, template, param, capability, region):
    """Create a new CloudFormation stack."""
    result = aws.create_stack(stack_name, template, param, capability, region)
    sys.exit(0 if result else 1)


@cli.command()
@click.argument("stack-name")
@click.argument("template", type=click.Path(exists=True))
@click.option("--param", "-p", multiple=True, help="Parameters as KEY=VALUE")
@click.option("--capability", "-c", multiple=True, type=click.Choice(CAPABILITIES), help="IAM capabilities")
@click.option("--region", "-r", help="AWS region")
def update(stack_name, template, param, capability, region):
    """Update an existing CloudFormation stack."""
    result = aws.update_stack(stack_name, template, param, capability, region)
    sys.exit(0 if result else 1)


@cli.command()
@click.argument("stack-name")
@click.option("--region", "-r", help="AWS region")
def delete(stack_name, region):
    """Delete a CloudFormation stack."""
    if not click.confirm(f"Delete stack '{stack_name}'?"):
        console.print("[dim]Aborted.[/dim]")
        return
    ok = aws.delete_stack(stack_name, region)
    sys.exit(0 if ok else 1)


@cli.command("list")
@click.option("--status", "-s", multiple=True, help="Filter by stack status")
@click.option("--region", "-r", help="AWS region")
def list_stacks(status, region):
    """List CloudFormation stacks."""
    aws.list_stacks(status, region)


@cli.command()
@click.argument("stack-name")
@click.option("--region", "-r", help="AWS region")
def describe(stack_name, region):
    """Describe a CloudFormation stack (status, outputs, params)."""
    aws.describe_stack(stack_name, region)


@cli.command()
@click.argument("stack-name")
@click.argument("template", type=click.Path(exists=True))
@click.option("--param", "-p", multiple=True, help="Parameters as KEY=VALUE")
@click.option("--capability", "-c", multiple=True, type=click.Choice(CAPABILITIES), help="IAM capabilities")
@click.option("--region", "-r", help="AWS region")
@click.option("--skip-cost", is_flag=True, help="Skip cost estimation preview")
def deploy(stack_name, template, param, capability, region, skip_cost):
    """Deploy a stack (create or update) and wait for completion."""
    if not skip_cost:
        from cfn_tool.cost import estimate_costs
        _new, _existing, confirmed = estimate_costs(template, stack_name, region)
        if not confirmed:
            console.print("[dim]Deploy aborted.[/dim]")
            sys.exit(0)
    aws.deploy_stack(stack_name, template, param, capability, region)


@cli.command()
@click.argument("template", type=click.Path(exists=True))
@click.option("--stack-name", "-s", default=None, help="Existing stack name to compare against")
@click.option("--region", "-r", help="AWS region")
def cost(template, stack_name, region):
    """Preview estimated monthly costs for resources in a template."""
    from cfn_tool.cost import estimate_costs
    estimate_costs(template, stack_name, region)


# --- Template operations ---

@cli.command()
@click.argument("template", type=click.Path(exists=True))
@click.option("--output", "-o", help="Output file (default: format in place)")
@click.option("--format", "to_format", type=click.Choice(["yaml", "json"]), help="Output format")
def fmt(template, output, to_format):
    """Format a CloudFormation template (normalize YAML/JSON)."""
    from cfn_tool.template_ops import fmt_template
    fmt_template(template, output, to_format)


@cli.command()
@click.argument("template_a", type=click.Path(exists=True))
@click.argument("template_b", type=click.Path(exists=True))
def diff(template_a, template_b):
    """Compare two CloudFormation templates."""
    from cfn_tool.template_ops import diff_templates
    same = diff_templates(template_a, template_b)
    sys.exit(0 if same else 1)


@cli.command()
@click.argument("template", type=click.Path(exists=True))
def tree(template):
    """Show resource dependency tree for a template."""
    from cfn_tool.template_ops import tree_template
    tree_template(template)


@cli.command()
@click.argument("templates", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--output", "-o", help="Output file (default: print to stdout)")
def merge(templates, output):
    """Merge two or more CloudFormation templates."""
    from cfn_tool.template_ops import merge_templates
    merge_templates(*templates, output=output)


@cli.command()
@click.argument("template", type=click.Path(exists=True))
@click.option("--output", "-o", default=None, help="Output filename (without extension)")
def diagram(template, output):
    """Generate an architecture diagram from a CloudFormation template."""
    from cfn_tool.diagram import generate_diagram
    result = generate_diagram(template, output)
    sys.exit(0 if result else 1)


# --- AWS operations ---

@cli.command()
@click.argument("stack-name")
@click.option("--region", "-r", help="AWS region")
def cat(stack_name, region):
    """Get the CloudFormation template from a running stack."""
    body = aws.get_stack_template(stack_name, region)
    if body:
        from rich.syntax import Syntax
        lang = "json" if body.strip().startswith("{") else "yaml"
        console.print(Syntax(body, lang, theme="monokai"))


@cli.command()
@click.argument("stack-name")
@click.option("--limit", "-n", default=50, help="Max number of events")
@click.option("--region", "-r", help="AWS region")
def logs(stack_name, limit, region):
    """Show the event log for a stack."""
    aws.get_stack_events(stack_name, limit, region)


@cli.command()
@click.option("--region", "-r", help="AWS region")
def info(region):
    """Show your current AWS account and region configuration."""
    aws.get_account_info(region)


@cli.command()
@click.argument("stack-name")
@click.option("--region", "-r", help="AWS region")
@click.option("--interval", "-i", default=5, help="Refresh interval in seconds")
def watch(stack_name, region, interval):
    """Display a live updating view of stack events."""
    import time
    seen = set()
    try:
        while True:
            cf = aws._client(region)
            try:
                resp = cf.describe_stack_events(StackName=stack_name)
                events = resp.get("StackEvents", [])
                new_events = []
                for e in reversed(events):
                    eid = e["EventId"]
                    if eid not in seen:
                        seen.add(eid)
                        new_events.append(e)
                for e in new_events:
                    status = e.get("ResourceStatus", "")
                    color = "green" if "COMPLETE" in status else "red" if "FAILED" in status else "yellow"
                    console.print(
                        f"[dim]{e.get('Timestamp', '')}[/dim] "
                        f"[{color}]{status}[/{color}] "
                        f"[cyan]{e.get('LogicalResourceId', '')}[/cyan] "
                        f"[dim]{e.get('ResourceType', '')}[/dim] "
                        f"{e.get('ResourceStatusReason', '')}"
                    )
                # Stop if stack reached a terminal state
                stack_resp = cf.describe_stacks(StackName=stack_name)
                stack_status = stack_resp["Stacks"][0]["StackStatus"]
                if stack_status.endswith("_COMPLETE") or stack_status.endswith("_FAILED"):
                    console.print(f"\n[bold]Final status: {stack_status}[/bold]")
                    break
            except ClientError as e:
                console.print(f"[red]✗[/red] {e.response['Error']['Message']}")
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped watching.[/dim]")
