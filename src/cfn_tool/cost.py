"""Cost estimation using AWS Pricing MCP Server."""

import asyncio
import json
import shutil
import time

import boto3
from botocore.exceptions import ClientError
from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.prompt import Confirm
from rich.table import Table
from rich.text import Text

console = Console()

# CFN resource type -> Pricing API service code + default filters
RESOURCE_PRICING = {
    "AWS::EC2::Instance": {
        "service_code": "AmazonEC2",
        "default_filters": [
            {"Field": "instanceType", "Value": "t3.micro", "Type": "EQUALS"},
            {"Field": "operatingSystem", "Value": "Linux", "Type": "EQUALS"},
            {"Field": "tenancy", "Value": "Shared", "Type": "EQUALS"},
            {"Field": "preInstalledSw", "Value": "NA", "Type": "EQUALS"},
            {"Field": "capacitystatus", "Value": "Used", "Type": "EQUALS"},
        ],
        "hours": 730,
        "calc_desc": "On-Demand hourly rate × 730 hrs/mo",
        "docs_url": "https://aws.amazon.com/ec2/pricing/on-demand/",
    },
    "AWS::RDS::DBInstance": {
        "service_code": "AmazonRDS",
        "default_filters": [
            {"Field": "instanceType", "Value": "db.t3.micro", "Type": "EQUALS"},
            {"Field": "databaseEngine", "Value": "MySQL", "Type": "EQUALS"},
            {"Field": "deploymentOption", "Value": "Single-AZ", "Type": "EQUALS"},
        ],
        "hours": 730,
        "calc_desc": "On-Demand hourly rate × 730 hrs/mo (Single-AZ)",
        "docs_url": "https://aws.amazon.com/rds/pricing/",
    },
    "AWS::EC2::NatGateway": {
        "service_code": "AmazonEC2",
        "default_filters": [
            {"Field": "productFamily", "Value": "NAT Gateway", "Type": "EQUALS"},
        ],
        "hours": 730,
        "calc_desc": "NAT Gateway hourly charge × 730 hrs/mo (excl. data processing)",
        "docs_url": "https://aws.amazon.com/vpc/pricing/",
    },
    "AWS::ElasticLoadBalancingV2::LoadBalancer": {
        "service_code": "AWSELB",
        "default_filters": [
            {"Field": "productFamily", "Value": "Load Balancer-Application", "Type": "EQUALS"},
        ],
        "hours": 730,
        "calc_desc": "ALB hourly charge × 730 hrs/mo (excl. LCU usage)",
        "docs_url": "https://aws.amazon.com/elasticloadbalancing/pricing/",
    },
    "AWS::Lambda::Function": {
        "service_code": "AWSLambda",
        "default_filters": [
            {"Field": "productFamily", "Value": "Serverless", "Type": "EQUALS"},
            {"Field": "groupDescription", "Value": "AWS Lambda Duration", "Type": "EQUALS"},
        ],
        "hours": 730,
        "calc_desc": "GB-second rate × assumed 1M invocations @ 128MB/200ms",
        "docs_url": "https://aws.amazon.com/lambda/pricing/",
    },
    "AWS::S3::Bucket": {
        "service_code": "AmazonS3",
        "default_filters": [
            {"Field": "productFamily", "Value": "Storage", "Type": "EQUALS"},
            {"Field": "storageClass", "Value": "General Purpose", "Type": "EQUALS"},
        ],
        "quantity_gb": 10,
        "calc_desc": "S3 Standard per-GB rate × 10 GB baseline",
        "docs_url": "https://aws.amazon.com/s3/pricing/",
    },
    "AWS::DynamoDB::Table": {
        "service_code": "AmazonDynamoDB",
        "default_filters": [
            {"Field": "productFamily", "Value": "Amazon DynamoDB PayPerRequest Throughput", "Type": "EQUALS"},
        ],
        "quantity_requests": 1000000,
        "calc_desc": "On-demand read/write request unit price × 1M requests baseline",
        "docs_url": "https://aws.amazon.com/dynamodb/pricing/on-demand/",
    },
    "AWS::ElastiCache::CacheCluster": {
        "service_code": "AmazonElastiCache",
        "default_filters": [
            {"Field": "instanceType", "Value": "cache.t3.micro", "Type": "EQUALS"},
            {"Field": "cacheEngine", "Value": "Redis", "Type": "EQUALS"},
        ],
        "hours": 730,
        "calc_desc": "Node hourly rate × 730 hrs/mo",
        "docs_url": "https://aws.amazon.com/elasticache/pricing/",
    },
    "AWS::EC2::Volume": {
        "service_code": "AmazonEC2",
        "default_filters": [
            {"Field": "productFamily", "Value": "Storage", "Type": "EQUALS"},
            {"Field": "volumeApiName", "Value": "gp3", "Type": "EQUALS"},
        ],
        "quantity_gb": 20,
        "calc_desc": "EBS gp3 per-GB/mo rate × 20 GB baseline",
        "docs_url": "https://aws.amazon.com/ebs/pricing/",
    },
    "AWS::EC2::EIP": {
        "service_code": "AmazonEC2",
        "default_filters": [
            {"Field": "productFamily", "Value": "IP Address", "Type": "EQUALS"},
        ],
        "hours": 730,
        "calc_desc": "Elastic IP hourly charge × 730 hrs/mo (when idle)",
        "docs_url": "https://aws.amazon.com/ec2/pricing/on-demand/#Elastic_IP_Addresses",
    },
    "AWS::KMS::Key": {
        "service_code": "awskms",
        "default_filters": [
            {"Field": "productFamily", "Value": "Key Management Service", "Type": "EQUALS"},
        ],
        "calc_desc": "Monthly key storage fee per CMK",
        "docs_url": "https://aws.amazon.com/kms/pricing/",
    },
    "AWS::Route53::HostedZone": {
        "service_code": "AmazonRoute53",
        "default_filters": [
            {"Field": "productFamily", "Value": "DNS Zone", "Type": "EQUALS"},
        ],
        "calc_desc": "Fixed monthly charge per hosted zone",
        "docs_url": "https://aws.amazon.com/route53/pricing/",
    },
    "AWS::SecretsManager::Secret": {
        "service_code": "AWSSecretsManager",
        "default_filters": [
            {"Field": "productFamily", "Value": "Secret", "Type": "EQUALS"},
        ],
        "calc_desc": "Monthly per-secret storage fee",
        "docs_url": "https://aws.amazon.com/secrets-manager/pricing/",
    },
    "AWS::SQS::Queue": {
        "service_code": "AWSQueueService",
        "default_filters": [
            {"Field": "productFamily", "Value": "Queue", "Type": "EQUALS"},
        ],
        "calc_desc": "Per-request pricing × assumed 1M requests/mo",
        "docs_url": "https://aws.amazon.com/sqs/pricing/",
    },
    "AWS::SNS::Topic": {
        "service_code": "AmazonSNS",
        "default_filters": [
            {"Field": "productFamily", "Value": "Message Delivery", "Type": "EQUALS"},
        ],
        "calc_desc": "Per-publish pricing × assumed 1M publishes/mo",
        "docs_url": "https://aws.amazon.com/sns/pricing/",
    },
    "AWS::Kinesis::Stream": {
        "service_code": "AmazonKinesis",
        "default_filters": [
            {"Field": "productFamily", "Value": "Kinesis Streams", "Type": "EQUALS"},
        ],
        "hours": 730,
        "calc_desc": "Shard hour rate × 730 hrs/mo × 1 shard",
        "docs_url": "https://aws.amazon.com/kinesis/data-streams/pricing/",
    },
    "AWS::CloudFront::Distribution": {
        "service_code": "AmazonCloudFront",
        "default_filters": [
            {"Field": "productFamily", "Value": "Request", "Type": "EQUALS"},
        ],
        "calc_desc": "Request pricing + assumed 100 GB data transfer/mo",
        "docs_url": "https://aws.amazon.com/cloudfront/pricing/",
    },
}

