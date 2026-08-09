"""NixOS integration for ntd."""

import json
import os
import subprocess
from pathlib import Path
from typing import Callable, Optional


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


def closure_size(store_path: Path) -> int:
    """Get the total closure size in bytes for a store path.

    Args:
        store_path: Path to the store item.

    Returns:
        Total closure size in bytes.

    Raises:
        NixOSError: If the nix command fails or the output cannot be parsed.
    """
    try:
        result = subprocess.run(
            ["nix", "path-info", "-S", str(store_path)],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise NixOSError(f"nix path-info failed: {e.stderr}")
    except FileNotFoundError:
        raise NixOSError("nix command not found")

    tokens = result.stdout.split()
    if not tokens:
        raise NixOSError("nix path-info produced no output")

    try:
        return int(tokens[-1])
    except ValueError:
        raise NixOSError(f"could not parse closure size from: {result.stdout!r}")


def copy_closure(
    store_path: Path,
    host_ip: str,
    ssh_user: str,
    ssh_key: Path,
    on_progress: Optional[Callable[[str], None]] = None,
) -> None:
    """Copy a Nix closure to a remote host.

    Args:
        store_path: Path to the store item to copy.
        host_ip: IP address of the target host.
        ssh_user: SSH username.
        ssh_key: Path to the SSH private key.
        on_progress: Optional callback invoked with each stderr line from
            `nix copy -v`. When provided, output is streamed live instead of
            buffered.

    Raises:
        NixOSError: If the copy fails.
    """
    ssh_target = f"ssh://{ssh_user}@{host_ip}"
    ssh_opts = f"-o StrictHostKeyChecking=accept-new -i {ssh_key}"

    env = os.environ.copy()
    env["NIX_SSHOPTS"] = ssh_opts

    cmd = ["nix", "copy", "--to", ssh_target, str(store_path)]

    if on_progress is None:
        try:
            subprocess.run(
                cmd,
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            raise NixOSError(f"nix copy failed: {e.stderr}")
        except FileNotFoundError:
            raise NixOSError("nix command not found")
        return

    cmd.append("-v")
    stderr_lines: list[str] = []

    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        raise NixOSError("nix command not found")

    assert proc.stderr is not None
    for line in proc.stderr:
        stderr_lines.append(line)
        on_progress(line)

    returncode = proc.wait()
    if returncode != 0:
        raise NixOSError(f"nix copy failed: {''.join(stderr_lines)}")


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


def deploy(
    store_path: Path,
    host_ip: str,
    ssh_user: str,
    ssh_key: Path,
    on_copy_progress: Optional[Callable[[str], None]] = None,
) -> None:
    """Deploy a NixOS configuration to a remote host.

    This copies the closure and activates the configuration.

    Args:
        store_path: Path to the system store item.
        host_ip: IP address of the target host.
        ssh_user: SSH username.
        ssh_key: Path to the SSH private key.
        on_copy_progress: Optional callback invoked with each stderr line
            during the closure copy step.

    Raises:
        NixOSError: If deployment fails.
    """
    copy_closure(store_path, host_ip, ssh_user, ssh_key, on_progress=on_copy_progress)
    activate_configuration(store_path, host_ip, ssh_user, ssh_key)
