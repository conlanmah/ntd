"""Tests for ntd.terraform module."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock, call
import subprocess

from ntd.terraform import (
    TerraformError,
    TerraformPlan,
    get_outputs,
    get_host_ip,
    list_outputs,
    flatten_outputs,
    plan,
    apply,
    cleanup_plan,
)


class TestGetOutputs:
    def test_missing_directory(self, tmp_path):
        with pytest.raises(TerraformError, match="not found"):
            get_outputs(tmp_path / "nonexistent")

    @patch("subprocess.run")
    def test_terraform_command_fails(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()

        mock_run.side_effect = subprocess.CalledProcessError(
            1, "terraform", stderr="Error"
        )
        with pytest.raises(TerraformError, match="terraform output failed"):
            get_outputs(tf_path)

    @patch("subprocess.run")
    def test_terraform_not_found(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()

        mock_run.side_effect = FileNotFoundError()
        with pytest.raises(TerraformError, match="not found"):
            get_outputs(tf_path)

    @patch("subprocess.run")
    def test_invalid_json(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()

        mock_run.return_value = MagicMock(stdout="not json", returncode=0)
        with pytest.raises(TerraformError, match="parse"):
            get_outputs(tf_path)

    @patch("subprocess.run")
    def test_successful_outputs(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()

        mock_run.return_value = MagicMock(
            stdout='{"vm_ip": {"value": "192.168.1.100", "type": "string"}}',
            returncode=0,
        )
        outputs = get_outputs(tf_path)
        assert outputs == {"vm_ip": "192.168.1.100"}


class TestGetHostIp:
    def test_simple_key(self):
        outputs = {"vm_ip": "192.168.1.100"}
        assert get_host_ip(outputs, "vm_ip") == "192.168.1.100"

    def test_nested_key(self):
        outputs = {"vms": {"vm1": {"ip": "192.168.1.100"}}}
        assert get_host_ip(outputs, "vms.vm1.ip") == "192.168.1.100"

    def test_missing_key(self):
        outputs = {"vm_ip": "192.168.1.100"}
        assert get_host_ip(outputs, "missing") is None

    def test_missing_nested_key(self):
        outputs = {"vms": {"vm1": {}}}
        assert get_host_ip(outputs, "vms.vm1.ip") is None

    def test_non_string_value(self):
        outputs = {"count": 42}
        assert get_host_ip(outputs, "count") is None


class TestListOutputs:
    @patch("ntd.terraform.get_outputs")
    def test_list_outputs(self, mock_get_outputs):
        mock_get_outputs.return_value = {
            "vm_ip": "192.168.1.100",
            "container_ip": "192.168.1.101",
        }
        outputs = list_outputs(Path("/fake"))
        assert set(outputs) == {"vm_ip", "container_ip"}


class TestFlattenOutputs:
    def test_flat_outputs(self):
        outputs = {"ip": "192.168.1.100", "name": "vm1"}
        flat = flatten_outputs(outputs)
        assert flat == {"ip": "192.168.1.100", "name": "vm1"}

    def test_nested_outputs(self):
        outputs = {"vms": {"vm1": {"ip": "192.168.1.100"}}}
        flat = flatten_outputs(outputs)
        assert flat == {"vms.vm1.ip": "192.168.1.100"}

    def test_mixed_outputs(self):
        outputs = {
            "single_ip": "10.0.0.1",
            "vms": {"vm1": {"ip": "192.168.1.100"}, "vm2": {"ip": "192.168.1.101"}},
        }
        flat = flatten_outputs(outputs)
        assert flat == {
            "single_ip": "10.0.0.1",
            "vms.vm1.ip": "192.168.1.100",
            "vms.vm2.ip": "192.168.1.101",
        }

    def test_numeric_values(self):
        outputs = {"port": 8080, "ratio": 0.5}
        flat = flatten_outputs(outputs)
        assert flat == {"port": "8080", "ratio": "0.5"}


class TestTerraformPlan:
    def test_is_destructive_with_replaces(self):
        p = TerraformPlan(has_changes=True, replaces=["proxmox_vm.vm1"])
        assert p.is_destructive() is True

    def test_is_destructive_with_destroys(self):
        p = TerraformPlan(has_changes=True, destroys=["proxmox_vm.vm1"])
        assert p.is_destructive() is True

    def test_is_not_destructive_creates_and_updates(self):
        p = TerraformPlan(has_changes=True, creates=["proxmox_vm.vm1"], updates=["proxmox_vm.vm2"])
        assert p.is_destructive() is False

    def test_is_not_destructive_no_changes(self):
        p = TerraformPlan(has_changes=False)
        assert p.is_destructive() is False


class TestPlan:
    def test_missing_directory(self, tmp_path):
        with pytest.raises(TerraformError, match="not found"):
            plan(tmp_path / "nonexistent")

    @patch("subprocess.run")
    def test_terraform_not_found(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()
        mock_run.side_effect = FileNotFoundError()
        with pytest.raises(TerraformError, match="not found"):
            plan(tf_path)

    @patch("subprocess.run")
    def test_plan_error_exitcode(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()
        mock_run.return_value = MagicMock(returncode=1, stderr="Error message", stdout="")
        with pytest.raises(TerraformError, match="terraform plan failed"):
            plan(tf_path)

    @patch("subprocess.run")
    def test_plan_missing_variable_error(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()
        stderr = 'No value for required variable\nvariable "my_secret"\nsome context'
        mock_run.return_value = MagicMock(returncode=1, stderr=stderr, stdout="")
        with pytest.raises(TerraformError, match="Missing required terraform variable: my_secret"):
            plan(tf_path)

    @patch("subprocess.run")
    def test_plan_no_changes(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        result = plan(tf_path)
        assert result.has_changes is False
        assert result.creates == []
        assert result.updates == []
        assert result.replaces == []
        assert result.destroys == []

    @patch("subprocess.run")
    def test_plan_with_changes(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()
        plan_json = json.dumps({
            "resource_changes": [
                {"address": "proxmox_lxc.vm1", "change": {"actions": ["create"]}},
                {"address": "proxmox_lxc.vm2", "change": {"actions": ["update"]}},
                {"address": "proxmox_lxc.vm3", "change": {"actions": ["delete"]}},
                {"address": "proxmox_lxc.vm4", "change": {"actions": ["delete", "create"]}},
                {"address": "data.something.x", "change": {"actions": ["read"]}},
            ]
        })
        mock_run.side_effect = [
            MagicMock(returncode=2, stderr="", stdout=""),
            MagicMock(returncode=0, stderr="", stdout=plan_json),
        ]
        result = plan(tf_path)
        assert result.has_changes is True
        assert result.creates == ["proxmox_lxc.vm1"]
        assert result.updates == ["proxmox_lxc.vm2"]
        assert result.destroys == ["proxmox_lxc.vm3"]
        assert result.replaces == ["proxmox_lxc.vm4"]
        assert result.plan_file == tf_path / ".ntd-plan"

    @patch("subprocess.run")
    def test_plan_show_fails(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()
        mock_run.side_effect = [
            MagicMock(returncode=2, stderr="", stdout=""),
            subprocess.CalledProcessError(1, "terraform show", stderr="show error"),
        ]
        with pytest.raises(TerraformError, match="terraform show failed"):
            plan(tf_path)

    @patch("subprocess.run")
    def test_plan_with_target(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        plan(tf_path, target="proxmox_lxc.vm1")
        cmd = mock_run.call_args_list[0][0][0]
        assert "-target" in cmd
        assert "proxmox_lxc.vm1" in cmd


class TestApply:
    def test_missing_directory(self, tmp_path):
        with pytest.raises(TerraformError, match="not found"):
            apply(tmp_path / "nonexistent")

    @patch("subprocess.run")
    def test_terraform_not_found(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()
        mock_run.side_effect = FileNotFoundError()
        with pytest.raises(TerraformError, match="not found"):
            apply(tf_path)

    @patch("subprocess.run")
    def test_apply_with_plan_file(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()
        plan_file = tmp_path / ".ntd-plan"
        plan_file.touch()
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        apply(tf_path, plan_file=plan_file)
        cmd = mock_run.call_args_list[0][0][0]
        assert str(plan_file) in cmd

    @patch("subprocess.run")
    def test_apply_auto_approve(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()
        mock_run.return_value = MagicMock(returncode=0, stderr="", stdout="")
        apply(tf_path, auto_approve=True)
        cmd = mock_run.call_args_list[0][0][0]
        assert "-auto-approve" in cmd

    @patch("subprocess.run")
    def test_apply_fails(self, mock_run, tmp_path):
        tf_path = tmp_path / "terraform"
        tf_path.mkdir()
        mock_run.return_value = MagicMock(returncode=1, stderr="Apply error", stdout="")
        with pytest.raises(TerraformError, match="terraform apply failed"):
            apply(tf_path)


class TestCleanupPlan:
    def test_cleanup_removes_plan_file(self, tmp_path):
        plan_file = tmp_path / ".ntd-plan"
        plan_file.touch()
        cleanup_plan(TerraformPlan(has_changes=True, plan_file=plan_file))
        assert not plan_file.exists()

    def test_cleanup_no_plan_file(self):
        cleanup_plan(TerraformPlan(has_changes=False, plan_file=None))

    def test_cleanup_missing_plan_file(self, tmp_path):
        nonexistent = tmp_path / "does-not-exist"
        cleanup_plan(TerraformPlan(has_changes=True, plan_file=nonexistent))
