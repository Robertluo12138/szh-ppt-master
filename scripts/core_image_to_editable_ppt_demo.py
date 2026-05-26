#!/usr/bin/env python3
"""core_image_to_editable_ppt_demo.py

Stdlib-only **one-command demo** for the core image-to-editable-PPT
loop on local / mock / synthetic inputs. Two modes share the same
underlying happy path:

  * ``--self-test`` — drives the demo entirely under a per-run
    ``tempfile.TemporaryDirectory()`` (no caller-visible artifacts
    retained), runs the documented fail-closed probes, and asserts the
    committed tree under REPO_ROOT is byte-identical before and after.
    The self-test exercises the operator-mode pathway from inside the
    outer tempdir, so both modes share one code path.

  * ``--out-dir DIR`` — **operator mode**: drives the same happy path
    into a caller-supplied directory that lives **outside the repo
    tree**, leaving the produced ``.pptx``, the runner-written report
    artifacts (``inventory.json`` / ``mock_d_one_adapter_plan.json``),
    the demo's per-run inventory snapshot, the sanitized handoff
    record, and the concise ``demo_summary.json`` on disk for a
    reviewer to inspect. The operator-mode arg gate refuses URI-shaped
    paths, symlink ``--out-dir`` or any symlink ancestor, paths under
    REPO_ROOT, paths whose parent does not exist, paths that are not a
    directory, and pre-existing non-empty directories (overwrite
    risk); refusals are reported with a per-failure diagnostic and
    rc=2 before any subprocess fires.

Either mode drives the existing mixed-lane mock pipeline once, runs
the existing validators (``validate_pptx_contract``,
``inspect_pptx_inventory``,
``validate_mixed_image_asset_provenance``), and derives the same
concise demo summary describing the product truth.

The demo does NOT introduce a new schema, a new validator, or a new
runtime contract. It reuses the existing helpers verbatim:

  * ``scripts/mixed_image_asset_pipeline_smoke.py`` — bundle
    materializer + runner-args helper (single source of truth for the
    synthetic mixed-lane bundle taxonomy);
  * ``scripts/mixed_image_asset_provenance_handoff_smoke.py`` —
    taxonomy-rich ``d_one_spec`` + ``descriptor_vocabulary`` bodies,
    runtime provenance derivation, sanitizer, validator subprocess
    runner;
  * ``scripts/core_editable_ppt_acceptance.py`` —
    ``_snapshot_committed_tree`` (no-repo-mutation gate, same broad
    surface the aggregate quality gate already protects).

Demo summary (written to ``<run-root>/demo_summary.json`` — the
per-run tempdir in ``--self-test`` mode, the operator's ``--out-dir``
in operator mode):

  * ``slide_count`` — read from the produced PPTX inventory readback.
  * ``pptx_path`` — absolute path inside the run root (tempdir in
    self-test, ``--out-dir`` in operator mode); never under REPO_ROOT.
  * ``report_dir`` — absolute path inside the run root.
  * ``explicit_boundaries`` — a fixed list of negation-pinned sentences
    naming what this demo does NOT do: no real D-One, no MCP, no
    Qoder, no model API, no image search, no public network access,
    no telemetry, no raw prompt-or-report-to-PPT automation. The
    truth-checker enforces the canonical list verbatim so a future
    drift in the wording (or a deletion) is refused.
  * ``embedded_media_count`` — number of ``ppt/media/*.{png,jpg,jpeg}``
    parts the produced PPTX carries; must be >= 2 (one per image lane).
  * ``editable_text_evidence`` / ``not_all_image_evidence`` /
    ``every_slide_has_native_shape_evidence`` — booleans projected
    from ``validate_pptx_contract``'s ``[PASS] minimal_evidence.*``
    stdout markers; together they prove the deck still carries
    native editable text (the export path was NOT a full-slide
    raster fallback).
  * ``source_class_coverage`` — sorted list, expected exactly
    ``[d_one_local, local_asset]`` (no collapse).
  * ``generated_intent_coverage_d_one_local`` — True iff every
    d_one_local row carries a ``generated_intent`` block whose
    closed-enum values lie in the canonical allow-lists.
  * ``local_asset_has_no_generated_intent`` — True iff every
    local_asset row is missing ``generated_intent`` (caller-staged
    bytes are not a generated artifact).
  * ``no_external_relationships`` — True iff no relationship inside
    the produced PPTX carries an external ``TargetMode`` or a URI
    scheme (delegated to ``validate_pptx_contract``'s
    ``relationships.no_external`` + ``relationships.no_file_uri`` +
    ``relationships.allow_list`` gates, restated by the demo from
    the contract validator's PASS markers).
  * ``real_d_one_status`` — fixed sentence ``"UNVERIFIED"``. Real
    D-One is NOT called by this demo.
  * ``validators`` — ``{validate_pptx_contract.rc,
    inspect_pptx_inventory.rc,
    validate_mixed_image_asset_provenance.rc}``.
  * ``notes`` — scope / embed-surface framing copied from the same
    committed-safe wording the mixed handoff smoke uses.

Happy path (one mock pipeline subprocess; one provenance validator
subprocess; one contract validator subprocess; one inventory
subprocess on the produced PPTX):

  H1   the bundle materializer + runner-args helpers reused from
       ``mixed_image_asset_pipeline_smoke`` drive a pipeline
       subprocess that returns rc=0;
  H2   ``validate_pptx_contract --pptx <out> --expected-slide-count
       2`` returns rc=0 and emits ``[PASS]`` for the
       ``minimal_evidence.editable_text`` /
       ``minimal_evidence.not_all_image_slide`` /
       ``minimal_evidence.every_slide_has_native_shape`` /
       ``relationships.no_external`` /
       ``relationships.no_file_uri`` /
       ``relationships.allow_list`` markers;
  H3   ``inspect_pptx_inventory --pptx <out>`` reports ``ok=true``,
       ``findings=[]``, ``slide_count=2``, AT LEAST TWO embeddable
       ``ppt/media/*`` PNG/JPG/JPEG parts, and zero relationship
       entries whose ``target_mode == "External"`` or whose
       ``target`` carries a URI-scheme prefix;
  H4   the runtime provenance derivation yields exactly two rows
       (source_class coverage = {d_one_local, local_asset}) with the
       d_one_local row's ``generated_intent`` equal to the
       spec-supplied taxonomy AND the local_asset row carrying NO
       ``generated_intent``;
  H5   the validator subprocess on the sanitized record returns
       rc=0 (every G1..G18 gate held);
  H6   the assembled demo summary passes the in-script truth-checker
       (every documented field carries the documented value), is
       written to ``<tempdir>/demo_summary.json`` as a regular
       non-symlink file, and echoes verbatim to stdout;
  H7   committed tree under REPO_ROOT is byte-identical before and
       after the run.

Fail-closed probes (direct, no pipeline re-run — every probe takes a
clone of the happy-path baseline, mutates one field, and asserts the
truth-checker / output-gate refuses; the operator-mode-specific
probes (OP*) exercise ``_validate_out_dir_arg`` directly):

  P1   ``_validate_summary_output_path`` refuses every path that
       lexically anchors under REPO_ROOT (the committed repo tree is
       off-limits for demo outputs). The probe NEVER calls
       ``unlink()`` on a repo-root path — if a future writer
       regression lets bytes land there, the committed-tree
       snapshot at the end of self-test surfaces the leak AND this
       probe reports a FAIL diagnostic. Silently unlinking a leak
       would mask a real regression and could destroy a
       pre-existing user file at the same path.
  P1b  ``_safe_unlink_under_tempdir`` is exercised directly against
       an existing REPO_ROOT path (``README.md``): the helper MUST
       no-op (no unlink, no byte mutation) even when a tempdir
       root is supplied. Locks the safety contract at the helper
       boundary, independent of the output-path gate.
  P2   on a truth-check failure ``_write_demo_summary_under_tempdir``
       leaves no stale ``demo_summary.json`` behind at the requested
       path — a probe that injects a missing required field MUST
       refuse to write (the file is scrubbed on rollback via
       ``_safe_unlink_under_tempdir`` so the scrub itself can never
       reach a repo path);
  P3   a summary that claims ``embedded_media_count == 0`` is refused
       by the truth-checker (the demo claims a working embed surface;
       zero media collapses that claim);
  P4   a summary that drops the d_one_local lane from
       ``source_class_coverage`` is refused (one image lane missing);
  P5   a summary that drops the local_asset lane from
       ``source_class_coverage`` is refused (symmetric to P4);
  P6   a summary that injects a positive real-D-One / MCP / public
       network / model API / image search / Qoder success claim
       (``Real D-One verified online`` / ``called MCP successfully``
       / ``model API returned`` / etc.) into the ``notes.scope`` /
       ``real_d_one_status`` text is refused — the demo's
       committed-safe UNVERIFIED sentence is the only allowed shape;
  P7   committed tree under REPO_ROOT is byte-identical before and
       after the run (defense-in-depth alongside H7 — the snapshot
       fires after every probe ran, so a probe that secretly leaked
       under REPO_ROOT shows up here).
  OP1  ``_validate_out_dir_arg`` refuses every URI-shaped argument
       (``file://``, ``http://``, ``data:``, ``ftp://``, ...) before
       any filesystem touch — the operator mode accepts local paths
       only;
  OP2  ``_validate_out_dir_arg`` refuses an ``--out-dir`` that is
       itself a symlink (broken or resolvable) — silently following
       a symlink would let an attacker who controls the symlink
       target redirect demo outputs into an unexpected location;
  OP3  ``_validate_out_dir_arg`` refuses an ``--out-dir`` whose parent
       (or any ancestor up to filesystem root) is a symlink — same
       attack surface as OP2 one level up;
  OP4  ``_validate_out_dir_arg`` refuses any ``--out-dir`` whose
       resolved path lexically anchors under REPO_ROOT (the committed
       tree is off-limits for demo outputs); the gate refuses BEFORE
       any mkdir, so the refused path is NEVER created;
  OP5  ``_validate_out_dir_arg`` refuses a pre-existing non-empty
       ``--out-dir`` (overwrite risk; the operator must opt in to a
       fresh path) AND leaves the pre-existing bytes byte-identical.

Clean-room: this demo shares no prompts, assets, examples, tables,
CSV rows, wording, code, or deck structure with any upstream
project. Aligned only with the upstream image-generation idea that a
single command should prove the local image-to-editable-PPT path
demo-ready end-to-end; the implementation, summary field set, probe
matrix, and refusal walker are this repo's own.

MOCK / STUB ONLY — NOT real D-One integration. Nothing in this
script calls D-One, MCP, Qoder, a public network, telemetry, any
model API, an image search, a browser, a screenshot service, or any
external service. The asset bytes are the same minimal magic-byte-
valid local payloads the existing pipeline smokes already use. The
demo summary is local audit evidence about that synthetic mock
chain, not a claim that any external service ran or succeeded.

Usage:
  # Operator mode — inspectable artifacts under DIR (DIR must be
  # outside the repo, non-URI, non-symlink, with no symlink ancestors,
  # and either nonexistent or an empty pre-existing directory):
  python3 scripts/core_image_to_editable_ppt_demo.py --out-dir DIR

  # Self-test — happy path + probes under a per-run tempdir:
  python3 scripts/core_image_to_editable_ppt_demo.py --self-test

Stdlib only. NETWORK-FREE. NO real D-One. NO MCP. NO Qoder. NO model
API. NO image search. NO telemetry. NOT a full prompt /
report / Markdown-to-PPTX automation — the demo composes the
existing mock chain through the existing pipeline smoke's
materializer and proves a reviewer can run ONE command to see the
image-to-editable-PPT loop work end-to-end on local inputs.
"""
from __future__ import annotations