# Resources that are always free
FREE_RESOURCES = {
    "AWS::IAM::Role", "AWS::IAM::Policy", "AWS::IAM::User",
    "AWS::IAM::InstanceProfile", "AWS::IAM::Group",
    "AWS::EC2::VPC", "AWS::EC2::Subnet", "AWS::EC2::InternetGateway",
    "AWS::EC2::RouteTable", "AWS::EC2::Route",
    "AWS::EC2::SecurityGroup", "AWS::EC2::SubnetRouteTableAssociation",
    "AWS::EC2::VPCGatewayAttachment",
    "AWS::ECS::Cluster", "AWS::ECS::TaskDefinition",
    "AWS::AutoScaling::AutoScalingGroup", "AWS::AutoScaling::LaunchConfiguration",
    "AWS::CloudFormation::Stack", "AWS::CloudFormation::WaitCondition",
    "AWS::SSM::Parameter", "AWS::CertificateManager::Certificate",
    "AWS::Cognito::UserPool", "AWS::ElasticBeanstalk::Environment",
}

# Fallback when MCP server is unavailable
FALLBACK_COSTS = {
    "AWS::EC2::Instance": 8.47, "AWS::RDS::DBInstance": 12.41,
    "AWS::RDS::DBCluster": 29.20, "AWS::EC2::NatGateway": 32.40,
    "AWS::ElasticLoadBalancingV2::LoadBalancer": 16.20,
    "AWS::Lambda::Function": 0.20, "AWS::S3::Bucket": 0.23,
    "AWS::DynamoDB::Table": 1.25, "AWS::ElastiCache::CacheCluster": 11.52,
    "AWS::EC2::EIP": 3.60, "AWS::EC2::Volume": 1.60,
    "AWS::EFS::FileSystem": 3.00, "AWS::Route53::HostedZone": 0.50,
    "AWS::KMS::Key": 1.00, "AWS::SecretsManager::Secret": 0.40,
    "AWS::SNS::Topic": 0.50, "AWS::SQS::Queue": 0.40,
    "AWS::CloudFront::Distribution": 8.50, "AWS::Kinesis::Stream": 10.80,
    "AWS::CodePipeline::Pipeline": 1.00, "AWS::WAFv2::WebACL": 5.00,
}

