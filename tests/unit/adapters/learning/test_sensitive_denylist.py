"""RED tests for sensitive denylist — argv-prefix matcher (Task 1 of 09-04).

Tests that the built-in denylist correctly identifies sensitive commands via
their first-positional-argv prefix, and leaves non-sensitive commands alone.
"""
from __future__ import annotations

import pytest

from token_sieve.adapters.learning.sensitive_denylist import matches


class TestSensitiveDenylistMatcher:
    """Tests for the sensitive denylist prefix matcher."""

    def test_aws_sts_blocked(self) -> None:
        """aws sts * is sensitive — credential retrieval."""
        assert matches("aws sts get-caller-identity") is True

    def test_aws_sts_with_subcommand_blocked(self) -> None:
        """aws sts assume-role with extra flags is still blocked."""
        assert matches("aws sts assume-role --role-arn arn:aws:iam::123:role/X") is True

    def test_gpg_decrypt_blocked(self) -> None:
        """gpg --decrypt is sensitive — decrypts secret material."""
        assert matches("gpg --decrypt secret.gpg") is True

    def test_pass_show_blocked(self) -> None:
        """pass show reveals stored passwords."""
        assert matches("pass show github/token") is True

    def test_vault_read_blocked(self) -> None:
        """vault read retrieves secret values."""
        assert matches("vault read secret/myapp") is True

    def test_kubectl_get_secret_blocked(self) -> None:
        """kubectl get secret retrieves Kubernetes secrets."""
        assert matches("kubectl get secret mysecret -o yaml") is True

    def test_op_item_get_blocked(self) -> None:
        """op item get retrieves 1Password items."""
        assert matches("op item get login") is True

    def test_gh_auth_token_blocked(self) -> None:
        """gh auth token reveals GitHub auth token."""
        assert matches("gh auth token") is True

    def test_aws_configure_get_blocked(self) -> None:
        """aws configure get reads AWS credentials from config."""
        assert matches("aws configure get aws_access_key_id") is True

    def test_ssh_add_L_blocked(self) -> None:
        """ssh-add -L lists loaded SSH identities."""
        assert matches("ssh-add -L") is True

    def test_openssl_blocked(self) -> None:
        """openssl can generate/expose cryptographic material."""
        assert matches("openssl rand -hex 32") is True

    def test_gpg_list_secret_keys_blocked(self) -> None:
        """gpg --list-secret-keys lists private keys."""
        assert matches("gpg --list-secret-keys") is True

    def test_aws_s3_ls_NOT_blocked(self) -> None:
        """aws s3 ls is NOT sensitive — only aws sts/* and aws configure get/* are."""
        assert matches("aws s3 ls") is False

    def test_pytest_NOT_blocked(self) -> None:
        """pytest is a normal development command, not sensitive."""
        assert matches("pytest tests/") is False

    def test_first_word_only_for_unmatched_binaries(self) -> None:
        """mygpg --decrypt is NOT blocked — denylist matches exact binary names."""
        assert matches("mygpg --decrypt") is False


class TestSensitiveDenylistEvasion:
    """C3 fix: denylist must not be bypassed by common shell tricks.

    All of these were evasions against the naive prefix matcher before C3.
    """

    def test_env_prefix_is_stripped(self) -> None:
        """FOO=bar before a sensitive command must still match."""
        assert matches("AWS_PROFILE=prod aws sts get-caller-identity") is True
        assert matches("FOO=bar BAR=baz gpg --decrypt secret.gpg") is True

    def test_sudo_wrapper_is_stripped(self) -> None:
        """sudo (with or without flags) must not allow bypass."""
        assert matches("sudo aws sts get-caller-identity") is True
        assert matches("sudo -u root kubectl get secret mysecret") is True

    def test_env_wrapper_is_stripped(self) -> None:
        """env (with or without flags) must not allow bypass."""
        assert matches("env aws sts get-caller-identity") is True
        assert matches("env -i PATH=/usr/bin aws sts get-caller-identity") is True

    def test_absolute_path_is_matched_by_basename(self) -> None:
        """Absolute paths like /usr/local/bin/aws must match 'aws'."""
        assert matches("/usr/local/bin/aws sts get-caller-identity") is True
        assert matches("/opt/homebrew/bin/gpg --decrypt blob.gpg") is True

    def test_bash_c_wrapper_is_recursively_matched(self) -> None:
        """bash -c 'aws sts ...' must match via recursion into the quoted argument."""
        assert matches("bash -c 'aws sts get-caller-identity'") is True
        assert matches('sh -c "gpg --decrypt secret.gpg"') is True

    def test_unterminated_quote_fails_closed(self) -> None:
        """Malformed quoting must NOT fall open — treat as sensitive."""
        # Prior behavior: shlex.split raises, function returned False (fail open).
        assert matches("aws sts 'unterminated") is True
        assert matches("gpg --decrypt 'no-close") is True

    def test_combined_evasions(self) -> None:
        """env prefix + absolute path + wrapper must still match."""
        assert matches("sudo -E AWS_REGION=us-east-1 /usr/local/bin/aws sts get-caller-identity") is True
