"""Tests for ntd.terraform module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

from ntd.terraform import (
    TerraformError,
    get_outputs,
    get_host_ip,
    list_outputs,
    flatten_outputs,
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
