# cfn-tool

A CLI to manage AWS CloudFormation stacks and templates, created to help engineers create CFN templates, estimate costs, generate architecture diagrams, and deploy infrastructure — all from one tool.

Inspired by [rain](https://github.com/aws-cloudformation/rain), with live cost estimation and architecture diagram generation powered by [MCP](https://modelcontextprotocol.io/).

## Install (macOS)

```bash
# One-liner: installs cfn-tool, Graphviz, uvx, shell completions, and PATH setup
./install.sh

# Or manual install
pip3 install ./cfn-tool
```

The install script automatically handles:
- Python package installation
- Graphviz (required for `cfn diagram`)
- uv/uvx (required for MCP server connections)
- Shell completions (zsh/bash)
- PATH configuration

## Commands

### Template Operations

Work with templates offline — no AWS credentials needed.

```bash
cfn lint template.yaml                            # Lint with cfn-lint rules
cfn fmt template.yaml                             # Format/normalize YAML in place
cfn fmt template.yaml -o out.json --format json   # Convert YAML → JSON
cfn diff base.yaml updated.yaml                   # Colored diff between templates
cfn tree template.yaml                            # Resource dependency tree
cfn merge base.yaml overlay.yaml -o merged.yaml   # Merge multiple templates
```

### Cost Estimation

Preview estimated monthly costs before deploying. Fetches live prices from the
[AWS Pricing MCP Server](https://awslabs.github.io/mcp/servers/aws-pricing-mcp-server)
when `uvx` is available, with static fallback estimates otherwise.

```bash
cfn cost template.yaml                  # Cost preview for a new stack
cfn cost template.yaml -s my-stack      # Compare new vs existing resources
cfn cost template.yaml -r eu-west-1     # Region-specific pricing
```

Output includes:
- Per-resource cost breakdown with NEW / existing status
- Calculation method (e.g. "On-Demand hourly rate × 730 hrs/mo")
- Source indicator: `live` (MCP API) / `est.` (fallback) / `?` (unknown)
- Links to AWS pricing documentation
- Resolves `!Ref` parameter defaults for accurate lookups

### Architecture Diagrams

Generate PNG architecture diagrams from templates via the
[AWS Diagram MCP Server](https://awslabs.github.io/mcp/servers/aws-diagram-mcp-server).
Auto-installs Graphviz if missing.

```bash
cfn diagram template.yaml              # Generate diagram as PNG
cfn diagram template.yaml -o my-arch   # Custom output filename
```

Resources are grouped into clusters by AWS service, with connections
derived from `!Ref`, `Fn::GetAtt`, and `DependsOn`.

### Stack Operations

Manage CloudFormation stacks. Requires AWS credentials (`aws configure` or env vars).

```bash
cfn create my-stack template.yaml -p Env=prod -c CAPABILITY_IAM
cfn update my-stack template.yaml -p Env=staging
cfn deploy my-stack template.yaml -c CAPABILITY_IAM   # Upsert + wait + cost preview
cfn deploy my-stack template.yaml --skip-cost          # Skip cost preview
cfn delete my-stack                                    # Delete with confirmation
cfn list                                               # List all stacks
cfn list -s CREATE_COMPLETE -s UPDATE_COMPLETE         # Filter by status
cfn describe my-stack                                  # Status, outputs, parameters
cfn cat my-stack                                       # Fetch template from running stack
cfn logs my-stack                                      # Event log table
cfn logs my-stack -n 100                               # Last 100 events
cfn watch my-stack                                     # Live event stream until complete
cfn validate template.yaml                             # Validate against AWS API
cfn info                                               # Current account, ARN, region
```

### Shell Completions

Tab completion for all commands, options, and arguments.

```bash
cfn completions zsh     # Install zsh completions (default on macOS)
cfn completions bash    # Install bash completions
cfn completions fish    # Install fish completions
```

### Global Options

```bash
cfn --version                       # Show version
cfn <command> --region us-west-2    # Override AWS region
cfn <command> --help                # Help for any command
```

## MCP Server Integration

cfn-tool connects to MCP servers as a client for live pricing and diagram generation.
No configuration needed — it spawns the servers automatically via `uvx`.

| Feature | MCP Server | What it does |
|---------|-----------|-------------|
| `cfn cost` | `awslabs.aws-pricing-mcp-server` | Real-time pricing from AWS Price List API |
| `cfn diagram` | `awslabs.aws-diagram-mcp-server` | PNG diagram generation via Python diagrams DSL |

cfn-tool also exposes itself as an MCP server (`cfn-mcp`) so AI assistants can
call its operations as tools.

## Requirements

- Python 3.9+
- AWS credentials configured (`aws configure` or environment variables)
- Graphviz — for `cfn diagram` (auto-installed by `install.sh`)
- uvx — for live pricing and diagrams (auto-installed by `install.sh`)

## License

MIT
