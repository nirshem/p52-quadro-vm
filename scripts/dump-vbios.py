#!/usr/bin/env python3
"""Read the Quadro P1000 option ROM from sysfs. Does not flash anything."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from p52vfio.probe import dump_sysfs_rom, nvidia_pair  # noqa: E402
from p52vfio.rom import normalize_rom  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vga", help="GPU PCI address. Default: the NVIDIA display device")
    parser.add_argument("--output", type=Path, default=Path("quadro-p1000.rom"))
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise SystemExit("sudo python3 scripts/dump-vbios.py")

    bdf = args.vga
    if not bdf:
        gpu, _audio = nvidia_pair()
        if gpu is None:
            raise SystemExit("No NVIDIA display device on this host. Pass --vga.")
        bdf = gpu.full_bdf

    print(f"Reading ROM from {bdf}. The VM must be shut down.")
    try:
        raw = dump_sysfs_rom(bdf)
    except OSError as exc:
        print(f"sysfs read failed: {exc}")
        raw = b""

    rom = normalize_rom(raw)
    if rom is None:
        failed = args.output.with_suffix(".raw")
        if raw:
            failed.write_bytes(raw)
            print(f"Wrote the unusable dump to {failed} ({len(raw)} bytes).")
        print(
            """
This laptop often exposes an empty ROM until the Quadro is awake, and an
empty ROM once vfio-pci owns the device. Two ways to get a real file:

1. Shut the VM down. If the host driver is still nouveau or nvidia, run this
   script again with an HDMI monitor plugged into the laptop HDMI port.
2. Boot Windows on the bare metal (not the VM) and save the VBIOS with GPU-Z
   (Video BIOS, save to file). Copy that file onto Ubuntu.

Then:
    sudo python3 scripts/fix-error43.py --rom /path/to/quadro-p1000.rom --apply

Do not flash that file back to the card.
"""
        )
        return 1

    args.output.write_bytes(rom)
    os.chmod(args.output, 0o644)
    print(f"Wrote {args.output} ({len(rom)} bytes).")
    print(f"sudo python3 scripts/fix-error43.py --rom {args.output} --apply")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
