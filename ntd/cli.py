"""CLI interface for ntd."""

import re
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from ntd.config import Config, ConfigError, Host, find_host, load_config, save_config
from ntd.status import get_status
from ntd.nixos import (
    NixOSError,
    build_configuration,
    closure_size,
    deploy,
    list_configurations,
)
from ntd.ssh import wait_for_ssh
from ntd.terraform import (
    TerraformError,
    TerraformPlan,
    apply as tf_apply,
    cleanup_plan,
    flatten_outputs,
    get_host_ip,
    get_outputs,
    plan as tf_plan,
)

console = Console()

_TOTAL_RE = re.compile(r"copying (\d+) paths?")
_ADVANCE_RE = re.compile(r"^copying path '")


def _format_bytes(n: int) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024:
            return f"{int(size)} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"


def _make_copy_progress_handler(progress: Progress, task_id):
    def handle(line: str) -> None:
        m = _TOTAL_RE.search(line)
        if m:
            progress.update(task_id, total=int(m.group(1)))
        elif _ADVANCE_RE.match(line):
            progress.advance(task_id)

    return handle


def _copy_progress_columns():
    return (
        SpinnerColumn(),
        TextColumn("[cyan]Copying closure to {task.description}[/cyan]"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
    )


def _size_label(store_path: Path) -> str:
    try:
        return _format_bytes(closure_size(store_path))
    except NixOSError:
        return "unknown size"


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
def status():
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

    statuses = get_status(config)

    table = Table(title="Host Status")
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
@click.argument("host", required=False, default=None)
def plan(host: str | None):
    """Preview deployment changes. Without HOST, shows terraform + all NixOS configs. With HOST, shows that host's NixOS config only."""
    try:
        config = load_config()
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    if host is None:
        _plan_all(config)
    else:
        _plan_host(config, host)


def _plan_all(config):
    console.print("[bold]Planning full deployment...[/bold]\n")

    # Step 1: Terraform plan (soft failure — plan is preview only)
    console.print("[bold]Step 1: Infrastructure (Terraform)[/bold]")
    terraform_plan = None
    try:
        terraform_plan = tf_plan(config.terraform_path)

        if terraform_plan.has_changes:
            for r in terraform_plan.creates:
                console.print(f"  [green]+ {r}[/green]")
            for r in terraform_plan.updates:
                console.print(f"  [yellow]~ {r}[/yellow]")
            for r in terraform_plan.replaces:
                console.print(f"  [yellow]-/+ {r}[/yellow] (replace)")
            for r in terraform_plan.destroys:
                console.print(f"  [red]- {r}[/red] (destroy)")

            if terraform_plan.is_destructive():
                console.print("\n  [yellow]Warning: Plan contains destructive changes[/yellow]")
        else:
            console.print("  No infrastructure changes")

    except TerraformError as e:
        console.print(f"  [yellow]Warning: Could not run terraform plan: {e}[/yellow]")
    finally:
        if terraform_plan:
            cleanup_plan(terraform_plan)

    # Step 2: NixOS configurations for all hosts
    console.print(f"\n[bold]Step 2: Configurations (NixOS)[/bold]")
    for host_config in config.hosts:
        console.print(f"\n  Building {host_config.nixos_configuration} ({host_config.name})...")
        try:
            store_path = build_configuration(config.nixos_path, host_config.nixos_configuration)
            console.print(f"  [green]{host_config.name}: {store_path}[/green]")
        except NixOSError as e:
            console.print(f"  [red]{host_config.name}: Build failed: {e}[/red]")
            sys.exit(1)

    console.print(f"\nRun 'ntd apply' to deploy all hosts.")


def _plan_host(config, host: str):
    host_config = find_host(config, host)
    if not host_config:
        console.print(f"[red]Error: Host '{host}' not found in configuration[/red]")
        console.print("Available hosts:")
        for h in config.hosts:
            console.print(f"  {h.name}")
        sys.exit(1)

    console.print(f"[bold]Planning deployment for {host}...[/bold]\n")

    # Get current IP from Terraform outputs for display only
    try:
        tf_outputs = get_outputs(config.terraform_path)
        ip = get_host_ip(tf_outputs, host_config.terraform_ip_output)
    except TerraformError:
        ip = None

    # Step 1: NixOS configuration only (terraform is not run for host-specific plan)
    console.print("[bold]Step 1: Configuration (NixOS)[/bold]")
    console.print(f"  Configuration: {host_config.nixos_configuration}")
    console.print(f"  Target IP: {ip or '[will be determined after terraform apply]'}")

    console.print("\n  Building configuration...")
    try:
        store_path = build_configuration(config.nixos_path, host_config.nixos_configuration)
        console.print("  [green]Build successful![/green]")
        console.print(f"  Store path: {store_path}")
    except NixOSError as e:
        console.print(f"  [red]Build failed: {e}[/red]")
        sys.exit(1)

    console.print(f"\n[bold]Summary:[/bold]")
    console.print(f"  Would deploy {store_path}")
    console.print(f"  -> {host} ({ip or 'IP pending'})")
    console.print(f"\nRun 'ntd apply {host}' to deploy.")


@cli.command()
@click.argument("host", required=False, default=None)
@click.option("--skip-terraform", is_flag=True, help="Skip terraform apply (no-args path only)")
@click.option("--skip-nixos", is_flag=True, help="Skip NixOS deploy (no-args path only)")
def apply(host: str | None, skip_terraform: bool, skip_nixos: bool):
    """Deploy infrastructure and NixOS. Without HOST, runs terraform + deploys all hosts. With HOST, deploys NixOS to that host only (no terraform)."""
    try:
        config = load_config()
    except ConfigError as e:
        console.print(f"[red]Error: {e}[/red]")
        sys.exit(1)

    if host is None:
        _apply_all(config, skip_terraform, skip_nixos)
    else:
        _apply_host(config, host, skip_terraform, skip_nixos)


def _apply_all(config, skip_terraform: bool, skip_nixos: bool):
    console.print("[bold]Deploying all hosts...[/bold]\n")

    creates_set: set[str] = set()
    replaces_set: set[str] = set()

    # Step 1: Terraform
    if not skip_terraform:
        console.print("[bold]Step 1: Infrastructure (Terraform)[/bold]")
        try:
            terraform_plan = tf_plan(config.terraform_path)

            if terraform_plan.has_changes:
                for r in terraform_plan.creates:
                    console.print(f"  [green]+ {r}[/green]")
                for r in terraform_plan.updates:
                    console.print(f"  [yellow]~ {r}[/yellow]")
                for r in terraform_plan.replaces:
                    console.print(f"  [yellow]-/+ {r}[/yellow] (replace)")
                for r in terraform_plan.destroys:
                    console.print(f"  [red]- {r}[/red] (destroy)")

                if terraform_plan.is_destructive():
                    console.print("\n  [yellow]Warning: Destructive changes detected![/yellow]")
                    if not click.confirm("  Continue with destructive changes?", default=False):
                        cleanup_plan(terraform_plan)
                        console.print("[yellow]Aborted.[/yellow]")
                        sys.exit(0)

                console.print("\n  Applying infrastructure changes...")
                tf_apply(config.terraform_path, plan_file=terraform_plan.plan_file, auto_approve=True)
                console.print("  [green]Infrastructure updated![/green]")

                creates_set = set(terraform_plan.creates)
                replaces_set = set(terraform_plan.replaces)
                cleanup_plan(terraform_plan)
            else:
                console.print("  No infrastructure changes needed")

        except TerraformError as e:
            console.print(f"  [red]Terraform failed: {e}[/red]")
            sys.exit(1)
    else:
        console.print("[dim]Step 1: Infrastructure (skipped)[/dim]")

    # Step 2: NixOS for all hosts
    if not skip_nixos:
        console.print(f"\n[bold]Step 2: Deploying NixOS configurations[/bold]")

        try:
            tf_outputs = get_outputs(config.terraform_path)
        except TerraformError as e:
            console.print(f"[red]Error: Could not get Terraform outputs: {e}[/red]")
            sys.exit(1)

        for host_config in config.hosts:
            ip = get_host_ip(tf_outputs, host_config.terraform_ip_output)
            if not ip:
                console.print(f"[red]Error: Could not determine IP for {host_config.name}[/red]")
                console.print(f"  Terraform output key: {host_config.terraform_ip_output}")
                sys.exit(1)

            # Check if this host was newly created or replaced — if so, wait for SSH.
            # The terraform_resource field may or may not include the resource type prefix
            # (e.g. "vm1" vs "proxmox_lxc.vm1"), so we check both exact match and suffix.
            all_changed = creates_set | replaces_set
            needs_ssh_wait = any(
                addr == host_config.terraform_resource or addr.endswith("." + host_config.terraform_resource)
                for addr in all_changed
            )

            if needs_ssh_wait:
                console.print(f"\n  Waiting for {host_config.name} ({ip}) to become reachable...")
                success, error_type = wait_for_ssh(ip, config.ssh_user, config.ssh_key, timeout=120)
                if not success:
                    if error_type == "host_key_changed":
                        console.print(f"  [red]SSH host key has changed for {ip}[/red]")
                        console.print("  To fix, remove the old key:")
                        console.print(f"    ssh-keygen -R {ip}")
                        console.print(f"\n  Then re-run: ntd apply")
                    else:
                        console.print(f"  [red]Timeout waiting for SSH on {ip}[/red]")
                    sys.exit(1)
                console.print(f"  [green]{host_config.name} is reachable![/green]")

            console.print(f"\n  [{host_config.name}] Building {host_config.nixos_configuration}...")
            try:
                store_path = build_configuration(config.nixos_path, host_config.nixos_configuration)
            except NixOSError as e:
                console.print(f"  [red][{host_config.name}] Build failed: {e}[/red]")
                sys.exit(1)

            description = f"{host_config.name} ({_size_label(store_path)})"
            try:
                with Progress(*_copy_progress_columns(), console=console) as progress:
                    task = progress.add_task(description, total=None)
                    deploy(
                        store_path,
                        ip,
                        config.ssh_user,
                        config.ssh_key,
                        on_copy_progress=_make_copy_progress_handler(progress, task),
                    )
                console.print(f"  [green][{host_config.name}] Deployed successfully![/green]")
            except NixOSError as e:
                console.print(f"  [red][{host_config.name}] Deployment failed: {e}[/red]")
                sys.exit(1)
    else:
        console.print("\n[dim]Step 2: NixOS deployments (skipped)[/dim]")

    console.print(f"\n[green]All hosts deployed successfully![/green]")


def _apply_host(config, host: str, skip_terraform: bool, skip_nixos: bool):
    if skip_terraform or skip_nixos:
        console.print("[yellow]Warning: --skip-terraform and --skip-nixos are ignored when a host is specified[/yellow]")

    host_config = find_host(config, host)
    if not host_config:
        console.print(f"[red]Error: Host '{host}' not found in configuration[/red]")
        console.print("Available hosts:")
        for h in config.hosts:
            console.print(f"  {h.name}")
        sys.exit(1)

    console.print(f"[bold]Deploying {host}...[/bold]\n")

    # Get IP from Terraform outputs
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

    # Step 1: NixOS only (terraform is not run for host-specific apply)
    console.print("[bold]Step 1: Configuration (NixOS)[/bold]")
    console.print(f"  Target: {ip}")
    console.print(f"  Configuration: {host_config.nixos_configuration}")

    console.print("\n  Building configuration...")
    try:
        store_path = build_configuration(config.nixos_path, host_config.nixos_configuration)
        console.print("  [green]Build successful![/green]")
    except NixOSError as e:
        console.print(f"  [red]Build failed: {e}[/red]")
        sys.exit(1)

    description = f"{host} ({_size_label(store_path)})"
    try:
        with Progress(*_copy_progress_columns(), console=console) as progress:
            task = progress.add_task(description, total=None)
            deploy(
                store_path,
                ip,
                config.ssh_user,
                config.ssh_key,
                on_copy_progress=_make_copy_progress_handler(progress, task),
            )
        console.print("  [green]Configuration deployed![/green]")
    except NixOSError as e:
        console.print(f"  [red]Deployment failed: {e}[/red]")
        sys.exit(1)

    console.print(f"\n[green]Successfully deployed {host}![/green]")


if __name__ == "__main__":
    cli()
