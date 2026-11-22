# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
"""Server-wide settings whose secrets are encrypted before database storage."""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass

from cryptography.fernet import Fernet
from sqlalchemy.orm import Session
from zt_common.smtp import SmtpConfig

from app.config import settings
from app.models import SystemSetting

SMTP_SETTINGS_KEY = "smtp"


# ai: gpt-5 | 2026-11-21
@dataclass(frozen=True)
class SmtpSettingsView:
    host: str
    port: int
    user: str
    use_tls: bool
    from_address: str
    password_set: bool
    source: str


# ai: gpt-5 | 2026-11-21
class SystemSmtpSettings:
    """Loads and updates the single outbound relay used by the whole server."""

    # ai: gpt-5 | 2026-11-21
    def __init__(self, db: Session) -> None:
        self._db = db
        key = base64.urlsafe_b64encode(hashlib.sha256(settings.secret_key.encode()).digest())
        self._cipher = Fernet(key)

    # ai: gpt-5 | 2026-11-21
    def view(self) -> SmtpSettingsView:
        stored = self._stored()
        if stored is None:
            config = settings.smtp_config
            return SmtpSettingsView(
                host=config.host, port=config.port, user=config.user, use_tls=config.use_tls,
                from_address=config.from_address, password_set=bool(config.password), source="environment",
            )
        return SmtpSettingsView(
            host=stored["host"], port=stored["port"], user=stored["user"], use_tls=stored["use_tls"],
            from_address=stored["from_address"], password_set=bool(stored.get("password")), source="database",
        )

    # ai: gpt-5 | 2026-11-21
    def effective_config(self) -> SmtpConfig:
        stored = self._stored()
        if stored is None:
            return settings.smtp_config
        encrypted = stored.get("password", "")
        password = self._cipher.decrypt(encrypted.encode()).decode() if encrypted else ""
        return SmtpConfig(
            host=stored["host"], port=stored["port"], user=stored["user"], password=password,
            use_tls=stored["use_tls"], from_address=stored["from_address"],
        )

    # ai: gpt-5 | 2026-11-21
    def save(
        self, *, host: str, port: int, user: str, password: str | None,
        use_tls: bool, from_address: str,
    ) -> SmtpSettingsView:
        existing = self._stored() or {}
        encrypted_password = existing.get("password", "")
        if password is not None:
            encrypted_password = self._cipher.encrypt(password.encode()).decode() if password else ""
        value = json.dumps({
            "host": host, "port": port, "user": user, "password": encrypted_password,
            "use_tls": use_tls, "from_address": from_address,
        }, separators=(",", ":"))
        row = self._db.get(SystemSetting, SMTP_SETTINGS_KEY)
        if row is None:
            self._db.add(SystemSetting(key=SMTP_SETTINGS_KEY, value=value))
        else:
            row.value = value
        self._db.flush()
        return self.view()

    # ai: gpt-5 | 2026-11-21
    def _stored(self) -> dict[str, object] | None:
        row = self._db.get(SystemSetting, SMTP_SETTINGS_KEY)
        return json.loads(row.value) if row is not None else None
