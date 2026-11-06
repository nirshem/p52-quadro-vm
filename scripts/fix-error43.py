#!/usr/bin/env python3
"""Patch a Windows libvirt domain so the Quadro P1000 notebook driver can start.

Dry-run by default. --apply installs the battery SSDT and defines the domain.
Shut the guest down first. A reboot does not reload a passed-through VBIOS.
"""

from __future__ import annotations

import argparse
import difflib
import os
import shutil
import sys
from pathlib import Path
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from p52vfio.domain import patch_domain  # noqa: E402
from p52vfio.probe import (  # noqa: E402
    bound_driver,
    domain_names,
    domain_state,
    domain_xml,
    full_bdf,
    nvidia_pair,
    read_subsystem,
    run,
    valid_rom,
)
from p52vfio.ssdt import ROM_INSTALL_PATH, SSDT_INSTALL_PATH, ssdt_battery  # noqa: E402

QEMU_NS = "http://libvirt.org/schemas/domain/qemu/1.0"


def _existing_rom(xml: str) -> str | None:
    root = ET.fromstring(xml)
    for hostdev in root.findall("./devices/hostdev"):
        rom = hostdev.find("rom")
        if rom is None:
            continue
        path = rom.get("file")
        if valid_rom(path):
            return path
    return None


def _choose_rom(explicit: str | None, xml: str) -> tuple[str | None, str | None]:
    """Return (source path or None, path that will be written into the XML)."""
    candidates = [explicit, ROM_INSTALL_PATH, _existing_rom(xml)]
    for path in candidates:
        if valid_rom(path):
            return path, ROM_INSTALL_PATH
    return None, None


def _choose_domain(name: str | None, gpu_bdf: str | None) -> str:
    if name:
        return name
    names = domain_names()
    if not names:
        raise SystemExit("No libvirt domains. Pass --xml, or create the Windows VM first.")
    if gpu_bdf is None:
        if len(names) == 1:
            return names[0]
        raise SystemExit("Pass --domain. Domains: " + ", ".join(names))
    matches = []
    short = gpu_bdf.lower().replace("0000:", "")
    for candidate in names:
        xml = domain_xml(candidate)
        if short in xml.lower() or full_bdf(gpu_bdf) in xml.lower():
            matches.append(candidate)
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise SystemExit(
            "No domain references the Quadro. Pass --domain. Domains: " + ", ".join(names)
        )
    raise SystemExit("More than one domain references the Quadro. Pass --domain: " + ", ".join(matches))


