"""MCP Server that exposes cfn-tool operations as tools."""

import json
import os
import io
from contextlib import redirect_stdout, redirect_stderr

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "cfn-tool",
    description="Manage AWS CloudFormation stacks — lint, deploy, diff, cost estimate, and more",
)


def _capture(fn, *args, **kwargs):
    """Run a function and capture its console output as a string."""
    from rich.console import Console
    buf = io.StringIO()
    console = Console(file=buf, force_terminal=False, no_color=True)
    # Temporarily patch the console in our modules
    import cfn_tool.aws as aws_mod
    original_console = aws_mod.console
    aws_mod.console = console
    try:
        result = fn(*args, **kwargs)
        output = buf.getvalue()
        return output, result
    except Exception as e:
        output = buf.getvalue()
        return f"{output}\nError: {e}", None
    finally:
        aws_mod.console = original_console


@mcp.tool()
def lint_template(template_path: str) -> str:
    """Lint a CloudFormation template for errors and warnings.

    Args:
        template_path: Path to the CloudFormation YAML or JSON template file
    """
    try:
        from cfnlint.config import ConfigMixIn
        from cfnlint.runner import Runner

        args = ConfigMixIn(["--template", template_path])
        r = Runner(args)
        matches = list(r.run())

        if not matches:
            return f"✓ No lint issues found in {template_path}"

        lines = []
        for m in matches:
            lines.append(f"{m.rule.severity.upper()} {m.filename}:{m.linenumber} — {m.message}")
        return "\n".join(lines)
    except ImportError:
        return "Error: cfn-lint is not installed. Run: pip install cfn-lint"
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
def validate_template(template_path: str, region: str | None = None) -> str:
    """Validate a CloudFormation template against the AWS API.

    Args:
        template_path: Path to the CloudFormation template file
        region: AWS region (optional, uses default if not specified)
    """
    from cfn_tool import aws
    output, result = _capture(aws.validate_template, template_path, region)
    return output


@mcp.tool()
def list_stacks(status_filter: str = "", region: str | None = None) -> str:
    """List CloudFormation stacks in your AWS account.

    Args:
        status_filter: Comma-separated status filters (e.g. "CREATE_COMPLETE,UPDATE_COMPLETE"). Empty for defaults.
        region: AWS region (optional)
    """
    from cfn_tool import aws
    statuses = tuple(s.strip() for s in status_filter.split(",") if s.strip()) if status_filter else ()
    output, _ = _capture(aws.list_stacks, statuses, region)
    return output


@mcp.tool()
def describe_stack(stack_name: str, region: str | None = None) -> str:
    """Describe a CloudFormation stack — status, outputs, parameters.

    Args:
        stack_name: Name or ID of the stack
        region: AWS region (optional)
    """
    from cfn_tool import aws
    output, _ = _capture(aws.describe_stack, stack_name, region)
    return output
