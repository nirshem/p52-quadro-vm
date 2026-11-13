#!/usr/bin/env python3
"""Launch Blade Runner via the Bottles FPLoader program, collect evidence, close it."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

LOG = Path("/home/administrator/workspace/p52/p52-quadro-vm/.cursor/debug-8cafc7.log")
BOTTLE = Path("/home/administrator/.var/app/com.usebottles.bottles/data/bottles/bottles/Fp_BAM")
FP = BOTTLE / "drive_c/Games/Future Pinball"
AGENT_VBS_LOG = BOTTLE / "drive_c/pinevent-agent.log"
CRASH = FP / "BAM/BAM_CRASH.log"
TABLE = r"C:\Games\Future Pinball\Tables\Blade Runner - Replicant Edition (PinEvent Lite - FizX - 1.0).fpt"
RUN_ID = sys.argv[1] if len(sys.argv) > 1 else "agent-run"
WAIT_S = int(sys.argv[2]) if len(sys.argv) > 2 else 120


def emit(hid: str, msg: str, data: dict) -> None:
    # #region agent log
    with LOG.open("a") as f:
        f.write(json.dumps({"sessionId": "8cafc7", "runId": RUN_ID, "hypothesisId": hid,
                            "location": "agent_run_fp.py", "message": msg, "data": data,
                            "timestamp": int(time.time() * 1000)}) + "\n")
    # #endregion


def fp_pids() -> str:
    return subprocess.run(["pgrep", "-af", r"Future Pinball\.exe|FPLoader\.exe"],
                          capture_output=True, text=True).stdout.strip()


def x_windows() -> list[tuple[str, str]]:
    tree = subprocess.run(["xwininfo", "-root", "-children", "-display", ":0"],
                          capture_output=True, text=True).stdout
    wins = []
    for ln in tree.splitlines():
        ln = ln.strip()
        if ln.startswith("0x") and '"' in ln:
            wid, rest = ln.split(" ", 1)
            title = rest.split('"')[1]
            if title and "has no name" not in rest:
                wins.append((wid, title))
    return wins


def screenshot(name: str) -> list[str]:
    outs = []
    for i, (wid, title) in enumerate(x_windows()):
        out = Path(f"/tmp/{RUN_ID}-{name}-{i}.png")
        xwd = subprocess.run(["xwd", "-id", wid, "-silent", "-display", ":0"], capture_output=True)
        if xwd.returncode == 0 and xwd.stdout:
            subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-f", "xwd_pipe", "-i", "-", str(out)],
                           input=xwd.stdout)
        outs.append(f"{title} -> {out if out.exists() else 'FAIL'}")
    return outs


def fp_mem() -> dict:
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            cmd = Path(f"/proc/{pid}/cmdline").read_bytes()
            if b"Future Pinball.exe" not in cmd:
                continue
            st = Path(f"/proc/{pid}/status").read_text()
            return {"pid": pid, **{k: v.strip() for k, v in
                    (ln.split(":", 1) for ln in st.splitlines() if ln.startswith(("VmSize", "VmPeak", "VmRSS")))}}
        except OSError:
            continue
    return {}


def sink_inputs() -> str:
    return subprocess.run(["pactl", "list", "sink-inputs"], capture_output=True, text=True).stdout


def main() -> int:
    subprocess.run(["pkill", "-f", r"Future Pinball\.exe|FPLoader\.exe"])
    time.sleep(2)
    if AGENT_VBS_LOG.exists():
        AGENT_VBS_LOG.unlink()
    crash_before = CRASH.stat().st_mtime if CRASH.exists() else 0
    env = dict(os.environ, DISPLAY=":0")
    cmd = ["flatpak", "run", "--command=bottles-cli", "com.usebottles.bottles", "run",
           "-b", "Fp_BAM", "-p", "FPLoader", "--", "/open", TABLE, "/play"]
    subprocess.Popen(cmd, env=env, stdout=open(f"/tmp/{RUN_ID}-wine.log", "w"), stderr=subprocess.STDOUT)
    emit("A", "launched", {"cmd": cmd})
    shots = []
    t0 = time.time()
    while time.time() - t0 < WAIT_S:
        for _ in range(5):
            time.sleep(2)
            mem = fp_mem()
            if mem:
                emit("D", "mem", {"t": int(time.time() - t0), **mem})
        el = int(time.time() - t0)
        crashed = CRASH.exists() and CRASH.stat().st_mtime > crash_before
        vbs = AGENT_VBS_LOG.read_text(errors="replace") if AGENT_VBS_LOG.exists() else ""
        si = sink_inputs()
        audio = [ln.strip() for ln in si.splitlines()
                 if any(k in ln for k in ("application.name", "Corked", "Mute", "Volume:", "media.name"))]
        emit("B", "poll", {"t": el, "windows": x_windows(), "crashed": crashed,
                           "vbs_log": vbs[-300:], "audio": audio[:12]})
        if el >= 40 and el % 20 < 10:
            shots.extend(screenshot(f"t{el}"))
        if crashed:
            break
    crash_tail = CRASH.read_text(errors="replace")[:900] if CRASH.exists() and CRASH.stat().st_mtime > crash_before else ""
    vbs = AGENT_VBS_LOG.read_text(errors="replace") if AGENT_VBS_LOG.exists() else ""
    emit("C", "result", {"vbs_log": vbs, "crash": crash_tail, "shots": shots})
    print(json.dumps({"vbs_log": vbs, "crash": crash_tail[:400], "shots": shots}, indent=1))
    if "--keep" not in sys.argv:
        subprocess.run(["pkill", "-f", r"Future Pinball\.exe|FPLoader\.exe"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
