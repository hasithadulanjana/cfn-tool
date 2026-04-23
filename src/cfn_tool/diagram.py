"""Generate architecture diagrams from CloudFormation templates."""

import json
import os
import shutil

from rich.console import Console

console = Console()

# Map CFN resource types to Python diagrams package class names
# Format: "AWS::Service::Resource" -> ("module_path", "ClassName")
CFN_TO_DIAGRAM = {
    # Compute
    "AWS::EC2::Instance": ("aws.compute", "EC2"),
    "AWS::Lambda::Function": ("aws.compute", "Lambda"),
    "AWS::ECS::Service": ("aws.compute", "ECS"),
    "AWS::ECS::Cluster": ("aws.compute", "ECS"),
    "AWS::ECS::TaskDefinition": ("aws.compute", "ECS"),
    "AWS::AutoScaling::AutoScalingGroup": ("aws.compute", "AutoScaling"),
    "AWS::ElasticBeanstalk::Environment": ("aws.compute", "ElasticBeanstalk"),
    # Storage
    "AWS::S3::Bucket": ("aws.storage", "S3"),
    "AWS::EFS::FileSystem": ("aws.storage", "ElasticFileSystemEFS"),
    "AWS::EC2::Volume": ("aws.storage", "ElasticBlockStoreEBS"),
    # Database
    "AWS::RDS::DBInstance": ("aws.database", "RDS"),
    "AWS::RDS::DBCluster": ("aws.database", "Aurora"),
    "AWS::DynamoDB::Table": ("aws.database", "Dynamodb"),
    "AWS::ElastiCache::CacheCluster": ("aws.database", "ElasticacheCacheNode"),
    "AWS::DocDB::DBCluster": ("aws.database", "DocumentdbMongodbCompatibility"),
    # Networking
    "AWS::EC2::VPC": ("aws.network", "VPC"),
    "AWS::EC2::Subnet": ("aws.network", "PublicSubnet"),
    "AWS::EC2::InternetGateway": ("aws.network", "InternetGateway"),
    "AWS::EC2::NatGateway": ("aws.network", "NATGateway"),
    "AWS::EC2::SecurityGroup": ("aws.network", "Nacl"),
    "AWS::ElasticLoadBalancingV2::LoadBalancer": ("aws.network", "ElbApplicationLoadBalancer"),
    "AWS::ElasticLoadBalancing::LoadBalancer": ("aws.network", "ElbClassicLoadBalancer"),
    "AWS::CloudFront::Distribution": ("aws.network", "CloudFront"),
    "AWS::ApiGateway::RestApi": ("aws.network", "APIGateway"),
    "AWS::ApiGatewayV2::Api": ("aws.network", "APIGateway"),
    "AWS::Route53::HostedZone": ("aws.network", "Route53"),
    "AWS::EC2::EIP": ("aws.network", "ElasticIp"),
    # Security / IAM
    "AWS::IAM::Role": ("aws.security", "IAMRole"),
    "AWS::IAM::Policy": ("aws.security", "IAM"),
    "AWS::IAM::User": ("aws.security", "IAM"),
    "AWS::KMS::Key": ("aws.security", "KeyManagementService"),
    "AWS::CertificateManager::Certificate": ("aws.security", "CertificateManager"),
    "AWS::WAFv2::WebACL": ("aws.security", "WAF"),
    "AWS::SecretsManager::Secret": ("aws.security", "SecretsManager"),
    "AWS::Cognito::UserPool": ("aws.security", "Cognito"),
    # Messaging / Integration
    "AWS::SNS::Topic": ("aws.integration", "SimpleNotificationServiceSns"),
    "AWS::SQS::Queue": ("aws.integration", "SimpleQueueServiceSqs"),
    "AWS::Events::Rule": ("aws.integration", "Eventbridge"),
    "AWS::StepFunctions::StateMachine": ("aws.integration", "StepFunctions"),
    "AWS::Kinesis::Stream": ("aws.analytics", "KinesisDataStreams"),
    # Monitoring
    "AWS::CloudWatch::Alarm": ("aws.management", "Cloudwatch"),
    "AWS::Logs::LogGroup": ("aws.management", "CloudwatchLogs"),
    # CI/CD
    "AWS::CodeBuild::Project": ("aws.devtools", "Codebuild"),
    "AWS::CodePipeline::Pipeline": ("aws.devtools", "Codepipeline"),
    # Other
    "AWS::SSM::Parameter": ("aws.management", "SystemsManager"),
    "AWS::CloudFormation::Stack": ("aws.management", "Cloudformation"),
}


