"""Unit tests for the Code 43 domain patch and host config text."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from p52vfio.domain import clean_cpu_arg, parse_bdf, patch_domain  # noqa: E402
from p52vfio.host import (  # noqa: E402
    group_blockers,
    intel_vga_present,
    merge_grub_cmdline,
    parse_lspci,
    pick_nvidia,
    remove_marked_block,
    strip_grub_tokens,
    upsert_marked_block,
    vfio_conf,
)
from p52vfio.rom import normalize_rom  # noqa: E402
from p52vfio.ssdt import SSDT_INSTALL_PATH, ssdt_battery  # noqa: E402

BROKEN = """<domain type='kvm' xmlns:qemu='http://libvirt.org/schemas/domain/qemu/1.0'>
  <name>win11</name>
  <memory unit='KiB'>8388608</memory>
  <vcpu placement='static'>4</vcpu>
  <os firmware='efi'>
    <type arch='x86_64' machine='pc-q35-8.2'>hvm</type>
    <boot dev='hd'/>
  </os>
  <features>
    <acpi/>
    <apic/>
    <hyperv mode='custom'>
      <relaxed state='on'/>
      <vapic state='on'/>
      <spinlocks state='on' retries='8191'/>
      <vendor_id state='on' value='1234567890ab'/>
    </hyperv>
    <kvm>
      <hidden state='on'/>
    </kvm>
  </features>
  <cpu mode='host-passthrough' check='none' migratable='off'>
    <feature policy='disable' name='hypervisor'/>
  </cpu>
  <clock offset='localtime'/>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>destroy</on_crash>
  <devices>
    <emulator>/usr/bin/qemu-system-x86_64</emulator>
    <disk type='file' device='disk'>
      <driver name='qemu' type='qcow2'/>
      <source file='/var/lib/libvirt/images/win11.qcow2'/>
      <target dev='vda' bus='virtio'/>
    </disk>
    <controller type='usb' index='0' model='qemu-xhci'/>
    <controller type='pci' index='0' model='pcie-root'/>
    <interface type='network'>
      <source network='default'/>
      <model type='virtio'/>
    </interface>
    <graphics type='spice' autoport='yes'/>
    <video>
      <model type='qxl' ram='65536' vram='65536' vgamem='16384' heads='1'/>
    </video>
    <memballoon model='virtio'/>
    <hostdev mode='subsystem' type='pci' managed='yes'>
      <source>
        <address domain='0x0000' bus='0x01' slot='0x00' function='0x0'/>
      </source>
      <rom file='/tmp/p1000.rom'/>
      <address type='pci' domain='0x0000' bus='0x07' slot='0x00' function='0x0'/>
    </hostdev>
    <hostdev mode='subsystem' type='pci' managed='yes'>
      <source>
        <address domain='0x0000' bus='0x01' slot='0x00' function='0x1'/>
      </source>
      <rom file='/tmp/audio.rom'/>
      <address type='pci' domain='0x0000' bus='0x08' slot='0x00' function='0x0'/>
    </hostdev>
  </devices>
  <qemu:commandline>
    <qemu:arg value='-cpu'/>
    <qemu:arg value='host,kvm=off,hv_vendor_id=KVMKVMKVM'/>
    <qemu:arg value='-set'/>
    <qemu:arg value='device.hostdev0.x-pci-device-id=7351'/>
  </qemu:commandline>
