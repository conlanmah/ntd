"""Tests for ntd.nixos module."""

import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
import subprocess

from ntd.nixos import (
    NixOSError,
    list_configurations,
    build_configuration,
    copy_closure,
    activate_configuration,
    deploy,
)


class TestListConfigurations:
    def test_missing_flake(self, tmp_path):
        with pytest.raises(NixOSError, match="flake.nix not found"):
            list_configurations(tmp_path)

    @patch("subprocess.run")
    def test_nix_command_fails(self, mock_run, tmp_path):
        (tmp_path / "flake.nix").touch()
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "nix", stderr="Error"
        )
        with pytest.raises(NixOSError, match="nix flake show failed"):
            list_configurations(tmp_path)

    @patch("subprocess.run")
    def test_nix_not_found(self, mock_run, tmp_path):
        (tmp_path / "flake.nix").touch()
        mock_run.side_effect = FileNotFoundError()
        with pytest.raises(NixOSError, match="nix command not found"):
            list_configurations(tmp_path)

    @patch("subprocess.run")
    def test_successful_list(self, mock_run, tmp_path):
        (tmp_path / "flake.nix").touch()
        mock_run.return_value = MagicMock(
            stdout='{"nixosConfigurations": {"vm1": {}, "vm2": {}}}',
            returncode=0,
        )
        configs = list_configurations(tmp_path)
        assert set(configs) == {"vm1", "vm2"}

    @patch("subprocess.run")
    def test_no_configurations(self, mock_run, tmp_path):
        (tmp_path / "flake.nix").touch()
        mock_run.return_value = MagicMock(
            stdout='{"devShells": {}}',
            returncode=0,
        )
        configs = list_configurations(tmp_path)
        assert configs == []


class TestBuildConfiguration:
    @patch("subprocess.run")
    def test_build_fails(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "nix", stderr="Build error"
        )
        with pytest.raises(NixOSError, match="nix build failed"):
            build_configuration(Path("/flake"), "config")

    @patch("subprocess.run")
    def test_nix_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        with pytest.raises(NixOSError, match="nix command not found"):
            build_configuration(Path("/flake"), "config")

    @patch("subprocess.run")
    def test_empty_output(self, mock_run):
        mock_run.return_value = MagicMock(stdout="", returncode=0)
        with pytest.raises(NixOSError, match="no output"):
            build_configuration(Path("/flake"), "config")

    @patch("subprocess.run")
    def test_successful_build(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="/nix/store/abc123-nixos-system",
            returncode=0,
        )
        path = build_configuration(Path("/flake"), "config")
        assert path == Path("/nix/store/abc123-nixos-system")


class TestCopyClosure:
    @patch("subprocess.run")
    def test_copy_fails(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "nix", stderr="Copy error"
        )
        with pytest.raises(NixOSError, match="nix copy failed"):
            copy_closure(
                Path("/nix/store/abc123"),
                "192.168.1.100",
                "root",
                Path("~/.ssh/id_ed25519"),
            )

    @patch("subprocess.run")
    def test_successful_copy(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        # Should not raise
        copy_closure(
            Path("/nix/store/abc123"),
            "192.168.1.100",
            "root",
            Path("~/.ssh/id_ed25519"),
        )
        mock_run.assert_called_once()


class TestActivateConfiguration:
    @patch("subprocess.run")
    def test_activation_fails(self, mock_run):
        mock_run.side_effect = subprocess.CalledProcessError(
            1, "ssh", stderr="SSH error"
        )
        with pytest.raises(NixOSError, match="activation failed"):
            activate_configuration(
                Path("/nix/store/abc123"),
                "192.168.1.100",
                "root",
                Path("~/.ssh/id_ed25519"),
            )

    @patch("subprocess.run")
    def test_successful_activation(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)
        # Should not raise
        activate_configuration(
            Path("/nix/store/abc123"),
            "192.168.1.100",
            "root",
            Path("~/.ssh/id_ed25519"),
        )


class TestDeploy:
    @patch("ntd.nixos.activate_configuration")
    @patch("ntd.nixos.copy_closure")
    def test_deploy_calls_both(self, mock_copy, mock_activate):
        deploy(
            Path("/nix/store/abc123"),
            "192.168.1.100",
            "root",
            Path("~/.ssh/id_ed25519"),
        )
        mock_copy.assert_called_once()
        mock_activate.assert_called_once()

    @patch("ntd.nixos.copy_closure")
    def test_deploy_fails_on_copy(self, mock_copy):
        mock_copy.side_effect = NixOSError("Copy failed")
        with pytest.raises(NixOSError, match="Copy failed"):
            deploy(
                Path("/nix/store/abc123"),
                "192.168.1.100",
                "root",
                Path("~/.ssh/id_ed25519"),
            )
