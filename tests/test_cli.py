"""Tests for ntd.cli module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call
from click.testing import CliRunner

from ntd.cli import cli
from ntd.config import Config, Host
from ntd.terraform import TerraformPlan
from ntd.nixos import NixOSError
from ntd.terraform import TerraformError


@pytest.fixture
def runner():
    return CliRunner()


def _two_host_config():
    return Config(
        terraform_path=Path("./terraform"),
        nixos_path=Path("."),
        ssh_user="root",
        ssh_key=Path("~/.ssh/id_ed25519"),
        hosts=[
            Host(name="vm1", terraform_resource="proxmox_vm.vm1", terraform_ip_output="vm1_ip", nixos_configuration="vm1"),
            Host(name="vm2", terraform_resource="proxmox_vm.vm2", terraform_ip_output="vm2_ip", nixos_configuration="vm2"),
        ],
    )


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

    @patch("ntd.cli.tf_plan")
    @patch("ntd.cli.build_configuration")
    @patch("ntd.cli.get_host_ip")
    @patch("ntd.cli.get_outputs")
    @patch("ntd.cli.load_config")
    def test_plan_success(
        self, mock_load, mock_outputs, mock_get_ip, mock_build, mock_tf_plan, runner, tmp_path
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
            mock_tf_plan.assert_not_called()

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
    @patch("ntd.cli.load_config")
    def test_apply_success(
        self, mock_load, mock_outputs, mock_get_ip, mock_build, mock_deploy, runner, tmp_path
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


class TestPlanNoArgs:
    @patch("ntd.cli.cleanup_plan")
    @patch("ntd.cli.tf_plan")
    @patch("ntd.cli.build_configuration")
    @patch("ntd.cli.load_config")
    def test_plan_no_args_success(self, mock_load, mock_build, mock_tf_plan, mock_cleanup, runner, tmp_path):
        mock_load.return_value = _two_host_config()
        mock_tf_plan.return_value = TerraformPlan(has_changes=False)
        mock_build.side_effect = [Path("/nix/store/aaa-vm1"), Path("/nix/store/bbb-vm2")]

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["plan"])
            assert result.exit_code == 0
            mock_tf_plan.assert_called_once()
            assert mock_build.call_count == 2
            assert "/nix/store/aaa-vm1" in result.output
            assert "/nix/store/bbb-vm2" in result.output

    @patch("ntd.cli.cleanup_plan")
    @patch("ntd.cli.tf_plan")
    @patch("ntd.cli.build_configuration")
    @patch("ntd.cli.load_config")
    def test_plan_no_args_terraform_has_changes(self, mock_load, mock_build, mock_tf_plan, mock_cleanup, runner, tmp_path):
        mock_load.return_value = _two_host_config()
        mock_tf_plan.return_value = TerraformPlan(
            has_changes=True,
            creates=["proxmox_vm.vm3"],
            updates=[],
            replaces=[],
            destroys=[],
            plan_file=Path("/tmp/.ntd-plan"),
        )
        mock_build.side_effect = [Path("/nix/store/aaa"), Path("/nix/store/bbb")]

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["plan"])
            assert result.exit_code == 0
            assert "proxmox_vm.vm3" in result.output
            mock_cleanup.assert_called_once()

    @patch("ntd.cli.cleanup_plan")
    @patch("ntd.cli.tf_plan")
    @patch("ntd.cli.build_configuration")
    @patch("ntd.cli.load_config")
    def test_plan_no_args_nixos_build_fails(self, mock_load, mock_build, mock_tf_plan, mock_cleanup, runner, tmp_path):
        mock_load.return_value = _two_host_config()
        mock_tf_plan.return_value = TerraformPlan(has_changes=False)
        mock_build.side_effect = NixOSError("Build error")

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["plan"])
            assert result.exit_code == 1

    @patch("ntd.cli.build_configuration")
    @patch("ntd.cli.tf_plan")
    @patch("ntd.cli.load_config")
    def test_plan_no_args_terraform_warning(self, mock_load, mock_tf_plan, mock_build, runner, tmp_path):
        mock_load.return_value = _two_host_config()
        mock_tf_plan.side_effect = TerraformError("terraform not found")
        mock_build.side_effect = [Path("/nix/store/aaa"), Path("/nix/store/bbb")]

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["plan"])
            assert result.exit_code == 0
            assert "Warning" in result.output
            assert mock_build.call_count == 2


class TestApplyNoArgs:
    @patch("ntd.cli.deploy")
    @patch("ntd.cli.build_configuration")
    @patch("ntd.cli.get_host_ip")
    @patch("ntd.cli.get_outputs")
    @patch("ntd.cli.cleanup_plan")
    @patch("ntd.cli.tf_plan")
    @patch("ntd.cli.load_config")
    def test_apply_no_args_success(
        self, mock_load, mock_tf_plan, mock_cleanup, mock_outputs, mock_get_ip, mock_build, mock_deploy, runner, tmp_path
    ):
        mock_load.return_value = _two_host_config()
        mock_tf_plan.return_value = TerraformPlan(has_changes=False)
        mock_outputs.return_value = {"vm1_ip": "192.168.1.100", "vm2_ip": "192.168.1.101"}
        mock_get_ip.side_effect = lambda outputs, key: outputs.get(key)
        mock_build.side_effect = [Path("/nix/store/aaa"), Path("/nix/store/bbb")]

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["apply"])
            assert result.exit_code == 0
            mock_tf_plan.assert_called_once()
            assert mock_deploy.call_count == 2
            assert "All hosts deployed successfully" in result.output

    @patch("ntd.cli.deploy")
    @patch("ntd.cli.build_configuration")
    @patch("ntd.cli.get_host_ip")
    @patch("ntd.cli.get_outputs")
    @patch("ntd.cli.tf_plan")
    @patch("ntd.cli.load_config")
    def test_apply_no_args_skip_terraform(
        self, mock_load, mock_tf_plan, mock_outputs, mock_get_ip, mock_build, mock_deploy, runner, tmp_path
    ):
        mock_load.return_value = _two_host_config()
        mock_outputs.return_value = {"vm1_ip": "10.0.0.1", "vm2_ip": "10.0.0.2"}
        mock_get_ip.side_effect = lambda outputs, key: outputs.get(key)
        mock_build.side_effect = [Path("/nix/store/aaa"), Path("/nix/store/bbb")]

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["apply", "--skip-terraform"])
            assert result.exit_code == 0
            mock_tf_plan.assert_not_called()
            assert mock_deploy.call_count == 2

    @patch("ntd.cli.deploy")
    @patch("ntd.cli.build_configuration")
    @patch("ntd.cli.get_outputs")
    @patch("ntd.cli.cleanup_plan")
    @patch("ntd.cli.tf_plan")
    @patch("ntd.cli.load_config")
    def test_apply_no_args_skip_nixos(
        self, mock_load, mock_tf_plan, mock_cleanup, mock_outputs, mock_build, mock_deploy, runner, tmp_path
    ):
        mock_load.return_value = _two_host_config()
        mock_tf_plan.return_value = TerraformPlan(has_changes=False)

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["apply", "--skip-nixos"])
            assert result.exit_code == 0
            mock_tf_plan.assert_called_once()
            mock_deploy.assert_not_called()

    @patch("ntd.cli.deploy")
    @patch("ntd.cli.build_configuration")
    @patch("ntd.cli.get_host_ip")
    @patch("ntd.cli.get_outputs")
    @patch("ntd.cli.wait_for_ssh")
    @patch("ntd.cli.cleanup_plan")
    @patch("ntd.cli.tf_apply")
    @patch("ntd.cli.tf_plan")
    @patch("ntd.cli.load_config")
    def test_apply_no_args_with_creates_waits_for_ssh(
        self, mock_load, mock_tf_plan, mock_tf_apply, mock_cleanup, mock_wait_ssh,
        mock_outputs, mock_get_ip, mock_build, mock_deploy, runner, tmp_path
    ):
        mock_load.return_value = Config(
            terraform_path=Path("./terraform"),
            nixos_path=Path("."),
            ssh_user="root",
            ssh_key=Path("~/.ssh/id_ed25519"),
            hosts=[Host(name="vm1", terraform_resource="vm1", terraform_ip_output="vm1_ip", nixos_configuration="vm1")],
        )
        mock_tf_plan.return_value = TerraformPlan(
            has_changes=True, creates=["proxmox_lxc.vm1"], updates=[], replaces=[], destroys=[],
            plan_file=Path("/tmp/.ntd-plan"),
        )
        mock_outputs.return_value = {"vm1_ip": "10.0.0.1"}
        mock_get_ip.return_value = "10.0.0.1"
        mock_wait_ssh.return_value = (True, None)
        mock_build.return_value = Path("/nix/store/aaa")

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["apply"])
            assert result.exit_code == 0
            mock_wait_ssh.assert_called_once()
            mock_deploy.assert_called_once()

    @patch("ntd.cli.deploy")
    @patch("ntd.cli.build_configuration")
    @patch("ntd.cli.get_host_ip")
    @patch("ntd.cli.get_outputs")
    @patch("ntd.cli.wait_for_ssh")
    @patch("ntd.cli.cleanup_plan")
    @patch("ntd.cli.tf_apply")
    @patch("ntd.cli.tf_plan")
    @patch("ntd.cli.load_config")
    def test_apply_no_args_ssh_wait_fails(
        self, mock_load, mock_tf_plan, mock_tf_apply, mock_cleanup, mock_wait_ssh,
        mock_outputs, mock_get_ip, mock_build, mock_deploy, runner, tmp_path
    ):
        mock_load.return_value = Config(
            terraform_path=Path("./terraform"),
            nixos_path=Path("."),
            ssh_user="root",
            ssh_key=Path("~/.ssh/id_ed25519"),
            hosts=[Host(name="vm1", terraform_resource="vm1", terraform_ip_output="vm1_ip", nixos_configuration="vm1")],
        )
        mock_tf_plan.return_value = TerraformPlan(
            has_changes=True, creates=["proxmox_lxc.vm1"], updates=[], replaces=[], destroys=[],
            plan_file=Path("/tmp/.ntd-plan"),
        )
        mock_outputs.return_value = {"vm1_ip": "10.0.0.1"}
        mock_get_ip.return_value = "10.0.0.1"
        mock_wait_ssh.return_value = (False, "timeout")

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["apply"])
            assert result.exit_code == 1
            mock_deploy.assert_not_called()

    @patch("ntd.cli.deploy")
    @patch("ntd.cli.build_configuration")
    @patch("ntd.cli.get_host_ip")
    @patch("ntd.cli.get_outputs")
    @patch("ntd.cli.load_config")
    def test_apply_host_skip_flags_warning(
        self, mock_load, mock_outputs, mock_get_ip, mock_build, mock_deploy, runner, tmp_path
    ):
        mock_load.return_value = Config(
            terraform_path=Path("./terraform"),
            nixos_path=Path("."),
            ssh_user="root",
            ssh_key=Path("~/.ssh/id_ed25519"),
            hosts=[Host(name="vm1", terraform_resource="proxmox_vm.vm1", terraform_ip_output="vm1_ip", nixos_configuration="vm1")],
        )
        mock_outputs.return_value = {"vm1_ip": "192.168.1.100"}
        mock_get_ip.return_value = "192.168.1.100"
        mock_build.return_value = Path("/nix/store/aaa")

        with runner.isolated_filesystem(temp_dir=tmp_path):
            result = runner.invoke(cli, ["apply", "vm1", "--skip-terraform"])
            assert result.exit_code == 0
            assert "Warning" in result.output
            assert "ignored" in result.output
            mock_deploy.assert_called_once()
