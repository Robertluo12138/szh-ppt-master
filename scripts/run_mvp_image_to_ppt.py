#!/usr/bin/env python3
"""One-command MVP wrapper: local source -> generation packet -> (returned
images) -> validated review package (MOCK / LOCAL only).

This is a THIN orchestration wrapper over two existing lower-level helpers.
It adds NO new renderer, NO new validation, and synthesises NO pixels: it
sequences the helpers and reuses their safety gates verbatim. The operator
runs it twice, with a human/internal image-generation step in between.

CLI shape::

    # First run: local .docx / .md / .markdown / .txt source -> packet
    python3 scripts/run_mvp_image_to_ppt.py \\
        --source /path/report.docx --out-dir /tmp/szh-mvp   # OUT outside repo

    # ... hand the packet to an image generator, drop the returned images
    # under <out-dir>/generation_packet/expected_images ...

    # Resume run: filled packet + returned local images -> review package
    python3 scripts/run_mvp_image_to_ppt.py --resume /tmp/szh-mvp

    # Self-test (every scenario under TMPDIR; nothing leaks under the repo)
    python3 scripts/run_mvp_image_to_ppt.py --self-test

First run (``--source S --out-dir O``):

  * ``O`` is validated by the SAME ``_validate_out_dir_arg`` gate the
    lower-level helpers apply (URI-shaped / symlink / symlink-ancestor /
    repo-tree / non-empty refusals; parent must exist) and then created.
  * ``.md`` / ``.markdown`` is used directly as the Markdown source.
    ``.docx`` / ``.txt`` is first normalised to Markdown via
    ``ingest_local_source_file.py --md-out`` (written to
    ``<O>/normalized_source.md``). Any other extension is refused (``.pdf``
    is a documented upstream TODO).
  * if the source basename is NOT identifier-safe for the lower-level
    helpers (Chinese characters, spaces, punctuation, parentheses -- common
    on a company business folder), a byte-for-byte copy is first staged to
    ``<O>/source_input/source_input.<ext>`` and fed to the helpers in its
    place, so the operator never has to rename or copy a business file by
    hand. The original file is never renamed or modified. Staging re-applies
    the helpers' own URI / symlink / symlink-ancestor / repo-generated /
    regular-file refusals before copying, and the helpers still re-run every
    content / byte / heading gate on the staged bytes -- it adapts the
    filename without loosening any safety check. If the run is then refused
    (e.g. credential / public-network content), the staged copy is removed,
    so refused raw source bytes never linger on disk.
  * the Markdown source feeds ``source_to_image_requests.py
    --generation-packet --out-dir <O>/generation_packet``, which writes the
    image_request_plan.json + a human-readable image_generation_requests.md
    + starter manifest.json / generated_provenance.json + an
    expected_images/README.md naming every required filename.
  * with ``--emit-strategy-plan`` the wrapper additionally projects a
    STARTER ``strategy_plan.json`` into the packet (one strategy record per
    slide -- core_message / page_type / visual_structure / image_need --
    biased toward editable structures, only the cover suggesting a generated
    image) via ``init_strategy_plan.py``, BEFORE any image generation. Opt-in;
    the default packet is byte-identical to prior runs.
  * the wrapper then prints the EXACT next step: drop the returned images
    under ``<O>/generation_packet/expected_images`` and re-run with
    ``--resume <O>``.

Resume run (``--resume O``, source-free):

  * runs ``source_to_image_requests.py --resume-packet --packet-dir
    <O>/generation_packet --images-dir <O>/generation_packet/expected_images
    --out-dir <O>/review``, which checks the returned images match the
    plan's expected filenames EXACTLY (valid PNG bytes — every requested
    filename ends in ``.png`` — no symlinks / extras / missing), drives the
    existing operator ``--bundle`` lane, and
    re-validates the result read-only.
  * the validated, editable deck lands at
    ``<O>/review/review_package/deck.pptx`` (the resume helper always nests
    a ``review_package/`` under its ``--out-dir``; the wrapper passes
    ``<O>/review`` so the packet under ``<O>/generation_packet`` is left
    untouched).

Stdlib-only. Local-only -- does NOT call D-One, MCP, Qoder, a public
network, telemetry, a model API, an image search, or any external service.
NOT real image generation; NOT full report-to-PPT automation.
"""

from __future__ import annotations

import sys

# Refuse `.pyc` writes from any imported module. Mirrors the gate every
# sibling helper applies; must be flipped BEFORE any first-party import.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import contextlib  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

# Reuse the lower-level helpers' OWN entry points + path gates so this
# wrapper cannot diverge from the contract they enforce. It calls their
# `main(argv)` in-process (the same reuse interface their self-tests use),
# adds no second validator, and inherits every refusal they already apply.
import ingest_local_source_file as ingest  # noqa: E402
import source_to_image_requests as s2ir  # noqa: E402
import init_strategy_plan as isp  # noqa: E402
from core_image_to_editable_ppt_demo import (  # noqa: E402
    _forbidden_symlink_ancestor,
    _validate_out_dir_arg,
)

# Fixed layout under the wrapper's --out-dir. The generation packet and the
# resume build live in distinct sibling subdirectories so the resume step
# never has to write into the (non-empty) packet directory.
_PACKET_SUBDIR = "generation_packet"
_REVIEW_SUBDIR = "review"
_NORMALIZED_MD = "normalized_source.md"

