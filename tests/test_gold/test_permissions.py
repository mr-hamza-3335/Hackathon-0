"""Tests for Gold tier security/permissions system."""

import pytest
from gold.security.permissions import (
    PermissionRegistry, Sandbox, RiskTier, Permission, ActionRequest,
)


class TestPermissionRegistry:
    def setup_method(self):
        self.registry = PermissionRegistry()

    def test_default_risk_tiers(self):
        assert self.registry.get_risk_tier("read_file") == RiskTier.T0
        assert self.registry.get_risk_tier("draft_email") == RiskTier.T1
        assert self.registry.get_risk_tier("send_email") == RiskTier.T2
        assert self.registry.get_risk_tier("shell_command") == RiskTier.T3

    def test_unknown_action_defaults_to_t3(self):
        assert self.registry.get_risk_tier("unknown_action") == RiskTier.T3

    def test_check_permission_allowed(self):
        allowed, reason = self.registry.check_permission("read_file")
        assert allowed is True

    def test_check_permission_denied_unknown(self):
        allowed, reason = self.registry.check_permission("nonexistent_action")
        assert allowed is False
        assert "Unknown" in reason

    def test_check_permission_disabled(self):
        self.registry.register_permission(
            Permission(action="test_action", risk_tier=RiskTier.T0, allowed=False)
        )
        allowed, reason = self.registry.check_permission("test_action")
        assert allowed is False
        assert "disabled" in reason

    def test_requires_approval(self):
        assert self.registry.requires_approval("read_file") is False
        assert self.registry.requires_approval("send_email") is True
        assert self.registry.requires_approval("shell_command") is True

    def test_rate_limiting(self):
        self.registry.register_permission(
            Permission(action="limited_action", risk_tier=RiskTier.T0, max_per_hour=2)
        )
        # First two should pass
        self.registry.record_execution("limited_action")
        self.registry.record_execution("limited_action")
        # Third should fail
        allowed, reason = self.registry.check_permission("limited_action")
        assert allowed is False
        assert "Rate limit" in reason

    def test_approval_queue(self):
        request = ActionRequest(
            id="test-1", action="send_email", tool="email",
            parameters={}, risk_tier=RiskTier.T2,
        )
        self.registry.queue_for_approval(request)

        pending = self.registry.get_pending_approvals()
        assert len(pending) == 1
        assert pending[0].id == "test-1"

    def test_approve_request(self):
        request = ActionRequest(
            id="test-2", action="send_email", tool="email",
            parameters={}, risk_tier=RiskTier.T2,
        )
        self.registry.queue_for_approval(request)
        assert self.registry.approve_request("test-2") is True
        assert len(self.registry.get_pending_approvals()) == 0

    def test_deny_request(self):
        request = ActionRequest(
            id="test-3", action="send_email", tool="email",
            parameters={}, risk_tier=RiskTier.T2,
        )
        self.registry.queue_for_approval(request)
        assert self.registry.deny_request("test-3", "not allowed") is True
        assert len(self.registry.get_pending_approvals()) == 0


class TestSandbox:
    def setup_method(self):
        self.sandbox = Sandbox(vault_root="./vault")

    def test_validate_path_within_vault(self):
        valid, _ = self.sandbox.validate_path("vault/tasks/test.md")
        assert valid is True

    def test_validate_shell_safe_command(self):
        valid, _ = self.sandbox.validate_shell_command("echo hello")
        assert valid is True

    def test_validate_shell_blocked_rm_rf(self):
        valid, reason = self.sandbox.validate_shell_command("rm -rf /")
        assert valid is False
        assert "blocked" in reason

    def test_validate_shell_blocked_sudo(self):
        valid, reason = self.sandbox.validate_shell_command("sudo rm something")
        assert valid is False

    def test_validate_file_size_ok(self):
        valid, _ = self.sandbox.validate_file_size(1024)
        assert valid is True

    def test_validate_file_size_too_large(self):
        valid, reason = self.sandbox.validate_file_size(100 * 1024 * 1024)
        assert valid is False
        assert "exceeds" in reason
