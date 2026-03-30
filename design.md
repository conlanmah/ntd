# ntd CLI Design

This document explores how ntd can bridge Terraform infrastructure and NixOS configurations with minimal coupling.

## Problem Statement

Existing tools require tight coupling:
- **Terranix**: Rewrite Terraform in Nix (couples format to Nix)
- **terraform-nixos modules**: Embed NixOS deployment in Terraform (couples deployment to TF)

**Goal**: A thin coordination layer that reads from both systems without requiring structural changes to either.

## Core Concepts

### Inventory as the Bridge

ntd maintains a lightweight inventory that maps Terraform resources to NixOS configurations:

```
┌─────────────────┐         ┌─────────────────┐
│    Terraform    │         │   NixOS Flake   │
│  (provisions)   │         │  (configures)   │
│                 │         │                 │
│  proxmox_vm_qemu│         │ nixosConfigs.*  │
│  outputs.*      │         │                 │
└────────┬────────┘         └────────┬────────┘
         │                           │
         │    ┌─────────────────┐    │
         └───►│  ntd inventory  │◄───┘
              │                 │
              │  vm1:           │
              │    tf: proxmox  │
              │    nix: server1 │
              │    ip: (dynamic)│
              └─────────────────┘
```

### Non-Invasive Discovery

ntd discovers resources by reading existing outputs, not by requiring specific formats:

**From Terraform:**
- Parses `terraform output -json` or reads state directly
- User defines which outputs map to hosts (one-time config)

**From NixOS:**
- Reads flake outputs: `nix flake show --json`
- Discovers `nixosConfigurations.*`

## CLI Commands

### `ntd init`

Interactive setup that creates `ntd.toml` by discovering existing resources:

```bash
$ ntd init
Found Terraform state in ./terraform
Found NixOS flake in ./nixos

Terraform outputs:
  - vm1_ip (string)
  - vm2_ip (string)
  - vms (object)

NixOS configurations:
  - server1
  - server2

Create mapping? [Y/n]
```

### `ntd inventory`

Shows current state by querying both systems:

```bash
$ ntd inventory
HOST      TERRAFORM          NIXOS      IP            STATUS
vm1       proxmox_vm.vm1     server1    192.168.1.10  deployed
vm2       proxmox_vm.vm2     server2    192.168.1.11  config-drift
vm3       proxmox_vm.vm3     -          192.168.1.12  unmanaged
```

### `ntd plan [host]`

Shows what would change without applying:

```bash
$ ntd plan vm1
Infrastructure (Terraform):
  No changes

Configuration (NixOS):
  ~ nginx.conf (modified)
  + prometheus-node-exporter (added)

Secrets:
  ~ api-token.sops.yaml (re-encrypted for new host key)
```

### `ntd apply [host]`

Orchestrated deployment:

```bash
$ ntd apply vm1

Step 1/4: Terraform apply (if infrastructure changes)
  → No infrastructure changes

Step 2/4: Build NixOS configuration
  → Building nixosConfigurations.server1...
  → /nix/store/abc123-nixos-system-server1

Step 3/4: Deploy secrets
  → Decrypting secrets/per-host/vm1.sops.yaml
  → Copying to vm1:/run/secrets

Step 4/4: Activate NixOS
  → Copying closure to vm1
  → Activating configuration
  ✓ Deployed successfully
```

### `ntd provision <name>`

Creates new infrastructure and bootstraps NixOS:

```bash
$ ntd provision webserver --template proxmox-vm --nixos server-base

Step 1/5: Generate host SSH key
  → Created secrets/per-host/webserver.sops.yaml

Step 2/5: Add to Terraform
  → Generated terraform/hosts/webserver.tf

Step 3/5: Terraform apply
  → Creating proxmox_vm_qemu.webserver...
  → IP: 192.168.1.15

Step 4/5: Bootstrap NixOS
  → Installing NixOS on target...

Step 5/5: Deploy configuration
  → Activating nixosConfigurations.webserver
```

### `ntd secrets`

Manage secrets (wraps sops operations):

```bash
$ ntd secrets rotate webserver --type ssh-key
$ ntd secrets edit webserver
$ ntd secrets add webserver api-token
```

### `ntd destroy <host>`

Coordinated teardown:

```bash
$ ntd destroy webserver
This will:
  - Remove Terraform resources for webserver
  - Remove secrets/per-host/webserver.sops.yaml
  - Remove from ntd inventory

Continue? [y/N]
```

## Configuration File

`ntd.toml` - minimal configuration pointing to existing resources:

```toml
[terraform]
path = "./terraform"
# How to extract host information from TF outputs
# Supports JSONPath-like expressions
hosts_from = "output.vms"  # or "resource.proxmox_vm_qemu.*"

[nixos]
path = "./nixos"
# Optional: custom attribute for configurations
# Default: nixosConfigurations
configurations = "nixosConfigurations"

[defaults]
# SSH settings
ssh_user = "root"
ssh_key = "~/.ssh/id_ed25519"

[secrets]
backend = "sops"
path = "./secrets"

# Host mappings (can be auto-discovered or manual)
[[hosts]]
name = "vm1"
terraform_resource = "proxmox_vm_qemu.vm1"
terraform_ip_output = "vm1_ip"  # or JSONPath: "vms.vm1.ip"
nixos_configuration = "server1"

[[hosts]]
name = "vm2"
terraform_resource = "proxmox_vm_qemu.vm2"
terraform_ip_output = "vm2_ip"
nixos_configuration = "server2"
```

