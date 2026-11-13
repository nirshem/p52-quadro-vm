/*
 * Fake battery for the Quadro P1000 notebook driver.
 * The shipped bytes are this table, compiled, in p52vfio.ssdt.SSDT_BATTERY.
 * OEM id is LENOVO. QEMU's own tables are relabeled the same way, because
 * the notebook driver treats an OEM id of BOCHS as a virtual machine.
 * QEMU's DSDT already defines \_SB.PCI0. The driver looks there.
 */
DefinitionBlock ("", "SSDT", 1, "LENOVO", "THINKP52", 0x00000001)
{
    External (_SB_.PCI0, DeviceObj)

    Scope (_SB.PCI0)
    {
        Device (BAT0)
        {
            Name (_HID, EisaId ("PNP0C0A"))
            Name (_UID, Zero)
            Method (_STA, 0, NotSerialized)
            {
                Return (0x1F)
            }

            Method (_BIF, 0, NotSerialized)
            {
                Return (Package (0x0D)
                {
                    One,
                    0x1770,
                    0x1770,
                    One,
                    0x39D0,
                    0x0258,
                    0x012C,
                    0x3C,
                    0x3C,
                    "",
                    "",
                    "LION",
                    ""
                })
            }

            Method (_BST, 0, NotSerialized)
            {
                Return (Package (0x04)
                {
                    Zero,
                    Zero,
                    0x1770,
                    0x39D0
                })
            }
        }
    }
}
