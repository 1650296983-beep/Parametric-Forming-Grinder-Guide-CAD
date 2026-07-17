#!/usr/bin/env python3
"""Patch only the Minisign key-ID metadata in a Tauri updater signature.

The v1.0.2 bridge release needs this because v1.0.0/v1.0.1 embedded the
correct Ed25519 public-key bytes with one incorrect key-ID byte. Minisign does
not include the key ID in either cryptographic signature, so this operation is
safe only when CI verifies both the original and patched signature against the
corresponding public-key files.
"""

from __future__ import annotations

import argparse
import base64
from pathlib import Path


KEY_ID_BYTES = 8
SIGNATURE_PREFIX_BYTES = 2
SUPPORTED_ALGORITHMS = {b"Ed", b"ED"}


def key_id_bytes(value: str) -> bytes:
    normalized = value.replace("-", "").strip()
    if len(normalized) != KEY_ID_BYTES * 2:
        raise ValueError("Minisign key ID must contain exactly 16 hexadecimal characters")
    try:
        return int(normalized, 16).to_bytes(KEY_ID_BYTES, "little")
    except ValueError as error:
        raise ValueError("Minisign key ID is not valid hexadecimal") from error


def patch_signature(signature: str, source_key_id: str, target_key_id: str) -> str:
    try:
        decoded = base64.b64decode(signature.strip(), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("Tauri updater signature is not valid outer Base64") from error

    lines = decoded.splitlines()
    if len(lines) != 4:
        raise ValueError("Tauri updater signature must contain four Minisign lines")
    try:
        primary = bytearray(base64.b64decode(lines[1], validate=True))
    except ValueError as error:
        raise ValueError("Minisign primary signature is not valid Base64") from error
    if len(primary) < SIGNATURE_PREFIX_BYTES + KEY_ID_BYTES:
        raise ValueError("Minisign primary signature is truncated")
    if bytes(primary[:SIGNATURE_PREFIX_BYTES]) not in SUPPORTED_ALGORITHMS:
        raise ValueError("Unsupported Minisign signature algorithm")

    source = key_id_bytes(source_key_id)
    target = key_id_bytes(target_key_id)
    key_id_slice = slice(SIGNATURE_PREFIX_BYTES, SIGNATURE_PREFIX_BYTES + KEY_ID_BYTES)
    if bytes(primary[key_id_slice]) != source:
        raise ValueError("Signature key ID does not match --source-key-id")
    primary[key_id_slice] = target
    lines[1] = base64.b64encode(primary).decode("ascii")
    return base64.b64encode(("\n".join(lines) + "\n").encode("utf-8")).decode("ascii")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("signature", type=Path, help="Tauri .sig file to patch in place")
    parser.add_argument("--source-key-id", required=True)
    parser.add_argument("--target-key-id", required=True)
    args = parser.parse_args()

    original = args.signature.read_text(encoding="utf-8")
    patched = patch_signature(original, args.source_key_id, args.target_key_id)
    args.signature.write_text(patched + "\n", encoding="utf-8")
    print(f"Patched updater signature key ID for {args.signature.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
