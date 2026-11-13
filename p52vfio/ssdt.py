"""Known-good fake battery SSDT for mobile NVIDIA drivers."""

from __future__ import annotations

import base64

# Same BAT0 methods as the Arch wiki mobile-NVIDIA table, compiled from
# guest/ssdt-battery.asl. OEM id is LENOVO, not BOCHS: the P1000 driver
# treats a BOCHS ACPI table as a virtual machine and refuses to start.
SSDT_BATTERY_B64 = """
U1NEVKEAAAABtkxFTk9WT1RISU5LUDUyAQAAAElOVEwoBiMgoA8AFVwuX1NCX1BDSTAGABBMBi5f
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
