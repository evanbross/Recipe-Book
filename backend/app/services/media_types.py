# =============================================================================
# Copyright (c) 2026 ZombieTech LLC. All rights reserved.
#
# SPDX-License-Identifier: PolyForm-Strict-1.0.0
# See LICENSE in the project root for the full terms.
#
# Licensing inquiries: license@zombietech.biz
# =============================================================================
# ai: claude-opus-5-5 | 2026-11-15
"""
Image media types the app accepts, in one place.

The set is what the Claude vision API accepts as image input, so an uploaded
image can always be sent for extraction, and every stored image (uploads,
scraped page images, email candidates) has the same guarantee. Kept as a leaf
module with no project imports so routes and services can all import it
without creating a cycle.
"""

SUPPORTED_IMAGE_MEDIA_TYPES: frozenset[str] = frozenset(
    {"image/jpeg", "image/png", "image/webp", "image/gif"}
)
