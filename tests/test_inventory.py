"""Tests for ntd.inventory module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from ntd.config import Config, Host
from ntd.inventory import HostStatus, check_reachable, get_inventory


class TestHostStatus:
    def test_host_status_creation(self):
        status = HostStatus(
            name="vm1",
            terraform_resource="proxmox_vm.vm1",
            nixos_config="vm1",
            ip="192.168.1.100",
            status="deployed",
        )
        assert status.name == "vm1"
        assert status.ip == "192.168.1.100"
        assert status.status == "deployed"


class TestCheckReachable:
    @patch("subprocess.run")
    def test_reachable_host(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        result = check_reachable(
            "192.168.1.100", "root", Path("~/.ssh/id_ed25519")
        )
        assert result is True

    @patch("subprocess.run")
    def test_unreachable_host(self, mock_run):
        mock_run.return_value = MagicMock(returncode=255)
        result = check_reachable(
            "192.168.1.100", "root", Path("~/.ssh/id_ed25519")
        )
        assert result is False

    @patch("subprocess.run")
    def test_ssh_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = check_reachable(
            "192.168.1.100", "root", Path("~/.ssh/id_ed25519")
        )
        assert result is False


class TestGetInventory:
    @patch("ntd.inventory.check_reachable")
    @patch("ntd.inventory.get_host_ip")
    @patch("ntd.inventory.get_outputs")
    def test_deployed_host(self, mock_outputs, mock_get_ip, mock_reachable):
        mock_outputs.return_value = {"vm1_ip": "192.168.1.100"}
        mock_get_ip.return_value = "192.168.1.100"
        mock_reachable.return_value = True

        config = Config(
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

        statuses = get_inventory(config)
        assert len(statuses) == 1
        assert statuses[0].status == "deployed"
        assert statuses[0].ip == "192.168.1.100"

    @patch("ntd.inventory.check_reachable")
    @patch("ntd.inventory.get_host_ip")
    @patch("ntd.inventory.get_outputs")
    def test_unreachable_host(self, mock_outputs, mock_get_ip, mock_reachable):
        mock_outputs.return_value = {"vm1_ip": "192.168.1.100"}
        mock_get_ip.return_value = "192.168.1.100"
        mock_reachable.return_value = False

        config = Config(
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

        statuses = get_inventory(config)
        assert len(statuses) == 1
        assert statuses[0].status == "unreachable"

    @patch("ntd.inventory.get_host_ip")
    @patch("ntd.inventory.get_outputs")
    def test_unknown_ip(self, mock_outputs, mock_get_ip):
        mock_outputs.return_value = {}
        mock_get_ip.return_value = None

        config = Config(
            terraform_path=Path("./terraform"),
            nixos_path=Path("."),
            ssh_user="root",
            ssh_key=Path("~/.ssh/id_ed25519"),
            hosts=[
                Host(
                    name="vm1",
                    terraform_resource="proxmox_vm.vm1",
                    terraform_ip_output="missing_key",
                    nixos_configuration="vm1",
                )
            ],
        )

        statuses = get_inventory(config)
        assert len(statuses) == 1
        assert statuses[0].status == "unknown"
        assert statuses[0].ip is None

    @patch("ntd.inventory.get_outputs")
    def test_terraform_error_handled(self, mock_outputs):
        from ntd.terraform import TerraformError

        mock_outputs.side_effect = TerraformError("Failed")

        config = Config(
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

        statuses = get_inventory(config)
        assert len(statuses) == 1
        assert statuses[0].status == "unknown"
