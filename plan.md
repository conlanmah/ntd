# Phase 1 Implementation Plan: ntd MVP

## Overview

Build the core CLI for ntd with three commands: `init`, `inventory`, and `apply`. This establishes the foundation for coordinating Terraform infrastructure with NixOS deployments.

## Scope

| Command | Purpose |
|---------|---------|
| `ntd init` | Interactive setup, creates `ntd.toml` |
| `ntd inventory` | Display hosts from config with live status |
| `ntd apply <host>` | Build and deploy NixOS configuration |

**Not in Phase 1**: secrets, provision, destroy, plan (detailed diff)

---

## Project Structure

```
ntd/
├── flake.nix                 # Update: add Python + dependencies
├── ntd/
│   ├── __init__.py
│   ├── __main__.py           # Module entrypoint
│   ├── cli.py                # Click CLI entrypoint
│   ├── config.py             # TOML config parsing
│   ├── terraform.py          # TF output/state queries
│   ├── nixos.py              # Flake discovery, build, deploy
│   └── inventory.py          # Merge TF + NixOS into unified view
└── tests/
    ├── test_config.py
    ├── test_terraform.py
    └── test_nixos.py
```

---

## Implementation Steps

### Step 1: Update flake.nix for Python

Add Python and required libraries to the devShell, plus a wrapper script for the `ntd` command:

```nix
# Add Python with dependencies:
getPython = pkgs: pkgs.python311.withPackages (ps: with ps; [
  click        # CLI framework
  rich         # Pretty terminal output
]);
# Note: tomli not needed - Python 3.11+ has tomllib in stdlib

# Add ntd wrapper script:
makeNtdWrapper = pkgs: pkgs.writeShellScriptBin "ntd" ''
  exec ${getPython pkgs}/bin/python -m ntd "$@"
'';
```

### Step 2: Create Package Structure

Create `ntd/__init__.py` and `ntd/__main__.py`:

```python
# ntd/__main__.py
from ntd.cli import cli

if __name__ == "__main__":
    cli()
```

### Step 3: Config Module (`ntd/config.py`)

Parse and validate `ntd.toml`:

```python
from dataclasses import dataclass
from pathlib import Path
import tomllib

@dataclass
class Host:
    name: str
    terraform_resource: str
    terraform_ip_output: str
    nixos_configuration: str

@dataclass
class Config:
    terraform_path: Path
    nixos_path: Path
    ssh_user: str
    ssh_key: Path
    hosts: list[Host]

def load_config(path: Path = Path("ntd.toml")) -> Config:
    """Load and validate ntd.toml"""
```

### Step 4: Terraform Module (`ntd/terraform.py`)

Query Terraform for host information:

```python
def get_outputs(tf_path: Path) -> dict:
    """Run `terraform output -json` and parse results"""

def get_host_ip(outputs: dict, ip_output_key: str) -> str:
    """Extract IP from terraform outputs using the configured key"""
```

### Step 5: NixOS Module (`ntd/nixos.py`)

Discover and deploy NixOS configurations:

```python
def list_configurations(flake_path: Path) -> list[str]:
    """Run `nix flake show --json` and extract nixosConfigurations"""

def build_configuration(flake_path: Path, config_name: str) -> Path:
    """Build config, return store path"""

def deploy(store_path: Path, host_ip: str, ssh_user: str, ssh_key: Path):
    """Copy closure and activate via nixos-rebuild --target-host"""
```

### Step 6: Inventory Module (`ntd/inventory.py`)

Merge data sources into unified view:

```python
from typing import Literal

@dataclass
class HostStatus:
    name: str
    terraform_resource: str
    nixos_config: str
    ip: str | None
    status: Literal["deployed", "unreachable", "unmanaged"]

def check_host_reachable(ip: str, ssh_user: str, ssh_key: Path) -> bool:
    """Shell out to ssh with short timeout to check connectivity"""

def get_inventory(config: Config) -> list[HostStatus]:
    """Query TF + NixOS + SSH to build current state"""
```

### Step 7: CLI Module (`ntd/cli.py`)

Click-based CLI with three commands:

```python
import click

@click.group()
def cli():
    """ntd - NixOS Terraform Deployer"""

@cli.command()
def init():
    """Interactive setup - discover TF/NixOS and create ntd.toml"""

@cli.command()
def inventory():
    """Show all hosts and their status"""

@cli.command()
@click.argument("host")
def apply(host: str):
    """Deploy NixOS configuration to a host"""
```

---

## Command Details

### `ntd init`

1. Search for `./terraform` or prompt for path
2. Search for `flake.nix` or prompt for path
3. Run `terraform output -json` to show available outputs
4. Run `nix flake show --json` to list nixosConfigurations
5. Prompt user to map outputs to configurations
6. Write `ntd.toml`

### `ntd inventory`

1. Load `ntd.toml`
2. Query Terraform outputs for IPs
3. For each host, attempt SSH connection to check reachability
4. Display table with: HOST, TERRAFORM, NIXOS, IP, STATUS

### `ntd apply <host>`

1. Load `ntd.toml`, find host config
2. Get host IP from Terraform outputs
3. Build NixOS configuration: `nix build .#nixosConfigurations.<name>.config.system.build.toplevel`
4. Copy closure: `nix copy --to ssh://user@host <store-path>`
5. Activate: `ssh user@host nixos-rebuild switch --flake .#<name>`

---

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| SSH approach | Shell out to `ssh` | Uses system SSH config, simpler |
| Config location | `./ntd.toml` only | Project-scoped, simpler |
| CLI invocation | `ntd` command via nix wrapper | Clean UX, nix provides the script |

---

## Verification

1. **Unit tests**: `python -m pytest tests/`
2. **Manual test**:
   - Run `nix develop` to enter shell
   - Run `ntd --help` to verify CLI works
   - Create test `ntd.toml` and run `ntd inventory`