# Fallback descriptions for resources only in FALLBACK_COSTS
FALLBACK_DESCRIPTIONS = {
    "AWS::RDS::DBCluster": ("Aurora cluster hourly rate (writer instance)", "https://aws.amazon.com/rds/aurora/pricing/"),
    "AWS::EFS::FileSystem": ("EFS Standard per-GB/mo × 10 GB baseline", "https://aws.amazon.com/efs/pricing/"),
    "AWS::CodePipeline::Pipeline": ("Fixed monthly charge per active pipeline", "https://aws.amazon.com/codepipeline/pricing/"),
    "AWS::WAFv2::WebACL": ("Monthly Web ACL fee + per-rule charge", "https://aws.amazon.com/waf/pricing/"),
}


# ---------------------------------------------------------------------------
# MCP Client — connects to awslabs.aws-pricing-mcp-server via stdio
# ---------------------------------------------------------------------------

async def _call_mcp_tool(tool_name: str, arguments: dict) -> dict | None:
    """Spawn the pricing MCP server and call a tool on it."""
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    uvx_path = shutil.which("uvx")
    if not uvx_path:
        return None

    server_params = StdioServerParameters(
        command=uvx_path,
        args=["awslabs.aws-pricing-mcp-server@latest"],
        env={
            "FASTMCP_LOG_LEVEL": "ERROR",
            "AWS_PROFILE": "default",
            "AWS_REGION": "us-east-1",
            "PATH": "/usr/local/bin:/usr/bin:/bin",
        },
    )

    try:
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                # result.content is a list of TextContent objects
                if result.content:
                    text = result.content[0].text
                    try:
                        return json.loads(text)
                    except (json.JSONDecodeError, TypeError):
                        return {"raw": text}
    except Exception:
        return None


