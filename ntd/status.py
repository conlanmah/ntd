"""Status management for ntd."""

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from ntd.config import Config
from ntd.terraform import TerraformError, get_host_ip, get_outputs


@dataclass
class HostStatus:
    """Status information for a host."""

    name: str
    terraform_resource: str
    nixos_config: str
    ip: str | None
    status: Literal["deployed", "unreachable", "unknown"]


def check_reachable(ip: str, ssh_user: str, ssh_key: Path, timeout: int = 5) -> bool:
    """Check if a host is reachable via SSH.

    Args:
        ip: IP address to check.
        ssh_user: SSH username.
        ssh_key: Path to the SSH private key.
        timeout: Connection timeout in seconds.

    Returns:
        True if the host is reachable, False otherwise.
    """
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o",
                f"ConnectTimeout={timeout}",
                "-o",
                "BatchMode=yes",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "-i",
                str(ssh_key),
                f"{ssh_user}@{ip}",
                "exit",
            ],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def get_status(config: Config) -> list[HostStatus]:
    """Get status information for all configured hosts.

    Args:
        config: The ntd configuration.

    Returns:
        List of HostStatus objects for each configured host.
    """
    # Try to get Terraform outputs
    try:
        tf_outputs = get_outputs(config.terraform_path)
    except TerraformError:
        tf_outputs = {}

    statuses = []

    for host in config.hosts:
        # Get IP from Terraform outputs
        ip = get_host_ip(tf_outputs, host.terraform_ip_output)

        # Determine status
        if ip is None:
            status: Literal["deployed", "unreachable", "unknown"] = "unknown"
        elif check_reachable(ip, config.ssh_user, config.ssh_key):
            status = "deployed"
        else:
            status = "unreachable"

        statuses.append(
            HostStatus(
                name=host.name,
                terraform_resource=host.terraform_resource,
                nixos_config=host.nixos_configuration,
                ip=ip,
                status=status,
            )
        )

    return statuses
