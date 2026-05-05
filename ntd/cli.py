"""CLI interface for ntd."""

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from ntd.config import Config, ConfigError, Host, find_host, load_config, save_config
from ntd.inventory import get_inventory
from ntd.nixos import NixOSError, build_configuration, deploy, list_configurations
from ntd.terraform import TerraformError, flatten_outputs, get_host_ip, get_outputs

console = Console()


@click.group()
def cli():
    """ntd - NixOS Terraform Deployer"""
    pass


@cli.command()
def init():
    """Interactive setup - discover TF/NixOS and create ntd.toml"""
    config_path = Path("ntd.toml")
    existing_config = None
    update_mode = False

    # Check for existing config
    if config_path.exists():
        try:
            existing_config = load_config(config_path)
            choice = click.prompt(
                "ntd.toml exists. Update existing config or recreate from scratch?",
                type=click.Choice(["update", "recreate"]),
                default="update",
            )
            update_mode = choice == "update"
        except ConfigError:
            console.print("[yellow]Existing ntd.toml is invalid, starting fresh[/yellow]")

    # Find Terraform directory
    default_tf = str(existing_config.terraform_path) if update_mode and existing_config else "./terraform"
    if Path(default_tf).exists():
        tf_path_str = click.prompt("Terraform directory", default=default_tf)
    else:
        tf_path_str = click.prompt("Terraform directory (./terraform not found)")
    tf_path = Path(tf_path_str).resolve()

    if not tf_path.exists():
        console.print(f"[red]Error: Directory not found: {tf_path}[/red]")
        sys.exit(1)

    # Find NixOS flake directory
    default_nix = str(existing_config.nixos_path) if update_mode and existing_config else "."
    flake_check = Path(default_nix) / "flake.nix"
    if flake_check.exists() or (Path(".") / "flake.nix").exists():
        nixos_path_str = click.prompt("NixOS flake directory", default=default_nix)
    else:
        nixos_path_str = click.prompt("NixOS flake directory (flake.nix not found in current dir)")
    nixos_path = Path(nixos_path_str).resolve()

    if not (nixos_path / "flake.nix").exists():
        console.print(f"[red]Error: flake.nix not found in: {nixos_path}[/red]")
        sys.exit(1)

    # SSH configuration
    default_user = existing_config.ssh_user if update_mode and existing_config else "root"
    ssh_user = click.prompt("SSH user", default=default_user)

    default_key = str(existing_config.ssh_key) if update_mode and existing_config else "~/.ssh/id_ed25519"
    ssh_key_str = click.prompt("SSH private key path", default=default_key)
    ssh_key = Path(ssh_key_str).expanduser()

    # Get Terraform outputs
    console.print("\n[bold]Discovering Terraform outputs...[/bold]")
    try:
        tf_outputs = get_outputs(tf_path)
        flat_outputs = flatten_outputs(tf_outputs)
        if flat_outputs:
            console.print("Available outputs:")
            for key, value in flat_outputs.items():
                console.print(f"  {key} = {value}")
        else:
            console.print("[yellow]No outputs found (have you run terraform apply?)[/yellow]")
    except TerraformError as e:
        console.print(f"[yellow]Could not get Terraform outputs: {e}[/yellow]")
        tf_outputs = {}
        flat_outputs = {}

    # Get NixOS configurations
    console.print("\n[bold]Discovering NixOS configurations...[/bold]")
    try:
        nixos_configs = list_configurations(nixos_path)
        if nixos_configs:
            console.print("Available configurations:")
            for cfg in nixos_configs:
                console.print(f"  {cfg}")
        else:
            console.print("[yellow]No nixosConfigurations found in flake[/yellow]")
    except NixOSError as e:
        console.print(f"[yellow]Could not list NixOS configurations: {e}[/yellow]")
        nixos_configs = []

    # Host configuration
    hosts = list(existing_config.hosts) if update_mode and existing_config else []

    if update_mode and hosts:
        console.print(f"\n[bold]Existing hosts ({len(hosts)}):[/bold]")
        for h in hosts:
            console.print(f"  {h.name}: {h.nixos_configuration} -> {h.terraform_ip_output}")

    console.print("\n[bold]Configure host mappings[/bold]")
    console.print("(Press Enter with empty name to finish)")

    while True:
        name = click.prompt("\nHost name", default="", show_default=False)
        if not name:
            break

        # Check if updating existing host
        existing_host = None
        for h in hosts:
            if h.name == name:
                existing_host = h
                break

        if existing_host:
            console.print(f"[yellow]Updating existing host: {name}[/yellow]")
            default_resource = existing_host.terraform_resource
            default_ip_output = existing_host.terraform_ip_output
            default_nixos = existing_host.nixos_configuration
        else:
            default_resource = ""
            default_ip_output = ""
            default_nixos = nixos_configs[0] if nixos_configs else ""

        tf_resource = click.prompt("  Terraform resource name", default=default_resource or "")
        tf_ip_output = click.prompt("  Terraform IP output key", default=default_ip_output or "")
        nixos_cfg = click.prompt("  NixOS configuration name", default=default_nixos or "")

        new_host = Host(
            name=name,
            terraform_resource=tf_resource,
            terraform_ip_output=tf_ip_output,
            nixos_configuration=nixos_cfg,
        )

        if existing_host:
            hosts = [new_host if h.name == name else h for h in hosts]
        else:
            hosts.append(new_host)

    if not hosts:
        console.print("[yellow]Warning: No hosts configured[/yellow]")

    # Create and save config
    config = Config(
        terraform_path=tf_path,
        nixos_path=nixos_path,
        ssh_user=ssh_user,
        ssh_key=ssh_key,
        hosts=hosts,
    )

    save_config(config, config_path)
    console.print(f"\n[green]Configuration saved to {config_path}[/green]")