def _mcp_call_sync(tool_name: str, arguments: dict) -> dict | None:
    """Synchronous wrapper around the async MCP client."""
    try:
        return asyncio.run(_call_mcp_tool(tool_name, arguments))
    except Exception:
        return None


def _enrich_filters(res_type: str, properties: dict, filters: list, param_defaults: dict) -> list:
    """Override default filters with actual values from template properties."""
    if not properties:
        return filters

    if res_type == "AWS::EC2::Instance":
        itype = _resolve_prop(properties.get("InstanceType"), param_defaults)
        if isinstance(itype, str):
            filters = [f for f in filters if f.get("Field") != "instanceType"]
            filters.append({"Field": "instanceType", "Value": itype, "Type": "EQUALS"})

    elif res_type == "AWS::RDS::DBInstance":
        db_class = _resolve_prop(properties.get("DBInstanceClass"), param_defaults)
        if isinstance(db_class, str):
            filters = [f for f in filters if f.get("Field") != "instanceType"]
            filters.append({"Field": "instanceType", "Value": db_class, "Type": "EQUALS"})
        engine = _resolve_prop(properties.get("Engine"), param_defaults)
        if isinstance(engine, str):
            engine_map = {
                "mysql": "MySQL", "postgres": "PostgreSQL", "mariadb": "MariaDB",
                "aurora-mysql": "Aurora MySQL", "aurora-postgresql": "Aurora PostgreSQL",
            }
            mapped = engine_map.get(engine.lower(), engine)
            filters = [f for f in filters if f.get("Field") != "databaseEngine"]
            filters.append({"Field": "databaseEngine", "Value": mapped, "Type": "EQUALS"})

    elif res_type == "AWS::ElastiCache::CacheCluster":
        node_type = _resolve_prop(properties.get("CacheNodeType"), param_defaults)
        if isinstance(node_type, str):
            filters = [f for f in filters if f.get("Field") != "instanceType"]
            filters.append({"Field": "instanceType", "Value": node_type, "Type": "EQUALS"})

    elif res_type == "AWS::EC2::Volume":
        vol_type = _resolve_prop(properties.get("VolumeType"), param_defaults)
        if isinstance(vol_type, str):
            filters = [f for f in filters if f.get("Field") != "volumeApiName"]
            filters.append({"Field": "volumeApiName", "Value": vol_type, "Type": "EQUALS"})

    return filters


def _get_price_via_mcp(res_type: str, properties: dict, region: str | None = None, param_defaults: dict | None = None) -> float | None:
    """Get price for a resource type via the MCP pricing server."""
    pricing_info = RESOURCE_PRICING.get(res_type)
    if not pricing_info:
        return None

    filters = list(pricing_info["default_filters"])
    filters = _enrich_filters(res_type, properties, filters, param_defaults or {})

    output_options = {
        "pricing_terms": ["OnDemand"],
        "exclude_free_products": True,
    }

    args = {
        "service_code": pricing_info["service_code"],
        "region": region or "us-east-1",
        "filters": filters,
        "output_options": output_options,
        "max_results": 5,
    }

    console.log(f"  [dim]Fetching price for {res_type}...[/dim]")
    result = _mcp_call_sync("get_pricing", args)

    if not result:
        return None

    return _extract_price(result, pricing_info)


