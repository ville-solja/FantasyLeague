"""Tests for plan-issue-67-gmail-smtp-integration.

Coverage map
------------
Story 1 — Configure Gmail as SMTP Sender:
  test_starttls_sends_email_with_valid_credentials
  test_env_example_contains_gmail_block
  test_feature_doc_exists
  test_smtp_host_unset_returns_false_no_exception          [failure path]

Story 2 — Support Gmail SSL Connection (Port 465):
  test_smtp_ssl_true_uses_smtp_ssl_class
  test_smtp_ssl_port_465_sends_successfully
  test_smtp_ssl_takes_priority_over_smtp_tls
  test_smtp_ssl_documented_in_env_example
  test_smtp_ssl_wrong_credentials_returns_false_no_exception  [failure path]
"""

import os
import re
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Story 1 — Configure Gmail as SMTP Sender
# ---------------------------------------------------------------------------

class TestConfigureGmailStarttls:

    def test_starttls_sends_email_with_valid_credentials(self, monkeypatch):
        """SMTP_TLS=true causes smtplib.SMTP with STARTTLS to be used and returns True."""
        monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
        monkeypatch.setenv("SMTP_PORT", "587")
        monkeypatch.setenv("SMTP_USER", "you@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "xxxx xxxx xxxx xxxx")
        monkeypatch.setenv("SMTP_TLS", "true")
        monkeypatch.delenv("SMTP_SSL", raising=False)

        with patch("smtplib.SMTP") as mock_smtp_cls:
            mock_smtp = MagicMock()
            mock_smtp_cls.return_value.__enter__ = lambda s: mock_smtp
            mock_smtp_cls.return_value.__exit__ = MagicMock(return_value=False)
            import importlib
            import email_utils
            importlib.reload(email_utils)
            result = email_utils.send_email("to@example.com", "Subject", "Body")

        assert result is True
        mock_smtp.starttls.assert_called_once()
        mock_smtp_cls.assert_called_once_with("smtp.gmail.com", 587)

    def test_env_example_contains_gmail_block(self):
        """The .env.example file contains a commented Gmail example block."""
        env_example = os.path.join(
            os.path.dirname(__file__), "..", "..", ".env.example"
        )
        with open(os.path.abspath(env_example)) as f:
            content = f.read()
        # Use anchored regex so the check is for the specific config line,
        # not an arbitrary substring match (avoids CodeQL url-sanitization FP).
        assert re.search(r"^#?\s*SMTP_HOST=smtp\.gmail\.com\s*$", content, re.MULTILINE), \
            "smtp.gmail.com SMTP_HOST example not found in .env.example"
        assert re.search(r"^#?\s*SMTP_PASSWORD=xxxx xxxx xxxx xxxx\s*$", content, re.MULTILINE), \
            "App Password example not found in .env.example"

    def test_feature_doc_exists(self):
        """markdown/features/reference/gmail-smtp-integration.md exists."""
        doc_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "markdown", "features",
            "reference", "gmail-smtp-integration.md"
        )
        assert os.path.isfile(os.path.abspath(doc_path))

    def test_smtp_host_unset_returns_false_no_exception(self, monkeypatch):
        """When SMTP_HOST is not set, send_email returns False and raises no exception."""
        monkeypatch.delenv("SMTP_HOST", raising=False)

        import importlib
        import email_utils
        importlib.reload(email_utils)
        result = email_utils.send_email("to@example.com", "Subject", "Body")
        assert result is False


# ---------------------------------------------------------------------------
# Story 2 — Support Gmail SSL Connection (Port 465)
# ---------------------------------------------------------------------------

