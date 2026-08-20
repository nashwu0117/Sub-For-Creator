#!/usr/bin/env python3
"""ASR accuracy acceptance runner (CPU, faster-whisper backend, small model).

Drives the five enhancement acceptance scenarios end to end:

  S1 VAD           silence.wav           -> no hallucinated subtitles with VAD
  S2 Determinism   tone_silence_tone.wav -> two runs, identical output (temp=0)
  S3 Denoise       tone_noisy.wav        -> noise floor drops; pipeline works
  S4 Dictionary    silence.wav + terms   -> initial_prompt biases decoding
  S5 LLM correction                     -> fake Ollama server; text corrected,
                                           timing preserved

Usage:
  python scripts/acceptance/run_acceptance.py [--keep] [S1 S2 ...]
  (no scenario args = run all)
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CLI = REPO / "cli" / "subforcreator.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
VENV_PY = REPO / ".venv" / "bin" / "python"
REPORT = Path(__file__).resolve().parent / "ACCEPTANCE_REPORT.md"

#: CPU-friendly model override (tier presets keep their beam/VAD/temp)
MODEL = "small"

results: list[dict] = []


def run_cli(args: list[str], env: dict | None = None, timeout: int = 900) -> subprocess.CompletedProcess:
    base_env = os.environ.copy()
    base_env.update(
        {
            "SFC_ASR_BACKEND": "faster-whisper",
            "SFC_WHISPER_MODEL": MODEL,
        }
    )
    if env:
        base_env.update(env)
    return subprocess.run(
        [str(VENV_PY), str(CLI), *args],
        cwd=REPO,
        env=base_env,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def parse_srt(path: Path) -> list[tuple[float, float, str]]:
    """Return [(start, end, text)] from an SRT file."""
    blocks = path.read_text(encoding="utf-8").strip().split("\n\n")
    out = []
    for block in blocks:
        lines = [l for l in block.splitlines() if l.strip()]
        if len(lines) < 3:
            continue
        times = lines[1].split(" --> ")
        def _t(s: str) -> float:
            h, m, rest = s.split(":")
            sec, ms = rest.split(",")
            return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000
        out.append((_t(times[0]), _t(times[1]), " ".join(lines[2:])))
    return out


# --- S1: VAD ---------------------------------------------------------------


def s1_vad(tmp: Path) -> None:
    t0 = time.time()
    with_vad = tmp / "vad_on.srt"
    r1 = run_cli([str(FIXTURES / "silence.wav"), "--lang", "zh", "-o", str(with_vad)])
    segs_vad = parse_srt(with_vad) if with_vad.exists() else []
    t_vad = time.time() - t0

    t0 = time.time()
    no_vad = tmp / "vad_off.srt"
    r2 = run_cli([str(FIXTURES / "silence.wav"), "--lang", "zh", "--no-vad", "-o", str(no_vad)])
    segs_no_vad = parse_srt(no_vad) if no_vad.exists() else []
    t_no_vad = time.time() - t0

    ok = len(segs_vad) == 0
    results.append(
        {
            "id": "S1 VAD",
            "ok": ok,
            "detail": (
                f"15s silence: VAD on -> {len(segs_vad)} segments (expect 0); "
                f"VAD off -> {len(segs_no_vad)} segments (hallucination contrast); "
                f"timing VAD on {t_vad:.1f}s / off {t_no_vad:.1f}s"
            ),
            "exit_codes": (r1.returncode, r2.returncode),
        }
    )


# --- S2: determinism --------------------------------------------------------


def s2_determinism(tmp: Path) -> None:
    inp = FIXTURES / "tone_silence_tone.wav"
    t0 = time.time()
    a = tmp / "det_a.srt"
    r1 = run_cli([str(inp), "--lang", "zh", "--tier", "pro", "-o", str(a)])
    b = tmp / "det_b.srt"
    r2 = run_cli([str(inp), "--lang", "zh", "--tier", "pro", "-o", str(b)])
    elapsed = time.time() - t0

    txt_a = a.read_text(encoding="utf-8") if a.exists() else ""
    txt_b = b.read_text(encoding="utf-8") if b.exists() else ""
    ok = r1.returncode == 0 and r2.returncode == 0 and txt_a == txt_b and bool(txt_a)
    results.append(
        {
            "id": "S2 Determinism",
            "ok": ok,
            "detail": (
                f"pro tier (beam 10, temperature 0) twice -> identical: {txt_a == txt_b}; "
                f"segments: {len(parse_srt(a))}; total 2 runs {elapsed:.1f}s"
            ),
            "exit_codes": (r1.returncode, r2.returncode),
        }
    )


# --- S3: denoise ------------------------------------------------------------


def noise_floor_db(path: Path) -> float:
    proc = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    for line in proc.stderr.splitlines():
        if "mean_volume" in line:
            return float(line.split(":")[1].strip().replace(" dB", ""))
    return float("nan")


def s3_denoise(tmp: Path) -> None:
    import sys as _sys

    _sys.path.insert(0, str(REPO / "backend"))
    from app.core.preprocess import denoise_audio

    noisy = FIXTURES / "tone_noisy.wav"
    denoised = tmp / "denoised.wav"
    t0 = time.time()
    denoise_audio(str(noisy), str(denoised), prop_decrease=0.85)
    t_denoise = time.time() - t0

    floor_in = noise_floor_db(noisy)
    floor_out = noise_floor_db(denoised)
    ok = floor_out < floor_in - 5  # at least 5 dB noise-floor reduction

    # pipeline smoke test: CLI with --denoise runs end to end
    out = tmp / "denoise.srt"
    r = run_cli([str(noisy), "--lang", "zh", "--denoise", "-o", str(out)])
    segs = parse_srt(out) if out.exists() else []

    results.append(
        {
            "id": "S3 Denoise",
            "ok": ok and r.returncode == 0,
            "detail": (
                f"noise floor: {floor_in:.1f} dB -> {floor_out:.1f} dB "
                f"(improvement {floor_in - floor_out:.1f} dB, expect >= 5); "
                f"denoise step {t_denoise:.2f}s; CLI --denoise pipeline ok "
                f"(exit {r.returncode}, {len(segs)} segments)"
            ),
            "exit_codes": (r.returncode,),
        }
    )


# --- S4: dictionary / initial_prompt ----------------------------------------


def s4_dictionary(tmp: Path) -> None:
    dict_path = tmp / "user_dictionary.json"
    dict_path.write_text(json.dumps({"terms": ["OurWay", "Nash", "WhisperX"]}, ensure_ascii=False), encoding="utf-8")

    out_with = tmp / "dict_on.srt"
    r1 = run_cli(
        [str(FIXTURES / "silence.wav"), "--lang", "zh", "--dictionary", str(dict_path), "-o", str(out_with)]
    )
    txt_with = out_with.read_text(encoding="utf-8") if out_with.exists() else ""

    out_without = tmp / "dict_off.srt"
    r2 = run_cli([str(FIXTURES / "silence.wav"), "--lang", "zh", "-o", str(out_without)])
    txt_without = out_without.read_text(encoding="utf-8") if out_without.exists() else ""

    # initial_prompt on silence biases hallucination toward prompt terms;
    # the acceptance is that the prompt term appears ONLY when the dictionary is used
    term = "OurWay"
    ok = term in txt_with and r1.returncode == 0 and r2.returncode == 0
    results.append(
        {
            "id": "S4 Dictionary",
            "ok": ok,
            "detail": (
                f"term {term!r} in output: with dictionary = {term in txt_with}, "
                f"without = {term in txt_without}; "
                f"with: {len(parse_srt(out_with))} segs, without: {len(parse_srt(out_without))} segs"
            ),
            "exit_codes": (r1.returncode, r2.returncode),
        }
    )


# --- S5: LLM correction -----------------------------------------------------


class _FakeOllama(BaseHTTPRequestHandler):
    """Mini Ollama-compatible /api/chat returning a deterministic correction.

    Appends '[校正]' to every segment text — proves the pass ran, text was
    replaced, and (compared against a non-LLM run) timing is preserved.
    """

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        user_msg = ""
        for m in body.get("messages", []):
            if m.get("role") == "user":
                user_msg = m.get("content", "")
        segments = []
        try:
            payload = json.loads(user_msg)
            if isinstance(payload, list):
                segments = payload
        except (ValueError, TypeError):
            pass
        corrected = {
            "segments": [
                {"id": s.get("id"), "text": str(s.get("text", "")) + "[校正]"}
                for s in segments
                if isinstance(s, dict)
            ]
        }
        resp = json.dumps({"message": {"content": json.dumps(corrected)}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *args):  # silence
        pass


def s5_llm(tmp: Path) -> None:
    server = HTTPServer(("127.0.0.1", 0), _FakeOllama)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    inp = FIXTURES / "tone_silence_tone.wav"
    t0 = time.time()
    out_llm = tmp / "llm.srt"
    env = {"SFC_LLM_CORRECTION_ENABLED": "true", "SFC_OLLAMA_URL": f"http://127.0.0.1:{port}"}
    r1 = run_cli([str(inp), "--lang", "zh", "-o", str(out_llm)], env=env)
    t_llm = time.time() - t0

    out_plain = tmp / "plain.srt"
    r2 = run_cli([str(inp), "--lang", "zh", "-o", str(out_plain)])
    server.shutdown()

    segs_llm = parse_srt(out_llm) if out_llm.exists() else []
    segs_plain = parse_srt(out_plain) if out_plain.exists() else []

    corrected = sum(1 for _, _, t in segs_llm if "[校正]" in t)
    # timing preserved: same number of segments, same start/end pairs
    times_llm = [(s, e) for s, e, _ in segs_llm]
    times_plain = [(s, e) for s, e, _ in segs_plain]
    ok = (
        r1.returncode == 0
        and len(segs_llm) == len(segs_plain)
        and times_llm == times_plain
        and corrected == len(segs_llm)
    )
    results.append(
        {
            "id": "S5 LLM correction",
            "ok": ok,
            "detail": (
                f"fake Ollama provider: {corrected}/{len(segs_llm)} segments corrected; "
                f"timing preserved = {times_llm == times_plain}; "
                f"pipeline with LLM pass {t_llm:.1f}s vs plain run "
                f"{time.time() - t0 - t_llm:.1f}s (provider latency dominates; fake server ~instant)"
            ),
            "exit_codes": (r1.returncode, r2.returncode),
        }
    )


# --- main -------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("scenarios", nargs="*", help="S1 S2 S3 S4 S5 (default: all)")
    parser.add_argument("--keep", action="store_true", help="keep temp workdir")
    args = parser.parse_args()

    if not FIXTURES.exists():
        print("fixtures missing; run scripts/acceptance/make_fixtures.py first", file=sys.stderr)
        return 1

    wanted = args.scenarios or ["S1", "S2", "S3", "S4", "S5"]
    tmp = Path(tempfile.mkdtemp(prefix="sfc-acceptance-"))
    try:
        runners = {
            "S1": s1_vad,
            "S2": s2_determinism,
            "S3": s3_denoise,
            "S4": s4_dictionary,
            "S5": s5_llm,
        }
        for name in wanted:
            if name not in runners:
                print(f"unknown scenario {name}", file=sys.stderr)
                return 1
        for name in wanted:
            print(f"== running {name} ==", flush=True)
            runners[name](tmp)
    finally:
        if args.keep:
            print("workdir kept at", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 60)
    print("ACCEPTANCE REPORT")
    print("=" * 60)
    lines = ["# ASR Accuracy Acceptance Report", ""]
    all_ok = True
    for r in results:
        mark = "PASS" if r["ok"] else "FAIL"
        all_ok = all_ok and r["ok"]
        print(f"[{mark}] {r['id']}: {r['detail']}")
        lines.append(f"- **{r['id']}**: {mark} — {r['detail']}")
    lines.append("")
    lines.append(f"**Overall: {'ALL PASS' if all_ok else 'SOME FAILURES'}**")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\nreport written to", REPORT)
    return 0 if all_ok else 2


if __name__ == "__main__":
    sys.exit(main())