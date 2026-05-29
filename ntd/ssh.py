"""SSH utilities for ntd."""

import socket
import subprocess
import time
from pathlib import Path


def wait_for_ssh(
    host: str,
    user: str,
    key: Path,
    timeout: int = 120,
    interval: int = 5,
) -> bool:
    """Wait for SSH to become available on a host.

    Uses exponential backoff starting from the given interval.

    Args:
        host: Hostname or IP address.
        user: SSH username.
        key: Path to SSH private key.
        timeout: Maximum seconds to wait.
        interval: Initial polling interval in seconds.

    Returns:
        True if SSH becomes available, False on timeout.
    """
    start_time = time.time()
    current_interval = interval

    while time.time() - start_time < timeout:
        if check_ssh(host, user, key):
            return True

        time.sleep(current_interval)
        current_interval = min(current_interval * 1.5, 30)

    return False


def check_ssh(host: str, user: str, key: Path) -> bool:
    """Check if SSH connection is possible.

    Args:
        host: Hostname or IP address.
        user: SSH username.
        key: Path to SSH private key.

    Returns:
        True if SSH connection succeeds, False otherwise.
    """
    try:
        result = subprocess.run(
            [
                "ssh",
                "-o", "StrictHostKeyChecking=accept-new",
                "-o", "ConnectTimeout=5",
                "-o", "BatchMode=yes",
                "-i", str(key),
                f"{user}@{host}",
                "true",
            ],
            capture_output=True,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_port(host: str, port: int = 22, timeout: int = 5) -> bool:
    """Check if a port is open on a host.

    Args:
        host: Hostname or IP address.
        port: Port number to check.
        timeout: Connection timeout in seconds.

    Returns:
        True if port is open, False otherwise.
    """
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        result = sock.connect_ex((host, port))
        sock.close()
        return result == 0
    except (socket.error, socket.timeout):
        return False
