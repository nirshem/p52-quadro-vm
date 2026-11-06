"""Host facts for a ThinkPad P52: IOMMU group, GRUB line, vfio ids."""

from __future__ import annotations

import re
from dataclasses import dataclass

GRUB_TOKENS = ("intel_iommu=on", "iommu=pt", "kvm.ignore_msrs=1")
MARKER = "p52-p1000-vfio"

_LSPCI_BDF = re.compile(
    r"^((?:[0-9a-f]{4}:)?[0-9a-f]{2}:[0-9a-f]{2}\.[0-7])\s+",
    re.I,
)
_CLASS = re.compile(r"\[([0-9a-f]{4})\]", re.I)
_VENDOR = re.compile(r"\[([0-9a-f]{4}):([0-9a-f]{4})\]", re.I)


@dataclass(frozen=True)
class PciDev:
    bdf: str
    class_id: str
    vendor: str
    device: str
    line: str

    @property
    def pci_id(self) -> str:
        return f"{self.vendor}:{self.device}"

    @property
    def full_bdf(self) -> str:
        if self.bdf.count(":") == 2:
            return self.bdf
        return "0000:" + self.bdf


def parse_lspci(text: str) -> list[PciDev]:
    found: list[PciDev] = []
    for raw in text.splitlines():
        line = raw.strip()
        match = _LSPCI_BDF.match(line)
        if not match:
            continue
        classes = _CLASS.findall(line)
        vendors = _VENDOR.findall(line)
        if not classes or not vendors:
            continue
        # The trailing [vvvv:dddd] is the device id. Class is the first [cccc].
        vendor, device = vendors[-1]
        found.append(
            PciDev(
                bdf=match.group(1).lower(),
                class_id=classes[0].lower(),
                vendor=vendor.lower(),
                device=device.lower(),
                line=line,
            )
        )
    return found


def pick_nvidia(devices: list[PciDev]) -> tuple[PciDev | None, PciDev | None]:
    """Return (display, hd-audio) for the discrete NVIDIA GPU."""
    displays = [
        d
        for d in devices
        if d.vendor == "10de" and d.class_id in {"0300", "0302"}
    ]
    if not displays:
        return None, None
    gpu = next((d for d in displays if d.device == "1cbb"), displays[0])
    slot = gpu.bdf.rsplit(".", 1)[0]
    audio = next(
        (
            d
            for d in devices
            if d.vendor == "10de"
            and d.class_id == "0403"
            and d.bdf.rsplit(".", 1)[0] == slot
        ),
        None,
    )
    return gpu, audio


def intel_vga_present(devices: list[PciDev]) -> bool:
    return any(d.vendor == "8086" and d.class_id == "0300" for d in devices)


def group_blockers(lines: list[str]) -> list[str]:
    """Devices in an IOMMU group that cannot be left behind or passed.

    PCI bridges stay on the host. The NVIDIA display and its audio function
    are the only endpoints that may share the Quadro's group.
    """
    bad: list[str] = []
    for line in lines:
        devs = parse_lspci(line)
        if not devs:
            continue
        dev = devs[0]
        if dev.class_id == "0604":
            continue
        if dev.vendor == "10de" and dev.class_id in {"0300", "0302", "0403"}:
            continue
        bad.append(line.strip())
    return bad


def merge_grub_cmdline(text: str, tokens: tuple[str, ...] = GRUB_TOKENS) -> str:
    """Add IOMMU tokens to GRUB_CMDLINE_LINUX_DEFAULT once."""

    def repl(match: re.Match[str]) -> str:
        quote = match.group(1)
        body = match.group(2)
        parts = body.split()
        for token in tokens:
            if token not in parts:
                parts.append(token)
        return f"GRUB_CMDLINE_LINUX_DEFAULT={quote}{' '.join(parts)}{quote}"

    pattern = re.compile(
        r"""^GRUB_CMDLINE_LINUX_DEFAULT=(["'])(.*)\1[ \t]*$""",
        re.M,
    )
    if not pattern.search(text):
        raise ValueError("GRUB_CMDLINE_LINUX_DEFAULT is missing from /etc/default/grub")
    return pattern.sub(repl, text, count=1)


def strip_grub_tokens(text: str, tokens: tuple[str, ...] = GRUB_TOKENS) -> str:
    def repl(match: re.Match[str]) -> str:
        quote = match.group(1)
        parts = [p for p in match.group(2).split() if p not in tokens]
        return f"GRUB_CMDLINE_LINUX_DEFAULT={quote}{' '.join(parts)}{quote}"

    pattern = re.compile(
        r"""^GRUB_CMDLINE_LINUX_DEFAULT=(["'])(.*)\1[ \t]*$""",
        re.M,
    )
    return pattern.sub(repl, text, count=1)


def vfio_conf(pci_ids: list[str]) -> str:
    ids = ",".join(pci_ids)
    return f"""# {MARKER}
options vfio-pci ids={ids} disable_vga=1 disable_idle_d3=1
softdep nouveau pre: vfio-pci
softdep nvidia pre: vfio-pci
softdep nvidia_drm pre: vfio-pci
softdep nvidia_modeset pre: vfio-pci
softdep nvidia_uvm pre: vfio-pci
softdep snd_hda_intel pre: vfio-pci
"""


def blacklist_conf() -> str:
    return f"""# {MARKER}
# The Quadro is reserved for the Windows VM. The laptop panel stays on Intel.
blacklist nouveau
blacklist nvidia
blacklist nvidia_drm
blacklist nvidia_modeset
blacklist nvidia_uvm
blacklist nvidiafb
install nouveau /bin/false
install nvidia /bin/false
install nvidia_drm /bin/false
install nvidia_modeset /bin/false
install nvidia_uvm /bin/false
"""


def initramfs_block() -> str:
    # i915 in the initramfs keeps the P52 panel up. Do not also list it in
    # /etc/modules: on this CPU it is usually built in, and a missing module
    # there delays boot.
    return f"""# BEGIN {MARKER}
vfio
vfio_iommu_type1
vfio_pci
i915
# END {MARKER}
"""


def modules_block() -> str:
    return f"""# BEGIN {MARKER}
vfio
vfio_iommu_type1
vfio_pci
# END {MARKER}
"""


def upsert_marked_block(text: str, block: str) -> str:
    pattern = re.compile(
        rf"# BEGIN {MARKER}\n.*?# END {MARKER}\n?",
        re.S,
    )
    if pattern.search(text):
        return pattern.sub(block.rstrip() + "\n", text, count=1)
    if text and not text.endswith("\n"):
        text += "\n"
    return text + block


def remove_marked_block(text: str) -> str:
    pattern = re.compile(
        rf"# BEGIN {MARKER}\n.*?# END {MARKER}\n?",
        re.S,
    )
    return pattern.sub("", text)


UDEV_RULES = f"""# {MARKER}
ACTION=="add", SUBSYSTEM=="pci", ATTR{{vendor}}=="0x10de", ATTR{{class}}=="0x030000", ATTR{{power/control}}="on"
ACTION=="add", SUBSYSTEM=="pci", ATTR{{vendor}}=="0x10de", ATTR{{class}}=="0x030200", ATTR{{power/control}}="on"
ACTION=="add", SUBSYSTEM=="pci", ATTR{{vendor}}=="0x10de", ATTR{{class}}=="0x040300", ATTR{{power/control}}="on"
"""
