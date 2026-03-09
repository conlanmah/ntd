# Secrets Management Architecture

This document describes how ntd manages secrets across Terraform and NixOS deployments.

## Overview

ntd uses **SOPS with age encryption** as the unified secrets backend for both Terraform and NixOS:

- **SOPS** (Secrets OPerationS) encrypts secrets as structured files that can be safely committed to git
- **age** provides the encryption, with keys derived from SSH keys via `ssh-to-age`
- **terraform-provider-sops** decrypts secrets during Terraform operations
- **sops-nix** decrypts secrets on NixOS machines at system activation

This approach keeps secrets in a single encrypted format usable by both tools.

## Key Hierarchy

```
┌─────────────────────────────────────────────────────────────┐
│                      Admin Machine                          │
│  ~/.config/sops/age/keys.txt (age private key)             │
│  Derived from: ssh-to-age -private-key < ~/.ssh/id_ed25519 │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ encrypts
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    Git Repository                           │
│  secrets/*.sops.yaml (encrypted secrets)                   │
│  .sops.yaml (encryption rules + authorized keys)           │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┴───────────────┐
              │                               │
              ▼                               ▼
┌──────────────────────────┐    ┌──────────────────────────┐
│       Terraform          │    │     NixOS Machines       │
│  terraform-provider-sops │    │  sops-nix module         │
│  Decrypts at apply time  │    │  Decrypts at activation  │
│  (ephemeral, not in      │    │  Secrets in /run/secrets │
│   state with TF 1.11+)   │    │  Host key authorizes     │
└──────────────────────────┘    └──────────────────────────┘
```

## Directory Structure

```
ntd/
├── .sops.yaml                    # SOPS configuration
├── secrets/
│   ├── ssh-keys.sops.yaml        # Machine SSH keys
│   ├── api-tokens.sops.yaml      # Service credentials
│   └── per-host/
│       ├── vm1.sops.yaml         # Host-specific secrets
│       └── vm2.sops.yaml
├── terraform/
│   └── main.tf                   # References secrets via provider
└── nixos/
    └── configurations/
        └── common.nix            # sops-nix secret declarations
```

## .sops.yaml Configuration

```yaml
keys:
  # Admin keys (humans who can edit secrets)
  - &admin_alice age1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

  # Machine host keys (derived from /etc/ssh/ssh_host_ed25519_key)
  - &host_vm1 age1yyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyyy
  - &host_vm2 age1zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz

creation_rules:
  # All hosts can read shared secrets
  - path_regex: secrets/ssh-keys\.sops\.yaml$
    key_groups:
      - age:
          - *admin_alice
          - *host_vm1
          - *host_vm2

  # Per-host secrets only readable by that host
  - path_regex: secrets/per-host/vm1\.sops\.yaml$
    key_groups:
      - age:
          - *admin_alice
          - *host_vm1
```

## SSH Key Provisioning Workflow

When ntd provisions a new machine:

### 1. Generate SSH Host Keys

```bash
# ntd generates a keypair for the new host
ssh-keygen -t ed25519 -f ./temp_host_key -N "" -C "host_newvm"
```

### 2. Derive age Public Key

```bash
# Convert SSH public key to age format for .sops.yaml
ssh-to-age < ./temp_host_key.pub
# Output: age1abc...
```

### 3. Encrypt and Store

```bash
# Add the new host's age key to .sops.yaml
# Then encrypt the private key into the secrets store
sops --encrypt --in-place secrets/per-host/newvm.sops.yaml
```

### 4. Terraform Provisions VM

```hcl
# terraform/main.tf
provider "sops" {}

data "sops_file" "host_keys" {
  source_file = "../secrets/ssh-keys.sops.yaml"
}

resource "proxmox_vm_qemu" "newvm" {
  name = "newvm"
  # ... other config

  provisioner "file" {
    content     = data.sops_file.host_keys.data["newvm_private_key"]
    destination = "/etc/ssh/ssh_host_ed25519_key"
  }
}
```

### 5. NixOS Configuration

```nix
# nixos/configurations/newvm.nix
{
  sops = {
    defaultSopsFile = ../../secrets/per-host/newvm.sops.yaml;
    age.sshKeyPaths = [ "/etc/ssh/ssh_host_ed25519_key" ];

    secrets = {
      "api_token" = {
        owner = "someservice";
      };
    };
  };

  # Reference decrypted secret
  services.someservice.tokenFile = config.sops.secrets."api_token".path;
}
```

## Credential Rotation

### Manual Rotation

```bash
# 1. Generate new credentials
ntd secrets rotate --host vm1 --type ssh-key

# 2. Re-encrypt with SOPS (automatic if using ntd)
sops secrets/per-host/vm1.sops.yaml
# Edit the secret, save, SOPS re-encrypts automatically

# 3. Redeploy
ntd deploy vm1
```

### Automated Rotation

ntd can implement scheduled rotation:

```bash
# Rotate all SSH keys older than 90 days
ntd secrets rotate --all --max-age 90d

# This will:
# 1. Generate new keypairs
# 2. Update sops-encrypted files
# 3. Queue affected hosts for redeployment
# 4. Optionally commit changes to git
```

## Bootstrapping a New Machine

The chicken-and-egg problem: a new machine needs its host key to decrypt secrets, but the host key is a secret.

### Solution: Two-Phase Provisioning

**Phase 1: Terraform provisions VM with temporary access**
- Terraform creates VM with cloud-init or temporary SSH key
- Installs the permanent host key from encrypted secrets
- Host key is decrypted by Terraform (using admin's age key)

**Phase 2: NixOS activation**
- Machine boots with host key in place
- sops-nix uses host key to decrypt runtime secrets
- No secrets in Nix store or Terraform state

## Security Properties

| Property | Implementation |
|----------|---------------|
| Secrets encrypted at rest | SOPS + age encryption |
| Secrets encrypted in git | SOPS files are ciphertext |
| No secrets in Terraform state | Ephemeral resources (TF 1.11+) |
| No secrets in Nix store | sops-nix decrypts to /run/secrets (tmpfs) |
| Key rotation | Re-encrypt + redeploy |
| Principle of least privilege | Per-host encryption rules in .sops.yaml |
| Audit trail | Git history shows who changed what (not plaintext) |

## Required Tools

Add to `flake.nix` devShell:

```nix
packages = with pkgs; [
  sops
  age
  ssh-to-age
  # ... existing packages
];
```

## References

- [sops-nix](https://github.com/Mic92/sops-nix)
- [terraform-provider-sops](https://github.com/carlpett/terraform-provider-sops)
- [age encryption](https://github.com/FiloSottile/age)
- [ssh-to-age](https://github.com/Mic92/ssh-to-age)
