"""Minimal SMTP email sender using Python stdlib.

Configuration via environment variables:
  SMTP_HOST      — required; if not set, sending is disabled and a warning is printed
  SMTP_PORT      — default 587
  SMTP_USER      — optional SMTP login username
  SMTP_PASSWORD  — optional SMTP login password
  SMTP_FROM      — sender address; defaults to SMTP_USER if set, else "noreply@fantasy"
  SMTP_TLS       — "true" (default) uses STARTTLS; "false" uses plain SMTP (not SSL)
"""
import os
import smtplib
from email.mime.text import MIMEText


def send_email(to_address: str, subject: str, body: str) -> bool:
    """Send a plain-text email. Returns True on success, False if SMTP is not configured."""
    host = os.getenv("SMTP_HOST", "")
    if not host:
        print(f"[EMAIL] SMTP_HOST not set — would have sent to {to_address}: {subject}")
        return False

    port     = int(os.getenv("SMTP_PORT", "587"))
    user     = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    from_addr = os.getenv("SMTP_FROM", user or "noreply@fantasy")
    use_tls  = os.getenv("SMTP_TLS", "true").lower() != "false"

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = from_addr
    msg["To"]      = to_address

    try:
        if use_tls:
            with smtplib.SMTP(host, port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                if user:
                    smtp.login(user, password)
                smtp.sendmail(from_addr, [to_address], msg.as_string())
        else:
            with smtplib.SMTP(host, port) as smtp:
                if user:
                    smtp.login(user, password)
                smtp.sendmail(from_addr, [to_address], msg.as_string())
        print(f"[EMAIL] Sent '{subject}' to {to_address}")
        return True
    except Exception as e:
        print(f"[EMAIL] Failed to send to {to_address}: {e}")
        return False
