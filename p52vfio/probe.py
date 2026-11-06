"""Read PCI and libvirt state from the Ubuntu host."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from p52vfio.host import PciDev, parse_lspci, pick_nvidia
from p52vfio.rom import normalize_rom


def run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, check=False, text=True, capture_output=True)


def lspci_text() -> str:
    for args in (["lspci", "-Dnn"], ["lspci", "-nn"]):
        result = run(args)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    return ""


def nvidia_pair() -> tuple[PciDev | None, PciDev | None]:
    return pick_nvidia(parse_lspci(lspci_text()))


def full_bdf(bdf: str) -> str:
    text = bdf.lower()
    if text.count(":") >= 2:
        return text
    return "0000:" + text


def read_subsystem(bdf: str) -> tuple[int, int] | None:
    base = Path("/sys/bus/pci/devices") / full_bdf(bdf)
    try:
        vendor = int((base / "subsystem_vendor").read_text().strip(), 16)
        device = int((base / "subsystem_device").read_text().strip(), 16)
    except (OSError, ValueError):
        return None
    if vendor == 0 and device == 0:
        return None
    return vendor, device


def bound_driver(bdf: str) -> str:
    link = Path("/sys/bus/pci/devices") / full_bdf(bdf) / "driver"
    try:
        return os.path.basename(os.readlink(link))
    except OSError:
        return ""


def iommu_lines_for(bdf: str) -> list[str]:
    groups = Path("/sys/kernel/iommu_groups")
    target = full_bdf(bdf)
    if not groups.is_dir():
        return []
    for group in groups.iterdir():
        members = group / "devices"
        names = [p.name for p in members.iterdir()] if members.is_dir() else []
        if target not in names:
            continue
        lines: list[str] = []
        for name in sorted(names):
            short = name[5:] if name.startswith("0000:") else name
            result = run(["lspci", "-nns", short])
            lines.append(result.stdout.strip() or name)
        return lines
    return []


def kernel_cmdline() -> str:
    try:
        return Path("/proc/cmdline").read_text()
    except OSError:
        return ""


def valid_rom(path: str | None) -> bool:
    if not path:
        return False
    file = Path(path)
    try:
        blob = file.read_bytes()
    except OSError:
        return False
    return normalize_rom(blob) is not None


def dump_sysfs_rom(bdf: str) -> bytes:
    dev = Path("/sys/bus/pci/devices") / full_bdf(bdf)
    rom = dev / "rom"
    power = dev / "power" / "control"
    if not rom.exists():
        raise FileNotFoundError(f"{rom} does not exist")
    if power.exists():
        power.write_text("on")
    rom.write_text("1")
    try:
        return rom.read_bytes()
    finally:
        try:
            rom.write_text("0")
        except OSError:
            pass


def domain_names() -> list[str]:
    result = run(["virsh", "list", "--all", "--name"])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "virsh list failed")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def domain_xml(name: str) -> str:
    result = run(["virsh", "dumpxml", "--inactive", name])
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"virsh dumpxml {name} failed")
    return result.stdout


def domain_state(name: str) -> str:
    result = run(["virsh", "domstate", name])
    if result.returncode != 0:
        return ""
    return result.stdout.strip()
