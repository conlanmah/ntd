"""Configuration management for ntd."""

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class Host:
    """A host configuration mapping Terraform resources to NixOS configs."""

    name: str
    terraform_resource: str
    terraform_ip_output: str
    nixos_configuration: str


@dataclass
class Config:
    """Main ntd configuration."""

    terraform_path: Path
    nixos_path: Path
    ssh_user: str
    ssh_key: Path
    hosts: list[Host] = field(default_factory=list)


class ConfigError(Exception):
    """Raised when configuration is invalid or cannot be loaded."""

    pass


def load_config(path: Path = Path("ntd.toml")) -> Config:
    """Load configuration from a TOML file.

    Args:
        path: Path to the ntd.toml configuration file.

    Returns:
        Parsed Config object.

    Raises:
        ConfigError: If the file doesn't exist or is invalid.
    """
    if not path.exists():
        raise ConfigError(f"Configuration file not found: {path}")

    try:
        with open(path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"Invalid TOML in {path}: {e}")

    # Validate required fields
    required = ["terraform_path", "nixos_path", "ssh_user", "ssh_key"]
    for field_name in required:
        if field_name not in data:
            raise ConfigError(f"Missing required field: {field_name}")

    # Parse hosts
    hosts = []
    for host_data in data.get("hosts", []):
        host_required = [
            "name",
            "terraform_resource",
            "terraform_ip_output",
            "nixos_configuration",
        ]
        for field_name in host_required:
            if field_name not in host_data:
                raise ConfigError(f"Host missing required field: {field_name}")
        hosts.append(
            Host(
                name=host_data["name"],
                terraform_resource=host_data["terraform_resource"],
                terraform_ip_output=host_data["terraform_ip_output"],
                nixos_configuration=host_data["nixos_configuration"],
            )
        )

    return Config(
        terraform_path=Path(data["terraform_path"]),
        nixos_path=Path(data["nixos_path"]),
        ssh_user=data["ssh_user"],
        ssh_key=Path(data["ssh_key"]),
        hosts=hosts,
    )


def save_config(config: Config, path: Path = Path("ntd.toml")) -> None:
    """Save configuration to a TOML file.

    Args:
        config: Configuration to save.
        path: Path to write the configuration file.
    """
    lines = [
        "# ntd configuration",
        f'terraform_path = "{config.terraform_path}"',
        f'nixos_path = "{config.nixos_path}"',
        f'ssh_user = "{config.ssh_user}"',
        f'ssh_key = "{config.ssh_key}"',
        "",
    ]

    for host in config.hosts:
        lines.extend(
            [
                "[[hosts]]",
                f'name = "{host.name}"',
                f'terraform_resource = "{host.terraform_resource}"',
                f'terraform_ip_output = "{host.terraform_ip_output}"',
                f'nixos_configuration = "{host.nixos_configuration}"',
                "",
            ]
        )

    path.write_text("\n".join(lines))


def find_host(config: Config, name: str) -> Optional[Host]:
    """Find a host by name in the configuration.

    Args:
        config: The configuration to search.
        name: The host name to find.

    Returns:
        The Host if found, None otherwise.
    """
    for host in config.hosts:
        if host.name == name:
            return host
    return None
