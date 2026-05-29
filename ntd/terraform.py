"""Terraform integration for ntd."""

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


class TerraformError(Exception):
    """Raised when a Terraform operation fails."""

    pass


@dataclass
class TerraformPlan:
    """Represents a parsed Terraform plan."""

    has_changes: bool
    creates: list[str] = field(default_factory=list)
    updates: list[str] = field(default_factory=list)
    replaces: list[str] = field(default_factory=list)
    destroys: list[str] = field(default_factory=list)
    plan_file: Optional[Path] = None

    def is_destructive(self) -> bool:
        """Check if plan contains destroy or replace operations."""
        return bool(self.replaces or self.destroys)


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


def plan(tf_path: Path, target: Optional[str] = None) -> TerraformPlan:
    """Run terraform plan and parse the results.

    Args:
        tf_path: Path to the Terraform directory.
        target: Optional resource target to limit the plan scope.

    Returns:
        TerraformPlan with categorized changes.

    Raises:
        TerraformError: If the terraform command fails.
    """
    if not tf_path.exists():
        raise TerraformError(f"Terraform directory not found: {tf_path}")

    # Create a temporary file for the plan
    plan_file = tf_path / ".ntd-plan"

    cmd = ["terraform", f"-chdir={tf_path}", "plan", "-out", str(plan_file), "-detailed-exitcode"]
    if target:
        cmd.extend(["-target", target])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        # Exit codes: 0 = no changes, 1 = error, 2 = changes present
        if result.returncode == 1:
            raise TerraformError(f"terraform plan failed: {result.stderr}")

        has_changes = result.returncode == 2

    except FileNotFoundError:
        raise TerraformError("terraform command not found")

    if not has_changes:
        return TerraformPlan(has_changes=False)

    # Parse the plan to categorize changes
    try:
        show_result = subprocess.run(
            ["terraform", f"-chdir={tf_path}", "show", "-json", str(plan_file)],
            capture_output=True,
            text=True,
            check=True,
        )
        plan_json = json.loads(show_result.stdout)
    except subprocess.CalledProcessError as e:
        raise TerraformError(f"terraform show failed: {e.stderr}")
    except json.JSONDecodeError as e:
        raise TerraformError(f"Failed to parse plan JSON: {e}")

    creates = []
    updates = []
    replaces = []
    destroys = []

    resource_changes = plan_json.get("resource_changes", [])
    for change in resource_changes:
        address = change.get("address", "unknown")
        actions = change.get("change", {}).get("actions", [])

        if actions == ["create"]:
            creates.append(address)
        elif actions == ["update"]:
            updates.append(address)
        elif actions == ["delete"]:
            destroys.append(address)
        elif "delete" in actions and "create" in actions:
            replaces.append(address)
        elif actions == ["read"]:
            pass  # Data source refresh, not a change

    return TerraformPlan(
        has_changes=True,
        creates=creates,
        updates=updates,
        replaces=replaces,
        destroys=destroys,
        plan_file=plan_file,
    )


def apply(tf_path: Path, plan_file: Optional[Path] = None, auto_approve: bool = False) -> None:
    """Run terraform apply.

    Args:
        tf_path: Path to the Terraform directory.
        plan_file: Optional path to a saved plan file.
        auto_approve: If True, skip interactive approval.

    Raises:
        TerraformError: If the terraform command fails.
    """
    if not tf_path.exists():
        raise TerraformError(f"Terraform directory not found: {tf_path}")

    cmd = ["terraform", f"-chdir={tf_path}", "apply"]

    if plan_file and plan_file.exists():
        cmd.append(str(plan_file))
    elif auto_approve:
        cmd.append("-auto-approve")

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise TerraformError(f"terraform apply failed: {result.stderr}")
    except FileNotFoundError:
        raise TerraformError("terraform command not found")


def cleanup_plan(plan: TerraformPlan) -> None:
    """Remove temporary plan file if it exists."""
    if plan.plan_file and plan.plan_file.exists():
        plan.plan_file.unlink()