import sys

# Refuse to write `.pyc` files for any module imported by this script.
# Mirrors the gate every sibling smoke applies; the bytecode flag must
# be flipped BEFORE any first-party import so the interpreter sees it
# at bytecode-write time.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"

sys.path.insert(0, str(SCRIPTS_DIR))

# Reuse the synthetic bundle / runtime-derivation / sanitizer /
# validator-driver / committed-tree-snapshot helpers from the existing
# smokes so the demo does not re-implement a single byte of the runtime
# contract. A future change to the bundle shape is exercised by THIS
# demo too because we drive the same code path.
from mixed_image_asset_pipeline_smoke import (  # noqa: E402
    _materialize_bundle,
    _runner_args,
)
from mixed_image_asset_provenance_handoff_smoke import (  # noqa: E402
    _D_ONE_CUSTOM_DESCRIPTOR,
    _D_ONE_PLACEMENT_ROLE,
    _D_ONE_SUBJECT_DOMAIN,
    _D_ONE_TEXT_POLICY,
    _derive_runtime_provenance,
    _descriptor_vocab_body,
    _run_validator as _run_provenance_validator,
    _sanitize,
    _taxonomy_d_one_spec_body,
)
from core_editable_ppt_acceptance import (  # noqa: E402
    _snapshot_committed_tree,
)

VALIDATE_PPTX_CONTRACT = SCRIPTS_DIR / "validate_pptx_contract.py"
INSPECT_PPTX_INVENTORY = SCRIPTS_DIR / "inspect_pptx_inventory.py"

# The committed-safe UNVERIFIED sentence the demo summary pins. The
# validator the demo invokes already runs a positive-claim refusal
# walker over its own free-form fields; the demo restates the same
# sentence locally so the summary truth-checker has a fixed string to
# compare against.
_REAL_D_ONE_STATUS = "UNVERIFIED"

_DEMO_SCOPE_NOTE = (
    "Mixed-lane mock-image core-loop demo. Drives a synthetic mixed-"
    "lane bundle (d_one_local + local_asset, two cover slides) "
    "through the local pipeline into a tempdir and produces a concise "
    "demo summary. NOT real D-One, NOT MCP, NOT Qoder, NOT a public-"
    "network run, NOT telemetry, NOT a prompt or report to PPTX "
    "automation."
)
_DEMO_EMBED_SURFACE_NOTE = (
    "PNG, JPG, and JPEG inside the ppt/media slot of the produced "
    "deck. The subset scripts/export_pptx.py supports today; anything "
    "outside that subset is fail-closed by the exporter."
)

# Negation-pinned operator-facing boundary statements the demo summary
# carries verbatim. Each line is shaped so the positive-claim refusal
# walker sees a negation token (``no ``, ``not ``, ``never ``, …) in
# the 15-character window before every flagged noun (``real d-one`` /
# ``mcp`` / ``qoder`` / ``model api`` / ``image search`` /
# ``public network``). Locked tuple — the truth-checker enforces
# byte-equality so a future drift in the wording surfaces as a
# refusal rather than as a quiet broadening of the demo's promise.
_EXPLICIT_BOUNDARIES: tuple[str, ...] = (
    "No real D-One call; image generation status is UNVERIFIED.",
    "No MCP call.",
    "No Qoder runtime invocation.",
    "No model API contact.",
    "No image search.",
    "No public network access.",
    "No telemetry emission.",
    "Raw prompt or report-to-PPT automation is NOT implemented.",
)

# Word-boundary refusal walker. Any positive real-D-One / MCP / public
# network / model API / image search / Qoder success claim in a
# summary text field flips the truth-checker to FAIL. Negation tokens
# within a 15-character window before the verb exempt the claim
# (mirrors the validator's own walker so the canonical UNVERIFIED
# sentence — which negates every verb — still passes).
_REAL_D_ONE_CLAIM_VERBS: tuple[str, ...] = (
    "verified", "succeeded", "successful", "ran successfully",
    "ran live", "called successfully", "returned successfully",
    "online", "live",
)
_REAL_D_ONE_CLAIM_NOUNS: tuple[str, ...] = (
    "real d-one", "real d_one", "d-one online", "d_one online",
    "mcp", "model api", "image search", "qoder", "public network",
)
_NEGATION_WINDOW = 15
_NEGATION_TOKENS: tuple[str, ...] = (
    "no ", "not ", "never ", "without ", "is not ", "are not ",
    "was not ", "were not ", "do not ", "does not ", "did not ",
    "unverified",
)

_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")
_ALLOWED_SYSTEM_SYMLINK_ALIASES = {
    "/tmp": "/private/tmp",
    "/var": "/private/var",
    "/etc": "/private/etc",
}


def _allowed_system_symlink_alias(path: Path) -> bool:
    expected = _ALLOWED_SYSTEM_SYMLINK_ALIASES.get(str(path))
    if expected is None:
        return False
    try:
        return str(path.resolve(strict=False)) == expected
    except OSError:
        return False


def _forbidden_symlink_ancestor(path: Path) -> tuple[Path, str] | None:
    """Return the first non-system symlink ancestor in the typed path."""
    for ancestor in path.parents:
        if not ancestor.is_symlink():
            continue
        if _allowed_system_symlink_alias(ancestor):
            continue
        try:
            target = os.readlink(ancestor)
        except OSError:
            target = "<unreadable>"
        return ancestor, target
    return None


