# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-14
"""The one place tag/category slugs are derived. Clients send names only."""
import re
import unicodedata

SLUG_MAX_LENGTH = 100


def slugify(name: str) -> str:
    """'Crème Brûlée' -> 'creme-brulee', 'Quick & Easy' -> 'quick-easy'.

    Accents fold to ASCII; every other run of non-alphanumerics becomes a single
    hyphen. Returns '' when the name has no ASCII letters or digits at all.
    """
    ascii_only = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-z0-9]+", "-", ascii_only.lower()).strip("-")
    return slug[:SLUG_MAX_LENGTH].rstrip("-")