</domain>
"""

LSPCI = """\
00:02.0 VGA compatible controller [0300]: Intel Corporation Coffee Lake-H GT2 [UHD Graphics 630] [8086:3e9b]
01:00.0 3D controller [0302]: NVIDIA Corporation GP107GLM [Quadro P1000 Mobile] [10de:1cbb]
01:00.1 Audio device [0403]: NVIDIA Corporation GP107GL High Definition Audio Controller [10de:0fb9]
"""


def _patch(xml: str = BROKEN, **kwargs):
    options = dict(
        gpu_bdf="0000:01:00.0",
        audio_bdf="0000:01:00.1",
        rom_path="/usr/share/vgabios/quadro-p1000.rom",
        ssdt_path=SSDT_INSTALL_PATH,
        gpu_subsys=(0x17AA, 0x224D),
        audio_subsys=(0x17AA, 0x224E),
        hide_kvm=False,
    )
    options.update(kwargs)
    return patch_domain(xml, **options)


class DomainPatchTest(unittest.TestCase):
    def test_removes_geforce_workaround_and_adds_battery(self) -> None:
        result = _patch()
        xml = result.xml
        self.assertNotIn("hidden", xml)
        self.assertNotIn("vendor_id", xml)
        self.assertNotIn("hypervisor", xml)
        self.assertNotIn("kvm=off", xml)
        self.assertNotIn("x-pci-device-id", xml)
        self.assertIn("file=/usr/share/vgabios/ssdt-battery.aml", xml)
        self.assertIn('driver="kvm"', xml)
        self.assertIn('model="none"', xml)
        self.assertIn("ua-p1000", xml)
        self.assertIn('function="0x1"', xml)
        self.assertIn('multifunction="on"', xml)
        self.assertNotIn("/tmp/audio.rom", xml)
        self.assertIn("/usr/share/vgabios/quadro-p1000.rom", xml)
        self.assertIn("6058", xml)
        self.assertIn("8781", xml)
        self.assertIn("8782", xml)
        self.assertNotIn("ns0", xml)
        self.assertTrue(any("Code 43" in note or "battery" in note.lower() for note in result.notes))

    def test_audio_shares_the_gpu_slot(self) -> None:
        root_xml = _patch().xml
        self.assertIn('bus="0x07" slot="0x00" function="0x1"', root_xml)

    def test_idempotent(self) -> None:
        once = _patch().xml
        twice = _patch(once).xml
        self.assertEqual(once, twice)

    def test_hide_kvm_is_opt_in_and_keeps_the_battery(self) -> None:
        xml = _patch(hide_kvm=True).xml
        self.assertIn('state="on"', xml)
        self.assertIn("GenuineIntel", xml)
        self.assertIn("<hidden", xml)
        self.assertIn("ssdt-battery.aml", xml)
        self.assertEqual(len("GenuineIntel"), 12)
        again = _patch(xml, hide_kvm=True).xml
        self.assertEqual(xml, again)

    def test_i440fx_is_reported(self) -> None:
        xml = BROKEN.replace("pc-q35-8.2", "pc-i440fx-8.2")
        notes = _patch(xml).notes
        self.assertTrue(any("i440fx" in note for note in notes))

    def test_missing_gpu_still_adds_the_battery(self) -> None:
        xml = _patch(gpu_bdf="0000:09:00.0", audio_bdf=None, rom_path=None).xml
        self.assertIn("ssdt-battery.aml", xml)

    def test_schema(self) -> None:
        xml = _patch().xml
        binary = shutil_which("virt-xml-validate")
        if binary is None:
            self.skipTest("virt-xml-validate is not installed")
        with tempfile.NamedTemporaryFile("w", suffix=".xml") as handle:
            handle.write(xml)
            handle.flush()
            result = subprocess.run(
                [binary, handle.name, "domain"],
                check=False,
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)


class CpuArgTest(unittest.TestCase):
    def test_strips_geforce_flags(self) -> None:
        self.assertEqual(clean_cpu_arg("host,kvm=off,hv_vendor_id=KVMKVMKVM"), "host")
        self.assertEqual(clean_cpu_arg("host"), "host")


class HostTest(unittest.TestCase):
    def test_lspci_picks_mobile_p1000(self) -> None:
        devices = parse_lspci(LSPCI)
        self.assertTrue(intel_vga_present(devices))
        gpu, audio = pick_nvidia(devices)
        self.assertIsNotNone(gpu)
        self.assertIsNotNone(audio)
        assert gpu and audio
        self.assertEqual(gpu.device, "1cbb")
        self.assertEqual(audio.device, "0fb9")
        self.assertEqual(gpu.full_bdf, "0000:01:00.0")

    def test_group_allows_bridge_and_blocks_usb(self) -> None:
        safe = [
            "00:01.0 PCI bridge [0604]: Intel Corporation 6th-9th Gen Core Processor PCIe Controller [8086:1901]",
            "01:00.0 3D controller [0302]: NVIDIA Corporation GP107GLM [Quadro P1000 Mobile] [10de:1cbb]",
            "01:00.1 Audio device [0403]: NVIDIA Corporation Device [10de:0fb9]",
        ]
        self.assertEqual(group_blockers(safe), [])
        dirty = safe + ["00:14.0 USB controller [0c03]: Intel Corporation [8086:a2af]"]
        self.assertEqual(len(group_blockers(dirty)), 1)

    def test_grub_tokens_are_idempotent(self) -> None:
        original = 'GRUB_CMDLINE_LINUX_DEFAULT="quiet splash"\n'
        once = merge_grub_cmdline(original)
        self.assertIn("intel_iommu=on", once)
        self.assertIn("iommu=pt", once)
        self.assertIn("kvm.ignore_msrs=1", once)
        self.assertEqual(merge_grub_cmdline(once), once)
        self.assertEqual(strip_grub_tokens(once), original)

    def test_marked_block_replaces_itself(self) -> None:
        first = "# BEGIN p52-p1000-vfio\nvfio\n# END p52-p1000-vfio\n"
        second = "# BEGIN p52-p1000-vfio\nvfio\nvfio_iommu_type1\n# END p52-p1000-vfio\n"
        text = upsert_marked_block("before\n", first)
        again = upsert_marked_block(text, second)
        self.assertEqual(again.count("BEGIN"), 1)
        self.assertIn("vfio_iommu_type1", again)
        self.assertEqual(remove_marked_block(again), "before\n")

    def test_vfio_conf_names_both_ids(self) -> None:
        text = vfio_conf(["10de:1cbb", "10de:0fb9"])
        self.assertIn("ids=10de:1cbb,10de:0fb9", text)
        self.assertIn("disable_idle_d3=1", text)

    def test_parse_bdf(self) -> None:
        self.assertEqual(parse_bdf("0000:01:00.0"), (0, 1, 0, 0))
        self.assertEqual(parse_bdf("01:00.1"), (0, 1, 0, 1))


class RomTest(unittest.TestCase):
    def test_accepts_a_pcir_image_and_drops_the_prefix(self) -> None:
        body = b"\x55\xaa\x40" + b"\x00" * 29 + b"PCIR" + b"\x00" * (0x40 * 512 - 36)
        self.assertTrue(body[0:2] == b"\x55\xaa")
        wrapped = b"\xff" * 16 + body
        self.assertEqual(normalize_rom(wrapped), body)

    def test_rejects_empty_and_ff(self) -> None:
        self.assertIsNone(normalize_rom(b""))
        self.assertIsNone(normalize_rom(b"\xff" * 4096))
        self.assertIsNone(normalize_rom(b"\x55\xaa" + b"\x00" * 600))


class SsdtTest(unittest.TestCase):
    def test_table_is_a_battery(self) -> None:
        data = ssdt_battery()
        self.assertEqual(data[:4], b"SSDT")
        iasl = shutil_which("iasl")
        if iasl is None:
            self.skipTest("iasl is not installed")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ssdt.aml"
            path.write_bytes(data)
            result = subprocess.run([iasl, "-d", str(path)], check=False, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            text = path.with_suffix(".dsl").read_text()
        self.assertIn("PNP0C0A", text)
        self.assertIn("PCI0", text)


def shutil_which(name: str) -> str | None:
    return __import__("shutil").which(name)


if __name__ == "__main__":
    unittest.main()
