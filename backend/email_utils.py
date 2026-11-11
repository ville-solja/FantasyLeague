"""Minimal SMTP email sender using Python stdlib.

Configuration via environment variables:
  SMTP_HOST      — required; if not set, sending is disabled and a warning is printed
  SMTP_PORT      — default 587
  SMTP_USER      — optional SMTP login username
  SMTP_PASSWORD  — optional SMTP login password
  SMTP_FROM      — sender address; defaults to SMTP_USER if set, else "noreply@fantasy"
  SMTP_TLS       — "true" (default) uses STARTTLS; "false" uses plain SMTP (not SSL)
  SMTP_SSL       — "true" uses smtplib.SMTP_SSL (direct SSL, typically port 465);
                   takes priority over SMTP_TLS when set

Every connection uses SMTP_TIMEOUT. Log lines carry no email address.
"""
import logging
import os
import smtplib
from email.mime.text import MIMEText

_logger = logging.getLogger(__name__)

SMTP_TIMEOUT = 10  # seconds per socket operation, so a hung server can't block a caller


def email_configured() -> bool:
    """True when SMTP_HOST is set, i.e. send_email() will actually try to send."""
    return bool(os.getenv("SMTP_HOST", ""))


def send_email(to_address: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True on success, False if SMTP is not configured
    or the send failed. Logs never carry an address (recipient, sender or login): only
    the subject, counts and the error type."""
    host = os.getenv("SMTP_HOST", "")
    if not host:
        _logger.warning("SMTP_HOST not set — would have sent: %s", subject)
        return False

    port      = int(os.getenv("SMTP_PORT", "587"))
    user      = os.getenv("SMTP_USER", "")
    password  = os.getenv("SMTP_PASSWORD", "")
    from_addr = os.getenv("SMTP_FROM", user or "noreply@fantasy")
    use_ssl   = os.getenv("SMTP_SSL", "false").lower() == "true"
    use_tls   = os.getenv("SMTP_TLS", "true").lower() != "false"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = to_address

    _logger.debug(
        "SMTP config — host=%s port=%d login=%s ssl=%s tls=%s timeout=%ss",
        host, port, "set" if user else "none", use_ssl, use_tls, SMTP_TIMEOUT,
    )

    try:
        if use_ssl:
            _logger.debug("Connecting via SMTP_SSL to %s:%d", host, port)
            with smtplib.SMTP_SSL(host, port, timeout=SMTP_TIMEOUT) as smtp:
                _logger.debug("Connected (SSL)")
                if user:
                    smtp.login(user, password)
                    _logger.debug("Logged in")
                refused = smtp.sendmail(from_addr, [to_address], msg.as_string())
        elif use_tls:
            _logger.debug("Connecting via SMTP+STARTTLS to %s:%d", host, port)
            with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT) as smtp:
                smtp.ehlo()
                _logger.debug("EHLO ok")
                smtp.starttls()
                smtp.ehlo()
                _logger.debug("STARTTLS ok")
                if user:
                    smtp.login(user, password)
                    _logger.debug("Logged in")
                refused = smtp.sendmail(from_addr, [to_address], msg.as_string())
        else:
            _logger.debug("Connecting via plain SMTP to %s:%d", host, port)
            with smtplib.SMTP(host, port, timeout=SMTP_TIMEOUT) as smtp:
                if user:
                    smtp.login(user, password)
                    _logger.debug("Logged in")
                refused = smtp.sendmail(from_addr, [to_address], msg.as_string())

        if refused:
            _logger.warning("Server refused %d recipient(s)", len(refused))
        else:
            _logger.debug("sendmail accepted by server (no refused recipients)")
        _logger.info("Sent '%s'", subject)
        return True
    except Exception as e:
        code = getattr(e, "smtp_code", None)
        _logger.error("Failed to send '%s': %s%s", subject, type(e).__name__,
                      f" (SMTP {code})" if code else "")
        return False
