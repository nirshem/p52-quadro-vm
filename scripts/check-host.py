#!/usr/bin/env python3
"""Report whether this P52 can pass the Quadro P1000 to a Windows VM."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from p52vfio.host import (  # noqa: E402
    GRUB_TOKENS,
    group_blockers,
    intel_vga_present,
    parse_lspci,
)
from p52vfio.probe import (  # noqa: E402
    bound_driver,
    domain_names,
    iommu_lines_for,
    kernel_cmdline,
    lspci_text,
    nvidia_pair,
    run,
)


def main() -> int:
    devices = parse_lspci(lspci_text())
    gpu, audio = nvidia_pair()
    intel = intel_vga_present(devices)
    cmdline = kernel_cmdline()
    print("ThinkPad P52 / Quadro P1000 passthrough check")
    print(f"Intel VGA for the laptop panel: {'yes' if intel else 'NO'}")
    if gpu:
        print(f"NVIDIA display: {gpu.full_bdf} {gpu.pci_id} driver={bound_driver(gpu.full_bdf) or 'none'}")
        print(f"  {gpu.line}")
    else:
        print("NVIDIA display: not found")
    if audio:
        print(f"NVIDIA audio:   {audio.full_bdf} {audio.pci_id} driver={bound_driver(audio.full_bdf) or 'none'}")
    else:
        print("NVIDIA audio:   not found (the HDMI function must be passed with the GPU)")

    missing = [token for token in GRUB_TOKENS if token not in cmdline.split()]
    if not cmdline:
        print("Kernel command line: unreadable")
    elif missing:
        print("Kernel command line is missing: " + " ".join(missing))
    else:
        print("Kernel command line: IOMMU tokens present")

    if gpu:
        group = iommu_lines_for(gpu.full_bdf)
        if not group and not Path("/sys/kernel/iommu_groups").is_dir():
            print("IOMMU groups: none. Enable Intel VT-d in the ThinkPad BIOS and intel_iommu=on.")
        elif not group:
            print("IOMMU group: the GPU is not in a group yet.")
        else:
            print("IOMMU group:")
            for line in group:
                print(f"  {line}")
            blocked = group_blockers(group)
            if blocked:
                print("This group is not safe to bind to vfio. Other devices share it:")
                for line in blocked:
                    print(f"  {line}")
            else:
                print("IOMMU group: only the Quadro, its audio function, and bridges.")

    try:
        names = domain_names()
    except RuntimeError as exc:
        names = []
        print(f"libvirt: {exc}")
    else:
        print("Domains: " + (", ".join(names) if names else "none"))

    log = run(["sh", "-c", "dmesg 2>/dev/null | tail -n 400"])
    text = log.stdout
    if "cannot reserve" in text and "BAR" in text:
        print("dmesg: BAR reservation failed. A Code 43 guest often follows that. Try pci=realloc after the battery fix.")
    if "Failed to find romfile" in text or "failed to find romfile" in text.lower():
        print("dmesg/log: QEMU could not open the VBIOS file. Put it in /usr/share/vgabios/.")

    print()
    if gpu is None:
        print("Next: boot the host in Hybrid Graphics so the Quadro is visible, then re-run this.")
        return 1
    if not intel:
        print("Next: BIOS Config > Display > Hybrid Graphics. Discrete-only leaves Ubuntu with no panel once the Quadro is passed through.")
        return 1
    print("Code 43 is fixed in the guest XML, not by rebinding the GPU:")
    print("    sudo python3 scripts/fix-error43.py --apply")
    print("Shut Windows down first. If the external monitor stays black after that, dump a VBIOS:")
    print("    sudo python3 scripts/dump-vbios.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
