# Updates

## 0.1.0 - Quadro P1000 Code 43 fix

- Patch the libvirt domain: drop the GeForce KVM hide, add the fake battery SSDT, pair HDMI audio as function 1, restore the subsystem id, install a VBIOS when one exists.
- Host helper to bind only the P1000 to vfio-pci, and a sysfs VBIOS dump that does not flash the card.
- Quadro notebook driver must be R580. R595 and later do not support this GPU.
