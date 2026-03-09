# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Command line tool for deploying NixOS containers and virtual machines to a Proxmox homelab using Terraform infrastructure.

## Development Environment

Uses Nix Flakes for reproducible development. Enter the shell with:

```bash
nix develop                    # x86_64-linux (default)
nix develop '.#aarch64-linux'  # ARM64 systems
```

The dev shell provides: nix, nixos-rebuild, nixos-generators (for LXC tarballs), openssh, terraform.

Cross-architecture builds require QEMU emulation enabled on the host system.

## Architecture

This is an early-stage project. The flake.nix defines development shells for x86_64 and aarch64 Linux with shared tooling for NixOS deployment workflows.

## Methodology

The priority is maintainable, readable code. Use tests to verify functionality of features: always run tests after changes, and never change, skip, or remove existing tests to make features pass. 

Follow planning documents:
- secrets.md for secrets management
- design.md for overall software plan
