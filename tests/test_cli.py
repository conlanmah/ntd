"""Tests for ntd.cli module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from click.testing import CliRunner

from ntd.cli import cli
from ntd.config import Config, Host


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def sample_config(tmp_path):
    """Create a sample config file."""
    config_content = '''
terraform_path = "./terraform"
nixos_path = "."
ssh_user = "root"
ssh_key = "~/.ssh/id_ed25519"

[[hosts]]
name = "vm1"
terraform_resource = "proxmox_vm.vm1"
terraform_ip_output = "vm1_ip"
nixos_configuration = "vm1"
'''
    config_file = tmp_path / "ntd.toml"
    config_file.write_text(config_content)
    return config_file


class TestCli:
    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "ntd - NixOS Terraform Deployer" in result.output

    def test_commands_exist(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert "init" in result.output
        assert "inventory" in result.output
        assert "plan" in result.output
        assert "apply" in result.output


class TestInventoryCommand:
    def test_no_config(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["inventory"])
            assert result.exit_code == 1
            assert "not found" in result.output or "Error" in result.output

    @patch("ntd.cli.get_inventory")
    @patch("ntd.cli.load_config")
    def test_inventory_display(self, mock_load, mock_inventory, runner, tmp_path):
        mock_load.return_value = Config(
            terraform_path=Path("./terraform"),
            nixos_path=Path("."),
            ssh_user="root",
            ssh_key=Path("~/.ssh/id_ed25519"),
            hosts=[
                Host(
                    name="vm1",
                    terraform_resource="proxmox_vm.vm1",
                    terraform_ip_output="vm1_ip",
                    nixos_configuration="vm1",
                )
            ],
        )

        from ntd.inventory import HostStatus

        mock_inventory.return_value = [
            HostStatus(
                name="vm1",
                terraform_resource="proxmox_vm.vm1",
                nixos_config="vm1",
                ip="192.168.1.100",
                status="deployed",
            )
        ]

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["inventory"])
            assert result.exit_code == 0
            assert "vm1" in result.output
            assert "192.168.1.100" in result.output


class TestPlanCommand:
    def test_no_config(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["plan", "vm1"])
            assert result.exit_code == 1

    @patch("ntd.cli.build_configuration")
    @patch("ntd.cli.get_host_ip")
    @patch("ntd.cli.get_outputs")
    @patch("ntd.cli.load_config")
    def test_plan_success(
        self, mock_load, mock_outputs, mock_get_ip, mock_build, runner, tmp_path
    ):
        mock_load.return_value = Config(
            terraform_path=Path("./terraform"),
            nixos_path=Path("."),
            ssh_user="root",
            ssh_key=Path("~/.ssh/id_ed25519"),
            hosts=[
                Host(
                    name="vm1",
                    terraform_resource="proxmox_vm.vm1",
                    terraform_ip_output="vm1_ip",
                    nixos_configuration="vm1",
                )
            ],
        )
        mock_outputs.return_value = {"vm1_ip": "192.168.1.100"}
        mock_get_ip.return_value = "192.168.1.100"
        mock_build.return_value = Path("/nix/store/abc123-nixos-system")

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["plan", "vm1"])
            assert result.exit_code == 0
            assert "vm1" in result.output
            assert "/nix/store/abc123-nixos-system" in result.output

    @patch("ntd.cli.load_config")
    def test_plan_host_not_found(self, mock_load, runner, tmp_path):
        mock_load.return_value = Config(
            terraform_path=Path("./terraform"),
            nixos_path=Path("."),
            ssh_user="root",
            ssh_key=Path("~/.ssh/id_ed25519"),
            hosts=[],
        )

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["plan", "nonexistent"])
            assert result.exit_code == 1
            assert "not found" in result.output


class TestApplyCommand:
    def test_no_config(self, runner, tmp_path):
        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["apply", "vm1"])
            assert result.exit_code == 1

    @patch("ntd.cli.deploy")
    @patch("ntd.cli.build_configuration")
    @patch("ntd.cli.get_host_ip")
    @patch("ntd.cli.get_outputs")
    @patch("ntd.cli.tf_plan")
    @patch("ntd.cli.load_config")
    def test_apply_success(
        self, mock_load, mock_tf_plan, mock_outputs, mock_get_ip, mock_build, mock_deploy, runner, tmp_path
    ):
        from ntd.terraform import TerraformPlan

        mock_load.return_value = Config(
            terraform_path=Path("./terraform"),
            nixos_path=Path("."),
            ssh_user="root",
            ssh_key=Path("~/.ssh/id_ed25519"),
            hosts=[
                Host(
                    name="vm1",
                    terraform_resource="proxmox_vm.vm1",
                    terraform_ip_output="vm1_ip",
                    nixos_configuration="vm1",
                )
            ],
        )
        mock_tf_plan.return_value = TerraformPlan(has_changes=False)
        mock_outputs.return_value = {"vm1_ip": "192.168.1.100"}
        mock_get_ip.return_value = "192.168.1.100"
        mock_build.return_value = Path("/nix/store/abc123-nixos-system")

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["apply", "vm1"])
            assert result.exit_code == 0
            assert "Successfully deployed" in result.output
            mock_deploy.assert_called_once()

    @patch("ntd.cli.load_config")
    def test_apply_host_not_found(self, mock_load, runner, tmp_path):
        mock_load.return_value = Config(
            terraform_path=Path("./terraform"),
            nixos_path=Path("."),
            ssh_user="root",
            ssh_key=Path("~/.ssh/id_ed25519"),
            hosts=[],
        )

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["apply", "nonexistent"])
            assert result.exit_code == 1
            assert "not found" in result.output
