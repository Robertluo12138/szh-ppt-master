#!/usr/bin/env python3
"""core_image_to_editable_ppt_demo.py

Tempdir-only, stdlib-only **one-command demo smoke** that proves the
current core image-to-editable-PPT loop end-to-end on local / mock /
synthetic inputs. This is a milestone proof — one ``--self-test``
invocation drives the existing mixed-lane mock pipeline once, runs the
existing validators (``validate_pptx_contract``,
``inspect_pptx_inventory``,
``validate_mixed_image_asset_provenance``), derives a concise demo
summary describing the product truth, writes every output under a
single ``tempfile.TemporaryDirectory()`` outside the committed repo
tree, and asserts the documented invariants.

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

Demo summary (written to ``<tempdir>/demo_summary.json``):

  * ``slide_count`` — read from the produced PPTX inventory readback.
  * ``pptx_path`` — absolute path inside the tempdir (no committed
    artifact).
  * ``report_dir`` — absolute path inside the tempdir.
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
truth-checker / output-gate refuses):

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
    ) as raw_td:
        td = Path(raw_td)
        happy_rc, baseline, _summary_path = _run_happy_path(td)
        if happy_rc != 0 or baseline is None:
            rc = 1
        else:
            probe_fails = _run_probes(td, baseline)
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
            "OK (core image-to-editable-PPT demo): happy path + every "
            "fail-closed probe passed; nothing under REPO_ROOT "
            "mutated. Real D-One remains UNVERIFIED — one local/mock "
            "command proves image-to-editable-PPT demo readiness."
        )
    return rc


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "One-command demo smoke proving the local/mock image-to-"
            "editable-PPT loop end-to-end. Drives the existing mixed-"
            "lane mock pipeline + validators once under a per-run "
            "tempdir, derives a concise demo summary JSON, asserts "
            "the documented invariants, and runs the documented fail-"
            "closed probes. Stdlib-only. NETWORK-FREE. NO real D-One. "
            "NO MCP. NO Qoder. NO model API. NO image search. NO "
            "telemetry. Self-test surface only today."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Required: run the happy path + every fail-closed probe."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: core_image_to_editable_ppt_demo.py requires "
            "--self-test (no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
