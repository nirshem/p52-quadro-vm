#!/usr/bin/env python3
"""Extract the VBScript from a Future Pinball .fpt (Table Data, zLZO chunk)."""
from __future__ import annotations

import struct
import sys

import olefile


def lzo1x_decompress(src: bytes, out_len: int) -> bytes:
    dst = bytearray()
    ip = 0

    def take_len(base: int, mask_bits: int) -> int:
        nonlocal ip
        t = base
        if t == 0:
            while src[ip] == 0:
                t += 255
                ip += 1
            t += mask_bits + src[ip]
            ip += 1
        return t

    t = src[ip]
    if t > 17:
        t -= 17
        ip += 1
        dst += src[ip:ip + t]
        ip += t
        state = 4 if t >= 4 else t
    else:
        state = 0
    while True:
        t = src[ip]
        ip += 1
        if t < 16:
            if state == 0:
                if t == 0:
                    while src[ip] == 0:
                        t += 255
                        ip += 1
                    t += 15 + src[ip]
                    ip += 1
                t += 3
                dst += src[ip:ip + t]
                ip += t
                state = 4
                continue
            if state == 4:
                m = len(dst) - (1 + 0x0800) - (t >> 2) - (src[ip] << 2)
                ip += 1
                n = 3
            else:
                m = len(dst) - 1 - (t >> 2) - (src[ip] << 2)
                ip += 1
                n = 2
            for _ in range(n):
                dst.append(dst[m])
                m += 1
            s = t & 3
            dst += src[ip:ip + s]
            ip += s
            state = s
            continue
        if t >= 64:
            m = len(dst) - 1 - ((t >> 2) & 7) - (src[ip] << 3)
            ip += 1
            n = (t >> 5) - 1 + 2
        elif t >= 32:
            n = t & 31
            if n == 0:
                while src[ip] == 0:
                    n += 255
                    ip += 1
                n += 31 + src[ip]
                ip += 1
            n += 2
            d = src[ip] | (src[ip + 1] << 8)
            ip += 2
            m = len(dst) - 1 - (d >> 2)
            t = d
        else:
            m = len(dst) - ((t & 8) << 11)
            n = t & 7
            if n == 0:
                while src[ip] == 0:
                    n += 255
                    ip += 1
                n += 7 + src[ip]
                ip += 1
            n += 2
            d = src[ip] | (src[ip + 1] << 8)
            ip += 2
            m -= d >> 2
            t = d
            if m == len(dst):
                break
            m -= 0x4000
        for _ in range(n):
            dst.append(dst[m])
            m += 1
        s = t & 3
        dst += src[ip:ip + s]
        ip += s
        state = s
    return bytes(dst[:out_len])


def extract(path: str) -> str:
    sys.setrecursionlimit(100000)
    ole = olefile.OleFileIO(path)
    data = ole.openstream("Future Pinball/Table Data").read()
    pos = 0
    while pos + 8 <= len(data):
        ln, tag = struct.unpack_from("<II", data, pos)
        if tag == 0x4F5A4C7A:
            size = struct.unpack_from("<I", data, pos + 8)[0]
            return lzo1x_decompress(data[pos + 12:pos + 4 + ln], size).decode("latin-1")
        pos += 4 + ln
    raise SystemExit("no zLZO script chunk")


if __name__ == "__main__":
    sys.stdout.write(extract(sys.argv[1]))
