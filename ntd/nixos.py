"""NixOS integration for ntd."""

import json
import os
import subprocess
from pathlib import Path


class NixOSError(Exception):
    """Raised when a NixOS operation fails."""

    pass


def list_configurations(flake_path: Path) -> list[str]:
    """List all nixosConfigurations defined in a flake.

    Args:
        flake_path: Path to the directory containing flake.nix.

    Returns:
        List of configuration names.

    Raises:
        NixOSError: If the nix command fails or flake.nix doesn't exist.
    """
    flake_file = flake_path / "flake.nix"
    if not flake_file.exists():
        raise NixOSError(f"flake.nix not found at: {flake_path}")

    try:
        result = subprocess.run(
            ["nix", "flake", "show", "--json", str(flake_path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise NixOSError(f"nix flake show failed: {e.stderr}")
    except FileNotFoundError:
        raise NixOSError("nix command not found")

    try:
        flake_info = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise NixOSError(f"Failed to parse nix flake show output: {e}")

    nixos_configs = flake_info.get("nixosConfigurations", {})
    return list(nixos_configs.keys())


def build_configuration(flake_path: Path, config_name: str) -> Path:
    """Build a NixOS configuration and return the store path.

    Args:
        flake_path: Path to the directory containing flake.nix.
        config_name: Name of the nixosConfiguration to build.

    Returns:
        Path to the built system in the Nix store.

    Raises:
        NixOSError: If the build fails.
    """
    flake_ref = f"{flake_path}#nixosConfigurations.{config_name}.config.system.build.toplevel"

    try:
        result = subprocess.run(
            ["nix", "build", flake_ref, "--print-out-paths", "--no-link"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise NixOSError(f"nix build failed: {e.stderr}")
    except FileNotFoundError:
        raise NixOSError("nix command not found")

    store_path = result.stdout.strip()
    if not store_path:
        raise NixOSError("nix build produced no output")

    return Path(store_path)


def copy_closure(store_path: Path, host_ip: str, ssh_user: str, ssh_key: Path) -> None:
    """Copy a Nix closure to a remote host.

    Args:
        store_path: Path to the store item to copy.
        host_ip: IP address of the target host.
        ssh_user: SSH username.
        ssh_key: Path to the SSH private key.

    Raises:
        NixOSError: If the copy fails.
    """
    ssh_target = f"ssh://{ssh_user}@{host_ip}"
    ssh_opts = f"-o StrictHostKeyChecking=accept-new -i {ssh_key}"

    env = os.environ.copy()
    env["NIX_SSHOPTS"] = ssh_opts

    try:
        subprocess.run(
            [
                "nix",
                "copy",
                "--to",
                ssh_target,
                str(store_path),
            ],
            env=env,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise NixOSError(f"nix copy failed: {e.stderr}")
    except FileNotFoundError:
        raise NixOSError("nix command not found")


def activate_configuration(
    store_path: Path, host_ip: str, ssh_user: str, ssh_key: Path
) -> None:
    """Activate a NixOS configuration on a remote host.

    Args:
        store_path: Path to the system store item.
        host_ip: IP address of the target host.
        ssh_user: SSH username.
        ssh_key: Path to the SSH private key.

    Raises:
        NixOSError: If activation fails.
    """
    switch_cmd = f"{store_path}/bin/switch-to-configuration switch"

    try:
        subprocess.run(
            [
                "ssh",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-i",
                str(ssh_key),
                f"{ssh_user}@{host_ip}",
                switch_cmd,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise NixOSError(f"Configuration activation failed: {e.stderr}")
    except FileNotFoundError:
        raise NixOSError("ssh command not found")


def deploy(store_path: Path, host_ip: str, ssh_user: str, ssh_key: Path) -> None:
    """Deploy a NixOS configuration to a remote host.

    This copies the closure and activates the configuration.

    Args:
        store_path: Path to the system store item.
        host_ip: IP address of the target host.
        ssh_user: SSH username.
        ssh_key: Path to the SSH private key.

    Raises:
        NixOSError: If deployment fails.
    """
    copy_closure(store_path, host_ip, ssh_user, ssh_key)
    activate_configuration(store_path, host_ip, ssh_user, ssh_key)
