"""Known-good fake battery SSDT for mobile NVIDIA drivers."""

from __future__ import annotations

import base64

# Arch wiki "Error 43 with mobile NVIDIA GPUs" and the ThinkPad P53
# passthrough notes use this exact table. It publishes BAT0 under
# \_SB.PCI0, which is where QEMU puts the PCI bus.
SSDT_BATTERY_B64 = """
U1NEVKEAAAAB9EJPQ0hTAEJYUENTU0RUAQAAAElOVEwYEBkgoA8AFVwuX1NCX1BDSTAGABBMBi5f
U0JfUENJMFuCTwVCQVQwCF9ISUQMQdAMCghfVUlEABQJX1NUQQCkCh8UK19CSUYApBIjDQELcBcL
cBcBC9A5C1gCCywBCjwKPA0ADQANTElPTgANABQSX0JTVACkEgoEAAALcBcL0Dk=
"""

SSDT_INSTALL_PATH = "/usr/share/vgabios/ssdt-battery.aml"
ROM_INSTALL_PATH = "/usr/share/vgabios/quadro-p1000.rom"


def ssdt_battery() -> bytes:
    data = base64.b64decode("".join(SSDT_BATTERY_B64.split()))
    if data[:4] != b"SSDT":
        raise RuntimeError("embedded battery SSDT is corrupt")
    return data