def _parse_template(path: str) -> tuple[dict, dict]:
    """Load template, return (resources, param_defaults)."""
    with open(path) as f:
        text = f.read()
    try:
        from cfn_tool.yaml_loader import load_yaml
        data = load_yaml(text)
    except Exception:
        data = json.loads(text)
    if not isinstance(data, dict):
        return {}, {}
    param_defaults = {}
    for pname, pval in (data.get("Parameters") or {}).items():
        if isinstance(pval, dict) and "Default" in pval:
            param_defaults[pname] = pval["Default"]
    return data.get("Resources", {}), param_defaults


def _find_refs(obj, resource_names: set) -> set:
    """Recursively find references to other resources."""
    refs = set()
    if isinstance(obj, dict):
        if "Ref" in obj and obj["Ref"] in resource_names:
            refs.add(obj["Ref"])
        if "Fn::GetAtt" in obj:
            att = obj["Fn::GetAtt"]
            name = att[0] if isinstance(att, list) else att.split(".")[0]
            if name in resource_names:
                refs.add(name)
        for v in obj.values():
            refs.update(_find_refs(v, resource_names))
    elif isinstance(obj, list):
        for item in obj:
            refs.update(_find_refs(item, resource_names))
    elif isinstance(obj, str) and obj in resource_names:
        # Our YAML loader turns !Ref X into just "X"
        refs.add(obj)
    return refs


def _build_diagram_code(resources: dict, template_name: str) -> str:
    """Build Python diagrams DSL code from CloudFormation resources."""
    resource_names = set(resources.keys())

    # Collect dependencies
    deps = {}
    for lid, res in resources.items():
        res_deps = set()
        # Explicit DependsOn
        depends_on = res.get("DependsOn", [])
        if isinstance(depends_on, str):
            depends_on = [depends_on]
        res_deps.update(d for d in depends_on if d in resource_names)
        # Refs in properties
        props = res.get("Properties", {}) or {}
        res_deps.update(_find_refs(props, resource_names))
        res_deps.discard(lid)  # no self-refs
        deps[lid] = res_deps

    # Group resources by service category for clusters
    clusters = {}
    standalone = []
    for lid, res in resources.items():
        res_type = res.get("Type", "")
        parts = res_type.split("::")
        if len(parts) >= 3:
            service = parts[1]  # e.g. "EC2", "RDS", "Lambda"
        else:
            service = "Other"
        if service not in clusters:
            clusters[service] = []
        clusters[service].append(lid)

    # Build variable names (sanitize logical IDs)
    var_names = {}
    for lid in resources:
        var_names[lid] = lid[0].lower() + lid[1:]

    # Generate code
    lines = []
    lines.append(f'with Diagram("{template_name}", show=False, direction="LR"):')

    # Create nodes grouped by cluster
    for service, lids in sorted(clusters.items()):
        if len(lids) > 1:
            lines.append(f'    with Cluster("{service}"):')
            indent = "        "
        else:
            indent = "    "

        for lid in lids:
            res_type = resources[lid].get("Type", "Unknown")
            mapping = CFN_TO_DIAGRAM.get(res_type)
            if mapping:
                mod, cls = mapping
                lines.append(f'{indent}{var_names[lid]} = {cls}("{lid}")')
            else:
                # Use a generic node for unmapped types
                short = res_type.split("::")[-1] if "::" in res_type else res_type
                lines.append(f'{indent}{var_names[lid]} = Custom("{lid}\\n({short})", "")')

    # Add connections
    lines.append("")
    for lid, lid_deps in deps.items():
        for dep in sorted(lid_deps):
            if dep in var_names:
                lines.append(f'    {var_names[dep]} >> {var_names[lid]}')

    return "\n".join(lines)


def _ensure_graphviz():
    """Check if Graphviz is installed, offer to install via brew if not."""
    import subprocess
    if shutil.which("dot"):
        return True

    console.print("[yellow]⚠[/yellow] Graphviz is not installed (required for diagram rendering).\n")

    if not shutil.which("brew"):
        console.print("[red]✗[/red] Homebrew not found. Install Graphviz manually:")
        console.print("    brew install graphviz")
        return False

    from rich.prompt import Confirm
    if not Confirm.ask("[bold]Install Graphviz via Homebrew now?[/bold]", default=True):
        console.print("[dim]Skipped. Run [bold]brew install graphviz[/bold] manually.[/dim]")
        return False

    with console.status("[bold cyan]📥 Installing Graphviz...", spinner="dots12"):
        result = subprocess.run(["brew", "install", "graphviz"], capture_output=True, text=True)

    if result.returncode == 0:
        console.print("[green]✓[/green] Graphviz installed successfully.\n")
        return True
    else:
        console.print(f"[red]✗[/red] Installation failed: {result.stderr.strip()}")
        return False


