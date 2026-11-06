#!/usr/bin/env python3
"""Bind the Quadro P1000 to vfio-pci and leave the Intel GPU for Ubuntu.

Dry-run unless --apply is given. Refuses to run when the laptop panel has
no Intel VGA, because blacklisting NVIDIA would then black out the machine.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from p52vfio.host import (  # noqa: E402
    MARKER,
    UDEV_RULES,
    blacklist_conf,
    group_blockers,
    initramfs_block,
    intel_vga_present,
    modules_block,
    merge_grub_cmdline,
    parse_lspci,
    remove_marked_block,
    strip_grub_tokens,
    upsert_marked_block,
    vfio_conf,
)
from p52vfio.probe import iommu_lines_for, lspci_text, nvidia_pair, run  # noqa: E402

VFIO_CONF = Path("/etc/modprobe.d/vfio-p1000.conf")
BLACKLIST = Path("/etc/modprobe.d/blacklist-nvidia-p1000.conf")
UDEV = Path("/etc/udev/rules.d/80-p1000-power.rules")
INITRAMFS = Path("/etc/initramfs-tools/modules")
MODULES = Path("/etc/modules")
GRUB = Path("/etc/default/grub")


def _require_root() -> None:
    if os.geteuid() != 0:
        raise SystemExit("sudo python3 scripts/apply-host.py --apply")


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.chmod(path, 0o644)


def _rebuild() -> None:
    initramfs = run(["update-initramfs", "-u"])
    sys.stdout.write(initramfs.stdout)
    sys.stderr.write(initramfs.stderr)
    if initramfs.returncode != 0:
        raise SystemExit(initramfs.returncode)
    grub = run(["update-grub"])
    sys.stdout.write(grub.stdout)
    sys.stderr.write(grub.stderr)
    if grub.returncode != 0:
        raise SystemExit(grub.returncode)


def undo(apply: bool) -> int:
    print("Remove vfio binding so the host can use the Quadro again.")
    if not apply:
        print("Dry run. Re-run with --undo --apply, then reboot.")
        return 0
    _require_root()
    for path in (VFIO_CONF, BLACKLIST, UDEV):
        if path.exists() and MARKER in path.read_text():
            path.unlink()
            print(f"Removed {path}")
    if INITRAMFS.exists():
        _write(INITRAMFS, remove_marked_block(INITRAMFS.read_text()))
    if MODULES.exists():
        _write(MODULES, remove_marked_block(MODULES.read_text()))
    if GRUB.exists():
        _write(GRUB, strip_grub_tokens(GRUB.read_text()))
    _rebuild()
    print("Reboot. The laptop panel stays on Intel; HDMI will work on Ubuntu again after reboot.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--undo", action="store_true")
    args = parser.parse_args()
    if args.undo:
        return undo(args.apply)

    devices = parse_lspci(lspci_text())
    if not intel_vga_present(devices):
        raise SystemExit(
            "No Intel VGA. BIOS must be Hybrid Graphics. Refusing to blacklist NVIDIA; "
            "that would leave the laptop with no display."
        )
    gpu, audio = nvidia_pair()
    if gpu is None or audio is None:
        raise SystemExit("Need both the Quadro display function and its audio function.")
    blockers = group_blockers(iommu_lines_for(gpu.full_bdf))
    if blockers:
        print("Refusing to bind vfio. These devices share the Quadro IOMMU group:")
        for line in blockers:
            print(f"  {line}")
        return 1

    ids = [gpu.pci_id, audio.pci_id]
    vfio = vfio_conf(ids)
    black = blacklist_conf()
    print(f"Will bind {gpu.full_bdf} ({gpu.pci_id}) and {audio.full_bdf} ({audio.pci_id}) to vfio-pci.")
    print("After reboot the laptop panel stays on Intel. HDMI and Mini DisplayPort go dark on Ubuntu;")
    print("they light up inside the Windows VM.")
    print()
    print(f"--- {VFIO_CONF} ---")
    print(vfio)
    print(f"--- {BLACKLIST} ---")
    print(black)
    if not args.apply:
        print("Dry run. BIOS first: Config > Display > Hybrid Graphics,")
        print("Security > Virtualization > Intel Virtualization Technology and VT-d enabled.")
        print("Then: sudo python3 scripts/apply-host.py --apply")
        print("Then reboot, then: python3 scripts/check-host.py")
        return 0

    _require_root()
    _write(VFIO_CONF, vfio)
    _write(BLACKLIST, black)
    _write(UDEV, UDEV_RULES)
    init_text = INITRAMFS.read_text() if INITRAMFS.exists() else ""
    _write(INITRAMFS, upsert_marked_block(init_text, initramfs_block()))
    mod_text = MODULES.read_text() if MODULES.exists() else ""
    _write(MODULES, upsert_marked_block(mod_text, modules_block()))
    if not GRUB.exists():
        raise SystemExit(f"{GRUB} is missing. This script only edits Ubuntu GRUB.")
    backup = Path("/etc/default/grub.p52-p1000.bak")
    if not backup.exists():
        shutil.copyfile(GRUB, backup)
    _write(GRUB, merge_grub_cmdline(GRUB.read_text()))
    _rebuild()
    print(f"GRUB backup: {backup}")
    print("Reboot the laptop, then run python3 scripts/check-host.py")
    print("The Quadro should show kernel driver vfio-pci.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
