#!/usr/bin/env python3
"""Run test suites in sequence and save server log + test output + user-visible response.

Usage:
  python scripts/run_tests.py
      Run unit tests only; save results to test_runs/<timestamp>/

  python scripts/run_tests.py --with-server
      Start server, run unit tests, then e2e smoke tests; save server log and
      one API response (what the user would see) to the same run dir.

  python scripts/run_tests.py --with-server --no-e2e
      Start server and run unit tests only (no e2e); still saves server log.

  python scripts/run_tests.py --out-dir my_run
      Use a specific output directory.

Output files (in <out_dir>/):
  - server_log.txt       Server stdout/stderr (only when --with-server).
  - test_results.txt     Pytest and (if run) e2e script output.
  - user_response.json   Last /api/execute response from e2e (when e2e runs).
  - summary.txt          Short summary of what ran and pass/fail.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Project root = parent of scripts/
PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_PORT = 8000
SERVER_READY_TIMEOUT = 60
E2E_TIMEOUT = 300  # e2e can run several requests


def make_out_dir(out_dir: str | None) -> Path:
    if out_dir:
        d = Path(out_dir)
    else:
        d = PROJECT_ROOT / "test_runs" / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    d.mkdir(parents=True, exist_ok=True)
    return d


def wait_for_server(base_url: str, timeout: int = SERVER_READY_TIMEOUT) -> bool:
    import urllib.request
    import urllib.error
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            req = urllib.request.Request(f"{base_url}/health", method="GET")
            with urllib.request.urlopen(req, timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            time.sleep(1)
    return False


def run_unit_tests(out_dir: Path) -> tuple[int, str]:
    """Run pytest tests/test_deterministic.py; return (exit_code, combined_output)."""
    out_file = out_dir / "test_results.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/test_deterministic.py", "-v", "--tb=short"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        f.write("=== Unit tests (pytest tests/test_deterministic.py) ===\n\n")
        f.write(out)
    return proc.returncode, out


def run_e2e(base_url: str, out_dir: Path, save_responses: bool = True) -> tuple[int, str]:
    """Run scripts/test_e2e_smoke.py; append output to test_results.txt. Return (exit_code, output)."""
    out_file = out_dir / "test_results.txt"
    cmd = [sys.executable, "scripts/test_e2e_smoke.py", "--base-url", base_url]
    if save_responses:
        cmd.extend(["--save-responses-dir", str(out_dir)])
    with open(out_file, "a", encoding="utf-8") as f:
        f.write("\n\n=== E2E smoke tests ===\n\n")
        proc = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=E2E_TIMEOUT,
        )
        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        f.write(out)
    return proc.returncode, out


def main() -> int:
    ap = argparse.ArgumentParser(description="Run tests and save server log + results.")
    ap.add_argument("--with-server", action="store_true", help="Start uvicorn and capture server log")
    ap.add_argument("--no-e2e", action="store_true", help="With --with-server, skip e2e smoke tests")
    ap.add_argument("--out-dir", type=str, default=None, help="Output directory (default: test_runs/<timestamp>)")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port for server (default 8000)")
    args = ap.parse_args()

    out_dir = make_out_dir(args.out_dir)
    base_url = f"http://127.0.0.1:{args.port}"
    server_proc = None
    summary_lines: list[str] = []

    print(f"Output directory: {out_dir}")

    # --- Start server if requested ---
    if args.with_server:
        server_log_file = out_dir / "server_log.txt"
        with open(server_log_file, "w", encoding="utf-8") as logf:
            logf.write(f"Server started at {datetime.now().isoformat()}\n")
            logf.write(f"Command: python -m uvicorn app.main:app --host 127.0.0.1 --port {args.port}\n\n")
            server_proc = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)],
                cwd=PROJECT_ROOT,
                stdout=logf,
                stderr=subprocess.STDOUT,
                env={**os.environ, "PYTHONUNBUFFERED": "1"},
            )
        print("Waiting for server to be ready...")
        if not wait_for_server(base_url):
            summary_lines.append("ERROR: Server did not become ready in time.")
            if server_proc:
                server_proc.terminate()
                server_proc.wait(timeout=5)
            with open(out_dir / "summary.txt", "w", encoding="utf-8") as f:
                f.write("\n".join(summary_lines))
            return 1
        print("Server ready.")

    # --- Unit tests (always) ---
    print("Running unit tests...")
    unit_code, unit_out = run_unit_tests(out_dir)
    summary_lines.append(f"Unit tests (pytest): {'PASS' if unit_code == 0 else 'FAIL'} (exit code {unit_code})")
    if unit_code != 0:
        print(unit_out[-2000:] if len(unit_out) > 2000 else unit_out)

    # --- E2E (optional); e2e script saves last API response to user_response.json ---
    e2e_code = 0
    if args.with_server and not args.no_e2e:
        print("Running e2e smoke tests...")
        e2e_code, e2e_out = run_e2e(base_url, out_dir, save_responses=True)
        summary_lines.append(f"E2E smoke tests: {'PASS' if e2e_code == 0 else 'FAIL'} (exit code {e2e_code})")
        summary_lines.append("Last API response saved to user_response.json")
        if e2e_code != 0:
            print(e2e_out[-2000:] if len(e2e_out) > 2000 else e2e_out)

    # --- Stop server ---
    if server_proc:
        server_proc.terminate()
        try:
            server_proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server_proc.kill()
        summary_lines.append("Server stopped.")

    # --- Summary ---
    summary_lines.insert(0, f"Run at {datetime.now().isoformat()}")
    summary_lines.insert(1, f"Output dir: {out_dir}")
    summary_lines.insert(2, "")
    with open(out_dir / "summary.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(summary_lines))
    print("\n" + "\n".join(summary_lines))
    print(f"\nResults saved to: {out_dir}")

    return 0 if (unit_code == 0 and e2e_code == 0) else 1


if __name__ == "__main__":
    sys.exit(main())
