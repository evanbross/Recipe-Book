# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-19
"""A software passkey for tests.

Builds the same JSON a browser's navigator.credentials.create() / .get() returns
(as @simplewebauthn/browser posts it), signed with a real ES256 key, so tests go
through py_webauthn's real verify_registration_response and
verify_authentication_response. Nothing about WebAuthn is mocked.

Byte layouts follow WebAuthn Level 3: authenticator data is
rpIdHash(32) | flags(1) | signCount(4, big-endian) | [attested credential data],
attested credential data is aaguid(16) | credIdLen(2) | credId | COSE key.
"""
import hashlib
import json
import secrets
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url, encode_cbor

FLAG_UP = 0x01   # user present
FLAG_UV = 0x04   # user verified
FLAG_BE = 0x08   # backup eligible
FLAG_BS = 0x10   # backed up
FLAG_AT = 0x40   # attested credential data included


# ai: claude-opus-5-5 | 2026-11-19
@dataclass
class SoftAuthenticator:
    """One passkey: a key pair, its credential id, and the user handle it was made for."""
    rp_id: str
    origin: str
    sign_count: int = 0
    credential_id: bytes = field(default_factory=lambda: secrets.token_bytes(16))
    user_handle: bytes | None = None
    _key: ec.EllipticCurvePrivateKey = field(default_factory=lambda: ec.generate_private_key(ec.SECP256R1()))

    def create(self, options: dict, *, origin: str | None = None, rp_id: str | None = None) -> dict:
        """Answer PublicKeyCredentialCreationOptionsJSON like navigator.credentials.create()."""
        self.user_handle = base64url_to_bytes(options["user"]["id"])
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        numbers = self._key.public_key().public_numbers()
        cose_key = encode_cbor({
            1: 2,     # kty: EC2
            3: -7,    # alg: ES256
            -1: 1,    # crv: P-256
            -2: numbers.x.to_bytes(32, "big"),
            -3: numbers.y.to_bytes(32, "big"),
        })
        attested = bytes(16) + len(self.credential_id).to_bytes(2, "big") + self.credential_id + cose_key
        auth_data = self._auth_data(FLAG_UP | FLAG_UV | FLAG_AT | FLAG_BE | FLAG_BS, rp_id) + attested
        attestation = encode_cbor({"fmt": "none", "attStmt": {}, "authData": auth_data})
        cred_id = bytes_to_base64url(self.credential_id)
        return {
            "id": cred_id,
            "rawId": cred_id,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "attestationObject": bytes_to_base64url(attestation),
                "transports": ["internal", "hybrid"],
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }

    def get(
        self, options: dict, *, origin: str | None = None, rp_id: str | None = None,
        sign_count: int | None = None, user_handle: bytes | None = None,
    ) -> dict:
        """Answer PublicKeyCredentialRequestOptionsJSON like navigator.credentials.get().
        Each call bumps the signature counter unless sign_count pins it."""
        self.sign_count = sign_count if sign_count is not None else self.sign_count + 1
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        auth_data = self._auth_data(FLAG_UP | FLAG_UV | FLAG_BE | FLAG_BS, rp_id)
        signature = self._key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        cred_id = bytes_to_base64url(self.credential_id)
        handle = user_handle if user_handle is not None else self.user_handle
        return {
            "id": cred_id,
            "rawId": cred_id,
            "type": "public-key",
            "response": {
                "clientDataJSON": bytes_to_base64url(client_data),
                "authenticatorData": bytes_to_base64url(auth_data),
                "signature": bytes_to_base64url(signature),
                "userHandle": bytes_to_base64url(handle) if handle else None,
            },
            "clientExtensionResults": {},
            "authenticatorAttachment": "platform",
        }

    def _client_data(self, ceremony: str, challenge: str, origin: str | None) -> bytes:
        return json.dumps({
            "type": ceremony,
            "challenge": challenge,
            "origin": origin or self.origin,
            "crossOrigin": False,
        }).encode()

    def _auth_data(self, flags: int, rp_id: str | None) -> bytes:
        rp_id_hash = hashlib.sha256((rp_id or self.rp_id).encode()).digest()
        return rp_id_hash + bytes([flags]) + self.sign_count.to_bytes(4, "big")
