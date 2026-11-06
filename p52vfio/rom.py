"""VBIOS image checks. Laptop ROMs are often empty or prefixed."""

from __future__ import annotations


def normalize_rom(blob: bytes) -> bytes | None:
    """Return a PCI option ROM, or None if the dump is not a ROM.

    Keeps every image after the first 55 AA signature. Truncating to the
    first image drops an EFI GOP image that follows the legacy ROM.
    """
    if not blob or blob == b"\xff" * len(blob):
        return None
    idx = blob.find(b"\x55\xaa")
    if idx < 0 or len(blob) - idx < 512:
        return None
    data = blob[idx:]
    head = data[:8192]
    if b"PCIR" not in head and b"NPDE" not in head and b"NVGI" not in data[:16384]:
        return None
    return data