def _windows_steps(domain: str, hid: bool) -> str:
    hide = ""
    if not hid:
        hide = f"""
If Device Manager still says Code 43 after the driver reinstall, shut the
guest down and run plan B:

    sudo python3 scripts/fix-error43.py --domain {domain} --apply --hide-kvm

Plan B hides KVM. Leave it off unless the battery fix was not enough.
Quadro cards usually Code 43 *because* that GeForce workaround is present.
"""
    return f"""
In the Windows guest, after the VM has been started once with the new XML:

1. Open Device Manager and expand Batteries. A battery must be listed.
   If Batteries is missing, the SSDT did not load. Check
   /var/log/libvirt/qemu/{domain}.log for acpitable or AppArmor denials.
2. Expand Display adapters. Uninstall the Quadro P1000.
   Check "Attempt to remove the driver for this device" / "Delete the driver".
3. Uninstall every NVIDIA program in Apps, then reboot the guest.
4. Install the notebook driver, not GeForce Experience:
   Product type: NVIDIA RTX / Quadro
   Series: Quadro Series (Notebooks)
   Product: Quadro P1000
   OS: Windows 11
   Branch: Production Branch R580 (version 582.x).
   Do not install R595 or R620. Those branches dropped Pascal.
   https://www.nvidia.com/Download/index.aspx
5. Plug the monitor into the laptop HDMI or Mini DisplayPort before setup.
   Those ports are wired to the Quadro. The internal panel stays on Ubuntu.
   A USB-C dock is the wrong port for this GPU.
6. If Code 43 is still there after setup, disable the P1000 in Device Manager
   and enable it again. On this chip that often finishes initialization.
{hide}
Hardware Ids on the adapter should contain PCI\\VEN_10DE&DEV_1CBB.
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", help="libvirt domain name")
    parser.add_argument("--xml", type=Path, help="patch this file instead of a live domain")
    parser.add_argument("--vga", help="GPU PCI address, for example 0000:01:00.0")
    parser.add_argument("--audio", help="NVIDIA HDMI audio PCI address")
    parser.add_argument("--rom", help="VBIOS file dumped from this P1000")
    parser.add_argument("--hide-kvm", action="store_true", help="plan B: hide the hypervisor")
    parser.add_argument("--no-subsystem", action="store_true", help="do not restore subsystem ids")
    parser.add_argument("--apply", action="store_true", help="define the domain and install the SSDT")
    args = parser.parse_args()

    if args.domain and args.xml:
        parser.error("pass only one of --domain and --xml")

    gpu_bdf = args.vga
    audio_bdf = args.audio
    if gpu_bdf is None or audio_bdf is None:
        gpu, audio = nvidia_pair()
        gpu_bdf = gpu_bdf or (gpu.full_bdf if gpu else None)
        audio_bdf = audio_bdf or (audio.full_bdf if audio else None)
    if gpu_bdf is None:
        raise SystemExit("Could not find a NVIDIA GPU. Pass --vga 0000:01:00.0")

    if args.xml:
        xml = args.xml.read_text()
        domain = args.xml.stem
    else:
        domain = _choose_domain(args.domain, gpu_bdf)
        xml = domain_xml(domain)

    source_rom, rom_path = _choose_rom(args.rom, xml)
    gpu_sub = None if args.no_subsystem else read_subsystem(gpu_bdf)
    audio_sub = None if args.no_subsystem or not audio_bdf else read_subsystem(audio_bdf)
    result = patch_domain(
        xml,
        gpu_bdf=gpu_bdf,
        audio_bdf=audio_bdf,
        rom_path=rom_path,
        ssdt_path=SSDT_INSTALL_PATH,
        gpu_subsys=gpu_sub,
        audio_subsys=audio_sub,
        hide_kvm=args.hide_kvm,
    )

    print(f"Domain: {domain}")
    print(f"GPU: {gpu_bdf}  driver={bound_driver(gpu_bdf) or 'unknown'}")
    if audio_bdf:
        print(f"Audio: {audio_bdf}  driver={bound_driver(audio_bdf) or 'unknown'}")
    if source_rom:
        print(f"VBIOS: {source_rom} -> {rom_path}")
    else:
        print("VBIOS: none yet. The battery fix still applies.")
        print("Dump one while the VM is off: sudo python3 scripts/dump-vbios.py")
    if gpu_sub is None and not args.no_subsystem:
        print("Subsystem id: not visible from here. The patch still removes the GeForce workaround and adds the battery.")
    print()
    for note in result.notes:
        print(f"- {note}")
    print()

    if not args.apply:
        diff = "".join(
            difflib.unified_diff(
                xml.splitlines(keepends=True),
                result.xml.splitlines(keepends=True),
                fromfile=f"{domain}.xml",
                tofile=f"{domain}.patched.xml",
            )
        )
        print(diff or "XML already has this fix.\n")
        print("Dry run. Re-run with --apply after Windows has shut down.")
        print(_windows_steps(domain, args.hide_kvm))
        return 0

    if os.geteuid() != 0:
        raise SystemExit("sudo python3 scripts/fix-error43.py --apply")

    if not args.xml:
        state = domain_state(domain)
        if state and state != "shut off":
            raise SystemExit(
                f"{domain} is {state}. Shut it down from Windows, then re-run. "
                f"If Windows will not shut down: virsh destroy {domain}"
            )

    ssdt_path = Path(SSDT_INSTALL_PATH)
    ssdt_path.parent.mkdir(parents=True, exist_ok=True)
    ssdt_path.write_bytes(ssdt_battery())
    os.chmod(ssdt_path, 0o644)
    print(f"Installed {ssdt_path}")

    if source_rom and rom_path:
        dest = Path(rom_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if Path(source_rom).resolve() != dest.resolve():
            shutil.copyfile(source_rom, dest)
        os.chmod(dest, 0o644)
        print(f"Installed {dest}")

    if args.xml:
        backup = args.xml.with_suffix(".xml.bak")
        if not backup.exists():
            shutil.copyfile(args.xml, backup)
        args.xml.write_text(result.xml)
        print(f"Wrote {args.xml} (backup {backup})")
    else:
        backup_dir = Path("/var/tmp/p52-p1000")
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / f"{domain}.before.xml"
        backup.write_text(xml)
        patched = backup_dir / f"{domain}.patched.xml"
        patched.write_text(result.xml)
        defined = run(["virsh", "define", str(patched)])
        if defined.returncode != 0:
            sys.stderr.write(defined.stderr)
            return defined.returncode
        print(f"Defined {domain}. Previous XML: {backup}")

    print(_windows_steps(domain, args.hide_kvm))
    if gpu_sub is not None:
        print(
            "If start fails and the libvirt log names x-pci-sub-vendor-id, "
            "re-run this command with --no-subsystem."
        )
    print("Start the guest only after the steps above are in front of you.")
    print(f"    virsh start {domain}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
