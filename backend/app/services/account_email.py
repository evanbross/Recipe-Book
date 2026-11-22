# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-19
"""Account emails through the admin-configured relay or environment fallback."""
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote

from sqlalchemy.orm import Session
from zt_common.smtp import send_email

from app.config import settings
from app.services.system_settings import SystemSmtpSettings

_SUBJECT_PREFIX = "RecipeBox — "

EmailKind = Literal["verification", "already_registered", "password_reset"]


# ai: claude-opus-5-5 | 2026-11-19
@dataclass(frozen=True)
class EmailToSend:
    """An email a service decided to send, handed to the route to send after it commits."""
    kind: EmailKind
    to: str
    link: str   # carries the raw single-use token, which only ever leaves the server in the email


# ai: claude-opus-5-5 | 2026-11-19
def verify_email_link(token: str) -> str:
    return f"{settings.public_url}/verify-email?token={quote(token)}"


# ai: claude-opus-5-5 | 2026-11-19
def reset_password_link(token: str) -> str:
    return f"{settings.public_url}/reset-password?token={quote(token)}"


# ai: claude-opus-5-5 | 2026-11-19
class AccountEmailService:
    """Composes and sends the account emails. Plain text only."""

    # ai: gpt-5 | 2026-11-21
    def __init__(self, db: Session) -> None:
        self._smtp = SystemSmtpSettings(db)

    def send(self, email: EmailToSend) -> None:
        if email.kind == "verification":
            self.send_verification(email.to, email.link)
        elif email.kind == "already_registered":
            self.send_already_registered(email.to, email.link)
        else:
            self.send_password_reset(email.to, email.link)

    def send_verification(self, to: str, link: str) -> None:
        self._send(to, "Confirm your email address", (
            "Someone (hopefully you) signed up for RecipeBox with this email address.\n\n"
            f"To finish creating your account, open this link within 24 hours:\n\n{link}\n\n"
            "If this wasn't you, ignore this email and no account will be created.\n"
        ))

    def send_already_registered(self, to: str, reset_link: str) -> None:
        self._send(to, "You already have an account", (
            "Someone (hopefully you) tried to sign up for RecipeBox with this email address, "
            "but it already has an account.\n\n"
            "Sign in the way you usually do. If you've forgotten your password, set a new one "
            f"within the next hour here:\n\n{reset_link}\n\n"
            "If this wasn't you, ignore this email; nothing has changed.\n"
        ))

    def send_password_reset(self, to: str, link: str) -> None:
        self._send(to, "Reset your password", (
            "Someone (hopefully you) asked to reset the RecipeBox password for this email address.\n\n"
            f"To choose a new password, open this link within the next hour:\n\n{link}\n\n"
            "Resetting signs you out everywhere else. If this wasn't you, ignore this email; "
            "your password hasn't changed.\n"
        ))

    def _send(self, to: str, subject: str, body: str) -> None:
        send_email(self._smtp.effective_config(), to=to, subject=_SUBJECT_PREFIX + subject, body_text=body)