## Minimal Coupling Strategy

### What ntd requires from Terraform:

1. **Outputs for host IPs** - Any structure, user maps it in config
2. **SSH access** - Provisioned VMs must be reachable

That's it. No special modules, providers, or structure required.

### What ntd requires from NixOS:

1. **Flake with nixosConfigurations** - Standard flake output
2. **SSH host key path** - For sops-nix integration (optional)

No special modules required. Users can optionally add `ntd.nix` module for tighter integration.

### Optional NixOS Module

For users who want deeper integration:

```nix
# ntd.nix - optional module
{ config, lib, ... }:
{
  options.ntd = {
    enable = lib.mkEnableOption "ntd integration";
    hostName = lib.mkOption { type = lib.types.str; };
  };

  config = lib.mkIf config.ntd.enable {
    # Standardized paths ntd expects
    sops.age.sshKeyPaths = [ "/etc/ssh/ssh_host_ed25519_key" ];

    # Expose metadata for ntd inventory
    environment.etc."ntd/host.json".text = builtins.toJSON {
      name = config.ntd.hostName;
      nixos_version = config.system.nixos.version;
    };
  };
}
```

## Deployment Methods

ntd uses a **pluggable deployer architecture** designed for future extensibility.

### Current Implementation (Built-in)

The initial implementation uses direct SSH and `nixos-rebuild`:

| Method | Use Case | Parallel | Rollback |
|--------|----------|----------|----------|
| `builtin` (default) | Simple, single host | No | Manual |

This keeps dependencies minimal and the codebase simple for early development.

### Future Backends (Planned)

The deployer interface is designed to accommodate these tools later if needed:

| Method | Use Case | When to Add |
|--------|----------|-------------|
| `colmena` | Fleet deployment with parallel/rollback | When managing 5+ hosts |
| `deploy-rs` | Multi-profile deployments | When needing advanced profiles |
| `nixos-anywhere` | Fresh installs from scratch | When automating initial provisioning |

These are not immediate dependencies - the architecture simply ensures we can swap them in without major refactoring.

## State Management

ntd is **stateless by design**:

- Terraform state lives in Terraform
- NixOS state is the deployed configuration
- ntd reads both systems on every command
- `ntd.toml` is configuration, not state

Benefits:
- No drift between ntd state and reality
- Works with existing workflows
- Multiple users can run ntd without conflicts

## Implementation Approach

### Phase 1: Core CLI
- `ntd init` - Interactive setup
- `ntd inventory` - Query TF + NixOS
- `ntd apply` - Deploy using nixos-rebuild
- Config file parsing

### Phase 2: Secrets Integration
- `ntd secrets` - Wrap sops operations
- Automatic key provisioning
- Integration with apply workflow

### Phase 3: Provisioning
- `ntd provision` - Create new hosts
- Templates for Proxmox VMs/LXC

### Phase 4: Advanced Deployment
- Parallel deployment
- Rollback support

## Technology Choices

**Language**: Python
- Rapid prototyping for an evolving design
- Rich ecosystem for CLI (click/typer), SSH (paramiko/fabric), and config parsing
- All dependencies provided via `flake.nix` devShell - no pip/virtualenv complexity
- Easy for homelab users to modify and contribute

**Dependencies** (provided via `flake.nix`):
- Python 3.11+ with libraries (click, paramiko, rich, tomli)
- Terraform CLI (shelling out)
- Nix CLI (shelling out)
- sops CLI (for secrets)

## Example Workflow

```bash
# Initial setup (once)
cd ~/homelab
ntd init
# Discovers ./terraform and ./nixos, creates ntd.toml

# Daily operations
ntd inventory              # See all hosts
ntd plan vm1               # Preview changes
ntd apply vm1              # Deploy changes

# Adding a new host
ntd provision newhost \
  --terraform-template proxmox-lxc \
  --nixos-config container-base

# Rotating secrets
ntd secrets rotate --all --max-age 90d
ntd apply --all
```

## References

- [Deploying NixOS using Terraform](https://nix.dev/tutorials/nixos/deploying-nixos-using-terraform.html)
- [Declarative deployment with Terraform and Nix](https://jonascarpay.com/posts/2022-09-19-declarative-deployment.html)

### Future Integration References

These tools may be integrated as deployment backends later:

- [Colmena](https://github.com/zhaofengli/colmena) - parallel deployment, rollback
- [deploy-rs](https://github.com/serokell/deploy-rs) - multi-profile deployments
- [nixos-anywhere](https://github.com/nix-community/nixos-anywhere) - fresh installs via SSH