# When the source basename is not identifier-safe for the lower-level
# helpers (Chinese characters, spaces, punctuation, parentheses -- common on
# a company business folder), the first run stages a byte-for-byte copy
# under this deterministic safe name inside the validated --out-dir and
# feeds THAT to the helpers, so the operator never has to rename or copy a
# business file by hand.
_STAGED_SUBDIR = "source_input"
_STAGED_STEM = "source_input"

# Source extensions routed straight to the Markdown bridge vs. normalised
# to Markdown via ingest_local_source_file.py first.
_MARKDOWN_SUFFIXES = frozenset({".md", ".markdown"})
_INGEST_SUFFIXES = frozenset({".docx", ".txt"})


def _stage_source_if_needed(
    source_arg: str, out_dir: Path, suffix: str
) -> tuple[str | None, str | None, list[str]]:
    """Adapt a business filename the lower-level helpers would refuse.

    Returns ``(effective_source, operator_note, failures)``.

    If the source basename is ALREADY accepted by the lower-level helpers
    (identifier-safe per their shared ``^[A-Za-z0-9_][A-Za-z0-9_.\\-]*$``
    pattern), the source is returned unchanged with no note and no staging,
    so a run with an acceptable name is byte-identical to calling the
    helpers directly.

    Otherwise (a Chinese / spaced / punctuated business filename), a
    VERBATIM byte copy is written to
    ``<out-dir>/source_input/source_input.<suffix>`` and that path is
    returned, so the helpers see an identifier-safe basename. The copy is
    created exclusively (never overwrites, never follows a symlink at the
    destination) and is preceded by the SAME original-path refusals the
    helpers apply (URI / symlink / symlink-ancestor / repo-generated /
    non-regular-file) -- these operate on the source PATH, which the copy
    dereferences by reading its bytes, so re-applying them here keeps
    staging from smuggling in a source the helpers would have refused. The
    helpers then re-run every CONTENT gate (extension, byte caps, UTF-8,
    credential / public-network / heading scans) on the staged bytes
    unchanged, so the wrapper adapts the filename without loosening any
    lower-level safety check. A mid-write failure removes the partial copy
    here; a DOWNSTREAM helper refusal is rolled back by the caller (see
    ``_discard_staged_source``) so refused raw source bytes never linger on
    disk -- just as the helpers leave nothing behind when they refuse.
    """
    # Reuse the lower-level helpers' OWN identifier-safe pattern so the
    # wrapper's "would they accept this basename?" test cannot drift from
    # theirs. ingest_local_source_file and source_to_image_requests carry
    # the identical regex; reusing the compiled copy keeps the three in
    # lock-step (a future divergence could only stage unnecessarily or
    # surface the helper's own refusal -- never bypass a gate).
    original_name = Path(source_arg).name
    if ingest._SAFE_NAME_RE.match(original_name):
        return source_arg, None, []

    # Basename is NOT safe -> we must stage. First re-apply the original-path
    # gates that a byte-copy would otherwise bypass.
    if "://" in source_arg:
        return None, None, [
            f"--source {source_arg!r} is URI-shaped; refused (local-only)"
        ]
    src = Path(source_arg)
    if src.is_symlink():
        return None, None, [
            f"--source {src} is a symlink; refused so a symlink cannot "
            f"redirect which bytes are staged"
        ]
    bad_ancestor = _forbidden_symlink_ancestor(src)
    if bad_ancestor is not None:
        ancestor, tgt = bad_ancestor
        return None, None, [
            f"--source {src} has a symlink ancestor {ancestor} (-> {tgt}); "
            f"refused so a symlink in the typed path cannot redirect the read"
        ]
    try:
        resolved = src.resolve(strict=False)
    except OSError as exc:
        return None, None, [
            f"--source {src} could not be resolved: {type(exc).__name__}: {exc}"
        ]
    if ingest._is_repo_generated_path(resolved):
        return None, None, [
            f"--source {resolved} resolves inside a repo generated-output "
            f"directory; refused -- a generated artifact must not be fed back "
            f"in as a source"
        ]
    if not src.is_file():
        return None, None, [f"--source {src} is not a regular file"]

    try:
        raw = src.read_bytes()
    except OSError as exc:
        return None, None, [
            f"cannot read --source {src}: {type(exc).__name__}: {exc}"
        ]

    staged_dir = out_dir / _STAGED_SUBDIR
    staged = staged_dir / f"{_STAGED_STEM}{suffix}"
    try:
        staged_dir.mkdir(parents=False, exist_ok=False)
    except OSError as exc:
        return None, None, [
            f"cannot create staging dir {staged_dir}: "
            f"{type(exc).__name__}: {exc}"
        ]
    # Exclusive create (O_EXCL): never overwrite an existing file, and never
    # follow a symlink planted at the destination path. On any write error,
    # remove the partial copy + the dir we just made so a failed stage never
    # leaves raw source bytes behind.
    try:
        fd = os.open(staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(raw)
    except OSError as exc:
        try:
            if staged.is_file() and not staged.is_symlink():
                staged.unlink()
            staged_dir.rmdir()
        except OSError:
            pass
        return None, None, [
            f"cannot stage --source to {staged}: {type(exc).__name__}: {exc}"
        ]

    note = (
        f"NOTE: source basename {original_name!r} is not identifier-safe for "
        f"the lower-level helpers; staged a byte-for-byte copy to {staged} "
        f"and used that as the source (your original file was not renamed or "
        f"modified)."
    )
    return str(staged), note, []


def _discard_staged_source(out_dir: Path, did_stage: bool, suffix: str) -> None:
    """Remove the staged source copy (and the dir created for it) when a
    first run FAILS after staging, so refused raw source bytes -- exactly the
    credential / public-network material the lower-level content gates exist
    to reject -- never linger on disk. The helpers leave nothing behind when
    they refuse a source; this keeps the wrapper's staging just as
    fail-closed. No-op when nothing was staged (an acceptable basename). Only
    the file the wrapper itself wrote is unlinked, and the dir is removed
    solely via ``rmdir`` (which refuses a non-empty dir), so an unexpected
    foreign file is preserved + surfaced rather than deleted."""
    if not did_stage:
        return
    staged_dir = out_dir / _STAGED_SUBDIR
    staged_file = staged_dir / f"{_STAGED_STEM}{suffix}"
    try:
        if staged_file.is_file() and not staged_file.is_symlink():
            staged_file.unlink()
        staged_dir.rmdir()  # removes the dir only if it is now empty
    except OSError as exc:
        print(
            f"WARNING: could not remove staged source under {staged_dir} after "
            f"a failed run ({type(exc).__name__}: {exc}); remove it manually so "
            f"refused source bytes do not linger",
            file=sys.stderr,
        )


def _run_first(
    source_arg: str, out_dir_arg: str, emit_strategy_plan: bool = False
) -> int:
    """First run: local source -> generation packet under <out-dir>.

    When ``emit_strategy_plan`` is set, also project a STARTER
    ``strategy_plan.json`` into the packet (before any image generation) via
    the ``init_strategy_plan`` helper. Opt-in; default leaves the packet
    byte-identical to prior runs."""
    # Same out-dir gate the lower-level helpers apply: URI / symlink /
    # symlink-ancestor / repo-tree / non-empty refusals, parent must exist.
    out_dir, failures = _validate_out_dir_arg(out_dir_arg)
    if failures or out_dir is None:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 2

    suffix = Path(source_arg).suffix.lower()
    if suffix in _MARKDOWN_SUFFIXES:
        needs_ingest = False
    elif suffix in _INGEST_SUFFIXES:
        needs_ingest = True
    else:
        print(
            f"FAIL: --source {source_arg} has unsupported extension "
            f"{suffix or '(none)'!r}; supported: .md / .markdown (used "
            f"directly) or .docx / .txt (normalised via "
            f"ingest_local_source_file.py). PDF is a documented TODO.",
            file=sys.stderr,
        )
        return 2

    # The gate above proved the parent exists and out-dir is missing-or-empty.
    if not out_dir.exists():
        try:
            out_dir.mkdir(parents=False, exist_ok=False)
        except OSError as exc:
            print(
                f"FAIL: cannot create --out-dir {out_dir}: "
                f"{type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            return 1

    # Adapt a business filename the lower-level helpers would refuse: a
    # Chinese / spaced / punctuated basename is staged to a deterministic
    # safe copy inside the already-validated out-dir; an acceptable name is
    # passed through unchanged. The helpers re-run every content gate on the
    # staged bytes, so this only adapts the filename (see
    # _stage_source_if_needed).
    effective_source, note, stage_failures = _stage_source_if_needed(
        source_arg, out_dir, suffix
    )
    if stage_failures or effective_source is None:
        for line in stage_failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 1
    did_stage = effective_source != source_arg
    if note:
        print(note)

    # If a downstream helper REFUSES the source (e.g. credential / public-
    # network content), roll back the staged copy so refused raw source
    # bytes never persist on disk -- the helpers themselves leave nothing
    # behind on refusal, and a staged copy is exactly the sensitive material
    # the content gate just rejected.
    if needs_ingest:
        md_path = out_dir / _NORMALIZED_MD
        rc = ingest.main(["--report", effective_source, "--md-out", str(md_path)])
        if rc != 0:
            _discard_staged_source(out_dir, did_stage, suffix)
            return rc
        markdown_source = str(md_path)
    else:
        markdown_source = effective_source

    packet_dir = out_dir / _PACKET_SUBDIR
    rc = s2ir.main(
        ["--source", markdown_source, "--generation-packet",
         "--out-dir", str(packet_dir)]
    )
    if rc != 0:
        _discard_staged_source(out_dir, did_stage, suffix)
        return rc

    # Optional: project a STARTER strategy plan from the just-built packet,
    # BEFORE any image generation. Opt-in; the default path is unchanged.
    # The starter biases the deck toward editable structures -- most slides
    # need no generated image. The packet itself is already complete, so a
    # projection failure does NOT roll back the packet (the staged source has
    # passed every content gate); it is surfaced and returned non-zero.
    if emit_strategy_plan:
        rc_sp = isp.main(["--packet-dir", str(packet_dir)])
        if rc_sp != 0:
            print(
                "FAIL: generation packet built, but --emit-strategy-plan "
                "projection failed (see above); the packet itself is intact.",
                file=sys.stderr,
            )
            return rc_sp

    expected_images = packet_dir / "expected_images"
    print()
    print("=== run_mvp_image_to_ppt: generation packet ready ===")
    print(f"  packet:  {packet_dir}")
    if emit_strategy_plan:
        print(f"  strategy_plan:  {packet_dir / 'strategy_plan.json'} "
              f"(starter -- refine before the deck build)")
    print()
    print("Next steps:")
    print(f"  1. Give {packet_dir / 'image_generation_requests.md'} to your "
          f"local / internal image generator.")
    print( "  2. Save each returned image under its EXACT requested filename "
          "into:")
    print(f"       {expected_images}")
    print( "  3. Finish the editable deck with:")
    print(f"       python3 scripts/run_mvp_image_to_ppt.py --resume {out_dir}")
    return 0


def _run_resume(out_dir_arg: str, style: str = "default") -> int:
    """Resume run: filled packet + returned images -> review package."""
    if not out_dir_arg:
        print(
            "FAIL: --resume requires a non-empty output directory (the path "
            "passed to the first run's --out-dir)",
            file=sys.stderr,
        )
        return 2
    # Reuse the helper's read-only input-dir gate (URI / symlink /
    # symlink-ancestor / missing / non-directory refusals) for the wrapper
    # out-dir the operator points back at.
    out_dir, failures = s2ir._validate_input_dir(out_dir_arg, "--resume")
    if failures or out_dir is None:
        for line in failures:
            print(f"FAIL: {line}", file=sys.stderr)
        return 2

    packet_dir = out_dir / _PACKET_SUBDIR
    if not packet_dir.is_dir():
        print(
            f"FAIL: no {_PACKET_SUBDIR}/ under --resume {out_dir}; run the "
            f"first step (--source ... --out-dir {out_dir}) before --resume.",
            file=sys.stderr,
        )
        return 2

    images_dir = packet_dir / "expected_images"
    review_root = out_dir / _REVIEW_SUBDIR
    resume_cmd = [
        "--resume-packet",
        "--packet-dir", str(packet_dir),
        "--images-dir", str(images_dir),
        "--out-dir", str(review_root),
    ]
    if style == "company":
        # Opt-in clean-room company style; default leaves the command
        # (and the produced deck) byte-identical to prior runs.
        resume_cmd += ["--style", "company"]
    rc = s2ir.main(resume_cmd)
    if rc != 0:
        return rc

    print()
    print("=== run_mvp_image_to_ppt: review package ready ===")
    print(f"  deck.pptx: {review_root / 'review_package' / 'deck.pptx'}")
    return 0


# ---------------------------------------------------------------------------
# Self-test. Every scenario runs under a per-run TMPDIR (outside the repo);
# no caller-visible artifacts are retained. It proves the WRAPPER's command
# surface only -- the lower-level helpers carry their own exhaustive gates.
# ---------------------------------------------------------------------------


@contextlib.contextmanager
def _captured():
    """Swallow the sequenced helpers' stdout/stderr so probe output stays
    readable; the buffer is surfaced only when a probe fails."""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
        yield buf


def _fill_expected_images(packet_dir: Path) -> None:
    """Write one byte-distinct valid PNG per expected filename, reusing the
    bridge's OWN expected-filename reader + PNG synthesiser so the test data
    matches the resume contract exactly."""
    expected, failures = s2ir._load_expected_filenames(packet_dir)
    if failures or expected is None:
        raise AssertionError(f"could not load expected filenames: {failures}")
    images_dir = packet_dir / "expected_images"
    for idx, name in enumerate(expected):
        rgb = ((idx * 37) % 256, (idx * 53) % 256, (idx * 71) % 256)
        (images_dir / name).write_bytes(s2ir._png_bytes(2 + idx, 2, rgb))


def _run_self_tests() -> int:
    print("=== run_mvp_image_to_ppt --self-test ===")
    results: list[tuple[str, bool, str]] = []

    def record(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    with tempfile.TemporaryDirectory(prefix="run-mvp-selftest-") as raw_td:
        td = Path(raw_td)
        # Reuse the bridge's own safe sample (ATX headings, passes the
        # credential / network / path safety scan) as every source body.
        sample = s2ir._SAMPLE_MD

        # T1 .md first run -> packet, exact resume instruction, then a full
        #    resume round-trip to a validated editable deck.
        try:
            out = td / "md_run"
            md = td / "report.md"
            md.write_text(sample, encoding="utf-8")
            with _captured() as buf:
                rc = _run_first(str(md), str(out))
            packet = out / _PACKET_SUBDIR
            expected_images = packet / "expected_images"
            text = buf.getvalue()
            ok = (
                rc == 0
                and (packet / "image_request_plan.json").is_file()
                and (packet / "image_generation_requests.md").is_file()
                and expected_images.is_dir()
                and str(expected_images) in text
                and f"--resume {out}" in text
            )
            record("md_first_run_packet+instruction", ok,
                   "" if ok else f"rc={rc}; resume/expected hint missing")
            if ok:
                _fill_expected_images(packet)
                with _captured() as buf:
                    rc2 = _run_resume(str(out))
                deck = out / _REVIEW_SUBDIR / "review_package" / "deck.pptx"
                ok2 = rc2 == 0 and deck.is_file()
                record("md_resume_roundtrip_deck", ok2,
                       "" if ok2 else f"rc={rc2}; deck missing\n{buf.getvalue()[-800:]}")
            else:
                record("md_resume_roundtrip_deck", False, "skipped: first run failed")
        except Exception as exc:  # pragma: no cover - defensive
            record("md_first_run_packet+instruction", False, f"raised {exc!r}")
            record("md_resume_roundtrip_deck", False, "skipped: exception above")

        # T1b resume with --style company applies the clean-room company
        #     design tokens end-to-end. rc==0 from the resume path already
        #     implies validate_operator_review_package passed (it runs inside
        #     --resume-packet), so a built deck proves selection + validation.
        try:
            out = td / "company_run"
            md = td / "report_company.md"
            md.write_text(sample, encoding="utf-8")
            with _captured():
                rc = _run_first(str(md), str(out))
            packet = out / _PACKET_SUBDIR
            if rc == 0:
                _fill_expected_images(packet)
                with _captured() as buf:
                    rc2 = _run_resume(str(out), style="company")
                deck = out / _REVIEW_SUBDIR / "review_package" / "deck.pptx"
                ok2 = rc2 == 0 and deck.is_file()
                record("resume_company_style_roundtrip_deck", ok2,
                       "" if ok2 else f"rc={rc2}; deck missing\n{buf.getvalue()[-800:]}")
            else:
                record("resume_company_style_roundtrip_deck", False,
                       "skipped: first run failed")
        except Exception as exc:  # pragma: no cover - defensive
            record("resume_company_style_roundtrip_deck", False, f"raised {exc!r}")

        # T2 .txt first run routes through ingest --md-out (normalized_source.md
        #    written) and still produces a packet.
        try:
            out = td / "txt_run"
            txt = td / "report.txt"
            txt.write_text(sample, encoding="utf-8")
            with _captured():
                rc = _run_first(str(txt), str(out))
            ok = (
                rc == 0
                and (out / _NORMALIZED_MD).is_file()
                and (out / _PACKET_SUBDIR / "image_request_plan.json").is_file()
            )
            record("txt_first_run_via_ingest", ok,
                   "" if ok else f"rc={rc}; normalized_source.md / packet missing")
        except Exception as exc:  # pragma: no cover - defensive
            record("txt_first_run_via_ingest", False, f"raised {exc!r}")

        # T3 .docx first run routes through ingest (heading-style extraction)
        #    and still produces a packet.
        try:
            out = td / "docx_run"
            docx = td / "report.docx"
            docx.write_bytes(ingest._make_docx(
                ingest._DOCX_HEADING_PARAGRAPHS,
                style_names=ingest._DOCX_HEADING_STYLE_NAMES,
            ))
            with _captured():
                rc = _run_first(str(docx), str(out))
            ok = (
                rc == 0
                and (out / _NORMALIZED_MD).is_file()
                and (out / _PACKET_SUBDIR / "image_request_plan.json").is_file()
            )
            record("docx_first_run_via_ingest", ok,
                   "" if ok else f"rc={rc}; normalized_source.md / packet missing")
        except Exception as exc:  # pragma: no cover - defensive
            record("docx_first_run_via_ingest", False, f"raised {exc!r}")

        # T4 resume with NO returned images fails closed (rc != 0).
        try:
            out = td / "missing_run"
            md = td / "report4.md"
            md.write_text(sample, encoding="utf-8")
            with _captured():
                _run_first(str(md), str(out))
                rc = _run_resume(str(out))
            record("resume_missing_images_fails", rc != 0,
                   "" if rc != 0 else "expected non-zero rc")
        except Exception as exc:  # pragma: no cover - defensive
            record("resume_missing_images_fails", False, f"raised {exc!r}")

        # T5 resume with a wrongly-named image fails closed (rc != 0).
        try:
            out = td / "mismatch_run"
            md = td / "report5.md"
            md.write_text(sample, encoding="utf-8")
            with _captured():
                _run_first(str(md), str(out))
            (out / _PACKET_SUBDIR / "expected_images" / "not_a_requested_name.png"
             ).write_bytes(s2ir._png_bytes(3, 2, (1, 2, 3)))
            with _captured():
                rc = _run_resume(str(out))
            record("resume_filename_mismatch_fails", rc != 0,
                   "" if rc != 0 else "expected non-zero rc")
        except Exception as exc:  # pragma: no cover - defensive
            record("resume_filename_mismatch_fails", False, f"raised {exc!r}")

        # T6 unsupported source extension is refused (rc == 2).
        try:
            out = td / "pdf_run"
            pdf = td / "report.pdf"
            pdf.write_text(sample, encoding="utf-8")
            with _captured():
                rc = _run_first(str(pdf), str(out))
            record("unsupported_extension_refused", rc == 2 and not out.exists(),
                   "" if rc == 2 else f"rc={rc}")
        except Exception as exc:  # pragma: no cover - defensive
            record("unsupported_extension_refused", False, f"raised {exc!r}")

        # T7 unsafe out-dir is refused by the reused gate: URI-shaped, and a
        #    path under the repo tree.
        try:
            md = td / "report7.md"
            md.write_text(sample, encoding="utf-8")
            with _captured():
                rc_uri = _run_first(str(md), "file:///tmp/x")
                rc_repo = _run_first(str(md), str(REPO_ROOT / "tmp_mvp_out"))
            ok = rc_uri == 2 and rc_repo == 2
            record("unsafe_out_dir_refused", ok,
                   "" if ok else f"uri={rc_uri} repo={rc_repo}")
        except Exception as exc:  # pragma: no cover - defensive
            record("unsafe_out_dir_refused", False, f"raised {exc!r}")

        # T8 argument-shape gates: --resume must not take --out-dir; --source
        #    requires --out-dir; --resume before a first run is refused.
        try:
            md = td / "report8.md"
            md.write_text(sample, encoding="utf-8")
            empty = td / "empty_resume"
            empty.mkdir()
            with _captured():
                rc_both = main(["--resume", str(empty), "--out-dir", str(td / "y")])
                rc_no_out = main(["--source", str(md)])
                rc_no_packet = main(["--resume", str(empty)])
            ok = rc_both == 2 and rc_no_out == 2 and rc_no_packet == 2
            record("arg_shape_gates", ok,
                   "" if ok else f"both={rc_both} no_out={rc_no_out} no_packet={rc_no_packet}")
        except Exception as exc:  # pragma: no cover - defensive
            record("arg_shape_gates", False, f"raised {exc!r}")

        # T9 a present-but-empty --resume "" is refused (rc 2), never
        #    mis-dispatched to the --source path where Path(None) would
        #    traceback. Covers `--resume ""` alone and with --out-dir.
        try:
            with _captured():
                rc_empty = main(["--resume", ""])
                rc_empty_out = main(["--resume", "", "--out-dir", str(td / "z")])
            ok = rc_empty == 2 and rc_empty_out == 2
            record("empty_resume_refused_no_traceback", ok,
                   "" if ok else f"empty={rc_empty} empty_out={rc_empty_out}")
        except Exception as exc:  # pragma: no cover - defensive
            record("empty_resume_refused_no_traceback", False, f"raised {exc!r}")

        # T10 a Chinese + space .md basename (refused by the lower-level
        #     helpers) is auto-staged to source_input/source_input.md as a
        #     byte-exact copy, the first run still produces a packet and
        #     prints a staging NOTE, and the staged source flows all the way
        #     through a resume round-trip to an editable deck.
        try:
            out = td / "cn_md_run"
            md = td / "霸王茶姬 3月复盘.md"
            md.write_text(sample, encoding="utf-8")
            with _captured() as buf:
                rc = _run_first(str(md), str(out))
            text = buf.getvalue()
            packet = out / _PACKET_SUBDIR
            staged = out / _STAGED_SUBDIR / f"{_STAGED_STEM}.md"
            ok = (
                rc == 0
                and staged.is_file()
                and staged.read_bytes() == sample.encode("utf-8")
                and (packet / "image_request_plan.json").is_file()
                and "NOTE:" in text
                and str(staged) in text
            )
            record("cn_md_staged_first_run_packet", ok,
                   "" if ok else f"rc={rc}; staged/packet/note missing")
            if ok:
                _fill_expected_images(packet)
                with _captured() as buf:
                    rc2 = _run_resume(str(out))
                deck = out / _REVIEW_SUBDIR / "review_package" / "deck.pptx"
                ok2 = rc2 == 0 and deck.is_file()
                record("cn_md_staged_resume_roundtrip_deck", ok2,
                       "" if ok2 else f"rc={rc2}; deck missing\n{buf.getvalue()[-800:]}")
            else:
                record("cn_md_staged_resume_roundtrip_deck", False,
                       "skipped: first run failed")
        except Exception as exc:  # pragma: no cover - defensive
            record("cn_md_staged_first_run_packet", False, f"raised {exc!r}")
            record("cn_md_staged_resume_roundtrip_deck", False, "skipped: exception above")

        # T11 a Chinese + space .txt basename is auto-staged, then routed
        #     through ingest (normalized_source.md) to a packet.
        try:
            out = td / "cn_txt_run"
            txt = td / "霸王茶姬 3月复盘.txt"
            txt.write_text(sample, encoding="utf-8")
            with _captured():
                rc = _run_first(str(txt), str(out))
            staged = out / _STAGED_SUBDIR / f"{_STAGED_STEM}.txt"
            ok = (
                rc == 0
                and staged.is_file()
                and (out / _NORMALIZED_MD).is_file()
                and (out / _PACKET_SUBDIR / "image_request_plan.json").is_file()
            )
            record("cn_txt_staged_first_run_via_ingest", ok,
                   "" if ok else f"rc={rc}; staged/normalized/packet missing")
        except Exception as exc:  # pragma: no cover - defensive
            record("cn_txt_staged_first_run_via_ingest", False, f"raised {exc!r}")

        # T12 a Chinese .docx basename is auto-staged, then routed through
        #     ingest heading-style extraction to a packet.
        try:
            out = td / "cn_docx_run"
            docx = td / "霸王茶姬.docx"
            docx.write_bytes(ingest._make_docx(
                ingest._DOCX_HEADING_PARAGRAPHS,
                style_names=ingest._DOCX_HEADING_STYLE_NAMES,
            ))
            with _captured():
                rc = _run_first(str(docx), str(out))
            staged = out / _STAGED_SUBDIR / f"{_STAGED_STEM}.docx"
            ok = (
                rc == 0
                and staged.is_file()
                and (out / _NORMALIZED_MD).is_file()
                and (out / _PACKET_SUBDIR / "image_request_plan.json").is_file()
            )
            record("cn_docx_staged_first_run_via_ingest", ok,
                   "" if ok else f"rc={rc}; staged/normalized/packet missing")
        except Exception as exc:  # pragma: no cover - defensive
            record("cn_docx_staged_first_run_via_ingest", False, f"raised {exc!r}")

        # T13 staging does NOT bypass the lower-level CONTENT gate: a
        #     Chinese-named .md whose BODY carries credential wording is
        #     still refused after staging (no packet produced), AND the
        #     staged copy of those refused raw bytes is rolled back -- it
        #     must not linger on disk.
        try:
            out = td / "cn_unsafe_run"
            md = td / "霸王茶姬 机密.md"
            md.write_text("# Overview\n\napi_key = abc123\n", encoding="utf-8")
            with _captured():
                rc = _run_first(str(md), str(out))
            ok = (
                rc != 0
                and not (out / _PACKET_SUBDIR / "image_request_plan.json").is_file()
                and not (out / _STAGED_SUBDIR).exists()
            )
            record("cn_unsafe_content_refused_and_rolled_back", ok,
                   "" if ok else f"rc={rc}; packet/staged-copy left behind")
        except Exception as exc:  # pragma: no cover - defensive
            record("cn_unsafe_content_refused_and_rolled_back", False, f"raised {exc!r}")

        # T13b the ingest-path refusal ALSO rolls back the staged copy: a
        #      Chinese-named .txt with credential wording is refused by
        #      ingest, leaving neither a staged raw copy nor normalized md.
        try:
            out = td / "cn_unsafe_txt_run"
            txt = td / "霸王茶姬 机密.txt"
            txt.write_text("# Overview\n\napi_key = abc123\n", encoding="utf-8")
            with _captured():
                rc = _run_first(str(txt), str(out))
            ok = (
                rc != 0
                and not (out / _STAGED_SUBDIR).exists()
                and not (out / _NORMALIZED_MD).exists()
            )
            record("cn_unsafe_txt_staged_rolled_back", ok,
                   "" if ok else f"rc={rc}; staged/normalized left behind")
        except Exception as exc:  # pragma: no cover - defensive
            record("cn_unsafe_txt_staged_rolled_back", False, f"raised {exc!r}")

        # T14 staging preserves the lower-level symlink refusal: a
        #     Chinese-named symlink source is refused and never dereferenced
        #     into the staging dir (the copy must not follow it).
        try:
            out = td / "cn_symlink_run"
            real = td / "real_cn_source.md"
            real.write_text(sample, encoding="utf-8")
            link = td / "霸王茶姬 链接.md"
            made = True
            try:
                link.symlink_to(real)
            except OSError:
                made = False
            if made:
                with _captured():
                    rc = _run_first(str(link), str(out))
                staged = out / _STAGED_SUBDIR / f"{_STAGED_STEM}.md"
                ok = rc != 0 and not staged.exists()
                detail = "" if ok else f"rc={rc}; symlink unexpectedly staged"
            else:  # pragma: no cover - platform without symlink support
                ok, detail = True, "skipped: symlinks unsupported here"
            record("cn_symlink_source_refused", ok, detail)
        except Exception as exc:  # pragma: no cover - defensive
            record("cn_symlink_source_refused", False, f"raised {exc!r}")

        # T15 an acceptable (identifier-safe) basename is NOT staged: no
        #     source_input/ dir is created, proving staging is inert for
        #     already-acceptable names and the existing path is unchanged.
        try:
            out = td / "safe_name_run"
            md = td / "report_safe.md"
            md.write_text(sample, encoding="utf-8")
            with _captured():
                rc = _run_first(str(md), str(out))
            ok = (
                rc == 0
                and not (out / _STAGED_SUBDIR).exists()
                and (out / _PACKET_SUBDIR / "image_request_plan.json").is_file()
            )
            record("safe_name_not_staged", ok,
                   "" if ok else f"rc={rc}; unexpected staging for safe name")
        except Exception as exc:  # pragma: no cover - defensive
            record("safe_name_not_staged", False, f"raised {exc!r}")

        # T16 --emit-strategy-plan writes a starter strategy_plan.json into
        #     the packet on the FIRST run (before image generation), and the
        #     extra packet file does not disturb the resume round-trip to an
        #     editable deck. init_strategy_plan validates + re-validates the
        #     plan it writes, so a returned rc==0 file is already schema- and
        #     semantics-valid; this probe proves the WIRING + coexistence.
        try:
            out = td / "strategy_run"
            md = td / "report16.md"
            md.write_text(sample, encoding="utf-8")
            with _captured():
                rc = _run_first(str(md), str(out), emit_strategy_plan=True)
            packet = out / _PACKET_SUBDIR
            strat = packet / "strategy_plan.json"
            ok = (
                rc == 0
                and strat.is_file()
                and (packet / "image_request_plan.json").is_file()
            )
            record("emit_strategy_plan_first_run", ok,
                   "" if ok else f"rc={rc}; strategy_plan.json missing")
            if ok:
                _fill_expected_images(packet)
                with _captured() as buf:
                    rc2 = _run_resume(str(out))
                deck = out / _REVIEW_SUBDIR / "review_package" / "deck.pptx"
                ok2 = rc2 == 0 and deck.is_file()
                record("emit_strategy_plan_then_resume_deck", ok2,
                       "" if ok2 else f"rc={rc2}; deck missing\n{buf.getvalue()[-800:]}")
            else:
                record("emit_strategy_plan_then_resume_deck", False,
                       "skipped: first run failed")
        except Exception as exc:  # pragma: no cover - defensive
            record("emit_strategy_plan_first_run", False, f"raised {exc!r}")
            record("emit_strategy_plan_then_resume_deck", False, "skipped: exception above")

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
            "One-command MVP wrapper (MOCK / LOCAL only): sequences the "
            "existing ingest + source-to-image-request helpers so an "
            "operator runs ONE command to turn a local .docx / .md / "
            ".markdown / .txt source into an image-generation packet, then "
            "ONE command to turn the filled packet plus returned local "
            "images into a validated, editable review_package/deck.pptx. "
            "Thin orchestration: it adds no renderer, no second validator, "
            "and synthesises no pixels -- it reuses the helpers' own safety "
            "gates verbatim. Local-only: no D-One, MCP, Qoder, public "
            "network, telemetry, model API, or image search. NOT real image "
            "generation; NOT full report-to-PPT automation."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--source",
        help=(
            "First run: path to a local .md / .markdown source (used "
            "directly) or a .docx / .txt source (normalised to Markdown via "
            "ingest_local_source_file.py --md-out first). A non-identifier-safe "
            "basename (Chinese characters, spaces, punctuation -- common on a "
            "company folder) is auto-staged to a byte-for-byte copy at "
            "<out-dir>/source_input/source_input.<ext> and used in place of "
            "the original, so you need NOT rename or copy the file yourself; "
            "every lower-level safety gate still runs on the staged bytes, and "
            "the staged copy is removed if the run is refused. "
            "Produces the generation packet under <out-dir>/generation_packet "
            "and prints where to drop the returned images. Pass "
            "--emit-strategy-plan to also project a starter strategy_plan.json "
            "into the packet before image generation. Requires --out-dir. "
            "PDF is a documented TODO."
        ),
    )
    mode.add_argument(
        "--resume",
        metavar="OUT_DIR",
        help=(
            "Resume run (source-free): the first run's --out-dir. Consumes "
            "the completed packet under <OUT_DIR>/generation_packet plus the "
            "returned images under <OUT_DIR>/generation_packet/expected_images "
            "and builds a validated review package via "
            "source_to_image_requests.py --resume-packet. The editable deck "
            "lands at <OUT_DIR>/review/review_package/deck.pptx. Do NOT pass "
            "--out-dir with --resume."
        ),
    )
    mode.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Run every scenario under a per-run TMPDIR (md first run + exact "
            "resume instruction + full resume round-trip to an editable "
            "deck, a --style company resume round-trip, "
            "docx/txt routed through ingest, missing / mismatched "
            "image refusals, unsupported-extension refusal, unsafe-out-dir "
            "refusal, argument-shape gates, Chinese-named md/txt/docx sources "
            "auto-staged through the first run, an acceptable name left "
            "un-staged, staging preserving the symlink + content safety "
            "gates, a refused run rolling back its staged copy, and "
            "--emit-strategy-plan writing a starter strategy plan that "
            "survives a resume round-trip). No caller-visible artifacts "
            "retained."
        ),
    )
    parser.add_argument(
        "--out-dir",
        help=(
            "Output directory for the first run (with --source). Must be "
            "outside the repo tree, not URI-shaped, not a symlink / under a "
            "symlink, and missing or empty; its parent must exist. Holds "
            "generation_packet/ (and review/ after --resume)."
        ),
    )
    parser.add_argument(
        "--emit-strategy-plan",
        action="store_true",
        help=(
            "First run only (with --source): after the generation packet is "
            "built and BEFORE any image generation, also project a STARTER "
            "strategy_plan.json into <out-dir>/generation_packet via "
            "init_strategy_plan.py. One strategy record per slide "
            "(core_message / page_type / visual_structure / image_need), "
            "biased toward editable structures -- only the cover suggests a "
            "generated image. Opt-in; default leaves the packet "
            "byte-identical to prior runs. No effect on --resume."
        ),
    )
    parser.add_argument(
        "--style", choices=("default", "company"), default="default",
        help=(
            "Deck design-token style applied on the --resume step. "
            "'default' (the default) projects the template theme -- "
            "byte-identical to prior runs. 'company' applies the "
            "clean-room company-style design tokens (warm palette + clean "
            "sans typography) to the editable deck; only the design_system "
            "differs, every safety / validation gate is unchanged. No "
            "effect on the first --source run (which builds only the "
            "image-generation packet)."
        ),
    )
    return parser


def main(argv: list[str]) -> int:
    args = _build_parser().parse_args(argv)

    if args.self_test:
        return _run_self_tests()

    # The required mutually-exclusive group guarantees exactly one of
    # --source / --resume / --self-test is present. Dispatch --resume on
    # `is not None` (NOT truthiness): a present-but-empty value (--resume "")
    # must still route to the resume path and be refused there, not fall
    # through to --source and traceback on Path(None) when --source was
    # never supplied.
    if args.resume is not None:
        # --resume is source-free and carries the out-dir as its value; a
        # separate --out-dir would be contradictory.
        if args.out_dir:
            print(
                "FAIL: --resume takes the first run's output directory as its "
                "value; do not also pass --out-dir",
                file=sys.stderr,
            )
            return 2
        return _run_resume(args.resume, args.style)

    # --source
    if not args.out_dir:
        print("FAIL: --source requires --out-dir", file=sys.stderr)
        return 2
    return _run_first(args.source, args.out_dir, args.emit_strategy_plan)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
