#!/usr/bin/env python3
"""init_strategy_plan.py
=======================

Narrow contract helper: project a STARTER ``strategy_plan.json`` from a
generation packet's ``image_request_plan.json``.

WHAT IT IS
----------
The strategy plan is the main quality path for the next layer above the
company-machine MVP: one strategy record per slide (core_message,
page_type, the editable visual_structure archetype, optional key_metrics,
and an image_need) so a deck is driven by a deliberate plan rather than by
"source headings + one image each". This helper writes a schema-valid
STARTER plan a human or agent then refines; it does NOT plan the deck for
you.

WHAT IT DERIVES (heading-level only -- no source body text)
-----------------------------------------------------------
From the packet's ``image_request_plan.json`` (itself one request per ATX
heading), per slide:

  * ``slide_index`` / ``slide_title`` / ``deck_title`` are copied through;
  * ``page_type`` / ``visual_structure`` are assigned a conservative
    starter: the first slide is a ``cover`` / ``cover_hero``, the last is a
    ``closing`` / ``closing_summary``, and every middle slide is a
    ``content`` / ``executive_summary_cards`` page;
  * ``core_message`` is a heading-derived seed (``"Core message for: ..."``)
    the author replaces; it is NOT extracted from the source body;
  * ``image_need`` is biased toward EDITABLE structures: ONLY the cover is
    ``recommended`` (the one slot where a hero image earns its place); every
    other slide is ``none``. The contract has no ``required`` value, so a
    generated image is never mandatory.

This intentionally REDUCES image reliance relative to the image_request
plan (which requests one image per heading): the starter strategy says most
slides need no generated image and should use editable shapes / tables / KPI
structures instead.

WHAT IT DOES NOT DO
-------------------
It reads no source body text, infers no metrics, designs no deck, generates
no images / render_models / SVG / PPTX, and calls no network (no D-One,
model API, MCP, telemetry, or image search). It refuses to overwrite an
existing output file and rolls back a write whose on-disk re-validation
fails.

USAGE
-----
    # default output: <packet-dir>/strategy_plan.json
    python3 scripts/init_strategy_plan.py --packet-dir <generation_packet>

    # explicit output path
    python3 scripts/init_strategy_plan.py --packet-dir <dir> --out <path>

    python3 scripts/init_strategy_plan.py --self-test

Exit codes:
    0  starter strategy_plan written (or every self-test probe passed).
    1  projection / validation / write failure.
    2  invocation / unsafe-path / parse error.
"""

from __future__ import annotations

import sys

# Refuse `.pyc` writes from any imported module; mirrors every sibling helper.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

# Reuse the source-to-image bridge's OWN input-dir + plan-schema gates and
# the strategy-layer semantic validator, so this helper cannot diverge from
# the contracts they enforce.
import source_to_image_requests as s2ir  # noqa: E402
from validate_strategy_layer import validate_strategy_plan_obj  # noqa: E402

_PLAN_FILENAME = "strategy_plan.json"

_BOUNDARY = (
    "Local-only deck strategy plan: one record per slide, derived from "
    "slide headings only with no document prose embedded. No image "
    "generator, D-One, model API, public network, or telemetry is invoked. "
    "Generated images are auxiliary - most slides use editable shapes, "
    "tables, and KPI structures."
)


def project_strategy_plan(plan: dict) -> dict:
    """Project a STARTER strategy_plan dict from a (validated)
    image_request_plan dict. Heading-derived only; biases image_need toward
    editable structures (only the cover is ``recommended``)."""
    requests = plan["image_requests"]
    n = len(requests)
    slides: list[dict] = []
    for req in requests:
        idx = req["index"]
        title = req["slide_title"]
        if idx == 1:
            page_type, visual_structure, image_need = (
                "cover", "cover_hero", "recommended",
            )
        elif idx == n:
            page_type, visual_structure, image_need = (
                "closing", "closing_summary", "none",
            )
        else:
            page_type, visual_structure, image_need = (
                "content", "executive_summary_cards", "none",
            )
        slides.append({
            "slide_index": idx,
            "slide_title": title,
            "core_message": f"Core message for: {title}",
            "page_type": page_type,
            "visual_structure": visual_structure,
            "image_need": image_need,
        })
    return {
        "schema_version": "1",
        "plan_id": "strategy_plan",
        "boundary": _BOUNDARY,
        "deck_title": plan["deck"]["title"],
        "slide_count": n,
        "slides": slides,
    }


def _safe_unlink(path: Path) -> None:
    """Remove a regular (non-symlink) file we just wrote, ignoring errors."""
    with contextlib.suppress(OSError):
        if path.is_file() and not path.is_symlink():
            path.unlink()


