# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-19
"""Password hashing (argon2id) and the rules a new password must meet."""
import logging

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256


# ai: claude-opus-5-5 | 2026-11-19
class WeakPasswordError(ValueError):
    """A new password breaks a rule. `reason` is a short code the frontend shows text for."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ai: claude-opus-5-5 | 2026-11-19
class PasswordHasherService:
    """argon2id with argon2-cffi's default parameters. When those defaults change
    in a library upgrade, needs_rehash() reports old hashes so sign-in can upgrade them."""

    def __init__(self, hasher: PasswordHasher | None = None) -> None:
        self._hasher = hasher or PasswordHasher()

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password_hash: str, password: str) -> bool:
        try:
            return self._hasher.verify(password_hash, password)
        except VerifyMismatchError:
            return False
        except (InvalidHashError, VerificationError) as exc:
            # A corrupt or foreign hash in the table: refuse, but leave a trail.
            logger.error("Stored password hash could not be checked: %s", type(exc).__name__)
            return False

    def needs_rehash(self, password_hash: str) -> bool:
        return self._hasher.check_needs_rehash(password_hash)

    @staticmethod
    def validate_new(password: str, email: str) -> None:
        """Raise WeakPasswordError unless the password meets the rules: 12-256
        characters and not the email address. No composition rules (NIST 800-63B)."""
        if len(password) < MIN_PASSWORD_LENGTH:
            raise WeakPasswordError("too_short")
        if len(password) > MAX_PASSWORD_LENGTH:
            raise WeakPasswordError("too_long")
        if password.strip().lower() == email.strip().lower():
            raise WeakPasswordError("same_as_email")


# Verified against when the email is unknown, so a miss takes as long as a wrong
# password and response time doesn't reveal which addresses have accounts.
DUMMY_HASH = PasswordHasherService().hash("not-a-real-password-just-burning-time")