@cli.command()
def inventory():
    """Show all hosts and their status"""
    try:
        config = load_config()
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        console.print("Run 'ntd init' to create a configuration.")
        sys.exit(1)

    if not config.hosts:
        console.print("[yellow]No hosts configured. Run 'ntd init' to add hosts.[/yellow]")
        return

    statuses = get_inventory(config)

    table = Table(title="Host Inventory")
    table.add_column("Name", style="cyan")
    table.add_column("NixOS Config", style="magenta")
    table.add_column("IP", style="green")
    table.add_column("Status")

    for host in statuses:
        ip_display = host.ip or "-"

        if host.status == "deployed":
            status_display = "[green]deployed[/green]"
        elif host.status == "unreachable":
            status_display = "[yellow]unreachable[/yellow]"
        else:
            status_display = "[red]unknown[/red]"

        table.add_row(host.name, host.nixos_config, ip_display, status_display)

    console.print(table)


@cli.command()
@click.argument("host")
def plan(host: str):
    """Preview what would be deployed to HOST"""
    try:
        config = load_config()
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    host_config = find_host(config, host)
    if not host_config:
        console.print(f"[red]Error: Host '{host}' not found in configuration[/red]")
        console.print("Available hosts:")
        for h in config.hosts:
            console.print(f"  {h.name}")
        sys.exit(1)

    # Get IP from Terraform
    console.print(f"[bold]Planning deployment for {host}...[/bold]\n")

    try:
        tf_outputs = get_outputs(config.terraform_path)
        ip = get_host_ip(tf_outputs, host_config.terraform_ip_output)
    except TerraformError as e:
        console.print(f"[yellow]Warning: Could not get Terraform outputs: {e}[/yellow]")
        ip = None

    console.print(f"Host: {host}")
    console.print(f"NixOS configuration: {host_config.nixos_configuration}")
    console.print(f"Target IP: {ip or '[unknown]'}")

    # Build the configuration
    console.print(f"\n[bold]Building NixOS configuration...[/bold]")
    try:
        store_path = build_configuration(config.nixos_path, host_config.nixos_configuration)
        console.print(f"[green]Build successful![/green]")
        console.print(f"Store path: {store_path}")
    except NixOSError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        sys.exit(1)

    console.print(f"\n[bold]Would deploy:[/bold]")
    console.print(f"  {store_path}")
    console.print(f"  -> {host} ({ip or 'IP unknown'})")
    console.print("\nRun 'ntd apply {host}' to deploy.")


@cli.command()
@click.argument("host")
def apply(host: str):
    """Deploy NixOS configuration to HOST"""
    try:
        config = load_config()
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    host_config = find_host(config, host)
    if not host_config:
        console.print(f"[red]Error: Host '{host}' not found in configuration[/red]")
        sys.exit(1)

    # Get IP from Terraform
    console.print(f"[bold]Deploying to {host}...[/bold]\n")

    try:
        tf_outputs = get_outputs(config.terraform_path)
        ip = get_host_ip(tf_outputs, host_config.terraform_ip_output)
    except TerraformError as e:
        console.print(f"[red]Error: Could not get Terraform outputs: {e}[/red]")
        sys.exit(1)

    if not ip:
        console.print(f"[red]Error: Could not determine IP for {host}[/red]")
        console.print(f"Terraform output key: {host_config.terraform_ip_output}")
        sys.exit(1)

    console.print(f"Target: {ip}")
    console.print(f"NixOS configuration: {host_config.nixos_configuration}")

    # Build the configuration
    console.print(f"\n[bold]Building NixOS configuration...[/bold]")
    try:
        store_path = build_configuration(config.nixos_path, host_config.nixos_configuration)
        console.print(f"[green]Build successful![/green]")
    except NixOSError as e:
        console.print(f"[red]Build failed: {e}[/red]")
        sys.exit(1)

    # Deploy
    console.print(f"\n[bold]Copying closure to {host}...[/bold]")
    try:
        deploy(store_path, ip, config.ssh_user, config.ssh_key)
        console.print(f"\n[green]Successfully deployed to {host}![/green]")
    except NixOSError as e:
        console.print(f"[red]Deployment failed: {e}[/red]")
        sys.exit(1)


if __name__ == "__main__":
    cli()
