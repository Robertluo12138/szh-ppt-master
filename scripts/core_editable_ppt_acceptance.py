#!/usr/bin/env python3
"""core_editable_ppt_acceptance.py

Aggregator that runs the existing acceptance smokes covering the core
editable-PPT contract surface end-to-end. Delegates only — no new
runtime behavior of its own. Each delegated smoke owns its own
positive + negative coverage; this aggregator proves they all pass
under the same invocation AND that no artifact lands in the committed
repo tree.

Delegated smokes (each invoked as a subprocess with ``--self-test``):

  - ``scripts/source_image_asset_acceptance_smoke.py`` — the
    read-only source-attached image-asset registry surface
    (``source_image_assets.json`` + ``validate_source_image_assets.py``
    G1..G13 alignment with ``source_manifest.json`` +
    ``image_manifest.json`` + ``slide_plans/*.json``, materialization
    into the workspace, native ``<p:pic>`` embed under
    ``ppt/media/imageN.<ext>``, contract + inventory validators).
  - ``scripts/image_asset_acceptance_smoke.py`` — the mockable
    D-One-stub chain end-to-end through the explicit-input
    acceptance path (``done_image_adapter`` ->
    ``run_d_one_generation --allow-synthetic-bytes`` ->
    ``materialize_image_assets`` -> ``run_explicit_pipeline`` ->
    ``validate_pptx_contract`` + ``validate_visual_quality`` +
    inventory post-conditions). MOCK / STUB ONLY — no real D-One.
  - ``scripts/image_asset_trial_evidence.py`` — re-runs the same
    mock chain under a tempdir and emits a reviewable structured
    JSON evidence file (pptx media parts, internal relationship,
    contract + inventory + editability + visual-quality results)
    so the current mock image-asset capability is reviewable
    without reading many self-test logs.
  - ``scripts/image_asset_negative_probes_smoke.py`` — the
    fail-closed companion to ``image_asset_acceptance_smoke``: every
    documented gate (missing image, wrong magic bytes, image_manifest
    id mismatch, unsafe local_path schemes, symlinked targets, etc.)
    must FIRE on the documented perturbation of the same baseline.
  - ``scripts/image_taxonomy_acceptance_smoke.py`` — proves the
    seven-dimensional clean-room D-One prompt-intent taxonomy
    (``rendering_style`` / ``palette_family`` / ``image_role`` /
    ``layout_pattern`` / ``modifier`` / ``text_policy`` /
    ``subject_domain``) survives the same mock chain end-to-end:
    ``done_image_adapter`` + ``run_d_one_generation`` +
    ``materialize_image_assets`` + ``run_explicit_pipeline``, plus
    in-process N1..N7 negative probes covering missing vocab,
    out-of-vocabulary values, stale plan drift, schema_version lock,
    and the descriptor-vocabulary forbidden-token / forbidden-phrase
    schema patterns. MOCK / STUB ONLY — no real D-One.
  - ``scripts/run_mock_image_pipeline.py`` — end-to-end runner that
    seeds a staging workspace and drives the mockable D-One stub
    chain through ``run_explicit_pipeline`` into a validated
    editable ``.pptx``, with happy-path + 12 documented fail-closed
    probes (missing ``--allow-synthetic-bytes``, taxonomy without
    vocab, invalid text_policy / subject_domain, plan schema_version
    downgrade, request-id mismatch, unsafe ``local_path`` URI scheme,
    symlinked ``--output`` / ``--workspace`` / ``--report-dir``,
    in-script ``sys.dont_write_bytecode=True`` flip closes the
    bytecode hole without ``PYTHONDONTWRITEBYTECODE=1`` in env,
    failure cleanup leaves no residue). MOCK / STUB ONLY — no real
    D-One.
  - ``scripts/mock_image_bundle_acceptance_smoke.py`` — top-level
    acceptance gate that drives the COMMITTED
    ``examples/synthetic_mock_image_trial/`` bundle through
    ``run_mock_image_pipeline.py --bundle`` into a tempfile-owned
    workspace/output/report directory OUTSIDE the repo tree, then
    asserts the documented invariants (rc=0; PPTX exists as regular
    non-symlink non-empty file; ``validate_pptx_contract.py
    --expected-slide-count 2`` passes; ``<report-dir>/inventory.json``
    reports ``ok=true`` / ``findings=[]`` / ``slide_count=2`` / no
    external relationships / AT LEAST TWO ``ppt/media`` PNG/JPG/JPEG
    parts (one per ``placement_role`` declared on the committed
    ``d_one_spec.json``) referencing at least two distinct slide
    indices; the committed bundle's ``d_one_spec.json`` declares BOTH
    ``placement_role`` values (``hero_page`` AND ``local_region``);
    ``[PASS] taxonomy preservation check`` stdout marker fires
    (proves both placement_role values landed on the produced plan
    byte-identical to the spec); ``scripts/__pycache__/`` byte-
    identical before/after even with ``PYTHONDONTWRITEBYTECODE``
    stripped from the subprocess env; no committed repo path
    mutated) plus seven tempfixture fail-closed probes (missing
    bundle, symlinked bundle parent, parent-traversal ``..`` bundle
    path, URI-shaped ``image_manifest_spec.local_path``, traversal
    ``../`` ``image_manifest_spec.local_path``, wrong
    ``placement_role`` flipping the hero_page request to
    ``local_region`` while the prompt still carries overlay-
    reservation cues, and a direct probe on the smoke's static
    ``_bundle_placement_roles`` helper against a bundle copy missing
    the ``local_region`` request). Complements the in-script
    tempfixture coverage of ``run_mock_image_pipeline --self-test``
    by exercising the committed bundle path directly. MOCK / STUB
    ONLY — no real D-One.
  - ``scripts/mock_image_bundle_trial_evidence.py`` — tempdir-only
    evidence emitter sibling to
    ``mock_image_bundle_acceptance_smoke``. Drives the same
    committed bundle through ``run_mock_image_pipeline.py --bundle``
    into a tempfile-owned workspace/output/report directory,
    re-runs ``validate_pptx_contract.py`` /
    ``inspect_pptx_inventory.py`` against the produced PPTX AND
    ``validate_mock_d_one_adapter_plan.py`` (with
    ``--require-both-placement-roles`` AND
    ``--descriptor-vocabulary <bundle/descriptor_vocabulary.json>``)
    against the runner-written
    ``<report-dir>/mock_d_one_adapter_plan.json`` sidecar, and
    emits a compact JSON evidence object (``summary.ok``, fixed
    ``real_d_one_status: UNVERIFIED``, pptx exists/size, inventory
    ok/findings/slide_count/media_parts_count/evidence_basis/no-
    external-relationships, validator rc fields, sidecar
    schema_version/request_count, and one record per generated
    request with id / placement_role / text_policy /
    subject_domain / optional custom_descriptor /
    manifest_local_path). Asserts BOTH ``hero_page`` AND
    ``local_region`` placement_role coverage and that the
    committed vocabulary gate was actually used. Adds five fail-
    closed probes (missing bundle, missing sidecar after a forced
    downstream failure, bad descriptor vocabulary, malformed-
    request summary refusal — synthetic sidecars that drop or
    corrupt a goal-required per-request field, or carry a non-
    dict request entry, or carry an empty requests list, must
    flip ``summary.ok=False`` via
    ``sidecar.all_requests_well_formed=False`` even when every
    other gate would be green; the well-formed baseline still
    passes — and a static helper refusing any evidence JSON that
    claims real D-One / MCP / public network / model API / image
    search / Qoder success). MOCK / STUB ONLY — no real D-One.
  - ``scripts/render_model_roundtrip_smoke.py`` — synthetic
    render_model -> editable .pptx round-trip exercising every
    primitive kind the exporter supports today (text, line, shape,
    image_slot, kpi, table) across the cover / comparison_table /
    two_column / kpi_dashboard layouts, plus the documented
    fail-closed probes (N1..N7b).
  - ``scripts/trace_acceptance_smoke.py`` — the default acceptance
    pipeline emits no ``conversion_trace`` sidecar, AND the opt-in
    ``scripts/export_pptx.py --trace-out`` path produces a sidecar
    that passes ``scripts/validate_conversion_trace.py`` +
    ``scripts/validate_artifacts.py``; the trace-positive PPTX itself
    passes ``scripts/validate_pptx_contract.py`` +
    ``scripts/inspect_pptx_inventory.py``.

The aggregator itself writes no ``.pptx`` / ``render_model`` /
``report`` / SVG / JSON. It runs each delegated smoke from
``REPO_ROOT`` with ``PYTHONDONTWRITEBYTECODE=1`` and aggregates
``stdout`` / ``stderr`` / ``rc``.

The aggregator exits 0 only if EVERY delegated smoke returns rc=0 AND
every committed top-level path under ``REPO_ROOT`` (see
``_COMMITTED_TOP_LEVEL`` — every committed root-level file hashed
directly, every committed top-level directory walked recursively) is
byte-identical before and after the run. Each delegated smoke
already snapshot-diffs ``REPO_ROOT/examples`` + ``REPO_ROOT/scripts``
on its own; the aggregator additionally re-checks the broader
committed surface so a leak under ``references``, ``schemas``,
``templates``, or a root-level committed file (``README.md`` /
``CLAUDE.md`` / ``SKILL.md`` / ``SECURITY.md`` / ``AGENTS.md`` /
``.gitignore``) is caught here too.

Stdlib only. NETWORK-FREE. NO-D-ONE. NO-Qoder. NO-MCP. NO model API.
NO image generation. NO browser. NO screenshot. NO telemetry. NOT a
full prompt/report/Markdown-to-PPTX automation — the delegated smokes
exercise synthetic fixtures only.

The script has only a ``--self-test`` invocation surface. It exits 0
on full pass, 1 on any scenario failure or repo mutation, 2 on a
missing flag.

Usage:
  python3 scripts/core_editable_ppt_acceptance.py --self-test
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

# Core editable-PPT smokes. Each must already exist on disk and accept
# ``--self-test`` as its only required surface. Order is fixed so the
# aggregator's stdout stays diff-stable across runs.
_CORE_SMOKES: tuple[Path, ...] = (
    SCRIPTS_DIR / "source_image_asset_acceptance_smoke.py",
    SCRIPTS_DIR / "image_asset_acceptance_smoke.py",
    SCRIPTS_DIR / "image_asset_trial_evidence.py",
    SCRIPTS_DIR / "image_asset_negative_probes_smoke.py",
    SCRIPTS_DIR / "image_taxonomy_acceptance_smoke.py",
    SCRIPTS_DIR / "run_mock_image_pipeline.py",
    SCRIPTS_DIR / "mock_image_bundle_acceptance_smoke.py",
    SCRIPTS_DIR / "mock_image_bundle_trial_evidence.py",
    SCRIPTS_DIR / "render_model_roundtrip_smoke.py",
    SCRIPTS_DIR / "trace_acceptance_smoke.py",
)

# Every committed top-level path under ``REPO_ROOT`` at the time this
# aggregator was written (mirrors ``git ls-tree -r --name-only HEAD``).
# Top-level files are snapshotted directly; top-level directories are
# walked recursively so a new file landing anywhere under them surfaces
# in the diff. Transient / gitignored top-level entries
# (``.git`` / ``.claude`` / ``dist`` / ``out`` / ``output`` /
# ``projects`` / ``build`` / ``__pycache__`` / etc.) are deliberately
# NOT in this list — they may legitimately churn during a run and are
# outside the "committed repo tree" the aggregator claims to protect.
# If a future commit adds a new top-level path, extend this tuple; the
# aggregator only diffs paths it actively snapshots, so a missing
# entry would silently leak.
_COMMITTED_TOP_LEVEL: tuple[str, ...] = (
    ".gitignore",
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "SECURITY.md",
    "SKILL.md",
    "examples",
    "references",
    "schemas",
    "scripts",
    "templates",
)


@dataclass
class _Outcome:
    smoke: Path
    rc: int
    stdout: str
    stderr: str


def _snapshot_committed_tree() -> dict[str, tuple[str, bytes]]:
    """Snapshot every entry in ``_COMMITTED_TOP_LEVEL`` under
    ``REPO_ROOT``. Each path is recorded with a type tag so that a
    symlink, FIFO, device, socket, or otherwise non-regular file
    appearing under the snapshot region (or a symlink whose target
    has been retargeted) shows up in the before/after diff instead
    of being silently skipped — historically the loop skipped every
    non-regular entry on both snapshots, so a delegated smoke that
    planted (say) a symlink at ``examples/leaked -> /tmp/foo`` would
    leave matching gaps in both dicts and tautologically pass.

    Value encoding:

      - regular file -> ``("file", <bytes>)``
      - symlink      -> ``("symlink", <os.readlink target bytes>)``
      - directory    -> ``("dir", b"")``
      - other        -> ``("other", b"")``   (FIFO / device / socket)

    A path that doesn't exist (or whose top-level entry is missing
    altogether) is simply absent from the dict — its appearance /
    disappearance is itself a diff.

    Top-level directories are walked via ``Path.rglob``, which on
    every supported Python version yields directory symlinks as
    leaves but does NOT descend through them — so an attacker who
    planted ``examples/linked -> /tmp/anything`` surfaces as one
    ``("symlink", target)`` entry rather than as a recursive
    explosion of files outside the repo. The top level itself is
    likewise recorded once and never followed when it is a symlink.
    """
    out: dict[str, tuple[str, bytes]] = {}
    for name in _COMMITTED_TOP_LEVEL:
        p = REPO_ROOT / name
        _record_snapshot_entry(p, name, out)
        # Only descend through a real directory; a top-level entry
        # that is a symlink (even to a directory) is recorded above
        # and not followed.
        if not p.is_symlink() and p.is_dir():
            for child in sorted(p.rglob("*")):
                _record_snapshot_entry(
                    child, str(child.relative_to(REPO_ROOT)), out,
                )
    return out


def _record_snapshot_entry(
    p: Path, key: str, out: dict[str, tuple[str, bytes]],
) -> None:
    """Record a single path's type + content discriminator in the
    snapshot. ``is_symlink`` is checked first because ``is_file`` /
    ``is_dir`` follow symlinks — a symlink to a regular file would
    otherwise be misrecorded as a plain file and its retargeting
    would not surface in the diff."""
    if p.is_symlink():
        try:
            tgt = os.readlink(p).encode("utf-8", "surrogateescape")
        except OSError:
            tgt = b"<unreadable-symlink-target>"
        out[key] = ("symlink", tgt)
        return
    if p.is_file():
        out[key] = ("file", p.read_bytes())
        return
    if p.is_dir():
        out[key] = ("dir", b"")
        return
    if p.exists():
        out[key] = ("other", b"")


def _run_smoke(smoke: Path) -> _Outcome:
    cmd = [sys.executable, str(smoke), "--self-test"]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    return _Outcome(
        smoke=smoke, rc=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


def _run_self_test() -> int:
    print(
        "=== core_editable_ppt_acceptance "
        "(delegated --self-test runs) ==="
    )

    # Preflight: the delegated-smoke list must be non-empty. With zero
    # smokes the loop below would iterate nothing, the
    # tree-before/tree-after snapshot would tautologically match, and
    # the aggregator would print "0 delegated smoke(s) passed" and
    # exit 0 — a false-green that hides accidental edits to
    # ``_CORE_SMOKES`` (typo, merge mistake, refactor leftover).
    # Refuse the run instead.
    if len(_CORE_SMOKES) == 0:
        print(
            "FAIL: _CORE_SMOKES is empty — the aggregator must run at "
            "least one delegated smoke. Add the editable-PPT core "
            "smokes back to the tuple at the top of this file.",
            file=sys.stderr,
        )
        return 1

    # Preflight: every delegated smoke must exist as a regular file
    # (not a symlink). A symlink at any of these paths could redirect
    # execution outside the repo; an outright missing file would
    # surface as a noisy subprocess exit. The preflight makes both
    # cases fail closed with one clear diagnostic.
    for smoke in _CORE_SMOKES:
        if smoke.is_symlink():
            print(
                f"FAIL: delegated smoke is a symlink (refused): {smoke}",
                file=sys.stderr,
            )
            return 1
        if not smoke.is_file():
            print(
                f"FAIL: delegated smoke missing: {smoke}",
                file=sys.stderr,
            )
            return 1

    tree_before = _snapshot_committed_tree()

    rc = 0
    for smoke in _CORE_SMOKES:
        rel = smoke.relative_to(REPO_ROOT)
        print(f"  [..] {rel} --self-test")
        outcome = _run_smoke(smoke)
        if outcome.rc != 0:
            print(
                f"  [FAIL] {rel} rc={outcome.rc}",
                file=sys.stderr,
            )
            if outcome.stdout:
                print(outcome.stdout, file=sys.stderr)
            if outcome.stderr:
                print(outcome.stderr, file=sys.stderr)
            rc = 1
        else:
            print(f"  [OK] {rel}")

    # Belt-and-braces: no delegated smoke is allowed to mutate any
    # path inside the committed repo tree. Each delegated smoke
    # already snapshot-diffs ``REPO_ROOT/examples`` +
    # ``REPO_ROOT/scripts`` on its own; the aggregator additionally
    # checks the broader committed surface (``references``,
    # ``schemas``, ``templates``, and the root-level committed files
    # — see ``_COMMITTED_TOP_LEVEL``) so a leak outside the delegated
    # smokes' narrower snapshot window is still caught here.
    # ``_snapshot_committed_tree`` records the type of every entry
    # (file / symlink / dir / other), so a smoke that plants a
    # symlink or retargets one — or creates a FIFO / socket / device
    # — under any snapshotted path shows up in the diff instead of
    # being silently skipped on both sides.
    tree_after = _snapshot_committed_tree()
    if tree_before != tree_after:
        changed = sorted(
            k for k in set(tree_before) | set(tree_after)
            if tree_before.get(k) != tree_after.get(k)
        )
        print(
            f"FAIL: committed tree under REPO_ROOT was mutated by the "
            f"aggregator run (changed: {changed!r})",
            file=sys.stderr,
        )
        rc = 1

    if rc == 0:
        print()
        print(
            f"OK (core editable PPT acceptance): "
            f"{len(_CORE_SMOKES)} delegated smoke(s) passed; every "
            f"committed top-level path under REPO_ROOT "
            f"({', '.join(_COMMITTED_TOP_LEVEL)}) is byte-identical "
            f"before and after the run."
        )
    return rc


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregator for the existing core editable-PPT acceptance "
            "smokes (source_image_asset_acceptance_smoke + "
            "image_asset_acceptance_smoke + image_asset_trial_evidence "
            "+ image_asset_negative_probes_smoke + "
            "image_taxonomy_acceptance_smoke + run_mock_image_pipeline "
            "+ mock_image_bundle_acceptance_smoke + "
            "mock_image_bundle_trial_evidence + "
            "render_model_roundtrip_smoke + trace_acceptance_smoke). "
            "Runs each delegated smoke as a subprocess from REPO_ROOT; "
            "writes no .pptx / render_model / report / SVG / JSON "
            "artifacts of its own. Stdlib-only. NETWORK-FREE. "
            "NO-D-ONE. NO-Qoder. NO-MCP. NO model API. NO image "
            "generation. NO browser. NO screenshot. NO telemetry."
        ),
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help=(
            "Required: run every delegated core editable-PPT smoke "
            "with --self-test. The script has no other CLI surface "
            "today."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: core_editable_ppt_acceptance.py requires "
            "--self-test (no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