def _extract_price(result: dict, pricing_info: dict) -> float | None:
    """Extract a monthly price from MCP get_pricing response."""
    try:
        raw = result.get("raw", "") if "raw" in result else json.dumps(result)

        # The MCP server returns pricing data that may contain price per unit
        # Try to find USD price in the response
        if isinstance(raw, str):
            data = json.loads(raw) if raw.startswith("{") or raw.startswith("[") else {}
        else:
            data = result

        # Walk through the response looking for price values
        price = _find_price_in_data(data)
        if price is not None and price > 0:
            hours = pricing_info.get("hours", 0)
            quantity_gb = pricing_info.get("quantity_gb", 0)
            quantity_req = pricing_info.get("quantity_requests", 0)
            if hours:
                return round(price * hours, 2)
            elif quantity_gb:
                return round(price * quantity_gb, 2)
            elif quantity_req:
                return round(price * quantity_req, 2)
            return round(price, 2)
    except Exception:
        pass
    return None


def _find_price_in_data(data, depth=0) -> float | None:
    """Recursively search for a USD price in nested pricing data."""
    if depth > 15:
        return None
    if isinstance(data, dict):
        # Direct price field
        usd = data.get("pricePerUnit", {}).get("USD") if isinstance(data.get("pricePerUnit"), dict) else None
        if usd:
            try:
                val = float(usd)
                if val > 0:
                    return val
            except (ValueError, TypeError):
                pass
        # Check for USD directly
        if "USD" in data:
            try:
                val = float(data["USD"])
                if val > 0:
                    return val
            except (ValueError, TypeError):
                pass
        for v in data.values():
            found = _find_price_in_data(v, depth + 1)
            if found is not None:
                return found
    elif isinstance(data, list):
        for item in data:
            found = _find_price_in_data(item, depth + 1)
            if found is not None:
                return found
    elif isinstance(data, str):
        # Try parsing stringified JSON
        if data.startswith("{") or data.startswith("["):
            try:
                return _find_price_in_data(json.loads(data), depth + 1)
            except Exception:
                pass
    return None


# ---------------------------------------------------------------------------
# Template parsing & existing stack check
# ---------------------------------------------------------------------------

def _get_existing_resources(stack_name: str, region: str | None = None) -> set[str]:
    """Get logical resource IDs from an existing stack."""
    cf = boto3.client("cloudformation", region_name=region) if region else boto3.client("cloudformation")
    try:
        paginator = cf.get_paginator("list_stack_resources")
        existing = set()
        for page in paginator.paginate(StackName=stack_name):
            for r in page.get("StackResourceSummaries", []):
                existing.add(r["LogicalResourceId"])
        return existing
    except ClientError:
        return set()


def _parse_template(path: str) -> tuple[dict, dict]:
    """Load template and return (Resources dict, parameter defaults dict)."""
    with open(path) as f:
        text = f.read()
    if not text.strip():
        console.print("[red]✗[/red] Template file is empty.")
        return {}, {}
    data = None
    try:
        from cfn_tool.yaml_loader import load_yaml
        data = load_yaml(text)
    except Exception:
        pass
    if data is None:
        try:
            data = json.loads(text)
        except Exception:
            pass
    if not isinstance(data, dict):
        console.print("[red]✗[/red] Failed to parse template. Ensure it's valid YAML or JSON.")
        return {}, {}

    # Build a map of parameter name -> default value
    param_defaults = {}
    for pname, pval in (data.get("Parameters") or {}).items():
        if isinstance(pval, dict) and "Default" in pval:
            param_defaults[pname] = pval["Default"]

    return data.get("Resources", {}), param_defaults


def _resolve_prop(value, param_defaults: dict):
    """If a property value looks like a parameter ref, resolve to its default."""
    if isinstance(value, str) and value in param_defaults:
        return param_defaults[value]
    return value


# ---------------------------------------------------------------------------
# Main estimate function
# ---------------------------------------------------------------------------

