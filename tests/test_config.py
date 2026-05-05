"""Tests for ntd.config module."""

import pytest
from pathlib import Path

from ntd.config import Config, Host, ConfigError, load_config, save_config, find_host


class TestHost:
    def test_host_creation(self):
        host = Host(
            name="vm1",
            terraform_resource="proxmox_vm.vm1",
            terraform_ip_output="vms.vm1.ip",
            nixos_configuration="vm1",
        )
        assert host.name == "vm1"
        assert host.terraform_resource == "proxmox_vm.vm1"
        assert host.terraform_ip_output == "vms.vm1.ip"
        assert host.nixos_configuration == "vm1"


class TestConfig:
    def test_config_creation(self):
        config = Config(
            terraform_path=Path("./terraform"),
            nixos_path=Path("."),
            ssh_user="root",
            ssh_key=Path("~/.ssh/id_ed25519"),
            hosts=[],
        )
        assert config.terraform_path == Path("./terraform")
        assert config.ssh_user == "root"
        assert config.hosts == []

    def test_config_with_hosts(self):
        host = Host(
            name="vm1",
            terraform_resource="proxmox_vm.vm1",
            terraform_ip_output="vms.vm1.ip",
            nixos_configuration="vm1",
        )
        config = Config(
            terraform_path=Path("./terraform"),
            nixos_path=Path("."),
            ssh_user="root",
            ssh_key=Path("~/.ssh/id_ed25519"),
            hosts=[host],
        )
        assert len(config.hosts) == 1
        assert config.hosts[0].name == "vm1"


class TestLoadConfig:
    def test_load_missing_file(self, tmp_path):
        with pytest.raises(ConfigError, match="not found"):
            load_config(tmp_path / "nonexistent.toml")

    def test_load_invalid_toml(self, tmp_path):
        config_file = tmp_path / "ntd.toml"
        config_file.write_text("invalid toml [[[")
        with pytest.raises(ConfigError, match="Invalid TOML"):
            load_config(config_file)

    def test_load_missing_required_field(self, tmp_path):
        config_file = tmp_path / "ntd.toml"
        config_file.write_text('terraform_path = "./tf"')
        with pytest.raises(ConfigError, match="Missing required field"):
            load_config(config_file)

    def test_load_valid_config(self, tmp_path):
        config_file = tmp_path / "ntd.toml"
        config_file.write_text('''
terraform_path = "./terraform"
nixos_path = "."
ssh_user = "root"
ssh_key = "~/.ssh/id_ed25519"

[[hosts]]
name = "vm1"
terraform_resource = "proxmox_vm.vm1"
terraform_ip_output = "vms.vm1.ip"
nixos_configuration = "vm1"
''')
        config = load_config(config_file)
        assert config.terraform_path == Path("./terraform")
        assert config.ssh_user == "root"
        assert len(config.hosts) == 1
        assert config.hosts[0].name == "vm1"

    def test_load_config_no_hosts(self, tmp_path):
        config_file = tmp_path / "ntd.toml"
        config_file.write_text('''
terraform_path = "./terraform"
nixos_path = "."
ssh_user = "root"
ssh_key = "~/.ssh/id_ed25519"
''')
        config = load_config(config_file)
        assert config.hosts == []


class TestSaveConfig:
    def test_save_config(self, tmp_path):
        config = Config(
            terraform_path=Path("./terraform"),
            nixos_path=Path("."),
            ssh_user="root",
            ssh_key=Path("~/.ssh/id_ed25519"),
            hosts=[
                Host(
                    name="vm1",
                    terraform_resource="proxmox_vm.vm1",
                    terraform_ip_output="vms.vm1.ip",
                    nixos_configuration="vm1",
                )
            ],
        )
        config_file = tmp_path / "ntd.toml"
        save_config(config, config_file)

        # Load it back
        loaded = load_config(config_file)
        assert loaded.terraform_path == config.terraform_path
        assert loaded.ssh_user == config.ssh_user
        assert len(loaded.hosts) == 1
        assert loaded.hosts[0].name == "vm1"


class TestFindHost:
    def test_find_existing_host(self):
        config = Config(
            terraform_path=Path("./terraform"),
            nixos_path=Path("."),
            ssh_user="root",
            ssh_key=Path("~/.ssh/id_ed25519"),
            hosts=[
                Host(
                    name="vm1",
                    terraform_resource="proxmox_vm.vm1",
                    terraform_ip_output="vms.vm1.ip",
                    nixos_configuration="vm1",
                ),
                Host(
                    name="vm2",
                    terraform_resource="proxmox_vm.vm2",
                    terraform_ip_output="vms.vm2.ip",
                    nixos_configuration="vm2",
                ),
            ],
        )
        host = find_host(config, "vm1")
        assert host is not None
        assert host.name == "vm1"

    def test_find_nonexistent_host(self):
        config = Config(
            terraform_path=Path("./terraform"),
            nixos_path=Path("."),
            ssh_user="root",
            ssh_key=Path("~/.ssh/id_ed25519"),
            hosts=[],
        )
        host = find_host(config, "vm1")
        assert host is None
