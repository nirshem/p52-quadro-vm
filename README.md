# P52 Quadro P1000 passthrough

## Idea

Pass the NVIDIA Quadro P1000 in a ThinkPad P52 through to a QEMU/KVM Windows 11 guest, and keep Ubuntu 24.04 on the Intel UHD 630. The laptop panel is wired to Intel. HDMI and Mini DisplayPort are wired to the Quadro, so those ports go dark on the host once the GPU is passed through and light up inside Windows.

Code 43 in the guest is the notebook driver refusing to start. The device is already on the PCI bus. The usual GeForce workaround (hide KVM, spoof the Hyper-V vendor id) causes Code 43 on this Quadro. The driver also returns Code 43 when the guest has no battery.

## Architecture

- `scripts/fix-error43.py` edits the libvirt domain. It removes the GeForce hide, installs a fake battery SSDT at `/usr/share/vgabios/ssdt-battery.aml`, puts the NVIDIA HDMI audio device on function 1 of the GPU, restores the Lenovo subsystem id, and points the GPU at a VBIOS file when one exists. Dry-run unless `--apply`.
- `scripts/dump-vbios.py` reads the option ROM from sysfs. It does not flash the card. The P1000 ROM BAR is often empty, and a missing ROM leaves the external monitor black.
- `scripts/apply-host.py` binds only the Quadro and its audio function to `vfio-pci`, with `disable_idle_d3=1`. It refuses to run if the Intel VGA is missing, so a Discrete-only BIOS cannot black out the panel.
- `scripts/check-host.py` prints IOMMU, driver, and the next command.
- `guest/ssdt-battery.asl` is the fake battery. The bytes that get installed live in `p52vfio/ssdt.py` (the known-good BOCHS SSDT, `BAT0` under `\_SB.PCI0`).
- Ubuntu's libvirt AppArmor profile already allows `/usr/share/vgabios/**`, which is why the ROM and SSDT go there.
- Plan B is `--hide-kvm`. Use it only after the battery fix still shows Code 43.

Guest driver: NVIDIA RTX / Quadro, Quadro Series (Notebooks), Quadro P1000, Windows 11, production branch **R580** (582.x). R595 and R620 dropped Pascal. Do not install GeForce Experience.

## Fix Code 43

On the Ubuntu host, from this directory, with Windows shut down (not rebooted):

```bash
python3 scripts/check-host.py
sudo python3 scripts/fix-error43.py --apply
virsh start win11
```

If the domain is not named `win11`, pass `--domain`. The script picks the domain that already contains the Quadro when there is only one.

Then, in Windows:

1. Device Manager must show a battery. If it does not, read `/var/log/libvirt/qemu/win11.log`.
2. Uninstall the Quadro and check delete-the-driver. Uninstall the NVIDIA apps. Reboot the guest.
3. Install the R580 notebook driver from https://www.nvidia.com/Download/index.aspx
4. The monitor has to be on the laptop HDMI or Mini DisplayPort before setup. A USB-C dock is not this GPU.
5. If Code 43 remains, disable the P1000 and enable it again.
6. Hardware Ids should contain `PCI\VEN_10DE&DEV_1CBB`.

If it is still Code 43:

```bash
sudo python3 scripts/dump-vbios.py
sudo python3 scripts/fix-error43.py --rom ./quadro-p1000.rom --apply
```

Dump the ROM while the VM is off. If sysfs returns an empty ROM, save it with GPU-Z from a bare-metal Windows boot. Do not flash it.

Plan B, only after the steps above:

```bash
sudo python3 scripts/fix-error43.py --apply --hide-kvm
```

## Host binding

BIOS: Config, Display, Hybrid Graphics. Security, Virtualization, Intel Virtualization Technology and VT-d enabled. UEFI only.

```bash
sudo python3 scripts/apply-host.py          # prints the files, changes nothing
sudo python3 scripts/apply-host.py --apply  # then reboot
python3 scripts/check-host.py               # Quadro driver must be vfio-pci
```

Undo, then reboot:

```bash
sudo python3 scripts/apply-host.py --undo --apply
```

`kvm.ignore_msrs=1`, `intel_iommu=on`, and `iommu=pt` are added to GRUB. A copy of the previous GRUB line is `/etc/default/grub.p52-p1000.bak`.

## Tests

```bash
python3 tests/test_passthrough.py -v
```

## Reading order for agents

1. Read this `README.md`.
2. Read `UPDATES.md` for the change history and current state before working.