def estimate_costs(
    template_path: str,
    stack_name: str | None = None,
    region: str | None = None,
) -> tuple[float, float, bool]:
    """
    Show cost estimate table for resources in a template.
    Uses MCP pricing server first, falls back to static prices.

    Returns (new_cost, existing_cost, user_confirmed).
    """
    # --- Phase 1: Parse template with spinner ---
    with console.status("[bold cyan]📄 Parsing template...", spinner="dots") as status:
        resources, param_defaults = _parse_template(template_path)
        time.sleep(0.3)  # brief pause so the spinner is visible

    if not resources:
        console.print("[yellow]No resources found in template.[/yellow]")
        return 0.0, 0.0, True

    res_count = len(resources)
    console.print(f"  [green]✓[/green] Found [bold]{res_count}[/bold] resource(s) in template\n")

    # --- Phase 2: Check existing stack ---
    existing_ids = set()
    if stack_name:
        with console.status(f"[bold cyan]🔍 Checking existing stack [bold]{stack_name}[/bold]...", spinner="dots"):
            existing_ids = _get_existing_resources(stack_name, region)
            time.sleep(0.2)
        if existing_ids:
            console.print(f"  [green]✓[/green] Stack exists with [bold]{len(existing_ids)}[/bold] resource(s)\n")
        else:
            console.print(f"  [yellow]⚠[/yellow] Stack [bold]{stack_name}[/bold] not found — treating all as new\n")

    # --- Phase 3: Fetch prices with progress bar ---
    mcp_available = shutil.which("uvx") is not None
    source = "MCP" if mcp_available else "fallback"

    # Collect pricing results
    price_results = {}  # logical_id -> (monthly, price_source, calc_desc, docs_url)

    # Separate billable resources from free ones
    billable = []
    for logical_id, res in sorted(resources.items()):
        res_type = res.get("Type", "Unknown")
        if res_type not in FREE_RESOURCES:
            billable.append((logical_id, res))

    if mcp_available and billable:
        console.print("  [bold cyan]💰 Fetching live prices from AWS Pricing MCP Server...[/bold cyan]\n")
        progress = Progress(
            SpinnerColumn("dots"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=30),
            TaskProgressColumn(),
            console=console,
        )
        with progress:
            task = progress.add_task("Pricing lookup", total=len(billable))
            for logical_id, res in billable:
                res_type = res.get("Type", "Unknown")
                properties = res.get("Properties", {}) or {}
                short_type = res_type.split("::")[-1]
                progress.update(task, description=f"[cyan]{short_type}[/cyan]")

                monthly = None
                price_source = ""
                calc_desc = ""
                docs_url = ""
                pricing_info = RESOURCE_PRICING.get(res_type)

                if pricing_info:
                    monthly = _get_price_via_mcp(res_type, properties, region, param_defaults)
                    if monthly is not None:
                        price_source = "live"
                        calc_desc = pricing_info.get("calc_desc", "")
                        docs_url = pricing_info.get("docs_url", "")

                if monthly is None and res_type in FALLBACK_COSTS:
                    monthly = FALLBACK_COSTS[res_type]
                    price_source = "est."
                    if pricing_info:
                        calc_desc = pricing_info.get("calc_desc", "")
                        docs_url = pricing_info.get("docs_url", "")
                    elif res_type in FALLBACK_DESCRIPTIONS:
                        calc_desc, docs_url = FALLBACK_DESCRIPTIONS[res_type]

                if monthly is None:
                    monthly = 0.0
                    price_source = "?"
                    calc_desc = "No pricing data available"

                price_results[logical_id] = (monthly, price_source, calc_desc, docs_url)
                progress.advance(task)

        console.print()
    elif billable:
        # No MCP — use fallback with a quick spinner
        with console.status("[bold cyan]💰 Calculating estimated costs...", spinner="dots"):
            for logical_id, res in billable:
                res_type = res.get("Type", "Unknown")
                pricing_info = RESOURCE_PRICING.get(res_type)
                monthly = FALLBACK_COSTS.get(res_type, 0.0)
                calc_desc = ""
                docs_url = ""
                if pricing_info:
                    calc_desc = pricing_info.get("calc_desc", "")
                    docs_url = pricing_info.get("docs_url", "")
                elif res_type in FALLBACK_DESCRIPTIONS:
                    calc_desc, docs_url = FALLBACK_DESCRIPTIONS[res_type]
                price_results[logical_id] = (monthly, "est.", calc_desc, docs_url)
            time.sleep(0.5)
        console.print()

    # --- Phase 4: Build and display the table ---
    table = Table(
        title="💰 Estimated Monthly Cost Preview",
        show_footer=True,
        title_style="bold white",
        border_style="bright_blue",
        header_style="bold bright_cyan",
    )
    table.add_column("Resource", style="cyan", footer_style="bold")
    table.add_column("Type", style="blue")
    table.add_column("Status", style="magenta")
    table.add_column("Est. Monthly", style="green", justify="right", footer_style="bold green")
    table.add_column("Calculation", style="dim")
    table.add_column("Src", style="dim")

    new_total = 0.0
    existing_total = 0.0
    unknown_types = []
    docs_links = []

    for logical_id, res in sorted(resources.items()):
        res_type = res.get("Type", "Unknown")
        is_existing = logical_id in existing_ids
        status = "[dim]existing[/dim]" if is_existing else "[bold yellow]NEW[/bold yellow]"

        if res_type in FREE_RESOURCES:
            table.add_row(logical_id, res_type.split("::")[-1], status, "[dim]free[/dim]", "No charge", "")
            continue

        monthly, price_source, calc_desc, docs_url = price_results.get(logical_id, (0.0, "?", "", ""))

        if monthly == 0.0 and price_source == "?":
            unknown_types.append(res_type)

        if is_existing:
            existing_total += monthly
        else:
            new_total += monthly

        if docs_url:
            docs_links.append((res_type.split("::")[-1], docs_url))

        cost_str = f"${monthly:.2f}" if monthly > 0 else "[dim]free[/dim]"
        table.add_row(logical_id, res_type.split("::")[-1], status, cost_str, calc_desc, price_source)

    grand_total = new_total + existing_total
    table.columns[0].footer = "TOTAL"
    table.columns[3].footer = f"${grand_total:.2f}/mo"

    console.print(table)

    # --- Phase 5: Summary panel ---
    summary_lines = []
    if new_total > 0:
        summary_lines.append(f"[bold yellow]⬆ New resources:[/bold yellow]      ${new_total:.2f}/mo")
    if existing_total > 0:
        summary_lines.append(f"[dim]● Existing resources:[/dim]  ${existing_total:.2f}/mo")
    summary_lines.append(f"[bold white]● Total estimated:[/bold white]     [bold green]${grand_total:.2f}/mo[/bold green]")

    if unknown_types:
        unique = sorted(set(unknown_types))
        summary_lines.append(f"\n[yellow]⚠ No pricing data for:[/yellow] {', '.join(unique)}")

    if docs_links:
        summary_lines.append("\n[bold]📚 Pricing docs:[/bold]")
        seen_urls = set()
        for name, url in docs_links:
            if url not in seen_urls:
                seen_urls.add(url)
                summary_lines.append(f"  [cyan]{name}[/cyan]: {url}")

    if source == "MCP":
        summary_lines.append("\n[dim]Src: live = AWS Pricing API via MCP │ est. = static fallback │ ? = no data[/dim]")
    else:
        summary_lines.append("\n[dim]Using estimated fallback prices. Install uvx for live pricing.[/dim]")

    panel = Panel(
        "\n".join(summary_lines),
        title="[bold]Cost Summary[/bold]",
        border_style="bright_blue",
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
    console.print()

    # --- Phase 6: Confirmation ---
    if new_total > 0:
        confirmed = Confirm.ask(
            f"[bold]New resources will add ~${new_total:.2f}/mo. Proceed?[/bold]",
            default=True,
        )
    else:
        confirmed = Confirm.ask(
            "[bold]No new costs. Proceed?[/bold]",
            default=True,
        )

    return new_total, existing_total, confirmed
