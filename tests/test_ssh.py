"""Tests for ntd.ssh module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

from ntd.ssh import check_ssh, wait_for_ssh


class TestCheckSsh:
    @patch("ntd.ssh.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stderr="")

        success, error_type = check_ssh("192.168.1.100", "root", Path("/tmp/key"))

        assert success is True
        assert error_type is None

    @patch("ntd.ssh.subprocess.run")
    def test_host_key_changed(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=255,
            stderr="REMOTE HOST IDENTIFICATION HAS CHANGED!\nOffending key..."
        )

        success, error_type = check_ssh("192.168.1.100", "root", Path("/tmp/key"))

        assert success is False
        assert error_type == "host_key_changed"

    @patch("ntd.ssh.subprocess.run")
    def test_host_key_verification_failed(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=255,
            stderr="Host key verification failed."
        )

        success, error_type = check_ssh("192.168.1.100", "root", Path("/tmp/key"))

        assert success is False
        assert error_type == "host_key_changed"

    @patch("ntd.ssh.subprocess.run")
    def test_connection_failed(self, mock_run):
        mock_run.return_value = MagicMock(
            returncode=255,
            stderr="Connection refused"
        )

        success, error_type = check_ssh("192.168.1.100", "root", Path("/tmp/key"))

        assert success is False
        assert error_type == "connection_failed"

    @patch("ntd.ssh.subprocess.run")
    def test_timeout_expired(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired("ssh", 10)

        success, error_type = check_ssh("192.168.1.100", "root", Path("/tmp/key"))

        assert success is False
        assert error_type == "connection_failed"


class TestWaitForSsh:
    @patch("ntd.ssh.check_ssh")
    @patch("ntd.ssh.time.sleep")
    def test_immediate_success(self, mock_sleep, mock_check):
        mock_check.return_value = (True, None)

        success, error_type = wait_for_ssh(
            "192.168.1.100", "root", Path("/tmp/key"), timeout=10
        )

        assert success is True
        assert error_type is None
        mock_sleep.assert_not_called()

    @patch("ntd.ssh.check_ssh")
    @patch("ntd.ssh.time.sleep")
    def test_host_key_changed_fails_fast(self, mock_sleep, mock_check):
        mock_check.return_value = (False, "host_key_changed")

        success, error_type = wait_for_ssh(
            "192.168.1.100", "root", Path("/tmp/key"), timeout=120
        )

        assert success is False
        assert error_type == "host_key_changed"
        mock_sleep.assert_not_called()

    @patch("ntd.ssh.check_ssh")
    @patch("ntd.ssh.time.sleep")
    @patch("ntd.ssh.time.time")
    def test_retry_on_connection_failure(self, mock_time, mock_sleep, mock_check):
        mock_time.side_effect = [0, 0, 5, 10]
        mock_check.side_effect = [
            (False, "connection_failed"),
            (True, None),
        ]

        success, error_type = wait_for_ssh(
            "192.168.1.100", "root", Path("/tmp/key"), timeout=120
        )

        assert success is True
        assert error_type is None
        assert mock_check.call_count == 2

    @patch("ntd.ssh.check_ssh")
    @patch("ntd.ssh.time.sleep")
    @patch("ntd.ssh.time.time")
    def test_timeout(self, mock_time, mock_sleep, mock_check):
        mock_time.side_effect = [0, 0, 60, 120, 125]
        mock_check.return_value = (False, "connection_failed")

        success, error_type = wait_for_ssh(
            "192.168.1.100", "root", Path("/tmp/key"), timeout=120
        )

        assert success is False
        assert error_type == "timeout"
