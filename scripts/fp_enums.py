#!/usr/bin/env python3
"""Dump every enum (name = value) from the Future Pinball MSFT type library.

Wine does not expose these enums to table scripts, so they are emitted as VBScript Consts.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

EXE = Path("/home/administrator/.var/app/com.usebottles.bottles/data/bottles/bottles/Fp_BAM/"
           "drive_c/Games/Future Pinball/Future Pinball.exe")
TKIND_ENUM = 0
VAR_CONST = 2


def enums(tlb: bytes) -> list[tuple[str, list[tuple[str, int]]]]:
    nr_typeinfos = struct.unpack_from("<i", tlb, 0x20)[0]
    varflags = struct.unpack_from("<i", tlb, 0x14)[0]
    pos = 0x54 + (4 if varflags & 0x100 else 0) + nr_typeinfos * 4
    seg = [struct.unpack_from("<iiii", tlb, pos + i * 16) for i in range(15)]
    ti_off, name_off = seg[0][0], seg[7][0]

    def name_at(off: int) -> str:
        n = tlb[name_off + off + 8]
        return tlb[name_off + off + 12:name_off + off + 12 + n].decode("latin-1")

    out = []
    for i in range(nr_typeinfos):
        base = ti_off + i * 0x64
        kind = struct.unpack_from("<i", tlb, base)[0] & 0xF
        if kind != TKIND_ENUM:
            continue
        memoffset = struct.unpack_from("<i", tlb, base + 4)[0]
        celement = struct.unpack_from("<i", tlb, base + 0x18)[0]
        name = name_at(struct.unpack_from("<i", tlb, base + 0x34)[0])
        nvars = celement >> 16
        infolen = struct.unpack_from("<i", tlb, memoffset)[0]
        rec = memoffset + 4
        values = []
        for _ in range(nvars):
            recsize = struct.unpack_from("<H", tlb, rec)[0]
            varkind = struct.unpack_from("<h", tlb, rec + 12)[0]
            offsvalue = struct.unpack_from("<i", tlb, rec + 16)[0]
            if varkind == VAR_CONST and offsvalue < 0:
                v = offsvalue & 0x3FFFFFF
                if v & 0x2000000:
                    v -= 0x4000000
            else:
                v = struct.unpack_from("<i", tlb, offsvalue + 2)[0] if varkind == VAR_CONST else None
            values.append(v)
            rec += recsize
        names_arr = memoffset + 4 + infolen + nvars * 4
        names = [name_at(struct.unpack_from("<i", tlb, names_arr + k * 4)[0]) for k in range(nvars)]
        out.append((name, list(zip(names, values))))
    return out


if __name__ == "__main__":
    data = EXE.read_bytes()
    tlb = data[data.find(b"MSFT"):]
    for ename, members in enums(tlb):
        print(f"' {ename}")
        for n, v in members:
            print(f"Const {n} = {v}")
        print()
    sys.exit(0)
