#!/usr/bin/env python3
"""Company-machine dry-run gate for the documented MVP quickstart.

Runs the EXACT documented MVP flow end-to-end from a fresh, outside-repo
output directory and proves it produces a validated, editable
``review_package/deck.pptx`` without polluting the repo. It is the
automated, fail-closed version of the manual quickstart in
``references/mvp-quickstart.md``:

  1. ``run_mvp_image_to_ppt.py --source examples/mvp_demo_source.md
     --out-dir <OUT>``            (local source -> generation packet)
  2. write one placeholder PNG per requested filename into
     ``<OUT>/generation_packet/expected_images``   (simulates the human /
     internal image-generation step; placeholder pixels only, NO source
     text embedded -- mirrors the quickstart's fully-local smoke snippet)
  3. ``run_mvp_image_to_ppt.py --resume <OUT>``     (packet + returned
     images -> editable deck)
  4. ``validate_operator_review_package.py --out-dir
     <OUT>/review/review_package``                 (read-only re-validation)

The gate drives the two documented entry points as SUBPROCESSES (the same
commands an operator types on a company machine), so their argparse +
fail-closed safety gates run verbatim; it adds no renderer, no second
validator, and synthesises no pixels beyond the placeholder PNGs. It fails
closed if any step exits non-zero, if ``deck.pptx`` is missing, if the
review-package validator refuses the result, or if the run leaves ANY new
artifact in the repo working tree / index (a ``git status --porcelain``
delta taken across the run).

Modes (mutually exclusive, exactly one required):

  --self-test
    Run the whole flow under an auto-removed
    ``tempfile.TemporaryDirectory()`` (outside the repo). Asserts every
    step, prints the produced deck + summary paths, then discards the temp
    output so nothing is retained. This is the acceptance gate.

  --out-dir DIR
    Run the same flow against a caller-supplied DIR that MUST be outside
    the repo tree (e.g. under ``/tmp``), missing or empty, with an existing
    parent. Retains the artifacts for inspection and prints the final deck
    + summary paths.

Stdlib-only. Local-only -- does NOT call D-One, MCP, Qoder, a public
network, telemetry, a model API, an image search, or any external service.
NOT real image generation; NOT full report-to-PPT automation. It only
sequences the existing documented commands and inspects their outputs.
"""

from __future__ import annotations

import sys

# Refuse `.pyc` writes from any module the subprocesses or this gate import.
# Mirrors the gate every sibling helper applies so a clean checkout does not
# gain ``scripts/__pycache__/*.pyc`` (which would muddy the repo-status
# delta below). Must be flipped BEFORE any first-party import.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import struct  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
import zlib  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

WRAPPER = SCRIPTS_DIR / "run_mvp_image_to_ppt.py"
PACKAGE_VALIDATOR = SCRIPTS_DIR / "validate_operator_review_package.py"
DEMO_SOURCE = REPO_ROOT / "examples" / "mvp_demo_source.md"

# Fixed layout the wrapper writes under its --out-dir (kept in sync with
# run_mvp_image_to_ppt.py's own constants; this gate only READS these paths).
_PACKET_SUBDIR = "generation_packet"
_EXPECTED_IMAGES = "expected_images"
_REVIEW_PACKAGE = ("review", "review_package")


# ---------------------------------------------------------------------------
# Placeholder PNG synthesis. Mirrors the documented quickstart snippet: read
# the produced image_request_plan.json and write one byte-distinct, valid
# 8-bit RGB PNG per requested filename. Placeholder pixels only -- NO source
# text is embedded. Stdlib-only (zlib + struct + crc32).
# ---------------------------------------------------------------------------