class TestGmailSslConnection:

    def test_smtp_ssl_true_uses_smtp_ssl_class(self, monkeypatch):
        """SMTP_SSL=true causes smtplib.SMTP_SSL to be used instead of smtplib.SMTP."""
        monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
        monkeypatch.setenv("SMTP_PORT", "465")
        monkeypatch.setenv("SMTP_USER", "you@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "xxxx xxxx xxxx xxxx")
        monkeypatch.setenv("SMTP_SSL", "true")

        with patch("smtplib.SMTP_SSL") as mock_ssl_cls, \
             patch("smtplib.SMTP") as mock_smtp_cls:
            mock_ssl = MagicMock()
            mock_ssl_cls.return_value.__enter__ = lambda s: mock_ssl
            mock_ssl_cls.return_value.__exit__ = MagicMock(return_value=False)
            import importlib
            import email_utils
            importlib.reload(email_utils)
            result = email_utils.send_email("to@example.com", "Subject", "Body")

        assert result is True
        mock_ssl_cls.assert_called_once_with("smtp.gmail.com", 465)
        mock_smtp_cls.assert_not_called()

    def test_smtp_ssl_port_465_sends_successfully(self, monkeypatch):
        """SMTP_SSL=true with smtp.gmail.com:465 and valid credentials returns True."""
        monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
        monkeypatch.setenv("SMTP_PORT", "465")
        monkeypatch.setenv("SMTP_USER", "you@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "xxxx xxxx xxxx xxxx")
        monkeypatch.setenv("SMTP_SSL", "true")

        with patch("smtplib.SMTP_SSL") as mock_ssl_cls:
            mock_ssl = MagicMock()
            mock_ssl_cls.return_value.__enter__ = lambda s: mock_ssl
            mock_ssl_cls.return_value.__exit__ = MagicMock(return_value=False)
            import importlib
            import email_utils
            importlib.reload(email_utils)
            result = email_utils.send_email("to@example.com", "Subject", "Body")

        assert result is True
        mock_ssl.sendmail.assert_called_once()

    def test_smtp_ssl_takes_priority_over_smtp_tls(self, monkeypatch):
        """SMTP_SSL=true takes the SSL path even when SMTP_TLS=false; plain SMTP is not used."""
        monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
        monkeypatch.setenv("SMTP_PORT", "465")
        monkeypatch.setenv("SMTP_USER", "you@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "xxxx xxxx xxxx xxxx")
        monkeypatch.setenv("SMTP_SSL", "true")
        monkeypatch.setenv("SMTP_TLS", "false")

        with patch("smtplib.SMTP_SSL") as mock_ssl_cls, \
             patch("smtplib.SMTP") as mock_smtp_cls:
            mock_ssl = MagicMock()
            mock_ssl_cls.return_value.__enter__ = lambda s: mock_ssl
            mock_ssl_cls.return_value.__exit__ = MagicMock(return_value=False)
            import importlib
            import email_utils
            importlib.reload(email_utils)
            result = email_utils.send_email("to@example.com", "Subject", "Body")

        assert result is True
        mock_ssl_cls.assert_called_once_with("smtp.gmail.com", 465)
        mock_smtp_cls.assert_not_called()

    def test_smtp_ssl_documented_in_env_example(self):
        """SMTP_SSL env var appears in .env.example."""
        env_example = os.path.join(
            os.path.dirname(__file__), "..", "..", ".env.example"
        )
        with open(os.path.abspath(env_example)) as f:
            content = f.read()
        assert "SMTP_SSL=true" in content

    def test_smtp_ssl_wrong_credentials_returns_false_no_exception(self, monkeypatch):
        """SMTP_SSL=true but login raises SMTPAuthenticationError → send_email returns False."""
        import smtplib

        monkeypatch.setenv("SMTP_HOST", "smtp.gmail.com")
        monkeypatch.setenv("SMTP_PORT", "465")
        monkeypatch.setenv("SMTP_USER", "you@gmail.com")
        monkeypatch.setenv("SMTP_PASSWORD", "wrong-password")
        monkeypatch.setenv("SMTP_SSL", "true")

        with patch("smtplib.SMTP_SSL") as mock_ssl_cls:
            mock_ssl = MagicMock()
            mock_ssl.login.side_effect = smtplib.SMTPAuthenticationError(535, b"Bad credentials")
            mock_ssl_cls.return_value.__enter__ = lambda s: mock_ssl
            mock_ssl_cls.return_value.__exit__ = MagicMock(return_value=False)
            import importlib
            import email_utils
            importlib.reload(email_utils)
            result = email_utils.send_email("to@example.com", "Subject", "Body")

        assert result is False
