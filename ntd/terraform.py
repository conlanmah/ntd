"""Terraform integration for ntd."""

import json
import subprocess
from pathlib import Path
from typing import Any, Optional


class TerraformError(Exception):
    """Raised when a Terraform operation fails."""

    pass


def get_outputs(tf_path: Path) -> dict[str, Any]:
    """Get all Terraform outputs as a dictionary.

    Args:
        tf_path: Path to the Terraform directory.

    Returns:
        Dictionary of Terraform outputs.

    Raises:
        TerraformError: If the terraform command fails.
    """
    if not tf_path.exists():
        raise TerraformError(f"Terraform directory not found: {tf_path}")

    try:
        result = subprocess.run(
            ["terraform", f"-chdir={tf_path}", "output", "-json"],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise TerraformError(f"terraform output failed: {e.stderr}")
    except FileNotFoundError:
        raise TerraformError("terraform command not found")

    try:
        outputs = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise TerraformError(f"Failed to parse terraform output: {e}")

    # Terraform outputs are wrapped in {value: ..., type: ...}
    # Extract just the values
    return {key: val.get("value") for key, val in outputs.items()}


def get_host_ip(outputs: dict[str, Any], ip_output_key: str) -> Optional[str]:
    """Extract a host IP from Terraform outputs using dot notation.

    Args:
        outputs: Terraform outputs dictionary.
        ip_output_key: Dot-notation path to the IP, e.g., "vms.vm1.ip"

    Returns:
        The IP address string if found, None otherwise.
    """
    parts = ip_output_key.split(".")
    current = outputs

    for part in parts:
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return None

    if isinstance(current, str):
        return current
    return None


def list_outputs(tf_path: Path) -> list[str]:
    """List all available output keys from Terraform.

    Args:
        tf_path: Path to the Terraform directory.

    Returns:
        List of output key names.

    Raises:
        TerraformError: If the terraform command fails.
    """
    outputs = get_outputs(tf_path)
    return list(outputs.keys())


def flatten_outputs(outputs: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Flatten nested outputs into dot-notation keys with their values.

    Args:
        outputs: Terraform outputs dictionary.
        prefix: Current key prefix for recursion.

    Returns:
        Flattened dictionary mapping dot-notation keys to values.
    """
    result = {}

    for key, value in outputs.items():
        full_key = f"{prefix}.{key}" if prefix else key

        if isinstance(value, dict):
            result.update(flatten_outputs(value, full_key))
        elif isinstance(value, str):
            result[full_key] = value
        elif isinstance(value, (int, float)):
            result[full_key] = str(value)

    return result
