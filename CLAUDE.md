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

The sibling repositories homelab and nixos-proxmox-ct are intentionally separate.
- homelab contains terraform and nixos configurations
- nixos-proxmox-ct contains a nix flake for a nixos proxmox container


The dev shell provides: nix, nixos-rebuild, nixos-generators (for LXC tarballs), openssh, terraform.

Cross-architecture builds require QEMU emulation enabled on the host system.

You are in a containerized environment with the development repositories mounted
Keep this in mind when trouble shooting path issues

Most commands are not immediately available, you will have to use nix-shell or develop to get python for example.

## Architecture

This is an early-stage project. The flake.nix defines development shells for x86_64 and aarch64 Linux with shared tooling for NixOS deployment workflows.

## Methodology

The priority is maintainable, readable code. Use tests to verify functionality of features: always run tests after changes, and never change, skip, or remove existing tests to make features pass. Reduce technical debt for the future, and make notes of where it is unavoidable, or intentionally created based on tradeoffs.

Follow planning documents:
- secrets.md for secrets management
- design.md for overall software plan
