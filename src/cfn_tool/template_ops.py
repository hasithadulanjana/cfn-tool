"""Template operations: fmt, diff, tree, merge."""

import json
import sys
from difflib import unified_diff
from pathlib import Path

import yaml
from rich.console import Console
from rich.syntax import Syntax
from rich.tree import Tree

console = Console()


def _load(path: str) -> dict:
    """Load a YAML or JSON CloudFormation template."""
    text = Path(path).read_text()
    try:
        from cfn_tool.yaml_loader import load_yaml
        return load_yaml(text)
    except Exception:
        return json.loads(text)


def _detect_format(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in (".json",):
        return "json"
    return "yaml"


def fmt_template(path: str, output: str | None = None, to_format: str | None = None):
    """Format/convert a CloudFormation template (like rain fmt)."""
    data = _load(path)
    fmt = to_format or _detect_format(output or path)

    if fmt == "json":
        formatted = json.dumps(data, indent=2, default=str)
    else:
        formatted = yaml.dump(data, default_flow_style=False, sort_keys=False, allow_unicode=True)

    if output:
        Path(output).write_text(formatted)
        console.print(f"[green]✓[/green] Formatted template written to [bold]{output}[/bold]")
    else:
        # Overwrite in place
        Path(path).write_text(formatted)
        console.print(f"[green]✓[/green] Formatted [bold]{path}[/bold] in place")


def diff_templates(path_a: str, path_b: str):
    """Diff two CloudFormation templates (like rain diff)."""
    # Normalize both to sorted YAML for consistent comparison
    data_a = _load(path_a)
    data_b = _load(path_b)
    yaml_a = yaml.dump(data_a, default_flow_style=False, sort_keys=True).splitlines(keepends=True)
    yaml_b = yaml.dump(data_b, default_flow_style=False, sort_keys=True).splitlines(keepends=True)

    diff = list(unified_diff(yaml_a, yaml_b, fromfile=path_a, tofile=path_b))
    if not diff:
        console.print("[green]✓[/green] Templates are identical.")
        return True

    diff_text = "".join(diff)
    syntax = Syntax(diff_text, "diff", theme="monokai")
    console.print(syntax)
    return False


def tree_template(path: str):
    """Show resource dependency tree (like rain tree)."""
    data = _load(path)
    resources = data.get("Resources", {})
    if not resources:
        console.print("[yellow]No resources found in template.[/yellow]")
        return

    # Build dependency map
    deps = {}
    for logical_id, res in resources.items():
        res_deps = set()
        # Explicit DependsOn
        depends_on = res.get("DependsOn", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        res_deps.update(depends_on)
        # Scan for Ref and Fn::GetAtt in properties
        _find_refs(res.get("Properties", {}), res_deps, set(resources.keys()))
        deps[logical_id] = res_deps

    # Find roots (resources nothing depends on via DependsOn)
    all_deps = set()
    for d in deps.values():
        all_deps.update(d)
    roots = [r for r in resources if r not in all_deps]
    if not roots:
        roots = list(resources.keys())

    tree = Tree("[bold]CloudFormation Resources[/bold]")
    visited = set()

    def _add_node(parent, logical_id, depth=0):
        if logical_id in visited or depth > 10:
            return
        visited.add(logical_id)
        res_type = resources.get(logical_id, {}).get("Type", "Unknown")
        node = parent.add(f"[cyan]{logical_id}[/cyan] [dim]({res_type})[/dim]")
        for dep in sorted(deps.get(logical_id, [])):
            if dep in resources:
                _add_node(node, dep, depth + 1)

    for root in sorted(roots):
        _add_node(tree, root)

    # Show any resources not yet visited
    for r in sorted(resources):
        if r not in visited:
            res_type = resources[r].get("Type", "Unknown")
            tree.add(f"[cyan]{r}[/cyan] [dim]({res_type})[/dim]")

    console.print(tree)


def _find_refs(obj, refs: set, resource_names: set):
    """Recursively find Ref and Fn::GetAtt references."""
    if isinstance(obj, dict):
        if "Ref" in obj and obj["Ref"] in resource_names:
            refs.add(obj["Ref"])
        if "Fn::GetAtt" in obj:
            att = obj["Fn::GetAtt"]
            name = att[0] if isinstance(att, list) else att.split(".")[0]
            if name in resource_names:
                refs.add(name)
        for v in obj.values():
            _find_refs(v, refs, resource_names)
    elif isinstance(obj, list):
        for item in obj:
            _find_refs(item, refs, resource_names)


def merge_templates(*paths: str, output: str | None = None):
    """Merge multiple CloudFormation templates (like rain merge)."""
    if len(paths) < 2:
        console.print("[red]Need at least 2 templates to merge.[/red]")
        return

    merged = {}
    # Sections that get merged as dicts
    dict_sections = [
        "Parameters", "Mappings", "Conditions", "Resources",
        "Outputs", "Metadata", "Rules",
    ]
    # Sections that get overwritten (last wins)
    scalar_sections = ["AWSTemplateFormatVersion", "Description", "Transform"]

    for p in paths:
        data = _load(p)
        for section in scalar_sections:
            if section in data:
                merged[section] = data[section]
        for section in dict_sections:
            if section in data:
                if section not in merged:
                    merged[section] = {}
                merged[section].update(data[section])

    fmt = _detect_format(output or paths[0])
    if fmt == "json":
        result = json.dumps(merged, indent=2, default=str)
    else:
        result = yaml.dump(merged, default_flow_style=False, sort_keys=False)

    if output:
        Path(output).write_text(result)
        console.print(f"[green]✓[/green] Merged {len(paths)} templates into [bold]{output}[/bold]")
    else:
        console.print(result)