def _png_bytes(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    def _chunk(typ: bytes, data: bytes) -> bytes:
        body = typ + data
        return (
            struct.pack(">I", len(data))
            + body
            + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
        )

    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit RGB
    raw = bytearray()
    row = bytes(rgb) * width
    for _ in range(height):
        raw.append(0)  # filter type 0 (None) per scanline
        raw += row
    idat = zlib.compress(bytes(raw), 9)
    return sig + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")


def _write_placeholder_images(packet_dir: Path) -> int:
    """Write one placeholder PNG per requested filename into the packet's
    ``expected_images/`` directory (already created by the first run, which
    seeds it with a README naming every return filename). Returns the count.

    Reads the documented public artifact ``image_request_plan.json`` rather
    than reaching into any helper internals, so it exercises the same packet
    surface an operator/image-generator consumes."""
    plan_path = packet_dir / "image_request_plan.json"
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    requests = plan.get("image_requests")
    if not isinstance(requests, list) or not requests:
        raise ValueError(
            f"{plan_path} carries no image_requests to fill; the first run "
            f"did not produce a usable generation packet."
        )
    images_dir = packet_dir / _EXPECTED_IMAGES
    for i, req in enumerate(requests, 1):
        filename = req["filename"]
        # Byte-distinct per index so each placeholder maps to a distinct
        # embedded ppt/media/* part (honest per-image provenance).
        rgb = ((i * 37) % 256, (i * 53) % 256, (i * 71) % 256)
        (images_dir / filename).write_bytes(_png_bytes(8, 8, rgb))
    return len(requests)


# ---------------------------------------------------------------------------
# Subprocess invocation. Each documented command runs verbatim under the
# repo root with byte-compilation disabled; output is captured and surfaced
# only when the stage fails so a green run stays readable.
# ---------------------------------------------------------------------------


@dataclass
class _Stage:
    name: str
    rc: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.rc == 0

    def tail(self, limit: int = 20) -> str:
        lines: list[str] = []
        for label, text in (("stdout", self.stdout), ("stderr", self.stderr)):
            kept = (text or "").splitlines()[-limit:]
            if kept:
                lines.append(f"{label} tail:")
                lines.extend(f"  {ln}" for ln in kept)
        return "\n".join(lines)


def _run(name: str, cmd: list[str]) -> _Stage:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, env=env,
    )
    return _Stage(name=name, rc=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


# ---------------------------------------------------------------------------
# Repo-status delta. The whole point of the dry run is to prove the
# documented flow produces a deck WITHOUT touching the repo. We snapshot
# `git status --porcelain` (which honours .gitignore, so a gitignored
# __pycache__/ or dist/ does not register) before and after the run and
# require the two to be identical.
# ---------------------------------------------------------------------------


def _git_status() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(REPO_ROOT), capture_output=True, text=True,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    return proc.stdout


def _status_delta(before: str | None, after: str | None) -> list[str]:
    """Lines present in `after` but not `before` (new repo artifacts), plus
    a sentinel if git status could not be read on either side."""
    if before is None or after is None:
        return ["<git status --porcelain could not be read>"]
    before_lines = set(before.splitlines())
    after_lines = set(after.splitlines())
    return sorted(after_lines - before_lines)


# ---------------------------------------------------------------------------
# Core dry run. Executes the four documented steps under `out_dir` (whose
# parent must exist; out_dir itself must be missing or empty -- the wrapper's
# own gate enforces that). Returns (ok, checks, deck, summary).
# ---------------------------------------------------------------------------


def _dry_run(
    out_dir: Path,
) -> tuple[bool, list[tuple[str, bool, str]], Path | None, Path | None]:
    checks: list[tuple[str, bool, str]] = []
    packet_dir = out_dir / _PACKET_SUBDIR
    review_pkg = out_dir.joinpath(*_REVIEW_PACKAGE)
    deck = review_pkg / "deck.pptx"
    summary = review_pkg / "summary.json"

    # Step 1: local source -> generation packet.
    s1 = _run(
        "first run: --source examples/mvp_demo_source.md --out-dir <OUT>",
        [sys.executable, str(WRAPPER),
         "--source", str(DEMO_SOURCE), "--out-dir", str(out_dir)],
    )
    checks.append(("first_run_builds_packet", s1.ok, s1.tail() if not s1.ok else ""))
    if not s1.ok:
        return False, checks, None, None

    # Step 2: simulate the image-generation step with placeholder PNGs.
    try:
        n = _write_placeholder_images(packet_dir)
        checks.append((f"placeholder_images_written({n})", True, ""))
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        checks.append(("placeholder_images_written", False, f"{type(exc).__name__}: {exc}"))
        return False, checks, None, None

    # Step 3: filled packet + returned images -> editable deck.
    s3 = _run(
        "resume run: --resume <OUT>",
        [sys.executable, str(WRAPPER), "--resume", str(out_dir)],
    )
    checks.append(("resume_run_builds_deck", s3.ok, s3.tail() if not s3.ok else ""))
    if not s3.ok:
        return False, checks, None, None

    # The deck MUST exist after a clean resume.
    if not deck.is_file():
        checks.append(("deck_pptx_present", False, f"missing {deck}"))
        return False, checks, None, None
    checks.append(("deck_pptx_present", True, ""))

    # Step 4: read-only re-validation of the produced review package.
    s4 = _run(
        "validate_operator_review_package --out-dir <OUT>/review/review_package",
        [sys.executable, str(PACKAGE_VALIDATOR), "--out-dir", str(review_pkg)],
    )
    checks.append(("review_package_validates", s4.ok, s4.tail() if not s4.ok else ""))
    if not s4.ok:
        return False, checks, deck, None

    if not summary.is_file():
        checks.append(("summary_json_present", False, f"missing {summary}"))
        return False, checks, deck, None
    checks.append(("summary_json_present", True, ""))

    return True, checks, deck, summary


def _execute(out_dir: Path) -> tuple[bool, Path | None, Path | None]:
    """Run the dry run under `out_dir`, bracketed by a repo-status snapshot,
    and print every check + the produced deck / summary paths."""
    before = _git_status()
    ok, checks, deck, summary = _dry_run(out_dir)
    after = _git_status()

    for name, c_ok, detail in checks:
        print(f"  [{'PASS' if c_ok else 'FAIL'}] {name}")
        if not c_ok and detail:
            for line in detail.splitlines():
                print(f"      {line}")

    delta = _status_delta(before, after)
    repo_ok = not delta
    if repo_ok:
        print("  [PASS] repo_unchanged (git status --porcelain identical pre/post)")
    else:
        print("  [FAIL] repo_unchanged -- the dry run added/changed repo artifacts:")
        for line in delta:
            print(f"      {line}")

    if deck is not None and deck.is_file():
        print()
        print(f"  deck.pptx:    {deck}")
        if summary is not None and summary.is_file():
            print(f"  summary.json: {summary}")

    return (ok and repo_ok), deck, summary


# ---------------------------------------------------------------------------
# Outside-repo guard for a caller-supplied --out-dir. The wrapper already
# refuses repo-tree out-dirs; this is a clearer, earlier gate-level message
# for the "never under the repo" requirement.
# ---------------------------------------------------------------------------


def _outside_repo_failure(out_dir_arg: str) -> str | None:
    resolved = Path(os.path.abspath(out_dir_arg))
    try:
        repo_real = REPO_ROOT.resolve()
    except OSError:  # pragma: no cover - defensive
        repo_real = REPO_ROOT
    if resolved == repo_real or repo_real in resolved.parents:
        return (
            f"--out-dir {out_dir_arg!r} resolves inside the repo tree "
            f"({repo_real}); choose an outside-repo path (e.g. under /tmp) so "
            f"the dry run cannot pollute the repo."
        )
    return None


# ---------------------------------------------------------------------------
# Mode drivers.
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    print("=== mvp_company_machine_dry_run --self-test ===")
    with tempfile.TemporaryDirectory(prefix="szh-mvp-dry-run-") as raw_td:
        # The wrapper requires out_dir missing-or-empty with an existing
        # parent; the TemporaryDirectory exists, so nest one level under it.
        out_dir = Path(raw_td) / "out"
        ok, _deck, _summary = _execute(out_dir)
    # The TemporaryDirectory (and the produced deck) are now removed --
    # nothing is retained outside the repo, and nothing was written inside it.
    if ok:
        print(
            "\nOK: documented MVP flow ran end-to-end (packet -> placeholder "
            "images -> editable deck -> validated review package); repo "
            "unchanged. Temp output discarded -- no repo pollution."
        )
        return 0
    print(
        "\nFAIL: company-machine dry run did not pass; see the failing "
        "check(s) above.",
        file=sys.stderr,
    )
    return 1


def _run_out_dir(out_dir_arg: str) -> int:
    print("=== mvp_company_machine_dry_run --out-dir ===")
    failure = _outside_repo_failure(out_dir_arg)
    if failure:
        print(f"FAIL: {failure}", file=sys.stderr)
        return 2
    out_dir = Path(out_dir_arg)
    ok, deck, _summary = _execute(out_dir)
    if ok and deck is not None:
        print(
            f"\nOK: documented MVP flow ran end-to-end; repo unchanged. "
            f"Artifacts retained under {out_dir}."
        )
        return 0
    print(
        "\nFAIL: company-machine dry run did not pass; see the failing "
        "check(s) above.",
        file=sys.stderr,
    )
    return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Company-machine dry-run gate: runs the documented MVP quickstart "
            "end-to-end from a fresh outside-repo output directory (run_mvp "
            "--source -> placeholder images -> run_mvp --resume -> "
            "validate_operator_review_package) and fails closed if the deck is "
            "missing, the review-package validator refuses the result, or the "
            "run leaves any new artifact in the repo (git status --porcelain "
            "delta). Drives the documented commands as subprocesses; adds no "
            "renderer / validator and synthesises only placeholder pixels. "
            "Stdlib-only, local-only: no D-One, MCP, Qoder, public network, "
            "telemetry, model API, or image search."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run the full documented flow under an auto-removed "
            "tempfile.TemporaryDirectory() (outside the repo), assert every "
            "step + the repo-status delta, print the produced deck + summary "
            "paths, then discard the temp output. The acceptance gate; retains "
            "nothing."
        ),
    )
    mode.add_argument(
        "--out-dir",
        metavar="DIR",
        help=(
            "Run the same flow against a caller-supplied DIR that MUST be "
            "outside the repo tree (e.g. under /tmp), missing or empty, with "
            "an existing parent. Retains the artifacts and prints the final "
            "deck + summary paths."
        ),
    )
    return parser


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)
    if args.self_test:
        return _run_self_test()
    return _run_out_dir(args.out_dir)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