def _render_diagram_direct(code: str, filename: str, output_dir: str) -> str | None:
    """
    Execute the diagrams DSL code directly in-process.
    Returns the output PNG path or None on failure.
    """
    import sys

    # Ensure Graphviz bin is on PATH for the diagrams package
    dot_path = shutil.which("dot")
    if dot_path:
        gv_dir = os.path.dirname(dot_path)
        if gv_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = gv_dir + ":" + os.environ.get("PATH", "")

    try:
        from diagrams import Diagram, Cluster, Edge
        from diagrams.aws import compute, storage, database, network, security
        from diagrams.aws import integration, analytics, management, devtools
        from diagrams.custom import Custom
        # Expose all submodule classes into exec namespace
        ns = {
            "Diagram": Diagram, "Cluster": Cluster, "Edge": Edge, "Custom": Custom,
        }
        for mod in [compute, storage, database, network, security,
                    integration, analytics, management, devtools]:
            for name in dir(mod):
                if not name.startswith("_"):
                    ns[name] = getattr(mod, name)
    except ImportError:
        console.print("[red]✗[/red] diagrams package not installed. Run: pip install diagrams")
        return None

    # Change to output dir so the PNG lands there
    orig_dir = os.getcwd()
    os.makedirs(output_dir, exist_ok=True)
    os.chdir(output_dir)
    try:
        exec(code, ns)  # noqa: S102
    except Exception as e:
        console.print(f"[red]✗[/red] Diagram render failed: {e}")
        return None
    finally:
        os.chdir(orig_dir)

    # diagrams saves as <diagram_title>.png
    # Find the most recently created PNG in output_dir
    pngs = sorted(
        [f for f in os.listdir(output_dir) if f.endswith(".png")],
        key=lambda f: os.path.getmtime(os.path.join(output_dir, f)),
        reverse=True,
    )
    if pngs:
        return os.path.join(output_dir, pngs[0])
    return None


def generate_diagram(
    template_path: str,
    output: str | None = None,
    workspace_dir: str | None = None,
) -> str | None:
    """
    Generate an architecture diagram PNG from a CloudFormation template.
    Renders directly using the diagrams Python package (no MCP server needed).
    """
    import time

    # Phase 0: Check Graphviz
    if not _ensure_graphviz():
        return None

    # Phase 1: Parse template
    with console.status("[bold cyan]📄 Parsing template...", spinner="dots"):
        resources, _ = _parse_template(template_path)
        time.sleep(0.2)

    if not resources:
        console.print("[red]✗[/red] No resources found in template.")
        return None

    console.print(f"  [green]✓[/green] Found [bold]{len(resources)}[/bold] resource(s)\n")

    # Phase 2: Build diagram code
    template_name = os.path.splitext(os.path.basename(template_path))[0]
    filename = output or template_name

    with console.status("[bold cyan]🎨 Building diagram...", spinner="dots"):
        code = _build_diagram_code(resources, template_name)
        time.sleep(0.2)

    console.print("  [green]✓[/green] Diagram code generated\n")
    from rich.syntax import Syntax
    console.print(Syntax(code, "python", theme="monokai", line_numbers=True))
    console.print()

    # Phase 3: Render directly
    out_dir = workspace_dir or os.getcwd()

    with console.status("[bold cyan]🖼️  Rendering diagram...", spinner="dots12"):
        output_path = _render_diagram_direct(code, filename, out_dir)

    if output_path:
        from rich.panel import Panel
        console.print(Panel(
            f"[bold green]✓ Diagram saved to:[/bold green]\n\n  [cyan]{output_path}[/cyan]",
            title="[bold]🖼️  Architecture Diagram[/bold]",
            border_style="bright_blue",
            padding=(1, 2),
        ))
        return output_path
    else:
        # Fallback: save code so user can run it manually
        code_path = os.path.join(out_dir, f"{filename}_diagram.py")
        with open(code_path, "w") as f:
            f.write(code)
        console.print(f"[yellow]⚠[/yellow] Render failed. Code saved to [bold]{code_path}[/bold]")
        console.print(f"  Run manually: [dim]python {code_path}[/dim]")
        return None