# ---------------------------------------------------------------------------
# Subprocess runners.
# ---------------------------------------------------------------------------


@dataclass
class _ToolOutcome:
    name: str
    rc: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.rc == 0

    @property
    def combined(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


def _run(name: str, cmd: list[str]) -> _ToolOutcome:
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    return _ToolOutcome(
        name=name, rc=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


def _run_pipeline(
    *, bundle_dir: Path, workspace: Path, output: Path, report_dir: Path,
) -> _ToolOutcome:
    cmd = _runner_args(
        bundle_dir=bundle_dir, workspace=workspace,
        output=output, report_dir=report_dir,
    )
    return _run("run_mock_image_pipeline --bundle", cmd)


def _run_contract_validator(
    *, pptx: Path, expected_slide_count: int,
) -> _ToolOutcome:
    return _run(
        "validate_pptx_contract",
        [
            sys.executable, str(VALIDATE_PPTX_CONTRACT),
            "--pptx", str(pptx),
            "--expected-slide-count", str(expected_slide_count),
        ],
    )


def _run_inventory(
    *, pptx: Path, out: Path | None = None,
) -> _ToolOutcome:
    cmd = [
        sys.executable, str(INSPECT_PPTX_INVENTORY),
        "--pptx", str(pptx),
    ]
    if out is not None:
        cmd += ["--out", str(out)]
    return _run("inspect_pptx_inventory", cmd)


# ---------------------------------------------------------------------------
# Demo summary assembly + truth-check.
# ---------------------------------------------------------------------------


def _project_minimal_evidence(stdout: str) -> dict[str, bool]:
    """Project the contract validator's minimal_evidence + relationship
    PASS/FAIL markers onto the demo summary's editable / native-shape /
    relationship booleans. The contract validator prints one
    ``[PASS] <gate>: <pptx>`` / ``[FAIL] <gate>: <pptx>`` line per
    gate; we look for the literal ``[PASS] minimal_evidence.<name>``
    prefix anywhere on a stdout line. A gate whose marker is absent is
    treated as False (the contract validator emits a marker for every
    gate it ran, so absence already signals regression)."""
    out: dict[str, bool] = {}
    for gate in (
        "minimal_evidence.editable_text",
        "minimal_evidence.not_all_image_slide",
        "minimal_evidence.every_slide_has_native_shape",
        "minimal_evidence.no_blank_slide",
        "relationships.no_external",
        "relationships.no_file_uri",
        "relationships.allow_list",
    ):
        marker = f"[PASS] {gate}"
        out[gate] = marker in stdout
    return out


def _count_external_relationships_from_inventory(inv: dict) -> int:
    """Count inventory relationships entries whose ``target_mode`` is
    ``External`` or whose ``target`` carries a URI-scheme prefix."""
    n = 0
    rels = inv.get("relationships") or []
    if not isinstance(rels, list):
        return 0
    for entry in rels:
        if not isinstance(entry, dict):
            continue
        tm = entry.get("target_mode")
        tg = entry.get("target")
        if isinstance(tm, str) and tm.lower() == "external":
            n += 1
            continue
        if isinstance(tg, str) and _URI_SCHEME_PREFIX.match(tg):
            n += 1
            continue
        if isinstance(tg, str) and tg.lower().startswith("file://"):
            n += 1
    return n


def _embedded_media_count(inv: dict) -> int:
    """Count embeddable ``ppt/media/*.{png,jpg,jpeg}`` parts in the
    inventory. Mirrors the embed surface ``export_pptx`` supports."""
    embeds: set[str] = set()
    for entry in inv.get("media_parts") or []:
        if not isinstance(entry, dict):
            continue
        part = entry.get("part")
        ext = entry.get("extension")
        if not isinstance(part, str) or not isinstance(ext, str):
            continue
        if ext.lower() not in {"png", "jpg", "jpeg"}:
            continue
        if not part.startswith("ppt/media/"):
            continue
        embeds.add(part)
    return len(embeds)


def _build_summary(
    *,
    pptx: Path,
    report_dir: Path,
    inventory: dict,
    contract: _ToolOutcome,
    inventory_outcome: _ToolOutcome,
    provenance_outcome: _ToolOutcome,
    runtime_provenance: dict,
) -> dict:
    """Compose the demo summary from the validator outputs + the
    runtime provenance derivation. No new contract — every field is a
    projection from an existing validator's truth."""
    rows = runtime_provenance.get("rows") or []
    coverage = sorted({
        r.get("source_class") for r in rows
        if isinstance(r, dict) and isinstance(r.get("source_class"), str)
    })
    d_one_rows = [
        r for r in rows
        if isinstance(r, dict) and r.get("source_class") == "d_one_local"
    ]
    local_rows = [
        r for r in rows
        if isinstance(r, dict) and r.get("source_class") == "local_asset"
    ]
    gi_d_one = all(
        isinstance(r.get("generated_intent"), dict)
        and {"placement_role", "text_policy", "subject_domain"}
        <= set(r["generated_intent"].keys())
        for r in d_one_rows
    ) if d_one_rows else False
    no_gi_local = all(
        "generated_intent" not in r for r in local_rows
    ) if local_rows else False
    contract_pass = _project_minimal_evidence(contract.stdout or "")

    return {
        "demo_id": "core_image_to_editable_ppt_demo",
        "schema_version": "1",
        "real_d_one_status": _REAL_D_ONE_STATUS,
        "slide_count": inventory.get("slide_count"),
        "pptx_path": str(pptx),
        "report_dir": str(report_dir),
        "embedded_media_count": _embedded_media_count(inventory),
        "minimal_evidence": {
            "editable_text": contract_pass.get(
                "minimal_evidence.editable_text", False,
            ),
            "not_all_image_slide": contract_pass.get(
                "minimal_evidence.not_all_image_slide", False,
            ),
            "every_slide_has_native_shape": contract_pass.get(
                "minimal_evidence.every_slide_has_native_shape", False,
            ),
            "no_blank_slide": contract_pass.get(
                "minimal_evidence.no_blank_slide", False,
            ),
        },
        "source_class_coverage": coverage,
        "generated_intent_coverage_d_one_local": gi_d_one,
        "local_asset_has_no_generated_intent": no_gi_local,
        "no_external_relationships": (
            contract_pass.get("relationships.no_external", False)
            and contract_pass.get("relationships.no_file_uri", False)
            and contract_pass.get("relationships.allow_list", False)
            and _count_external_relationships_from_inventory(inventory)
            == 0
        ),
        "inventory": {
            "ok": inventory.get("ok") is True,
            "findings_empty": (inventory.get("findings") or []) == [],
            "evidence_basis": inventory.get("evidence_basis"),
        },
        "validators": {
            "validate_pptx_contract": {"rc": contract.rc},
            "inspect_pptx_inventory": {"rc": inventory_outcome.rc},
            "validate_mixed_image_asset_provenance": {
                "rc": provenance_outcome.rc,
            },
        },
        "expected_taxonomy": {
            "placement_role": _D_ONE_PLACEMENT_ROLE,
            "text_policy": _D_ONE_TEXT_POLICY,
            "subject_domain": _D_ONE_SUBJECT_DOMAIN,
            "custom_descriptor": _D_ONE_CUSTOM_DESCRIPTOR,
        },
        "notes": {
            "scope": _DEMO_SCOPE_NOTE,
            "embed_surface": _DEMO_EMBED_SURFACE_NOTE,
        },
        "explicit_boundaries": list(_EXPLICIT_BOUNDARIES),
    }


def _scan_for_positive_real_d_one_claim(
    summary: dict,
) -> list[str]:
    """Walk every string-valued field in the summary and refuse any
    positive real-D-One / MCP / public network / model API / image
    search / Qoder success claim. Returns a list of offending
    field-paths; empty list means clean. Negation tokens within a
    15-character window before the verb exempt the claim (so the
    canonical UNVERIFIED sentence still passes)."""
    offenders: list[str] = []

    def _scan(value: object, label: str) -> None:
        if isinstance(value, str):
            lowered = value.lower()
            for noun in _REAL_D_ONE_CLAIM_NOUNS:
                idx = 0
                while True:
                    found = lowered.find(noun, idx)
                    if found == -1:
                        break
                    window_start = max(0, found - _NEGATION_WINDOW)
                    window = lowered[window_start:found]
                    if any(
                        n in window for n in _NEGATION_TOKENS
                    ):
                        idx = found + len(noun)
                        continue
                    offenders.append(
                        f"{label}: positive real-D-One/MCP/network/"
                        f"model/image-search/Qoder noun {noun!r} at "
                        f"offset {found} without a negation token "
                        f"within {_NEGATION_WINDOW} chars"
                    )
                    idx = found + len(noun)
            for verb in _REAL_D_ONE_CLAIM_VERBS:
                idx = 0
                while True:
                    found = lowered.find(verb, idx)
                    if found == -1:
                        break
                    window_start = max(0, found - _NEGATION_WINDOW)
                    window = lowered[window_start:found]
                    if any(
                        n in window for n in _NEGATION_TOKENS
                    ):
                        idx = found + len(verb)
                        continue
                    if "unverified" in lowered:
                        idx = found + len(verb)
                        continue
                    offenders.append(
                        f"{label}: positive success verb {verb!r} at "
                        f"offset {found} without a negation token "
                        f"within {_NEGATION_WINDOW} chars"
                    )
                    idx = found + len(verb)
        elif isinstance(value, dict):
            for k, v in value.items():
                _scan(v, f"{label}.{k}" if label else str(k))
        elif isinstance(value, list):
            for i, v in enumerate(value):
                _scan(v, f"{label}[{i}]")

    _scan(summary, "summary")
    return offenders


def _check_summary_truth(summary: dict) -> list[str]:
    """In-script truth-checker for the demo summary. Returns a list
    of failure diagnostics; empty list means the summary describes a
    healthy demo run."""
    failures: list[str] = []

    if summary.get("demo_id") != "core_image_to_editable_ppt_demo":
        failures.append(
            f"summary.demo_id={summary.get('demo_id')!r}; expected "
            f"'core_image_to_editable_ppt_demo'"
        )
    if summary.get("schema_version") != "1":
        failures.append(
            f"summary.schema_version={summary.get('schema_version')!r}; "
            f"expected '1'"
        )
    if summary.get("real_d_one_status") != _REAL_D_ONE_STATUS:
        failures.append(
            f"summary.real_d_one_status="
            f"{summary.get('real_d_one_status')!r}; expected "
            f"{_REAL_D_ONE_STATUS!r}"
        )

    slide_count = summary.get("slide_count")
    if not isinstance(slide_count, int) or slide_count != 2:
        failures.append(
            f"summary.slide_count={slide_count!r}; expected 2"
        )

    pptx_path = summary.get("pptx_path")
    if not isinstance(pptx_path, str) or not pptx_path:
        failures.append(
            f"summary.pptx_path={pptx_path!r}; expected a non-empty "
            f"string"
        )

    report_dir = summary.get("report_dir")
    if not isinstance(report_dir, str) or not report_dir:
        failures.append(
            f"summary.report_dir={report_dir!r}; expected a non-empty "
            f"string"
        )

    embedded = summary.get("embedded_media_count")
    if not isinstance(embedded, int) or embedded < 2:
        failures.append(
            f"summary.embedded_media_count={embedded!r}; expected "
            f"int >= 2 (one media part per image lane)"
        )

    mev = summary.get("minimal_evidence") or {}
    for gate in (
        "editable_text", "not_all_image_slide",
        "every_slide_has_native_shape", "no_blank_slide",
    ):
        if mev.get(gate) is not True:
            failures.append(
                f"summary.minimal_evidence.{gate}={mev.get(gate)!r}; "
                f"expected True (validate_pptx_contract must emit "
                f"'[PASS] minimal_evidence.{gate}')"
            )

    coverage = summary.get("source_class_coverage")
    if coverage != ["d_one_local", "local_asset"]:
        failures.append(
            f"summary.source_class_coverage={coverage!r}; expected "
            f"['d_one_local', 'local_asset'] (both image lanes "
            f"must be present)"
        )

    if summary.get("generated_intent_coverage_d_one_local") is not True:
        failures.append(
            f"summary.generated_intent_coverage_d_one_local="
            f"{summary.get('generated_intent_coverage_d_one_local')!r}; "
            f"expected True (every d_one_local row must carry a "
            f"generated_intent block)"
        )
    if summary.get("local_asset_has_no_generated_intent") is not True:
        failures.append(
            f"summary.local_asset_has_no_generated_intent="
            f"{summary.get('local_asset_has_no_generated_intent')!r}; "
            f"expected True (caller-staged bytes are not a generated "
            f"artifact)"
        )
    if summary.get("no_external_relationships") is not True:
        failures.append(
            f"summary.no_external_relationships="
            f"{summary.get('no_external_relationships')!r}; expected "
            f"True (no external / file:// / URI-scheme relationship "
            f"allowed in the produced PPTX)"
        )

    inv = summary.get("inventory") or {}
    if inv.get("ok") is not True:
        failures.append(
            f"summary.inventory.ok={inv.get('ok')!r}; expected True"
        )
    if inv.get("findings_empty") is not True:
        failures.append(
            f"summary.inventory.findings_empty="
            f"{inv.get('findings_empty')!r}; expected True"
        )

    val = summary.get("validators") or {}
    for k in (
        "validate_pptx_contract",
        "inspect_pptx_inventory",
        "validate_mixed_image_asset_provenance",
    ):
        entry = val.get(k) or {}
        rc = entry.get("rc")
        if rc != 0:
            failures.append(
                f"summary.validators.{k}.rc={rc!r}; expected 0"
            )

    boundaries = summary.get("explicit_boundaries")
    if boundaries != list(_EXPLICIT_BOUNDARIES):
        failures.append(
            f"summary.explicit_boundaries={boundaries!r}; expected "
            f"the locked tuple {list(_EXPLICIT_BOUNDARIES)!r} verbatim "
            f"(any drift in the operator-facing boundary statements "
            f"is refused so a quiet broadening of the demo's promise "
            f"is impossible)"
        )

    failures.extend(_scan_for_positive_real_d_one_claim(summary))
    return failures


# ---------------------------------------------------------------------------
# Summary output writer + path gate.
# ---------------------------------------------------------------------------


def _validate_summary_output_path(
    *, summary_path: Path, tempdir_root: Path,
) -> list[str]:
    """Refuse any summary output path that would land under
    REPO_ROOT, that is a symlink (broken or resolvable), or that does
    not lexically anchor under the per-run tempdir root.

    The committed repo tree is off-limits for demo outputs — a leak
    would surface in the no-repo-mutation snapshot but the cheaper
    refusal here makes the contract obvious at the API layer."""
    failures: list[str] = []
    if summary_path.is_symlink():
        failures.append(
            f"summary path is a symlink: {summary_path} -> "
            f"{os.readlink(summary_path)}"
        )
        return failures
    try:
        resolved = summary_path.resolve(strict=False)
    except OSError as exc:
        failures.append(
            f"summary path could not be resolved: {type(exc).__name__}: "
            f"{exc}"
        )
        return failures
    repo_root = REPO_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(repo_root)
        failures.append(
            f"summary path {resolved} lexically anchors under "
            f"REPO_ROOT={repo_root} — demo outputs must land under "
            f"the per-run tempdir, never under the committed repo tree"
        )
    except ValueError:
        pass
    tempdir_resolved = tempdir_root.resolve(strict=False)
    try:
        resolved.relative_to(tempdir_resolved)
    except ValueError:
        failures.append(
            f"summary path {resolved} does not lexically anchor under "
            f"the per-run tempdir root {tempdir_resolved}"
        )
    return failures


def _path_is_under_tempdir(
    *, path: Path, tempdir_root: Path,
) -> bool:
    """True iff ``path`` lexically resolves under ``tempdir_root``
    AND not under REPO_ROOT. Belt-and-braces gate used everywhere
    ``_write_demo_summary_under_tempdir`` would otherwise call
    ``unlink()`` — a repo-root path must never be deletable by this
    script even if the output-path gate has a future regression."""
    try:
        resolved = path.resolve(strict=False)
        tempdir_resolved = tempdir_root.resolve(strict=False)
        repo_resolved = REPO_ROOT.resolve(strict=False)
    except OSError:
        return False
    try:
        resolved.relative_to(repo_resolved)
        # Falls under REPO_ROOT — refuse outright.
        return False
    except ValueError:
        pass
    try:
        resolved.relative_to(tempdir_resolved)
        return True
    except ValueError:
        return False


def _safe_unlink_under_tempdir(
    *, path: Path, tempdir_root: Path,
) -> None:
    """Unlink ``path`` ONLY if it lexically resolves under
    ``tempdir_root`` AND not under REPO_ROOT AND is a regular file
    (not a symlink). Silently no-ops otherwise — the caller's
    contract is "best-effort scrub of a tempdir-owned stale file",
    never "delete an arbitrary path the gate may have let through"."""
    if not _path_is_under_tempdir(path=path, tempdir_root=tempdir_root):
        return
    if path.is_symlink():
        return
    if not path.is_file():
        return
    try:
        path.unlink()
    except OSError:
        pass


def _write_demo_summary_under_tempdir(
    *, summary: dict, summary_path: Path, tempdir_root: Path,
) -> list[str]:
    """Write the summary JSON to ``summary_path`` only when (1) the
    path passes the output gate AND (2) the in-script truth-checker
    accepts the summary AND (3) the positive-real-D-One claim walker
    finds nothing. On any failure the path is unlinked via the
    tempdir-only ``_safe_unlink_under_tempdir`` helper — so a future
    regression that lets a repo-root path past the output gate STILL
    cannot delete a repo file from this writer."""
    failures = _validate_summary_output_path(
        summary_path=summary_path, tempdir_root=tempdir_root,
    )
    if failures:
        return failures

    truth_failures = _check_summary_truth(summary)
    if truth_failures:
        # Defense-in-depth: even though we have not written yet, scrub
        # any stale file the caller may have left at the path so a
        # later assertion that "no stale summary remained after a
        # failed run" is satisfied. The unlink is gated to tempdir-
        # anchored paths so a repo-root path past the gate is still
        # safe.
        _safe_unlink_under_tempdir(
            path=summary_path, tempdir_root=tempdir_root,
        )
        return truth_failures

    rendered = json.dumps(summary, indent=2, sort_keys=True) + "\n"
    try:
        summary_path.write_text(rendered, encoding="utf-8")
    except OSError as exc:
        failures.append(
            f"write_text failed: {type(exc).__name__}: {exc}"
        )
        _safe_unlink_under_tempdir(
            path=summary_path, tempdir_root=tempdir_root,
        )
        return failures
    return []


# ---------------------------------------------------------------------------
# Operator-mode --out-dir argument gate.
# ---------------------------------------------------------------------------


def _validate_out_dir_arg(out_dir_str: str) -> tuple[Path | None, list[str]]:
    """Validate an operator-supplied ``--out-dir`` argument string.

    Returns ``(resolved_path_or_None, failures)``. The caller must
    treat the argument as refused whenever ``failures`` is non-empty
    OR ``resolved_path_or_None`` is ``None``, and MUST NOT mkdir /
    write to the path in that case.

    Refuses, in order, BEFORE any filesystem mutation:
      * URI-shaped argument (``file://`` / ``http://`` / ``data:`` /
        any RFC-3986 scheme prefix). The operator mode accepts local
        paths only.
      * ``out-dir`` is itself a symlink (broken or resolvable).
        Silently following a symlink would let an attacker who
        controls the link target redirect demo outputs into an
        unexpected location.
      * any ancestor of ``out-dir`` up to the filesystem root is a
        symlink. Same attack surface one level up — the gate would
        not see a symlink-on-write if the redirect is higher up.
      * resolved ``out-dir`` lexically anchors under REPO_ROOT. The
        committed tree is off-limits for demo outputs; the snapshot
        check would catch a leak but the cheaper refusal here makes
        the contract obvious at the API layer.
      * ``out-dir`` parent does not exist. Refusing to ``mkdir -p``
        avoids masking a typo in the operator's argument.
      * ``out-dir`` exists and is not a directory (regular file,
        device, FIFO, …). Refused outright.
      * ``out-dir`` exists, is a directory, and is non-empty.
        Overwrite risk — the operator must opt in to a fresh path.
    """
    failures: list[str] = []

    if _URI_SCHEME_PREFIX.match(out_dir_str):
        return None, [
            f"--out-dir argument {out_dir_str!r} looks URI-shaped; "
            f"operator mode only accepts local file paths."
        ]

    out_dir = Path(out_dir_str)

    if out_dir.is_symlink():
        try:
            tgt = os.readlink(out_dir)
        except OSError:
            tgt = "<unreadable>"
        return None, [
            f"--out-dir {out_dir} is a symlink (-> {tgt}); refused so "
            f"a symlink target cannot redirect demo outputs."
        ]

    forbidden_ancestor = _forbidden_symlink_ancestor(out_dir)
    if forbidden_ancestor is not None:
        ancestor, tgt = forbidden_ancestor
        return None, [
            f"--out-dir {out_dir} has a symlink ancestor "
            f"{ancestor} (-> {tgt}); refused so a symlink in the "
            f"operator's typed path cannot redirect demo outputs."
        ]

    try:
        resolved = out_dir.resolve(strict=False)
    except OSError as exc:
        return None, [
            f"--out-dir {out_dir} could not be resolved: "
            f"{type(exc).__name__}: {exc}"
        ]

    repo_root = REPO_ROOT.resolve(strict=False)
    try:
        resolved.relative_to(repo_root)
        return None, [
            f"--out-dir {resolved} lexically anchors under "
            f"REPO_ROOT={repo_root}; refused — demo outputs must "
            f"land outside the committed repo tree."
        ]
    except ValueError:
        pass

    if not out_dir.parent.exists():
        return None, [
            f"--out-dir {out_dir} parent {out_dir.parent} does not "
            f"exist; create the parent explicitly before re-running "
            f"so a typo in the path cannot be masked by an implicit "
            f"mkdir -p."
        ]

    if out_dir.exists():
        if not out_dir.is_dir():
            return None, [
                f"--out-dir {out_dir} exists and is not a directory "
                f"(refusing to write under a regular file / device / "
                f"FIFO / etc.)."
            ]
        try:
            existing = list(out_dir.iterdir())
        except OSError as exc:
            return None, [
                f"--out-dir {out_dir} cannot be listed: "
                f"{type(exc).__name__}: {exc}"
            ]
        if existing:
            return None, [
                f"--out-dir {out_dir} exists and is non-empty "
                f"({len(existing)} entr"
                f"{'y' if len(existing) == 1 else 'ies'}); refused to "
                f"avoid overwriting pre-existing artifacts. Pass a "
                f"fresh path."
            ]

    return out_dir, failures


def _run_operator_mode(out_dir: Path) -> int:
    """Run the happy path into the operator-supplied ``--out-dir``.

    The caller MUST have already passed ``out_dir`` through
    ``_validate_out_dir_arg``; this function trusts the gate.

    Creates the directory if it does not exist (strict, non-recursive
    — the validator already confirmed the parent exists), then drives
    the same ``_run_happy_path`` the self-test uses. Leaves all
    artifacts on disk for a reviewer to inspect; does NOT scrub them
    on failure (the operator asked for a directory of artifacts, so
    partial outputs on failure are inspectable too).
    """
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
    print(
        f"=== core_image_to_editable_ppt_demo "
        f"(--out-dir {out_dir}) ==="
    )
    happy_rc, summary, summary_path = _run_happy_path(out_dir)
    if happy_rc != 0 or summary is None or summary_path is None:
        print(
            f"FAIL (operator mode): happy path did not complete; "
            f"inspect {out_dir} for partial artifacts.",
            file=sys.stderr,
        )
        return 1
    print()
    print(
        f"OK (operator mode): inspectable artifacts under {out_dir}. "
        f"Real D-One UNVERIFIED. No public network, no MCP, no "
        f"Qoder, no model API, no image search, no telemetry. Raw "
        f"prompt or report-to-PPT automation NOT implemented."
    )
    return 0


# ---------------------------------------------------------------------------
# Happy path.
# ---------------------------------------------------------------------------


def _run_happy_path(td: Path) -> tuple[int, dict | None, Path | None]:
    print(
        "--- happy path: synthetic mixed-lane bundle -> mock pipeline "
        "-> validate_pptx_contract -> inspect_pptx_inventory -> "
        "validate_mixed_image_asset_provenance -> demo summary ---"
    )

    bundle_info = _materialize_bundle(
        td, d_one_spec_overrides=_taxonomy_d_one_spec_body(),
    )
    bundle_dir = bundle_info["bundle"]
    # Same paired descriptor_vocabulary.json the handoff smoke uses.
    vocab_path = bundle_dir / "descriptor_vocabulary.json"
    vocab_path.write_text(
        json.dumps(_descriptor_vocab_body(), indent=2, sort_keys=True)
        + "\n",
    )

    workspace = td / "demo_ws"
    output = td / "demo.pptx"
    report_dir = td / "demo_report"

    print(f"  bundle:    {bundle_dir}")
    print(f"  workspace: {workspace}")
    print(f"  output:    {output}")
    print(f"  report:    {report_dir}")

    pipeline = _run_pipeline(
        bundle_dir=bundle_dir, workspace=workspace,
        output=output, report_dir=report_dir,
    )
    if not pipeline.ok:
        print(f"  [FAIL] pipeline rc={pipeline.rc}")
        tail = (
            pipeline.stderr or pipeline.stdout or ""
        ).splitlines()[-15:]
        for line in tail:
            print(f"    {line}")
        return 1, None, None
    print(f"  [PASS] pipeline rc=0")

    if not output.is_file() or output.is_symlink():
        print(
            f"  [FAIL] expected produced PPTX as a regular non-symlink "
            f"file at {output}"
        )
        return 1, None, None
    print(f"  [PASS] produced PPTX exists as a regular non-symlink file")

    contract = _run_contract_validator(pptx=output, expected_slide_count=2)
    if not contract.ok:
        print(f"  [FAIL] validate_pptx_contract rc={contract.rc}")
        for line in (
            contract.stderr or contract.stdout or ""
        ).splitlines()[-20:]:
            print(f"    {line}")
        return 1, None, None
    print(f"  [PASS] validate_pptx_contract rc=0")

    # Inventory: re-walk the produced PPTX and write a per-run JSON to
    # tempdir so the demo summary references a snapshot, not the
    # runner-written one (which is named the same way but landed
    # earlier in the chain). Both should describe the same package.
    demo_inventory_path = td / "demo_inventory.json"
    inventory_outcome = _run_inventory(
        pptx=output, out=demo_inventory_path,
    )
    if not inventory_outcome.ok:
        print(
            f"  [FAIL] inspect_pptx_inventory rc={inventory_outcome.rc}"
        )
        for line in (
            inventory_outcome.stderr or inventory_outcome.stdout or ""
        ).splitlines()[-20:]:
            print(f"    {line}")
        return 1, None, None
    print(f"  [PASS] inspect_pptx_inventory rc=0")
    try:
        inventory = json.loads(demo_inventory_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(
            f"  [FAIL] cannot parse {demo_inventory_path}: "
            f"{type(exc).__name__}: {exc}"
        )
        return 1, None, None

    runtime, errors = _derive_runtime_provenance(
        bundle_dir=bundle_dir, workspace=workspace,
        output_pptx=output, report_dir=report_dir,
    )
    if errors or runtime is None:
        print(
            f"  [FAIL] runtime provenance derivation produced "
            f"{len(errors)} error(s):"
        )
        for e in errors:
            print(f"    - {e}")
        return 1, None, None
    rows = runtime.get("rows") or []
    coverage = sorted({
        r.get("source_class") for r in rows
        if isinstance(r, dict) and r.get("source_class")
    })
    if set(coverage) != {"d_one_local", "local_asset"}:
        print(
            f"  [FAIL] runtime provenance source_class coverage="
            f"{coverage!r}; expected exactly "
            f"['d_one_local', 'local_asset']"
        )
        return 1, None, None
    print(
        f"  [PASS] runtime provenance derived; "
        f"{len(rows)} row(s); source_class coverage={coverage!r}"
    )

    sanitizer = _sanitize(runtime, tempdir_root=str(td))
    if not sanitizer.ok or sanitizer.record is None:
        print(
            f"  [FAIL] sanitizer refused the runtime object "
            f"({len(sanitizer.failures)} failure(s)):"
        )
        for f in sanitizer.failures:
            print(f"    - {f}")
        return 1, None, None
    print(
        f"  [PASS] sanitized runtime provenance into a committed-safe "
        f"handoff record"
    )

    evidence_path = td / "demo_handoff_record.json"
    provenance = _run_provenance_validator(
        sanitizer.record, evidence_path=evidence_path,
    )
    if not provenance.ok:
        print(
            f"  [FAIL] validate_mixed_image_asset_provenance rc="
            f"{provenance.rc}"
        )
        for line in (
            provenance.stderr or provenance.stdout or ""
        ).splitlines()[-20:]:
            print(f"    {line}")
        return 1, None, None
    print(
        f"  [PASS] validate_mixed_image_asset_provenance rc=0 on the "
        f"sanitized handoff record"
    )

    summary = _build_summary(
        pptx=output, report_dir=report_dir, inventory=inventory,
        contract=contract,
        inventory_outcome=inventory_outcome,
        provenance_outcome=provenance,
        runtime_provenance=runtime,
    )
    summary_path = td / "demo_summary.json"
    out_failures = _write_demo_summary_under_tempdir(
        summary=summary, summary_path=summary_path, tempdir_root=td,
    )
    if out_failures:
        print(
            f"  [FAIL] demo summary truth-check or output gate refused "
            f"({len(out_failures)} failure(s)):"
        )
        for f in out_failures:
            print(f"    - {f}")
        return 1, summary, None
    if not summary_path.is_file() or summary_path.is_symlink():
        print(
            f"  [FAIL] expected demo summary at {summary_path} as a "
            f"regular non-symlink file"
        )
        return 1, summary, None
    print(f"  [PASS] demo summary written to {summary_path}")

    # Echo a compact human-readable view to stdout so a reviewer can
    # see the milestone truth without opening the JSON file.
    print()
    print("--- demo summary ---")
    print(json.dumps(summary, indent=2, sort_keys=True))
    print()
    return 0, summary, summary_path


# ---------------------------------------------------------------------------
# Direct probes (no pipeline re-run).
# ---------------------------------------------------------------------------


@dataclass
class _ProbeOutcome:
    name: str
    ok: bool
    detail: str = ""


def _clone(record: dict) -> dict:
    return json.loads(json.dumps(record))


def _probe_repo_output_refused(
    *, td: Path, baseline: dict,
) -> _ProbeOutcome:
    """P1 — the output-path gate must refuse any path that lexically
    anchors under REPO_ROOT. This probe NEVER calls ``unlink()`` on
    a repo-root path: if a future writer regression lets bytes land
    under REPO_ROOT the snapshot at the end of self-test catches it,
    AND the probe surfaces the leak as a FAIL diagnostic. Silently
    unlinking the leak would mask a real regression."""
    name = "P1 demo summary path inside REPO_ROOT refused"
    target = REPO_ROOT / "demo_summary_should_never_land_here.json"

    # Pre-condition: the probe must not run if the target already
    # exists — we cannot tell a pre-existing user file from a leak,
    # and we must not delete a pre-existing file regardless.
    if target.exists() or target.is_symlink():
        return _ProbeOutcome(
            name, False,
            f"probe pre-condition violated: {target} already exists "
            f"(refusing to run because the probe must not touch a "
            f"pre-existing repo path)",
        )

    failures = _write_demo_summary_under_tempdir(
        summary=_clone(baseline), summary_path=target, tempdir_root=td,
    )
    if not failures:
        return _ProbeOutcome(
            name, False,
            f"expected refusal; output-path gate returned no "
            f"failures for {target}. The committed-tree snapshot at "
            f"the end of self-test will surface any leaked bytes; "
            f"this probe does NOT unlink {target} because doing so "
            f"would silently destroy evidence of the regression.",
        )
    if target.exists() or target.is_symlink():
        return _ProbeOutcome(
            name, False,
            f"output-path gate returned failures but {target} now "
            f"exists or is a symlink — the gate must refuse BEFORE "
            f"any bytes hit disk. This probe does NOT unlink "
            f"{target} because doing so would silently destroy "
            f"evidence of the regression; the committed-tree "
            f"snapshot will surface the leak too.",
        )
    return _ProbeOutcome(name, True)


def _probe_safe_unlink_refuses_repo_root_path(
    *, td: Path,
) -> _ProbeOutcome:
    """P1b — direct probe on ``_safe_unlink_under_tempdir``: even if
    a caller asks it to unlink a path under REPO_ROOT (e.g. a future
    output-path gate regression that lets a repo path through), the
    helper must NO-OP. We exercise the helper against an existing
    repo file (``README.md``) AND assert (a) it returns silently,
    (b) the repo file is byte-identical before and after, and (c) the
    file is NOT unlinked. This locks the safety contract at the
    helper boundary, independent of the output-path gate."""
    name = (
        "P1b _safe_unlink_under_tempdir no-ops on a REPO_ROOT path "
        "even with a tempdir root supplied"
    )
    target = REPO_ROOT / "README.md"
    if not target.is_file():
        return _ProbeOutcome(
            name, False,
            f"probe pre-condition violated: {target} is not a regular "
            f"file (cannot exercise the no-op contract)",
        )
    before_bytes = target.read_bytes()
    try:
        _safe_unlink_under_tempdir(path=target, tempdir_root=td)
    except Exception as exc:
        return _ProbeOutcome(
            name, False,
            f"_safe_unlink_under_tempdir raised on a REPO_ROOT path: "
            f"{type(exc).__name__}: {exc}",
        )
    if not target.is_file():
        return _ProbeOutcome(
            name, False,
            f"_safe_unlink_under_tempdir unlinked {target} — the "
            f"helper MUST no-op on any path that resolves under "
            f"REPO_ROOT",
        )
    after_bytes = target.read_bytes()
    if before_bytes != after_bytes:
        return _ProbeOutcome(
            name, False,
            f"_safe_unlink_under_tempdir mutated {target} bytes — "
            f"the helper MUST no-op on any path that resolves under "
            f"REPO_ROOT",
        )
    return _ProbeOutcome(name, True)


def _probe_no_stale_summary_after_failed_run(
    *, td: Path, baseline: dict,
) -> _ProbeOutcome:
    name = (
        "P2 truth-check failure leaves no stale demo_summary.json "
        "behind"
    )
    bad = _clone(baseline)
    bad["embedded_media_count"] = 0  # forces a truth-check failure
    summary_path = td / "p2_demo_summary.json"
    # Plant a stale byte string so we can verify the writer scrubbed it.
    summary_path.write_text("stale\n")
    failures = _write_demo_summary_under_tempdir(
        summary=bad, summary_path=summary_path, tempdir_root=td,
    )
    if not failures:
        return _ProbeOutcome(
            name, False,
            "expected truth-check refusal; got an empty failure list",
        )
    if summary_path.exists():
        return _ProbeOutcome(
            name, False,
            f"truth-check failed but a stale {summary_path} remained "
            f"(contents={summary_path.read_text()!r})",
        )
    return _ProbeOutcome(name, True)


def _probe_zero_embedded_media_fails(
    *, baseline: dict,
) -> _ProbeOutcome:
    name = "P3 summary claiming zero embedded media is refused"
    bad = _clone(baseline)
    bad["embedded_media_count"] = 0
    failures = _check_summary_truth(bad)
    if not any(
        "embedded_media_count" in f for f in failures
    ):
        return _ProbeOutcome(
            name, False,
            f"expected embedded_media_count diagnostic; got "
            f"{failures!r}",
        )
    return _ProbeOutcome(name, True)


def _probe_missing_d_one_lane_fails(
    *, baseline: dict,
) -> _ProbeOutcome:
    name = "P4 summary missing d_one_local lane is refused"
    bad = _clone(baseline)
    bad["source_class_coverage"] = ["local_asset"]
    failures = _check_summary_truth(bad)
    if not any(
        "source_class_coverage" in f for f in failures
    ):
        return _ProbeOutcome(
            name, False,
            f"expected source_class_coverage diagnostic; got "
            f"{failures!r}",
        )
    return _ProbeOutcome(name, True)


def _probe_missing_local_asset_lane_fails(
    *, baseline: dict,
) -> _ProbeOutcome:
    name = "P5 summary missing local_asset lane is refused"
    bad = _clone(baseline)
    bad["source_class_coverage"] = ["d_one_local"]
    failures = _check_summary_truth(bad)
    if not any(
        "source_class_coverage" in f for f in failures
    ):
        return _ProbeOutcome(
            name, False,
            f"expected source_class_coverage diagnostic; got "
            f"{failures!r}",
        )
    return _ProbeOutcome(name, True)


def _probe_real_d_one_claim_refused(
    *, baseline: dict,
) -> _ProbeOutcome:
    name = (
        "P6 positive real-D-One/MCP/network/model/image-search/Qoder "
        "success claim is refused"
    )
    perturbations: list[tuple[str, dict]] = []

    for marker in (
        "Real D-One verified online",
        "called MCP successfully",
        "model API returned successfully",
        "image search succeeded",
        "Qoder runtime succeeded",
        "public network ran live",
    ):
        bad = _clone(baseline)
        bad["notes"]["scope"] = marker
        perturbations.append((marker, bad))

    # Real D-One status drift — the canonical sentence is the only
    # allowed shape; any other text trips the truth-checker.
    drift = _clone(baseline)
    drift["real_d_one_status"] = "VERIFIED"
    perturbations.append(("real_d_one_status=VERIFIED", drift))

    for marker, bad in perturbations:
        failures = _check_summary_truth(bad)
        if not failures:
            return _ProbeOutcome(
                name, False,
                f"expected refusal for marker {marker!r}; got an "
                f"empty failure list",
            )
    return _ProbeOutcome(name, True)


def _probe_out_dir_uri_refused() -> _ProbeOutcome:
    """OP1 — every URI-shaped argument is refused before any
    filesystem touch."""
    name = "OP1 URI-shaped --out-dir argument refused"
    for cand in (
        "file:///tmp/should-not-be-followed",
        "http://example.invalid/out",
        "data:text/plain;base64,QUJD",
        "ftp://host.invalid/out",
        "custom-scheme:foo",
    ):
        validated, failures = _validate_out_dir_arg(cand)
        if validated is not None or not failures:
            return _ProbeOutcome(
                name, False,
                f"expected refusal for URI-shaped --out-dir {cand!r}; "
                f"got validated={validated!r}, failures={failures!r}",
            )
    return _ProbeOutcome(name, True)


def _probe_out_dir_symlink_refused(td: Path) -> _ProbeOutcome:
    """OP2 — an ``--out-dir`` that is itself a symlink is refused
    even when the link target is a writable empty directory."""
    name = "OP2 symlink --out-dir refused"
    real_target = td / "op2_real_target"
    try:
        real_target.mkdir()
    except OSError as exc:
        return _ProbeOutcome(
            name, False,
            f"cannot create probe target: {type(exc).__name__}: {exc}",
        )
    link = td / "op2_symlink_out"
    try:
        os.symlink(real_target, link)
    except (OSError, NotImplementedError) as exc:
        return _ProbeOutcome(
            name, False,
            f"cannot create probe symlink: {type(exc).__name__}: {exc}",
        )
    validated, failures = _validate_out_dir_arg(str(link))
    if validated is not None or not failures:
        return _ProbeOutcome(
            name, False,
            f"expected refusal for symlink --out-dir {link}; got "
            f"validated={validated!r}, failures={failures!r}",
        )
    return _ProbeOutcome(name, True)


def _probe_out_dir_symlink_ancestor_refused(td: Path) -> _ProbeOutcome:
    """OP3 — an ``--out-dir`` whose parent is a symlink is refused
    even when the leaf path does not exist yet."""
    name = "OP3 symlink ancestor of --out-dir refused"
    real_parent = td / "op3_real_parent"
    try:
        real_parent.mkdir()
    except OSError as exc:
        return _ProbeOutcome(
            name, False,
            f"cannot create probe target: {type(exc).__name__}: {exc}",
        )
    link_parent = td / "op3_symlink_parent"
    try:
        os.symlink(real_parent, link_parent)
    except (OSError, NotImplementedError) as exc:
        return _ProbeOutcome(
            name, False,
            f"cannot create probe symlink: {type(exc).__name__}: {exc}",
        )
    nested_parent = real_parent / "nested"
    try:
        nested_parent.mkdir()
    except OSError as exc:
        return _ProbeOutcome(
            name, False,
            f"cannot create nested target: {type(exc).__name__}: {exc}",
        )
    leaf = link_parent / "nested" / "op3_child_out"
    # Sanity: the leaf must NOT pre-exist (we want the symlink-
    # ancestor refusal, not a pre-existing-leaf refusal). The nested
    # parent exists through the symlink, so this probe catches a gate
    # that only checks the direct parent and misses deeper ancestors.
    if leaf.exists() or leaf.is_symlink():
        return _ProbeOutcome(
            name, False,
            f"probe pre-condition violated: {leaf} already exists",
        )
    validated, failures = _validate_out_dir_arg(str(leaf))
    if validated is not None or not failures:
        return _ProbeOutcome(
            name, False,
            f"expected refusal for symlink-ancestor --out-dir {leaf}; "
            f"got validated={validated!r}, failures={failures!r}",
        )
    return _ProbeOutcome(name, True)


def _probe_out_dir_under_repo_refused() -> _ProbeOutcome:
    """OP4 — any path that resolves under REPO_ROOT is refused
    BEFORE any mkdir, so the refused path is never created on disk."""
    name = "OP4 --out-dir under REPO_ROOT refused"
    for cand in (
        REPO_ROOT / "should_not_land_here_op4",
        REPO_ROOT / "scripts" / "should_not_land_here_op4",
        REPO_ROOT / "examples" / "should_not_land_here_op4",
    ):
        # Pre-condition: never run against a pre-existing path under
        # the repo (the probe must not destroy operator state).
        if cand.exists() or cand.is_symlink():
            return _ProbeOutcome(
                name, False,
                f"probe pre-condition violated: {cand} already exists; "
                f"the probe refuses to run rather than touch a pre-"
                f"existing repo path",
            )
        validated, failures = _validate_out_dir_arg(str(cand))
        if validated is not None or not failures:
            return _ProbeOutcome(
                name, False,
                f"expected refusal for repo-contained --out-dir {cand}; "
                f"got validated={validated!r}, failures={failures!r}",
            )
        if cand.exists() or cand.is_symlink():
            return _ProbeOutcome(
                name, False,
                f"refusal returned but {cand} now exists or is a "
                f"symlink — the gate must refuse BEFORE any mkdir",
            )
    return _ProbeOutcome(name, True)


def _probe_out_dir_non_empty_refused(td: Path) -> _ProbeOutcome:
    """OP5 — a pre-existing non-empty ``--out-dir`` is refused AND
    the pre-existing bytes are left byte-identical."""
    name = "OP5 pre-existing non-empty --out-dir refused"
    cand = td / "op5_non_empty_out"
    try:
        cand.mkdir()
    except OSError as exc:
        return _ProbeOutcome(
            name, False,
            f"cannot create probe target: {type(exc).__name__}: {exc}",
        )
    leftover_path = cand / "prior_run_marker.txt"
    leftover_bytes = b"pre-existing operator bytes - must not be touched\n"
    leftover_path.write_bytes(leftover_bytes)

    validated, failures = _validate_out_dir_arg(str(cand))
    if validated is not None or not failures:
        return _ProbeOutcome(
            name, False,
            f"expected refusal for non-empty --out-dir {cand}; got "
            f"validated={validated!r}, failures={failures!r}",
        )
    # Sanity: the leftover bytes must be untouched.
    if not leftover_path.is_file():
        return _ProbeOutcome(
            name, False,
            f"refusal returned but {leftover_path} was removed — the "
            f"gate must refuse without touching pre-existing bytes",
        )
    if leftover_path.read_bytes() != leftover_bytes:
        return _ProbeOutcome(
            name, False,
            f"refusal returned but {leftover_path} bytes were mutated "
            f"— the gate must refuse without touching pre-existing "
            f"bytes",
        )
    return _ProbeOutcome(name, True)


def _run_probes(td: Path, baseline: dict) -> int:
    fails = 0
    print()
    print("--- fail-closed probes (direct; no pipeline re-run) ---")
    probes: list[_ProbeOutcome] = [
        _probe_repo_output_refused(td=td, baseline=baseline),
        _probe_safe_unlink_refuses_repo_root_path(td=td),
        _probe_no_stale_summary_after_failed_run(
            td=td, baseline=baseline,
        ),
        _probe_zero_embedded_media_fails(baseline=baseline),
        _probe_missing_d_one_lane_fails(baseline=baseline),
        _probe_missing_local_asset_lane_fails(baseline=baseline),
        _probe_real_d_one_claim_refused(baseline=baseline),
        _probe_out_dir_uri_refused(),
        _probe_out_dir_symlink_refused(td),
        _probe_out_dir_symlink_ancestor_refused(td),
        _probe_out_dir_under_repo_refused(),
        _probe_out_dir_non_empty_refused(td),
    ]
    for p in probes:
        mark = "PASS" if p.ok else "FAIL"
        print(f"  [{mark}] {p.name}")
        if not p.ok:
            if p.detail:
                print(f"    detail: {p.detail}")
            fails += 1
    return fails


# ---------------------------------------------------------------------------
# Self-test top level.
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    print(
        "=== core_image_to_editable_ppt_demo (--self-test) ==="
    )

    tree_before = _snapshot_committed_tree()
    if not tree_before:
        print(
            "FAIL: committed-tree snapshot is empty — refusing to "
            "run because a downstream regression cannot be detected "
            "against an empty baseline.",
            file=sys.stderr,
        )
        return 1

    rc = 0
    with tempfile.TemporaryDirectory(
        prefix="szh_core_image_to_editable_ppt_demo_",
    ) as raw_outer:
        outer = Path(raw_outer)

        # Exercise the operator-mode pathway from inside the outer
        # tempdir so --self-test and --out-dir share one code path.
        # The leaf path does NOT pre-exist — _run_operator_mode mkdirs
        # it via the strict, non-recursive mkdir the validator allows.
        operator_out = outer / "operator_out"
        validated, op_failures = _validate_out_dir_arg(str(operator_out))
        if validated is None or op_failures:
            print(
                f"FAIL: self-test --out-dir gate refused the inner "
                f"operator path ({len(op_failures)} failure(s)):",
                file=sys.stderr,
            )
            for f in op_failures:
                print(f"  - {f}", file=sys.stderr)
            rc = 1
            baseline: dict | None = None
        else:
            operator_rc = _run_operator_mode(validated)
            if operator_rc != 0:
                rc = 1
                baseline = None
            else:
                summary_path = validated / "demo_summary.json"
                try:
                    baseline = json.loads(
                        summary_path.read_text(encoding="utf-8"),
                    )
                except (OSError, json.JSONDecodeError) as exc:
                    print(
                        f"FAIL: cannot re-read operator-mode "
                        f"demo_summary.json at {summary_path}: "
                        f"{type(exc).__name__}: {exc}",
                        file=sys.stderr,
                    )
                    rc = 1
                    baseline = None

        if rc == 0 and baseline is not None:
            # Run the fail-closed probes against the just-produced
            # baseline summary, using a fresh scratch tempdir inside
            # the outer tempdir so probe-planted files do not collide
            # with operator-mode artifacts.
            probes_scratch = outer / "probes_scratch"
            probes_scratch.mkdir()
            probe_fails = _run_probes(probes_scratch, baseline)
            if probe_fails:
                rc = 1

    tree_after = _snapshot_committed_tree()
    if tree_before != tree_after:
        changed = sorted(
            k for k in set(tree_before) | set(tree_after)
            if tree_before.get(k) != tree_after.get(k)
        )
        print(
            f"FAIL: committed tree under REPO_ROOT mutated during "
            f"the demo self-test (changed: {changed!r})",
            file=sys.stderr,
        )
        rc = 1

    if rc == 0:
        print()
        print(
            "OK (core image-to-editable-PPT demo): operator-mode "
            "happy path + every fail-closed probe passed; nothing "
            "under REPO_ROOT mutated. Real D-One remains UNVERIFIED "
            "— one local/mock command proves image-to-editable-PPT "
            "demo readiness."
        )
    return rc


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "One-command demo for the local/mock image-to-editable-"
            "PPT loop. Drives the existing mixed-lane mock pipeline "
            "+ validators once, derives a concise demo summary JSON, "
            "and asserts the documented invariants. Two modes share "
            "one happy path: --self-test (per-run tempdir + fail-"
            "closed probes) or --out-dir DIR (operator mode; "
            "inspectable artifacts retained under DIR outside the "
            "repo tree). Stdlib-only. NETWORK-FREE. NO real D-One. "
            "NO MCP. NO Qoder. NO model API. NO image search. NO "
            "telemetry."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--self-test", action="store_true",
        help=(
            "Self-test mode: drive the happy path through a per-run "
            "tempdir (no caller-visible artifacts retained), then "
            "run the fail-closed probes including the operator-mode "
            "--out-dir argument-gate probes (OP1..OP5)."
        ),
    )
    mode.add_argument(
        "--out-dir", dest="out_dir", default=None, metavar="DIR",
        help=(
            "Operator mode: write the produced .pptx, the runner-"
            "written report/inventory/sidecar artifacts, the demo's "
            "per-run inventory snapshot, the sanitized handoff "
            "record, and demo_summary.json under DIR. DIR must be "
            "outside the repo tree, non-URI, non-symlink (with no "
            "symlink ancestors), parent must exist, and DIR must be "
            "either nonexistent (will be created) or an empty pre-"
            "existing directory."
        ),
    )
    args = parser.parse_args(argv)

    if args.out_dir is not None:
        validated, failures = _validate_out_dir_arg(args.out_dir)
        if validated is None or failures:
            print(
                f"FAIL: --out-dir refused ({len(failures)} "
                f"failure(s)):",
                file=sys.stderr,
            )
            for f in failures:
                print(f"  - {f}", file=sys.stderr)
            return 2
        return _run_operator_mode(validated)

    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