def _emit(packet_dir: Path, out_path: Path) -> tuple[int, list[str]]:
    """Read + validate the packet plan, project the starter strategy_plan,
    validate it, and write it fail-closed (refuse overwrite/symlink;
    re-validate on disk; roll back on failure). Returns ``(rc, failures)``."""
    plan_path = packet_dir / "image_request_plan.json"
    if plan_path.is_symlink():
        return 2, [f"packet image_request_plan.json {plan_path} is a symlink; refused"]
    if not plan_path.is_file():
        return 2, [
            f"no image_request_plan.json in --packet-dir {packet_dir}; run the "
            f"first generation step before projecting a strategy plan"
        ]
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return 2, [f"cannot read {plan_path}: {type(exc).__name__}: {exc}"]

    # Reuse the bridge's own schema gate on the INPUT plan.
    plan_errors = s2ir._validate_plan(plan)
    if plan_errors:
        return 1, [
            f"input image_request_plan.json failed schema validation: {e}"
            for e in plan_errors
        ]

    strategy = project_strategy_plan(plan)

    # Validate the projection in memory BEFORE touching disk.
    out_errors = validate_strategy_plan_obj(strategy)
    if out_errors:
        return 1, [f"projected strategy_plan failed validation: {e}" for e in out_errors]

    # Refuse to overwrite, and never follow a symlink planted at the path.
    if out_path.is_symlink():
        return 1, [f"refusing to write through symlink at {out_path}"]
    if out_path.exists():
        return 1, [
            f"refusing to overwrite existing {out_path}; remove it first to "
            f"regenerate the starter strategy plan"
        ]

    text = json.dumps(strategy, indent=2, ensure_ascii=False) + "\n"
    try:
        fd = os.open(out_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
    except OSError as exc:
        return 1, [f"cannot write {out_path}: {type(exc).__name__}: {exc}"]

    # Re-read + re-validate on disk; roll back our own file on any failure.
    try:
        disk = json.loads(out_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        _safe_unlink(out_path)
        return 1, [f"re-read of {out_path} failed: {type(exc).__name__}: {exc}"]
    disk_errors = validate_strategy_plan_obj(disk)
    if disk_errors:
        _safe_unlink(out_path)
        return 1, [f"on-disk strategy_plan failed re-validation: {e}" for e in disk_errors]
    return 0, []


# ---------------------------------------------------------------------------
# Self-test. Pure projection probes plus a real-packet round-trip built with
# the source-to-image bridge. Every scenario runs under a per-run TMPDIR; no
# caller-visible artifact is retained.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _captured():
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield buf


def _build_packet(work: Path, body: str) -> Path:
    """Build a real generation packet from Markdown using the bridge; return
    the packet dir (carrying image_request_plan.json). ``work`` is created if
    needed; the bridge creates the (missing) packet dir under it."""
    work.mkdir(parents=True, exist_ok=True)
    src = work / "report.md"
    src.write_text(body, encoding="utf-8")
    packet = work / "generation_packet"
    with _captured():
        rc = s2ir.main(
            ["--source", str(src), "--generation-packet", "--out-dir", str(packet)]
        )
    if rc != 0:
        raise AssertionError(f"could not build packet: rc={rc}")
    return packet


def _run_self_tests() -> int:
    print("=== init_strategy_plan --self-test ===")
    results: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    # P1 pure projection: a 3-slide plan -> cover recommended, middle/last none.
    try:
        fake = {
            "deck": {"title": "Demo Deck"},
            "image_requests": [
                {"index": 1, "slide_title": "Opening"},
                {"index": 2, "slide_title": "Middle"},
                {"index": 3, "slide_title": "Wrap"},
            ],
        }
        strat = project_strategy_plan(fake)
        ok = (
            validate_strategy_plan_obj(strat) == []
            and strat["slide_count"] == 3
            and strat["deck_title"] == "Demo Deck"
            and strat["slides"][0]["image_need"] == "recommended"
            and strat["slides"][0]["visual_structure"] == "cover_hero"
            and strat["slides"][1]["image_need"] == "none"
            and strat["slides"][2]["image_need"] == "none"
            and strat["slides"][2]["visual_structure"] == "closing_summary"
        )
        record("pure_projection_valid_and_biased", ok)
    except Exception as exc:  # pragma: no cover - defensive
        record("pure_projection_valid_and_biased", False, f"raised {exc!r}")

    # P2 editable-first bias: exactly one slide is image_need 'recommended'.
    try:
        fake = {
            "deck": {"title": "T"},
            "image_requests": [
                {"index": i, "slide_title": f"H{i}"} for i in range(1, 6)
            ],
        }
        strat = project_strategy_plan(fake)
        rec = sum(1 for s in strat["slides"] if s["image_need"] == "recommended")
        non = sum(1 for s in strat["slides"] if s["image_need"] == "none")
        record("editable_first_single_hero", rec == 1 and non == 4,
                "" if rec == 1 and non == 4 else f"recommended={rec} none={non}")
    except Exception as exc:  # pragma: no cover - defensive
        record("editable_first_single_hero", False, f"raised {exc!r}")

    with tempfile.TemporaryDirectory(prefix="init-strategy-selftest-") as raw_td:
        td = Path(raw_td)

        # P3 real-packet round-trip: build a packet, emit, re-validate on disk.
        try:
            packet = _build_packet(td / "rt", s2ir._SAMPLE_MD)
            with _captured():
                rc = main(["--packet-dir", str(packet)])
            out = packet / _PLAN_FILENAME
            ok = rc == 0 and out.is_file()
            if ok:
                disk = json.loads(out.read_text(encoding="utf-8"))
                ok = (
                    validate_strategy_plan_obj(disk) == []
                    and disk["slides"][0]["image_need"] == "recommended"
                    and sum(1 for s in disk["slides"]
                            if s["image_need"] == "recommended") == 1
                )
            record("real_packet_roundtrip_valid", ok,
                    "" if ok else f"rc={rc}; plan missing/invalid")
        except Exception as exc:  # pragma: no cover - defensive
            record("real_packet_roundtrip_valid", False, f"raised {exc!r}")

        # P4 refuse-to-overwrite: a second run on the same packet fails closed.
        try:
            packet = _build_packet(td / "ow", s2ir._SAMPLE_MD)
            with _captured():
                rc1 = main(["--packet-dir", str(packet)])
                rc2 = main(["--packet-dir", str(packet)])
            record("refuse_overwrite", rc1 == 0 and rc2 != 0,
                    "" if rc1 == 0 and rc2 != 0 else f"rc1={rc1} rc2={rc2}")
        except Exception as exc:  # pragma: no cover - defensive
            record("refuse_overwrite", False, f"raised {exc!r}")

        # P5 unsafe / missing --packet-dir is refused (rc 2), no write.
        try:
            with _captured():
                rc_uri = main(["--packet-dir", "file:///tmp/x"])
                rc_missing = main(["--packet-dir", str(td / "nope")])
            ok = rc_uri == 2 and rc_missing == 2
            record("unsafe_packet_dir_refused", ok,
                    "" if ok else f"uri={rc_uri} missing={rc_missing}")
        except Exception as exc:  # pragma: no cover - defensive
            record("unsafe_packet_dir_refused", False, f"raised {exc!r}")

        # P6 a malformed packet plan is refused before any strategy_plan write.
        try:
            bad = td / "bad_packet"
            bad.mkdir()
            (bad / "image_request_plan.json").write_text("{}", encoding="utf-8")
            with _captured():
                rc = main(["--packet-dir", str(bad)])
            ok = rc != 0 and not (bad / _PLAN_FILENAME).exists()
            record("malformed_plan_refused", ok,
                    "" if ok else f"rc={rc}; strategy_plan written anyway")
        except Exception as exc:  # pragma: no cover - defensive
            record("malformed_plan_refused", False, f"raised {exc!r}")

    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, detail in results:
        tag = "PASS" if ok else "FAIL"
        suffix = f" -- {detail}" if detail and not ok else ""
        print(f"  [{tag}] {name}{suffix}")
    print(f"\n{passed}/{len(results)} probe(s) passed.")
    return 0 if passed == len(results) else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Project a STARTER strategy_plan.json (one strategy record per "
            "slide) from a generation packet's image_request_plan.json. "
            "Heading-level only -- reads no source body text, infers no "
            "metrics, designs no deck, and generates no images. Biases "
            "image_need toward editable structures (only the cover slide is "
            "'recommended'). Writes a schema-valid starter a human/agent "
            "refines. Local-only; no network."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--packet-dir", metavar="DIR",
        help=(
            "Generation packet directory carrying image_request_plan.json "
            "(e.g. <out-dir>/generation_packet). The starter strategy plan "
            "is written to <DIR>/strategy_plan.json unless --out is given. "
            "Refuses a URI-shaped / symlinked / missing / non-directory path."
        ),
    )
    mode.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run hermetic probes under a per-run TMPDIR: pure projection "
            "validity + editable-first bias (one hero), a real-packet "
            "round-trip, refuse-to-overwrite, unsafe/missing --packet-dir "
            "refusal, and a malformed packet plan refused before any write. "
            "No caller-visible artifact retained."
        ),
    )
    parser.add_argument(
        "--out", metavar="PATH",
        help=(
            "Explicit output path for the starter strategy_plan.json. "
            "Defaults to <packet-dir>/strategy_plan.json. Refuses to "
            "overwrite an existing file or write through a symlink."
        ),
    )
    return parser


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)

    if args.self_test:
        return _run_self_tests()

    # Reuse the bridge's read-only input-dir gate (URI / symlink /
    # symlink-ancestor / missing / non-directory refusals).
    packet_dir, failures = s2ir._validate_input_dir(args.packet_dir, "--packet-dir")
    if failures or packet_dir is None:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 2

    out_path = Path(args.out) if args.out else packet_dir / _PLAN_FILENAME

    rc, errs = _emit(packet_dir, out_path)
    if rc != 0:
        for line in errs:
            print(f"FAIL: {line}", file=sys.stderr)
        return rc

    print(f"OK: wrote starter {out_path}")
    print(
        "  Next: refine core_message / key_metrics / visual_structure per "
        "slide, then validate with\n"
        f"    python3 scripts/validate_strategy_layer.py --strategy-plan {out_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
