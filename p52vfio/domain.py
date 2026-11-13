"""Libvirt domain edits that clear Code 43 on a Quadro P1000."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

QEMU_NS = "http://libvirt.org/schemas/domain/qemu/1.0"
ET.register_namespace("qemu", QEMU_NS)

GPU_ALIAS = "ua-p1000"
AUDIO_ALIAS = "ua-p1000-hda"
HIDE_VENDOR_ID = "GenuineIntel"  # exactly 12 characters, required by QEMU


def qtag(name: str) -> str:
    return f"{{{QEMU_NS}}}{name}"


@dataclass
class PatchResult:
    xml: str
    notes: list[str] = field(default_factory=list)


def parse_bdf(bdf: str) -> tuple[int, int, int, int]:
    match = re.fullmatch(
        r"(?:([0-9a-f]{1,4}):)?([0-9a-f]{1,2}):([0-9a-f]{1,2})\.([0-7])",
        bdf.lower(),
    )
    if not match:
        raise ValueError(f"not a PCI address: {bdf}")
    domain = int(match.group(1) or "0", 16)
    return domain, int(match.group(2), 16), int(match.group(3), 16), int(match.group(4), 16)


def _addr_tuple(el: ET.Element) -> tuple[int, int, int, int] | None:
    if el.get("bus") is None or el.get("slot") is None or el.get("function") is None:
        return None
    return (
        int(el.get("domain", "0"), 16),
        int(el.get("bus", "0"), 16),
        int(el.get("slot", "0"), 16),
        int(el.get("function", "0"), 16),
    )


def _hex(n: int, width: int = 2) -> str:
    return f"0x{n:0{width}x}"


def clean_cpu_arg(value: str) -> str:
    """Drop GeForce-only CPU flags. Quadro Code 43 gets worse with kvm=off."""
    text = value
    text = re.sub(r"(^|,)kvm=off", "", text)
    text = re.sub(r"(^|,)hv_vendor_id=[^,]*", "", text)
    text = re.sub(r",,", ",", text).strip(",")
    return text


def _ensure_child(parent: ET.Element, tag: str) -> ET.Element:
    found = parent.find(tag)
    if found is None:
        found = ET.SubElement(parent, tag)
    return found


def _host_source_address(hostdev: ET.Element) -> ET.Element | None:
    source = hostdev.find("source")
    if source is None:
        return None
    return source.find("address")


def _guest_address(hostdev: ET.Element) -> ET.Element | None:
    for child in list(hostdev):
        if child.tag == "address" and child.get("type") == "pci":
            return child
    return None


def _matches(addr: ET.Element | None, bdf: str) -> bool:
    if addr is None:
        return False
    return _addr_tuple(addr) == parse_bdf(bdf)


def _find_hostdev(root: ET.Element, bdf: str) -> ET.Element | None:
    for hostdev in root.findall("./devices/hostdev"):
        if hostdev.get("type") != "pci":
            continue
        if _matches(_host_source_address(hostdev), bdf):
            return hostdev
    return None


def _strip_geforce_hide(root: ET.Element, notes: list[str]) -> None:
    features = root.find("features")
    if features is not None:
        kvm = features.find("kvm")
        if kvm is not None:
            hidden = kvm.find("hidden")
            if hidden is not None:
                kvm.remove(hidden)
                notes.append("Removed <kvm><hidden>. On a Quadro that spoof causes Code 43.")
            if len(list(kvm)) == 0 and not kvm.attrib:
                features.remove(kvm)
        hyperv = features.find("hyperv")
        if hyperv is not None:
            vendor = hyperv.find("vendor_id")
            if vendor is not None:
                hyperv.remove(vendor)
                notes.append("Removed Hyper-V vendor_id spoof.")
            if len(list(hyperv)) == 0:
                features.remove(hyperv)
    cpu = root.find("cpu")
    if cpu is not None:
        for feature in list(cpu.findall("feature")):
            if feature.get("name") == "hypervisor":
                cpu.remove(feature)
                notes.append("Stopped hiding the hypervisor CPUID bit.")
    cmdline = root.find(qtag("commandline"))
    if cmdline is not None:
        args = [a for a in list(cmdline) if a.tag == qtag("arg")]
        index = 0
        while index < len(args):
            value = args[index].get("value", "")
            if value == "-set" and index + 1 < len(args):
                nxt = args[index + 1].get("value", "")
                if "x-pci-device-id" in nxt or "x-pci-vendor-id" in nxt or "x-pci-sub-" in nxt:
                    cmdline.remove(args[index])
                    cmdline.remove(args[index + 1])
                    notes.append(f"Removed QEMU -set {nxt}.")
                    index += 2
                    continue
            cleaned = clean_cpu_arg(value)
            if cleaned != value:
                if cleaned:
                    args[index].set("value", cleaned)
                else:
                    cmdline.remove(args[index])
                notes.append("Removed kvm=off / hv_vendor_id from the QEMU CPU argument.")
            index += 1
        if not list(cmdline):
            root.remove(cmdline)


def _enable_hide(root: ET.Element, notes: list[str]) -> None:
    if len(HIDE_VENDOR_ID) != 12:
        raise RuntimeError("vendor_id must be 12 characters")
    features = _ensure_child(root, "features")
    kvm = features.find("kvm")
    if kvm is None:
        kvm = ET.Element("kvm")
        ioapic = features.find("ioapic")
        if ioapic is None:
            features.append(kvm)
        else:
            features.insert(list(features).index(ioapic), kvm)
    hidden = _ensure_child(kvm, "hidden")
    hidden.set("state", "on")
    hyperv = _ensure_child(features, "hyperv")
    hyperv.set("mode", "custom")
    vendor = _ensure_child(hyperv, "vendor_id")
    vendor.set("state", "on")
    vendor.set("value", HIDE_VENDOR_ID)
    cpu = root.find("cpu")
    if cpu is not None and cpu.find("feature[@name='hypervisor']") is None:
        ET.SubElement(cpu, "feature", {"policy": "disable", "name": "hypervisor"})
    notes.append(
        "Plan B: hid KVM from the guest. Use this only if Code 43 remains after the battery fix."
    )


def _ensure_ioapic(root: ET.Element, notes: list[str]) -> None:
    features = _ensure_child(root, "features")
    ioapic = features.find("ioapic")
    if ioapic is None:
        ioapic = ET.Element("ioapic", {"driver": "kvm"})
        # Keep ACPI/APIC first; append is valid and simpler.
        features.append(ioapic)
        notes.append("Set the I/O APIC to the KVM driver so the GPU interrupt is delivered.")
    elif ioapic.get("driver") != "kvm":
        ioapic.set("driver", "kvm")
        notes.append("Switched the I/O APIC driver to kvm.")


def _ensure_alias(hostdev: ET.Element, name: str) -> None:
    alias = hostdev.find("alias")
    if alias is None:
        alias = ET.Element("alias", {"name": name})
        hostdev.insert(0, alias)
    else:
        alias.set("name", name)


def _set_rom(hostdev: ET.Element, rom_path: str | None) -> None:
    rom = hostdev.find("rom")
    if rom_path is None:
        if rom is not None:
            hostdev.remove(rom)
        return
    if rom is None:
        rom = ET.SubElement(hostdev, "rom")
    rom.set("bar", "on")
    rom.set("file", rom_path)
    if "enabled" in rom.attrib:
        del rom.attrib["enabled"]


def _guest_pci_taken(root: ET.Element, addr: tuple[int, int, int, int], skip: ET.Element | None) -> bool:
    for el in root.findall(".//address"):
        if el is skip or el.get("type") != "pci":
            continue
        if _addr_tuple(el) == addr:
            return True
    return False


def _place_audio_beside_gpu(gpu: ET.Element, audio: ET.Element, root: ET.Element, notes: list[str]) -> None:
    gpu_addr = _guest_address(gpu)
    audio_addr = _guest_address(audio)
    if gpu_addr is None:
        notes.append("GPU has no guest PCI address yet; left the audio function where it is.")
        return
    parsed = _addr_tuple(gpu_addr)
    if parsed is None:
        notes.append("GPU guest PCI address is incomplete; left the audio function where it is.")
        return
    domain, bus, slot, _func = parsed
    target = (domain, bus, slot, 1)
    gpu_addr.set("function", "0x0")
    gpu_addr.set("multifunction", "on")
    if audio_addr is not None and _addr_tuple(audio_addr) == target:
        audio_addr.attrib.pop("multifunction", None)
        notes.append("HDMI audio is already function 1 of the GPU.")
        return
    if _guest_pci_taken(root, target, audio_addr):
        notes.append(
            "Could not move HDMI audio to function 1: that PCI function is already used. "
            "Code 43 often remains until the audio function shares the GPU slot."
        )
        return
    if audio_addr is None:
        audio_addr = ET.SubElement(audio, "address")
    audio_addr.set("type", "pci")
    audio_addr.set("domain", _hex(domain, 4))
    audio_addr.set("bus", _hex(bus))
    audio_addr.set("slot", _hex(slot))
    audio_addr.set("function", "0x1")
    audio_addr.attrib.pop("multifunction", None)
    notes.append("Moved the NVIDIA HDMI audio device to function 1 of the GPU.")


def _override(root: ET.Element) -> ET.Element:
    found = root.find(qtag("override"))
    if found is None:
        found = ET.SubElement(root, qtag("override"))
    return found


def _device_frontend(override: ET.Element, alias: str) -> ET.Element:
    for device in override.findall(qtag("device")):
        if device.get("alias") == alias:
            frontend = device.find(qtag("frontend"))
            if frontend is None:
                frontend = ET.SubElement(device, qtag("frontend"))
            return frontend
    device = ET.SubElement(override, qtag("device"), {"alias": alias})
    return ET.SubElement(device, qtag("frontend"))


def _set_unsigned(frontend: ET.Element, name: str, value: int) -> None:
    for prop in list(frontend.findall(qtag("property"))):
        if prop.get("name") == name:
            prop.set("type", "unsigned")
            prop.set("value", str(value))
            return
    ET.SubElement(
        frontend,
        qtag("property"),
        {"name": name, "type": "unsigned", "value": str(value)},
    )


def _drop_id_spoof(frontend: ET.Element) -> None:
    for prop in list(frontend.findall(qtag("property"))):
        if prop.get("name") in {"x-pci-device-id", "x-pci-vendor-id"}:
            frontend.remove(prop)


def _apply_subsystem(
    root: ET.Element,
    alias: str,
    subsys: tuple[int, int] | None,
    notes: list[str],
    label: str,
) -> None:
    if subsys is None:
        return
    vendor, device = subsys
    frontend = _device_frontend(_override(root), alias)
    _drop_id_spoof(frontend)
    _set_unsigned(frontend, "x-pci-sub-vendor-id", vendor)
    _set_unsigned(frontend, "x-pci-sub-device-id", device)
    notes.append(
        f"Restored {label} subsystem id {vendor:#06x}:{device:#06x}. "
        "QEMU sometimes presents 0000:0000, and the notebook driver then fails."
    )


def _set_acpi_oem(root: ET.Element, notes: list[str]) -> None:
    """QEMU labels every ACPI table BOCHS. The notebook driver treats that as a VM."""
    cmdline = root.find(qtag("commandline"))
    if cmdline is None:
        cmdline = ET.SubElement(root, qtag("commandline"))
    target = "x-oem-id=LENOVO,x-oem-table-id=THINKP52"
    args = [a for a in list(cmdline) if a.tag == qtag("arg")]
    for arg in args:
        if (arg.get("value") or "").startswith("x-oem-id="):
            if arg.get("value") != target:
                arg.set("value", target)
                notes.append("Set the ACPI OEM id to LENOVO so the notebook driver does not see BOCHS.")
            return
    ET.SubElement(cmdline, qtag("arg"), {"value": "-machine"})
    ET.SubElement(cmdline, qtag("arg"), {"value": target})
    notes.append("Set the ACPI OEM id to LENOVO so the notebook driver does not see BOCHS.")


def _set_acpitable(root: ET.Element, ssdt_path: str, notes: list[str]) -> None:
    cmdline = root.find(qtag("commandline"))
    if cmdline is None:
        cmdline = ET.SubElement(root, qtag("commandline"))
    args = [a for a in list(cmdline) if a.tag == qtag("arg")]
    for index, arg in enumerate(args):
        if arg.get("value") == "-acpitable" and index + 1 < len(args):
            nxt = args[index + 1]
            if nxt.get("value", "").startswith("file="):
                previous = nxt.get("value")
                nxt.set("value", f"file={ssdt_path}")
                if previous != f"file={ssdt_path}":
                    notes.append(f"Pointed the fake battery SSDT at {ssdt_path}.")
                return
    ET.SubElement(cmdline, qtag("arg"), {"value": "-acpitable"})
    ET.SubElement(cmdline, qtag("arg"), {"value": f"file={ssdt_path}"})
    notes.append(
        "Added a fake battery under \\_SB.PCI0. The P1000 notebook driver returns Code 43 when the guest has no battery."
    )


def _ensure_spice(root: ET.Element, notes: list[str]) -> None:
    devices = _ensure_child(root, "devices")
    videos = devices.findall("video")
    if not videos:
        video = ET.SubElement(devices, "video")
        ET.SubElement(video, "model", {"type": "virtio", "heads": "1"})
        notes.append("Added a virtio display so the guest stays reachable while the Quadro is in Code 43.")
    else:
        for video in videos:
            model = video.find("model")
            if model is not None and model.get("type") == "none":
                model.set("type", "virtio")
                model.set("heads", model.get("heads", "1"))
                notes.append("Replaced the disabled video device with virtio so Windows can be operated from virt-manager.")
    if devices.find("graphics") is None:
        graphics = ET.SubElement(devices, "graphics", {"type": "spice", "autoport": "yes"})
        ET.SubElement(graphics, "listen", {"type": "address"})
        notes.append("Added a SPICE console.")


def _none_balloon(root: ET.Element, notes: list[str]) -> None:
    devices = _ensure_child(root, "devices")
    balloon = devices.find("memballoon")
    if balloon is None:
        ET.SubElement(devices, "memballoon", {"model": "none"})
        notes.append("Disabled the memory balloon.")
    elif balloon.get("model") != "none":
        balloon.set("model", "none")
        for child in list(balloon):
            balloon.remove(child)
        notes.append("Disabled the memory balloon. It fights GPU passthrough.")


def _place_driver(hostdev: ET.Element) -> None:
    """Keep <driver> next to the alias. The schema rejects it after <address>."""
    driver = hostdev.find("driver")
    if driver is None:
        driver = ET.Element("driver")
    else:
        hostdev.remove(driver)
    driver.set("name", "vfio")
    alias = hostdev.find("alias")
    index = list(hostdev).index(alias) + 1 if alias is not None else 0
    hostdev.insert(index, driver)


def _prepare_gpu(hostdev: ET.Element, rom_path: str | None, notes: list[str]) -> None:
    hostdev.set("mode", "subsystem")
    hostdev.set("type", "pci")
    hostdev.set("managed", "yes")
    _ensure_alias(hostdev, GPU_ALIAS)
    _place_driver(hostdev)
    previous = hostdev.find("rom")
    previous_file = previous.get("file") if previous is not None else None
    _set_rom(hostdev, rom_path)
    if rom_path and previous_file != rom_path:
        notes.append(f"Pass the Quadro VBIOS from {rom_path}. The laptop ROM BAR is empty, so the driver Code 43s without this file.")
    elif rom_path is None and previous is not None:
        notes.append("Removed a VBIOS path QEMU cannot use. Dump a real ROM before the external monitor will light.")


def _prepare_audio(hostdev: ET.Element, notes: list[str]) -> None:
    hostdev.set("managed", "yes")
    _ensure_alias(hostdev, AUDIO_ALIAS)
    if hostdev.find("rom") is not None:
        hostdev.remove(hostdev.find("rom"))
        notes.append("Removed the VBIOS file from the audio function. It belongs only on the GPU.")
    _place_driver(hostdev)


def machine_warning(root: ET.Element) -> str | None:
    ostype = root.find("./os/type")
    if ostype is None:
        return None
    machine = ostype.get("machine", "")
    if machine.startswith("pc-i440fx") or machine == "pc":
        return (
            f"This VM uses machine type {machine}. Code 43 is much more likely than on q35. "
            "Changing chipset after Windows is installed breaks the boot disk, so this was left as-is."
        )
    return None


def patch_domain(
    xml: str,
    *,
    gpu_bdf: str,
    audio_bdf: str | None,
    rom_path: str | None,
    ssdt_path: str,
    gpu_subsys: tuple[int, int] | None,
    audio_subsys: tuple[int, int] | None,
    hide_kvm: bool,
) -> PatchResult:
    root = ET.fromstring(xml)
    notes: list[str] = []
    warning = machine_warning(root)
    if warning:
        notes.append(warning)

    if hide_kvm:
        stripped: list[str] = []
        _strip_geforce_hide(root, stripped)
        if stripped:
            notes.append("Cleared the previous hypervisor spoof before applying plan B.")
        _enable_hide(root, notes)
    else:
        _strip_geforce_hide(root, notes)

    _ensure_ioapic(root, notes)

    gpu = _find_hostdev(root, gpu_bdf)
    audio = _find_hostdev(root, audio_bdf) if audio_bdf else None
    if gpu is None:
        notes.append(f"No hostdev in the XML matches {gpu_bdf}. The battery was still added.")
    else:
        _prepare_gpu(gpu, rom_path, notes)
        _apply_subsystem(root, GPU_ALIAS, gpu_subsys, notes, "GPU")
    if audio is not None and gpu is not None:
        _prepare_audio(audio, notes)
        _place_audio_beside_gpu(gpu, audio, root, notes)
        _apply_subsystem(root, AUDIO_ALIAS, audio_subsys, notes, "HDMI audio")
    elif audio_bdf and audio is None:
        notes.append(f"No hostdev matches the NVIDIA audio device {audio_bdf}. Pass function 1 as well.")

    _set_acpitable(root, ssdt_path, notes)
    _set_acpi_oem(root, notes)
    _ensure_spice(root, notes)
    _none_balloon(root, notes)

    if hasattr(ET, "indent"):
        ET.indent(root, space="  ")
    for element in root.iter():
        if len(list(element)) == 0 and element.text and not element.text.strip():
            element.text = None
    xml_out = ET.tostring(root, encoding="unicode")
    if not xml_out.endswith("\n"):
        xml_out += "\n"
    return PatchResult(xml=xml_out, notes=_dedupe(notes))


def _dedupe(notes: list[str]) -> list[str]:
    seen: list[str] = []
    for note in notes:
        if note not in seen:
            seen.append(note)
    return seen
