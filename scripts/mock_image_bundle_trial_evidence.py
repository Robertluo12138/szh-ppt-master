#!/usr/bin/env python3
"""Mock-image bundle trial evidence emitter (LOCAL, STUB, NOT real D-One).

Tempdir-only, stdlib-only evidence layer over the already-passing
``scripts/mock_image_bundle_acceptance_smoke.py`` path. Drives the
COMMITTED ``examples/synthetic_mock_image_trial/`` bundle through
``scripts/run_mock_image_pipeline.py --bundle`` into a tempfile-owned
workspace / output / report directory OUTSIDE the repo tree, then
re-runs ``scripts/validate_mock_d_one_adapter_plan.py`` (with
``--require-both-placement-roles`` and ``--descriptor-vocabulary
<bundle/descriptor_vocabulary.json>``) against the runner-written
``<report-dir>/mock_d_one_adapter_plan.json`` sidecar, runs
``scripts/validate_pptx_contract.py`` and
``scripts/inspect_pptx_inventory.py`` against the produced PPTX, and
emits a compact JSON evidence object both to stdout AND to a temp
report file.

Sibling to ``scripts/image_asset_trial_evidence.py`` but scoped to
the BUNDLE path (not the synthetic-fixture path). Both ship under the
core editable-PPT acceptance aggregate as separate evidence emitters.

After the evidence JSON is written, the emitter shells out to
``scripts/validate_mock_image_bundle_trial_evidence.py --evidence
<happy>/evidence.json --require-files`` from a clean process boundary
to re-check the just-written bytes against the committed schema
``schemas/mock_image_bundle_trial_evidence.schema.json`` plus the
documented semantic + string-safety + real-D-One claim-refusal gates
(and the in-tempdir filesystem contract). The standalone validator
never imports this emitter, so a bug where the in-script summary gate
is green but the emitted JSON carries an internally-inconsistent or
forbidden shape is caught from a clean process boundary. No circular
fields are added to the evidence (the validator outcome is recorded
in the emitter's stdout, not in the evidence JSON itself).

What the JSON evidence records (every value observed under
``tempfile.TemporaryDirectory()`` — never read from or written to the
committed repo tree):

  - ``summary.ok`` — single boolean: every observed gate held.
  - ``real_d_one_status`` — fixed sentence pinned to ``UNVERIFIED``
    plus the explicit list of services NOT called (D-One, MCP,
    public network, model API, image search, Qoder, telemetry).
  - ``pptx.{path,exists,size_bytes}`` — final deck under the
    tempdir, its existence as a regular non-symlink file, and its
    size in bytes.
  - ``inventory.{ok,findings,slide_count,media_parts_count,
    evidence_basis,no_external_relationships}`` — fields lifted
    from ``<report-dir>/inventory.json`` (written by
    ``run_explicit_pipeline`` via ``inspect_pptx_inventory``) plus
    the derived ``no_external_relationships`` boolean.
  - ``validators.validate_pptx_contract.{rc,ok}`` — belt-and-braces
    contract validator with ``--expected-slide-count 2``.
  - ``validators.inspect_pptx_inventory.{rc,ok}`` — belt-and-braces
    inventory inspector (the pipeline already wrote
    ``<report-dir>/inventory.json``; this proves the standalone CLI
    re-runs clean against the produced deck).
  - ``validators.validate_mock_d_one_adapter_plan.{rc,ok,
    vocabulary_gate_used,require_both_placement_roles_used}`` —
    sidecar validator outcome PLUS two booleans proving the
    bundle's committed ``descriptor_vocabulary.json`` was passed
    on the validator command line AND
    ``--require-both-placement-roles`` was active (so the G9 +
    G13 gates actually fired against the runner-written sidecar).
  - ``sidecar.{path,exists,schema_version,request_count,
    placement_role_coverage,text_policy_coverage,
    covers_multiple_text_policies,requests}`` — fields lifted
    from the runner-written ``mock_d_one_adapter_plan.json``.
    Each ``requests[]`` entry carries ``id`` / ``placement_role``
    / ``text_policy`` / ``subject_domain`` /
    ``manifest_local_path`` plus the optional ``custom_descriptor``
    (preserved verbatim when the request carries the escape-hatch
    field, omitted otherwise so the JSON does not invent a value).
    ``text_policy_coverage`` is the sorted unique set of per-
    request text_policy values and ``covers_multiple_text_policies``
    is True iff at least ``EXPECTED_MIN_DISTINCT_TEXT_POLICIES``
    (today: 2) distinct text_policy values were observed; the
    emitter's ``summary.ok`` gate refuses a record where every
    per-request text_policy collapsed to the same value (typically
    all ``no_text``) so the committed bundle path exercises mixed
    per-request text_policy end-to-end, not only the adapter-only
    smoke.
  - ``notes.scope`` / ``notes.embed_surface`` — fixed framing so
    the evidence reader knows what this emitter does NOT prove.

Snapshot check: ``REPO_ROOT/examples`` and ``REPO_ROOT/scripts`` are
byte-snapshotted before the run and re-snapshotted after; either tree
mutating aborts the script non-zero (same gate every other acceptance
smoke applies).

``--self-test`` runs the happy path PLUS five fail-closed probes,
each asserting the documented failure mode actually flips a non-zero
exit (or, for the helper-only probes, surfaces the regression at the
static helper layer):

  1. missing bundle: point the runner at a non-existent bundle path
     and confirm no PPTX, no sidecar, no evidence written.
  2. forced downstream failure: corrupt the bundle's
     ``image_manifest_spec.json`` (URI-scheme local_path) so the
     downstream chain aborts BEFORE
     ``run_mock_image_pipeline`` writes the audit sidecar; assert the
     sidecar is absent and the evidence emitter refuses to claim
     success.
  3. bad descriptor vocabulary: copy the bundle then strip the
     ``text_policy`` allowed-values block from
     ``descriptor_vocabulary.json``; on the second pass through the
     sidecar validator with the bad vocab, the G13 gate refuses and
     the validator exits non-zero — the evidence emitter must
     propagate that as a failed gate.
  4. malformed-request summary refusal (direct probe, uses tempdir
     only for synthetic sidecar bytes): build synthetic sidecars
     whose any request drops or corrupts a goal-required field
     (``id`` / ``placement_role`` / ``text_policy`` /
     ``subject_domain`` / ``manifest_local_path``), or carries a
     non-dict entry, or is an empty requests list, and assert
     ``_summary_ok`` flips False even when every other gate
     (validator, inventory, PPTX, placement-role coverage) would
     otherwise be green. Without this, a schema-valid-but-goal-
     short sidecar would let the emitter false-green a record full
     of nulls. The well-formed baseline is re-asserted to still
     produce ``summary.ok=True`` so the gate is not a blanket fail.
  5. evidence-claim refusal (direct probe, no subprocess): build a
     tampered evidence JSON that claims real D-One / MCP / public
     network / model API / image search / Qoder success and assert
     the in-script ``_evidence_refuses_real_d_one_claims`` helper
     flags every variant. This is the static gate that keeps the
     emitted JSON honest about what the mock chain actually proves.

Stdlib-only. NETWORK-FREE. NO real D-One. NO MCP. NO Qoder. NO model
API. NO image search. NO telemetry. NOT a full prompt/report/
Markdown-to-PPTX automation — this emitter composes the committed
mock chain and records what it produced; it does not extend any
pipeline stage and does not extract source content.

Usage:
  python3 scripts/mock_image_bundle_trial_evidence.py --self-test
"""
from __future__ import annotations

import sys

# Refuse to write `.pyc` files for any module imported by this script.
# The emitter's contract is that it writes only into the per-run
# tempdir; without this gate the first-party imports below would
# silently leak `scripts/__pycache__/<mod>.cpython-*.pyc` on a clean
# checkout. PYTHONDONTWRITEBYTECODE=1 in the env achieves the same
# thing for callers who remember the prefix; the in-script flip closes
# the hole unconditionally. Must come BEFORE any first-party import.
sys.dont_write_bytecode = True

import argparse  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import shutil  # noqa: E402
import subprocess  # noqa: E402
import tempfile  # noqa: E402
from dataclasses import dataclass  # noqa: E402
from pathlib import Path  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
TEMPLATE_ROOT = REPO_ROOT / "templates" / "layouts"
COMMITTED_BUNDLE = REPO_ROOT / "examples" / "synthetic_mock_image_trial"

# Committed-bundle invariants. Mirrors
# ``mock_image_bundle_acceptance_smoke``'s constants verbatim — the
# evidence emitter and the smoke share the same source-of-truth
# expectations about what the committed bundle produces.
EXPECTED_SLIDE_COUNT = 2
EXPECTED_PLACEMENT_ROLES: frozenset[str] = frozenset({
    "hero_page", "local_region",
})
# Goal-pinned minimum number of distinct text_policy values across
# the sidecar's requests[]. The committed bundle must exercise mixed
# per-request text_policy end-to-end — a sidecar in which every
# request's text_policy collapsed to the same value (typically all
# 'no_text') is refused by both the emitter's summary.ok gate and the
# downstream validator's G10 diversity gate.
EXPECTED_MIN_DISTINCT_TEXT_POLICIES = 2
EVIDENCE_SIDECAR_FILENAME = "mock_d_one_adapter_plan.json"
EXPECTED_EVIDENCE_BASIS = (
    "OOXML structure only; not proof of full PowerPoint editability"
)
# Locked sidecar plan schema version (mirrors
# run_mock_image_pipeline.LOCKED_PLAN_SCHEMA_VERSION).
EXPECTED_SIDECAR_SCHEMA_VERSION = 4

# Per-request fields the goal requires the evidence to record on
# EVERY generated request. The sidecar schema treats the taxonomy
# fields as optional, but the goal pins them — so the emitter must
# refuse to claim summary.ok=True for any record that drops one of
# these or carries it as a non-string / empty value. ``custom_
# descriptor`` is the explicit escape-hatch field and stays optional.
_REQUIRED_REQUEST_FIELDS: tuple[str, ...] = (
    "id",
    "placement_role",
    "text_policy",
    "subject_domain",
    "manifest_local_path",
)

# Embed surface scripts/export_pptx.py supports today.
_EMBEDDABLE_MEDIA_EXTS: tuple[str, ...] = (".png", ".jpg", ".jpeg")

# RFC-3986-shaped scheme detector — used by the relationship walk.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# Schema framing for the evidence file. Bump only when the field set
# changes. Internal to this script — no separate schema file today.
EVIDENCE_SCHEMA_VERSION = "1"
EVIDENCE_FILENAME = "mock_image_bundle_trial_evidence.json"

REAL_D_ONE_STATUS = (
    "UNVERIFIED — real D-One is NOT called by this evidence emitter. "
    "The PNG bytes embedded in the produced PPTX come from the "
    "in-script mock provider in scripts/run_d_one_generation.py "
    "(--allow-synthetic-bytes), not from any external service. No "
    "MCP, no public network, no model API, no image search, no "
    "Qoder, no telemetry."
)

# Token sets for the static claim refusal helper. The gate is narrow:
# refuse a JSON that asserts the mock chain proved a real-D-One / MCP
# / network / model / image-search / Qoder integration succeeded. The
# canonical happy-path emitter never writes any of these tokens
# alongside a positive verdict — every mention of "D-One" in the
# happy-path JSON is wrapped in the fixed UNVERIFIED sentence whose
# verbs are individually negated ("is NOT called") AND every "noun
# without a verb" mention sits in a scope flag ("real_d_one_status",
# "covers_both_placement_roles") whose value is either the disclaimer
# string or a boolean derived from observation.
_FORBIDDEN_CLAIM_VERBS: tuple[str, ...] = (
    "verified", "passed", "succeeded", "succeeds", "succeed",
    "online", "live", "enabled",
    "called", "reached", "fetched", "received",
)
_FORBIDDEN_CLAIM_NOUNS: tuple[str, ...] = (
    "real d-one", "real_d_one", "real-d-one",
    "live d-one", "live_d_one", "live-d-one",
    "production d-one", "production_d_one", "production-d-one",
    # Bare D-One — required so a key like `d_one_status` or `d-one`
    # (without the `real_`/`live_`/`production_` qualifier) is
    # recognised as noun-bearing. The separator (`_` or `-`) is what
    # keeps these forms out of normal English; without it (`done`,
    # `dane`, etc.) the gate would false-trip on common words.
    "d_one", "d-one",
    "mcp", "model context protocol",
    "public network", "public_network", "public-network",
    "model api", "model_api", "model-api",
    "image search", "image_search", "image-search",
    "qoder",
)

# Negation tokens. Each is matched as a lower-cased substring inside
# a SHORT window before the verb (see ``_verb_is_negated``). A short
# window is deliberate: a single distant negation elsewhere in the
# same string must not be allowed to shield a clean un-negated verb
# (the previous whole-string scan let
# ``"no telemetry; real D-One verified online"`` pass because a stray
# "no" disqualified the entire string). 15 chars covers the canonical
# "is NOT called" / "is not enabled" / "was not received" patterns
# without giving attackers a free pad.
_NEGATION_TOKENS: tuple[str, ...] = (
    " not ", " no ", " never ", " without ", " none ",
    "n't",
    "is not", "are not", "was not", "were not",
    "do not", "does not", "did not",
    "will not", "would not", "cannot",
)
_NEGATION_WINDOW_CHARS = 15


# ---------------------------------------------------------------------------
# Subprocess helpers. We shell out to every downstream tool so each
# script's argparse + fail-closed gates + stdout/stderr cascade is
# exercised verbatim.
# ---------------------------------------------------------------------------


@dataclass
class ToolOutcome:
    name: str
    cmd: list[str]
    rc: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.rc == 0

    @property
    def combined(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


def _run_tool(
    name: str, cmd: list[str], *, env: dict[str, str] | None = None,
) -> ToolOutcome:
    proc_env = (
        env if env is not None
        else {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    )
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=proc_env,
    )
    return ToolOutcome(
        name=name, cmd=cmd, rc=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


def _print_outcome(o: ToolOutcome) -> None:
    print(f"  [{'PASS' if o.ok else 'FAIL'}] {o.name} (rc={o.rc})")
    if not o.ok:
        for stream_name, body in (("stdout", o.stdout), ("stderr", o.stderr)):
            tail = (body or "").splitlines()[-12:]
            if tail:
                print(f"    {stream_name} tail:")
                for line in tail:
                    print(f"      {line}")


# ---------------------------------------------------------------------------
# Snapshot helpers — repo-immutability gate.
# ---------------------------------------------------------------------------


def _snapshot_dir(dir_path: Path) -> dict[str, bytes]:
    snapshot: dict[str, bytes] = {}
    if not dir_path.is_dir():
        return snapshot
    for p in sorted(dir_path.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(dir_path)
        snapshot[str(rel)] = p.read_bytes()
    return snapshot


def _diff_keys(
    before: dict[str, bytes], after: dict[str, bytes],
) -> list[str]:
    return [
        k for k in sorted(set(before) | set(after))
        if before.get(k) != after.get(k)
    ]


# ---------------------------------------------------------------------------
# Pipeline + validator drivers.
# ---------------------------------------------------------------------------


def _runner_cmd(
    *, bundle: Path, workspace: Path, output: Path, report_dir: Path,
) -> list[str]:
    """Build the run_mock_image_pipeline --bundle command. Mirrors the
    invocation shape used by mock_image_bundle_acceptance_smoke."""
    return [
        sys.executable, str(SCRIPTS_DIR / "run_mock_image_pipeline.py"),
        "--bundle", str(bundle),
        "--workspace", str(workspace),
        "--template-root", str(TEMPLATE_ROOT),
        "--output", str(output),
        "--report-dir", str(report_dir),
        "--allow-synthetic-bytes",
    ]


def _run_runner(
    *, bundle: Path, workspace: Path, output: Path, report_dir: Path,
) -> ToolOutcome:
    return _run_tool(
        "run_mock_image_pipeline (--bundle synthetic_mock_image_trial)",
        _runner_cmd(
            bundle=bundle, workspace=workspace,
            output=output, report_dir=report_dir,
        ),
    )


def _run_contract_validator(
    *, pptx: Path, expected_slide_count: int,
) -> ToolOutcome:
    return _run_tool(
        f"validate_pptx_contract (--expected-slide-count "
        f"{expected_slide_count})",
        [
            sys.executable, str(SCRIPTS_DIR / "validate_pptx_contract.py"),
            "--pptx", str(pptx),
            "--expected-slide-count", str(expected_slide_count),
        ],
    )


def _run_inventory_inspector(*, pptx: Path) -> ToolOutcome:
    return _run_tool(
        "inspect_pptx_inventory",
        [
            sys.executable, str(SCRIPTS_DIR / "inspect_pptx_inventory.py"),
            "--pptx", str(pptx),
        ],
    )


def _run_sidecar_validator(
    *, sidecar_path: Path, bundle: Path,
) -> ToolOutcome:
    """Re-run validate_mock_d_one_adapter_plan.py with both
    --require-both-placement-roles AND --descriptor-vocabulary against
    the runner-written sidecar. Both flags are required by the goal so
    G9 + G13 actually fire against the sidecar bytes."""
    return _run_tool(
        "validate_mock_d_one_adapter_plan (--require-both-placement-"
        "roles, --descriptor-vocabulary)",
        [
            sys.executable,
            str(SCRIPTS_DIR / "validate_mock_d_one_adapter_plan.py"),
            "--plan", str(sidecar_path),
            "--d-one-spec", str(bundle / "d_one_spec.json"),
            "--image-manifest-spec",
            str(bundle / "image_manifest_spec.json"),
            "--require-both-placement-roles",
            "--descriptor-vocabulary",
            str(bundle / "descriptor_vocabulary.json"),
        ],
    )


# ---------------------------------------------------------------------------
# Evidence collection. Each helper reads from a tempdir-only artifact
# (PPTX zip, inventory.json, sidecar.json) and returns a flat dict of
# the fields the trial evidence reports on plus the derived booleans
# the reviewer would otherwise have to re-compute.
# ---------------------------------------------------------------------------


def _collect_pptx_evidence(pptx: Path) -> dict:
    is_file = pptx.is_file() and not pptx.is_symlink()
    return {
        "path": str(pptx),
        "exists": is_file,
        "size_bytes": pptx.stat().st_size if is_file else 0,
    }


def _inventory_has_no_external_relationships(inv: dict) -> bool:
    """Mirrors the relationship walk in mock_image_bundle_acceptance_
    smoke._check_inventory_invariants: every relationship target_mode
    must be internal (or absent) AND no Target may carry a URI-scheme
    prefix. The inventory's findings list is what
    inspect_pptx_inventory.py's gates flag — but we also re-derive the
    boolean here so the evidence JSON can claim 'no external rels'
    without depending on the findings list being complete."""
    relationships = inv.get("relationships")
    if not isinstance(relationships, list):
        return False
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        target = rel.get("target") or ""
        mode = (rel.get("target_mode") or "").lower()
        if mode and mode != "internal":
            return False
        if isinstance(target, str) and _URI_SCHEME_PREFIX.match(target):
            return False
    return True


def _collect_inventory_evidence(
    inventory_path: Path, *, expected_slide_count: int,
) -> dict:
    """Lift the subset of ``<report-dir>/inventory.json`` the trial
    evidence reports on plus pass/fail booleans for each gate."""
    out: dict = {
        "path": str(inventory_path),
        "exists": False,
        "parses_as_json": False,
        "ok": None,
        "findings": None,
        "slide_count": None,
        "media_parts_count": None,
        "evidence_basis": None,
        "evidence_basis_matches": False,
        "slide_count_matches_plan": False,
        "media_parts_count_min_met": False,
        "no_external_relationships": False,
        "findings_empty": False,
    }
    if not (inventory_path.is_file() and not inventory_path.is_symlink()):
        return out
    out["exists"] = True
    try:
        inv = json.loads(inventory_path.read_text())
    except (json.JSONDecodeError, OSError):
        return out
    out["parses_as_json"] = True
    out["ok"] = inv.get("ok")
    out["findings"] = inv.get("findings")
    out["slide_count"] = inv.get("slide_count")
    mp = inv.get("media_parts")
    if isinstance(mp, list):
        embedded = [
            m for m in mp
            if isinstance(m, dict)
            and isinstance(m.get("extension"), str)
            and "." + m["extension"].lower() in _EMBEDDABLE_MEDIA_EXTS
        ]
        out["media_parts_count"] = len(embedded)
        # Committed bundle declares one image per placement_role, so
        # the embed count floor is the placement-role count.
        out["media_parts_count_min_met"] = (
            len(embedded) >= len(EXPECTED_PLACEMENT_ROLES)
        )
    out["evidence_basis"] = inv.get("evidence_basis")
    out["evidence_basis_matches"] = (
        inv.get("evidence_basis") == EXPECTED_EVIDENCE_BASIS
    )
    out["slide_count_matches_plan"] = (
        inv.get("slide_count") == expected_slide_count
    )
    out["findings_empty"] = inv.get("findings") == []
    out["no_external_relationships"] = (
        _inventory_has_no_external_relationships(inv)
    )
    return out


def _collect_sidecar_evidence(sidecar_path: Path) -> dict:
    """Lift the subset of the runner-written
    ``<report-dir>/mock_d_one_adapter_plan.json`` the trial evidence
    reports on. ``requests[]`` carries one record per generated
    request with the goal-required fields (id / placement_role /
    text_policy / subject_domain / manifest_local_path) plus the
    optional ``custom_descriptor`` when the request itself carries
    the escape-hatch field.

    Records the sibling booleans ``all_requests_well_formed`` and
    ``malformed_request_indices`` so a sidecar that drops a goal-
    required per-request field — or carries it as a null / non-
    string / empty value, or has a non-dict request entry — flips
    summary.ok to False rather than silently emitting a record full
    of nulls. The sidecar schema treats the taxonomy fields as
    optional; the goal pins them, so the evidence emitter must hold
    the stricter line."""
    out: dict = {
        "path": str(sidecar_path),
        "exists": False,
        "parses_as_json": False,
        "schema_version": None,
        "schema_version_locked": False,
        "request_count": None,
        "request_count_matches_requests": False,
        "requests": [],
        "malformed_request_indices": [],
        "all_requests_well_formed": False,
        "placement_role_coverage": [],
        "covers_both_placement_roles": False,
        "text_policy_coverage": [],
        "covers_multiple_text_policies": False,
    }
    if not (sidecar_path.is_file() and not sidecar_path.is_symlink()):
        return out
    out["exists"] = True
    try:
        doc = json.loads(sidecar_path.read_text())
    except (json.JSONDecodeError, OSError):
        return out
    out["parses_as_json"] = True
    out["schema_version"] = doc.get("schema_version")
    out["schema_version_locked"] = (
        doc.get("schema_version") == EXPECTED_SIDECAR_SCHEMA_VERSION
    )
    out["request_count"] = doc.get("request_count")
    requests = doc.get("requests")
    if isinstance(requests, list):
        out["request_count_matches_requests"] = (
            doc.get("request_count") == len(requests)
        )
        records: list[dict] = []
        roles: set[str] = set()
        text_policies: set[str] = set()
        malformed: list[int] = []
        for i, req in enumerate(requests):
            if not isinstance(req, dict):
                malformed.append(i)
                # Record the index slot so the records list stays
                # 1:1 with the raw sidecar entries — a reviewer can
                # then point at "evidence.sidecar.requests[2]" and
                # see the placeholder rather than re-counting bytes
                # to find which index was the bad one.
                records.append({"__malformed__": True})
                continue
            rec: dict = {}
            for f in _REQUIRED_REQUEST_FIELDS:
                rec[f] = req.get(f)
            # Optional escape-hatch field — preserved verbatim when
            # present so the reviewer can see the approved value.
            # Omitted otherwise so the JSON does not invent it.
            if isinstance(req.get("custom_descriptor"), str):
                rec["custom_descriptor"] = req["custom_descriptor"]
            records.append(rec)
            # A request is well-formed iff every goal-required field
            # is a non-empty string. Anything else (None, integer,
            # empty string, missing key) flags the index as
            # malformed so the summary gate flips below.
            if not all(
                isinstance(rec.get(f), str) and rec[f]
                for f in _REQUIRED_REQUEST_FIELDS
            ):
                malformed.append(i)
            role = req.get("placement_role")
            if isinstance(role, str):
                roles.add(role)
            tp = req.get("text_policy")
            if isinstance(tp, str) and tp:
                text_policies.add(tp)
        out["requests"] = records
        out["malformed_request_indices"] = malformed
        # The full set of conditions a well-formed requests list
        # must meet: every entry is a dict, every goal-required
        # field is a non-empty string, and there is at least one
        # request (a zero-length list is a vacuous green that
        # cannot prove the bundle generated any image).
        out["all_requests_well_formed"] = (
            not malformed
            and len(records) == len(requests)
            and len(records) > 0
        )
        out["placement_role_coverage"] = sorted(roles)
        out["covers_both_placement_roles"] = (
            roles == EXPECTED_PLACEMENT_ROLES
        )
        # Mixed-text_policy coverage. The committed bundle must
        # exercise per-request text_policy judgement end-to-end;
        # the smoke / runner / sidecar validator already do per-id
        # parity (so a drift would surface there), and this derived
        # pair surfaces the diversity gate at the evidence layer so
        # a reviewer can read it from the JSON bytes alone.
        out["text_policy_coverage"] = sorted(text_policies)
        out["covers_multiple_text_policies"] = (
            len(text_policies) >= EXPECTED_MIN_DISTINCT_TEXT_POLICIES
        )
    return out


# ---------------------------------------------------------------------------
# Evidence-claim refusal helper. Walks the (assembled) evidence JSON
# and returns a list of (path, value) pairs that look like a claim
# that real D-One / MCP / public network / model API / image search /
# Qoder ran AND succeeded. The happy-path emitter must produce an
# evidence JSON for which this helper returns the empty list; the
# self-test's claim-refusal probe builds tampered JSONs covering every
# forbidden combination and asserts the helper flags each one.
# ---------------------------------------------------------------------------


def _is_word_boundary(text_low: str, start: int, end: int) -> bool:
    """True iff the slice ``text_low[start:end]`` is bracketed by
    non-alphanumeric chars (or string boundaries) on both sides — i.e.
    the substring is a standalone word, not buried inside a longer
    token. Without this gate the verb "verified" inside the negation
    "unverified" would falsely register as a positive claim verb."""
    if start > 0 and text_low[start - 1].isalnum():
        return False
    if end < len(text_low) and text_low[end].isalnum():
        return False
    return True


def _verb_is_negated(text_low: str, verb_start: int) -> bool:
    """True iff the ``_NEGATION_WINDOW_CHARS``-char window immediately
    BEFORE ``verb_start`` contains a negation token. A short, local
    window is the whole point: a stray "no" or "not" far away in the
    same string must not be allowed to shield a clean un-negated verb.
    The window is padded with single spaces on both ends so the
    boundary-anchored tokens (`` not ``, `` no ``, `` never ``) match
    at the start/end of the window slice. Underscore- and hyphen-
    separated identifier-style negations (``is_not_called`` /
    ``is-not-called``) are normalized to spaces so the same
    space-padded tokens match against keys exactly as they do against
    prose strings."""
    window_start = max(0, verb_start - _NEGATION_WINDOW_CHARS)
    raw = text_low[window_start:verb_start]
    normalized = raw.replace("_", " ").replace("-", " ")
    window = " " + normalized + " "
    return any(token in window for token in _NEGATION_TOKENS)


def _key_carries_positive_verb(key_low: str) -> bool:
    """True iff the lower-cased ``key_low`` contains a forbidden verb
    at a word boundary AND that verb is not negated by an in-key
    negation token (per ``_verb_is_negated``, which normalises ``_``
    and ``-`` so ``is_not_called`` / ``was-not-reached`` count as
    admissions rather than positive claims)."""
    for verb in _FORBIDDEN_CLAIM_VERBS:
        idx = 0
        while True:
            pos = key_low.find(verb, idx)
            if pos < 0:
                break
            end = pos + len(verb)
            if (_is_word_boundary(key_low, pos, end)
                    and not _verb_is_negated(key_low, pos)):
                return True
            idx = pos + 1
    return False


def _string_asserts_success(
    value: str, *, key_provides_noun: bool = False,
) -> bool:
    """True when ``value`` makes a POSITIVE success claim about a
    real / live / MCP / network / model / image-search / Qoder
    integration. A claim is positive iff:

      * at least one forbidden noun is in scope (either present
        as a substring of ``value`` OR contributed by the enclosing
        dict key when ``key_provides_noun`` is True — e.g. the value
        ``"passed"`` at the key ``"d_one_status"`` is a positive
        claim about D-One even though the value itself names no
        noun), AND
      * at least one forbidden verb appears in ``value`` as a
        standalone word AND is NOT preceded by a negation token in
        the local 15-char window.

    The canonical UNVERIFIED sentence pairs the noun "real d-one"
    with the verb "called" but the verb is preceded by "is NOT "
    inside the local negation window, so each verb instance is
    skipped and the function returns False. A tampered string like
    ``"no telemetry; real D-One verified online"`` does NOT receive
    a free pass: the "no" is far from any verb, so "verified" and
    "online" are individually un-negated and the claim trips."""
    low = value.lower()
    has_noun = key_provides_noun or any(
        noun in low for noun in _FORBIDDEN_CLAIM_NOUNS
    )
    if not has_noun:
        return False
    for verb in _FORBIDDEN_CLAIM_VERBS:
        idx = 0
        while True:
            pos = low.find(verb, idx)
            if pos < 0:
                break
            end = pos + len(verb)
            if (_is_word_boundary(low, pos, end)
                    and not _verb_is_negated(low, pos)):
                return True
            # Advance by 1 (not by len(verb)) so overlapping verb
            # candidates (e.g. ``succeed`` inside ``succeeded``) are
            # each evaluated individually.
            idx = pos + 1
    return False


def _evidence_refuses_real_d_one_claims(
    evidence: dict | list,
) -> list[tuple[str, str]]:
    """Walk ``evidence`` recursively. Return ``(json_path, value)``
    pairs flagging any forbidden claim of real-D-One / MCP / public
    network / model API / image search / Qoder success.

    Two refusal shapes:

      A. ANY string scalar — regardless of where it sits in the tree
         — that asserts success per ``_string_asserts_success``. The
         enclosing dict key (the closest one above any number of
         intervening list indices) contributes a "noun in scope" so a
         verb-only string under a noun-bearing key (e.g. ``{
         "d_one_status": "passed"}``) is still caught.
      B. A boolean ``True`` value at a key that contributes a
         positive claim about a forbidden service WHEN a noun is in
         scope. The current key contributes a positive claim iff it
         names a forbidden noun directly (e.g. ``{"mcp": True}``) OR
         it carries an un-negated forbidden verb at a word boundary
         while a noun is already in scope from an ancestor (e.g.
         ``{"mcp": {"called": True}}``). Identifier-style negations
         in the key (``is_not_called`` / ``was-not-reached``) keep
         their negation thanks to the ``_`` / ``-`` normalisation in
         ``_verb_is_negated``.

    The fixed UNVERIFIED real_d_one_status sentence does NOT trip
    shape A because every verb in that sentence is individually
    preceded by a negation token within the local window."""
    findings: list[tuple[str, str]] = []

    def _walk(
        node, path: str, *, key_provides_noun: bool = False,
    ) -> None:
        if isinstance(node, dict):
            # Noun-in-scope PROPAGATES through dict descendants: once
            # an ancestor key carries a forbidden noun, every value
            # below it inherits "the noun is in scope" until the
            # walk leaves the subtree. Without propagation a shape
            # like ``{"d_one": {"status": "passed"}}`` would slip
            # past because the inner key `status` itself carries no
            # noun — the outer `d_one` was the qualifier.
            for k, v in node.items():
                key_low = str(k).lower()
                sub_path = f"{path}.{k}" if path else str(k)
                child_key_has_noun = any(
                    noun in key_low for noun in _FORBIDDEN_CLAIM_NOUNS
                )
                child_key_has_verb = (
                    _key_carries_positive_verb(key_low)
                )
                effective_provides_noun = (
                    key_provides_noun or child_key_has_noun
                )
                # Shape B (extended). Trip on boolean True whenever a
                # noun is in scope AND the current key contributes
                # either a noun (direct claim, e.g. ``{"mcp": True}``)
                # or an un-negated success verb (nested claim, e.g.
                # ``{"mcp": {"called": True}}``). A bare True under a
                # noun-parent at a key that names neither (e.g.
                # ``{"d_one": {"foo": True}}``) does NOT trip — the
                # gate is a claim detector, not a blanket noun ban.
                if (
                    v is True
                    and effective_provides_noun
                    and (child_key_has_noun or child_key_has_verb)
                ):
                    findings.append((sub_path, "True"))
                _walk(
                    v, sub_path,
                    key_provides_noun=effective_provides_noun,
                )
        elif isinstance(node, list):
            # Lists propagate the enclosing dict key's noun-in-scope
            # flag — every element is "at" the same logical key.
            for i, item in enumerate(node):
                _walk(
                    item, f"{path}[{i}]",
                    key_provides_noun=key_provides_noun,
                )
        elif isinstance(node, str):
            if _string_asserts_success(
                node, key_provides_noun=key_provides_noun,
            ):
                findings.append((path, node))

    _walk(evidence, "")
    return findings


# ---------------------------------------------------------------------------
# Trial runner. Drives the committed bundle through every stage and
# returns the assembled evidence dict + the per-stage tool outcomes.
# ---------------------------------------------------------------------------


def _summary_ok(evidence: dict) -> bool:
    """Single boolean: every observed gate held. Mirrors the per-field
    gating in the canonical happy-path evidence — a False here means
    the JSON dump above already names which gate did not pass."""
    p = evidence["pptx"]
    if not (p["exists"] and p["size_bytes"] > 0):
        return False
    v = evidence["validators"]
    if not v["validate_pptx_contract"]["ok"]:
        return False
    if not v["inspect_pptx_inventory"]["ok"]:
        return False
    sv = v["validate_mock_d_one_adapter_plan"]
    if not sv["ok"]:
        return False
    if not sv["vocabulary_gate_used"]:
        return False
    if not sv["require_both_placement_roles_used"]:
        return False
    inv = evidence["inventory"]
    if not (inv["exists"] and inv["parses_as_json"] and inv["ok"] is True):
        return False
    if not (
        inv["findings_empty"]
        and inv["slide_count_matches_plan"]
        and inv["media_parts_count_min_met"]
        and inv["evidence_basis_matches"]
        and inv["no_external_relationships"]
    ):
        return False
    sc = evidence["sidecar"]
    if not (sc["exists"] and sc["parses_as_json"]):
        return False
    if not sc["schema_version_locked"]:
        return False
    if not sc["request_count_matches_requests"]:
        return False
    if not sc["covers_both_placement_roles"]:
        return False
    # Goal-pinned mixed per-request text_policy coverage. A sidecar in
    # which every request's text_policy collapsed to the same value is
    # refused — the committed bundle must exercise per-request
    # text_policy judgement end-to-end, not only through the adapter-
    # only smoke. The downstream validator's G10 gate re-asserts this
    # from a clean process boundary against the emitted JSON.
    if not sc["covers_multiple_text_policies"]:
        return False
    # Goal-required per-request coverage. The sidecar schema treats
    # taxonomy fields as optional, so a schema-valid sidecar can
    # still drop a goal-required field — without this gate the
    # emitter would happily report ``summary.ok=True`` while
    # documenting ``"text_policy": null`` (or similar) on the per-
    # request records.
    if not sc["all_requests_well_formed"]:
        return False
    # Final self-honesty gate: the assembled evidence must not contain
    # any forbidden real-D-One / MCP / network / model / image-search /
    # Qoder success claim. The canonical emitter never writes any; a
    # downstream mutation that injected one would surface here.
    if _evidence_refuses_real_d_one_claims(evidence):
        return False
    return True


@dataclass
class _TrialResult:
    evidence: dict
    runner: ToolOutcome
    contract: ToolOutcome | None
    inspect: ToolOutcome | None
    sidecar_validator: ToolOutcome | None


def _run_trial(
    td: Path, *, bundle: Path,
) -> _TrialResult:
    """Drive the committed bundle through the runner + validator chain
    inside ``td`` and gather the evidence. Returns the assembled
    evidence dict and the per-stage tool outcomes so the caller can
    print pass/fail tails on failure."""
    workspace = td / "trial_ws"
    output = td / "trial.pptx"
    report_dir = td / "trial_report"

    print("--- mock chain: committed bundle via run_mock_image_pipeline ---")
    print(f"  bundle:    {bundle}")
    print(f"  workspace: {workspace}")
    print(f"  output:    {output}")
    print(f"  report:    {report_dir}")
    print()

    runner = _run_runner(
        bundle=bundle, workspace=workspace, output=output,
        report_dir=report_dir,
    )
    _print_outcome(runner)

    contract: ToolOutcome | None = None
    inspect: ToolOutcome | None = None
    if runner.ok and output.is_file() and not output.is_symlink():
        contract = _run_contract_validator(
            pptx=output, expected_slide_count=EXPECTED_SLIDE_COUNT,
        )
        _print_outcome(contract)
        inspect = _run_inventory_inspector(pptx=output)
        _print_outcome(inspect)

    sidecar_path = report_dir / EVIDENCE_SIDECAR_FILENAME
    sidecar_validator: ToolOutcome | None = None
    # Only invoke the sidecar validator when the sidecar exists. A
    # missing sidecar is itself a fail-closed signal (the runner did
    # not get far enough to write it); collect_sidecar_evidence will
    # carry exists=False into the evidence JSON and the summary gate
    # will flip false. The probe test exercises this exact branch.
    if sidecar_path.is_file() and not sidecar_path.is_symlink():
        sidecar_validator = _run_sidecar_validator(
            sidecar_path=sidecar_path, bundle=bundle,
        )
        _print_outcome(sidecar_validator)

    evidence: dict = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_id": "mock_image_bundle_trial_evidence",
        "real_d_one_status": REAL_D_ONE_STATUS,
        "pptx": _collect_pptx_evidence(output),
        "validators": {
            "validate_pptx_contract": {
                "rc": contract.rc if contract else None,
                "ok": contract.ok if contract else False,
            },
            "inspect_pptx_inventory": {
                "rc": inspect.rc if inspect else None,
                "ok": inspect.ok if inspect else False,
            },
            "validate_mock_d_one_adapter_plan": {
                "rc": sidecar_validator.rc if sidecar_validator else None,
                "ok": sidecar_validator.ok if sidecar_validator else False,
                # Proof the goal-required gates fired against the
                # runner-written sidecar: the vocabulary path and the
                # placement-role flag are both on the validator CLI.
                # Both are True only when the validator was invoked
                # at all AND the cmd carried both flags.
                "vocabulary_gate_used": bool(
                    sidecar_validator
                    and "--descriptor-vocabulary" in sidecar_validator.cmd
                ),
                "require_both_placement_roles_used": bool(
                    sidecar_validator
                    and "--require-both-placement-roles"
                    in sidecar_validator.cmd
                ),
            },
        },
        "inventory": _collect_inventory_evidence(
            report_dir / "inventory.json",
            expected_slide_count=EXPECTED_SLIDE_COUNT,
        ),
        "sidecar": _collect_sidecar_evidence(sidecar_path),
        "bundle_path": str(bundle),
        "report_dir": str(report_dir),
        "notes": {
            "scope": (
                "Mock-image bundle trial evidence only. Drives the "
                "COMMITTED examples/synthetic_mock_image_trial bundle "
                "through run_mock_image_pipeline.py --bundle into a "
                "tempfile-owned workspace/output/report directory and "
                "records the produced PPTX + inventory + sidecar. NOT "
                "real D-One, NOT MCP, NOT Qoder, NOT a public-network "
                "run, NOT telemetry, NOT a prompt/report-to-PPTX "
                "automation."
            ),
            "embed_surface": (
                "PNG/JPG/JPEG inside ppt/media/* — the subset "
                "scripts/export_pptx.py supports today. Anything "
                "outside that subset is fail-closed by the exporter."
            ),
        },
    }
    evidence["summary"] = {"ok": _summary_ok(evidence)}
    return _TrialResult(
        evidence=evidence, runner=runner, contract=contract,
        inspect=inspect, sidecar_validator=sidecar_validator,
    )


# ---------------------------------------------------------------------------
# Negative probes (self-test only). Each probe asserts the documented
# failure mode actually trips a non-zero exit / surfaces the regression
# at the documented layer. The probes never call real D-One / MCP / a
# public network / a model API / image search / Qoder / telemetry.
# ---------------------------------------------------------------------------


@dataclass
class _NegativeOutcome:
    name: str
    ok: bool
    detail: str = ""


def _copy_committed_bundle(dest: Path) -> None:
    """Materialize a non-symlinked copy of the committed bundle under
    ``dest``. ``symlinks=False`` mirrors the smoke's helper — no
    committed bundle entry is a symlink today, but the explicit flag
    makes the copy posture intentional."""
    shutil.copytree(COMMITTED_BUNDLE, dest, symlinks=False)


def _probe_missing_bundle(td: Path) -> _NegativeOutcome:
    """Run the trial against a bundle directory that does not exist.
    The runner's bundle-resolver aborts at the boundary, no sidecar is
    written, no PPTX is produced, and the assembled evidence's
    summary.ok flips False."""
    bundle = td / "missing_bundle_dir"
    probe_td = td / "missing_bundle_run"
    probe_td.mkdir()
    result = _run_trial(probe_td, bundle=bundle)
    runner_aborted = not result.runner.ok
    no_pptx = not (probe_td / "trial.pptx").exists()
    no_sidecar = not (
        probe_td / "trial_report" / EVIDENCE_SIDECAR_FILENAME
    ).exists()
    summary_false = result.evidence["summary"]["ok"] is False
    ok = runner_aborted and no_pptx and no_sidecar and summary_false
    detail = ""
    if not ok:
        detail = (
            f"runner_aborted={runner_aborted}, no_pptx={no_pptx}, "
            f"no_sidecar={no_sidecar}, summary_false={summary_false}, "
            f"runner.rc={result.runner.rc}"
        )
    return _NegativeOutcome(
        "missing bundle: trial aborts at the runner boundary; no PPTX, "
        "no sidecar, summary.ok=False",
        ok, detail,
    )


def _probe_forced_downstream_failure(td: Path) -> _NegativeOutcome:
    """Copy the committed bundle, corrupt ``image_manifest_spec.json``
    (URI-scheme local_path), and assert the runner's downstream chain
    aborts BEFORE the audit sidecar is written. The trial's evidence
    must therefore carry sidecar.exists=False AND summary.ok=False —
    the emitter cannot claim success when there is no sidecar to
    re-validate.

    This is the goal's 'missing sidecar after a forced downstream
    failure' probe."""
    bundle = td / "forced_fail_bundle"
    _copy_committed_bundle(bundle)
    manifest_path = bundle / "image_manifest_spec.json"
    body = json.loads(manifest_path.read_text())
    body["images"][0]["local_path"] = "http://attacker/x.png"
    manifest_path.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n",
    )

    probe_td = td / "forced_fail_run"
    probe_td.mkdir()
    result = _run_trial(probe_td, bundle=bundle)
    runner_aborted = not result.runner.ok
    no_sidecar = not (
        probe_td / "trial_report" / EVIDENCE_SIDECAR_FILENAME
    ).exists()
    sidecar_recorded_missing = (
        result.evidence["sidecar"]["exists"] is False
    )
    summary_false = result.evidence["summary"]["ok"] is False
    ok = (
        runner_aborted and no_sidecar
        and sidecar_recorded_missing and summary_false
    )
    detail = ""
    if not ok:
        detail = (
            f"runner_aborted={runner_aborted}, no_sidecar={no_sidecar}, "
            f"sidecar_recorded_missing={sidecar_recorded_missing}, "
            f"summary_false={summary_false}, runner.rc={result.runner.rc}"
        )
    return _NegativeOutcome(
        "forced downstream failure (URI-scheme local_path): runner "
        "aborts before sidecar is written; evidence records "
        "sidecar.exists=False and summary.ok=False",
        ok, detail,
    )


def _probe_bad_descriptor_vocabulary(td: Path) -> _NegativeOutcome:
    """Copy the committed bundle, strip the ``text_policy``
    allowed-values block from ``descriptor_vocabulary.json``, and
    re-run the trial. The runner forwards the vocabulary to
    done_image_adapter (which would itself refuse the perturbed vocab
    before writing the staging plan), so the runner aborts and no
    sidecar lands — but the trial's contract is that an evidence JSON
    cannot claim success when the vocabulary gate failed anywhere in
    the chain. Assert summary.ok=False and the validate_mock_d_one_
    adapter_plan validators.ok stays False."""
    bundle = td / "bad_vocab_bundle"
    _copy_committed_bundle(bundle)
    vocab_path = bundle / "descriptor_vocabulary.json"
    body = json.loads(vocab_path.read_text())
    # Remove the text_policy allowed-values block; the spec carries
    # text_policy=no_text, which becomes an out-of-vocab value as soon
    # as the allow-list is missing.
    if (isinstance(body.get("image_taxonomy"), dict)
            and "text_policy" in body["image_taxonomy"]):
        del body["image_taxonomy"]["text_policy"]
    vocab_path.write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n",
    )

    probe_td = td / "bad_vocab_run"
    probe_td.mkdir()
    result = _run_trial(probe_td, bundle=bundle)
    runner_aborted = not result.runner.ok
    sidecar_ok = result.evidence["validators"][
        "validate_mock_d_one_adapter_plan"
    ]["ok"]
    summary_false = result.evidence["summary"]["ok"] is False
    # On a bad-vocab run, the runner aborts before writing the
    # sidecar; the sidecar validator therefore never runs and its
    # `ok` stays False. Both shapes are valid refusals — the gate is
    # that summary.ok flips False AND the sidecar validator did not
    # spuriously pass.
    ok = runner_aborted and (sidecar_ok is False) and summary_false
    detail = ""
    if not ok:
        detail = (
            f"runner_aborted={runner_aborted}, "
            f"sidecar_validator_ok={sidecar_ok}, "
            f"summary_false={summary_false}, runner.rc={result.runner.rc}"
        )
    return _NegativeOutcome(
        "bad descriptor vocabulary (text_policy allowed-values block "
        "stripped): chain refuses; sidecar validator does not "
        "spuriously pass; summary.ok=False",
        ok, detail,
    )


def _probe_evidence_refuses_real_d_one_claims() -> _NegativeOutcome:
    """Direct probe on the static ``_evidence_refuses_real_d_one_
    claims`` helper. Build tampered evidence JSONs covering every
    forbidden shape AND every Codex-flagged false-negative class
    (positive claim at non-status key, claim inside list element,
    claim under a noun-bearing key with verb-only value, distant
    negation that must NOT shield a clean un-negated verb) and assert
    the helper flags each one. Also confirms the canonical happy-path
    evidence stub (with the fixed UNVERIFIED sentence AND the fixed
    ``notes.scope`` / ``notes.embed_surface`` framing the emitter
    actually writes) does NOT trip the helper.

    This is the goal's 'any evidence JSON that tries to claim real
    D-One / MCP / network / model / image-search / Qoder success'
    probe. Direct (no subprocess) because the surface under test is
    this script's own helper, not a downstream runtime gate."""
    failures: list[str] = []

    # 1. Canonical clean JSON: the UNVERIFIED sentence AT a noun-
    # bearing key AND the full ``notes`` framing the emitter writes
    # must all stay clean. If any of these tripped, the happy-path
    # emitter would fail its own self-honesty gate.
    clean = {
        "real_d_one_status": REAL_D_ONE_STATUS,
        "notes": {
            "scope": (
                "Mock-image bundle trial evidence only. NOT real "
                "D-One, NOT MCP, NOT Qoder, NOT a public-network "
                "run, NOT telemetry, NOT a prompt/report-to-PPTX "
                "automation."
            ),
            "embed_surface": (
                "PNG/JPG/JPEG inside ppt/media/* — the subset "
                "scripts/export_pptx.py supports today."
            ),
        },
        "validators": {"validate_pptx_contract": {"ok": True}},
        "sidecar": {
            "covers_both_placement_roles": True,
            "placement_role_coverage": ["hero_page", "local_region"],
        },
        "summary": {"ok": True},
    }
    clean_findings = _evidence_refuses_real_d_one_claims(clean)
    if clean_findings:
        failures.append(
            f"clean evidence stub falsely tripped the gate: "
            f"{clean_findings!r}"
        )

    # 2. Status-bearing key with a real-D-One success claim (verb +
    # noun). Must trip.
    tampered_a = {
        "real_d_one_status": (
            "Real D-One verified online: production run succeeded."
        ),
    }
    if not _evidence_refuses_real_d_one_claims(tampered_a):
        failures.append(
            "tampered_a (real D-One verified success claim) did not "
            "trip the gate"
        )

    # 3. Boolean True at a key naming a forbidden noun. Must trip on
    # every variant.
    for key in (
        "mcp", "qoder", "public_network", "image_search", "model_api",
        "real_d_one",
    ):
        if not _evidence_refuses_real_d_one_claims({key: True}):
            failures.append(
                f"boolean tampered (key={key!r}: True) did not trip"
            )

    # 4. Deeply nested status claim. Must trip even when buried under
    # an arbitrary number of dicts + lists.
    tampered_nested = {
        "results": [
            {"validators": {"mcp_status": (
                "live MCP enabled: called the model API and "
                "received bytes"
            )}},
        ],
    }
    if not _evidence_refuses_real_d_one_claims(tampered_nested):
        failures.append(
            "nested status claim (mcp_status with live+called verbs) "
            "did not trip the gate"
        )

    # 5. Codex-flagged false negative: positive claim at a NON-status
    # key (the previous gate only inspected a fixed set of status-
    # bearing keys; a claim under ``notes.detail`` or any other key
    # slipped past).
    tampered_non_status = {
        "notes": {"detail": (
            "Real D-One verified online: production run succeeded."
        )},
    }
    if not _evidence_refuses_real_d_one_claims(tampered_non_status):
        failures.append(
            "positive claim at non-status key did not trip the gate"
        )

    # 6. Codex-flagged false negative: positive claim INSIDE a list
    # element (the previous walker recursed into lists but never
    # scanned string scalars sitting at list indices).
    tampered_list = {
        "messages": ["Real D-One verified online."],
    }
    if not _evidence_refuses_real_d_one_claims(tampered_list):
        failures.append(
            "positive claim inside a list element did not trip the gate"
        )

    # 7. Codex-flagged false negative: a distant single negation
    # token elsewhere in the string must NOT shield a clean
    # un-negated verb later in the same string. The previous gate
    # scanned for any negation token anywhere in the value and short-
    # circuited, so ``"no telemetry; real D-One verified online"``
    # passed silently.
    tampered_distant_negation = {
        "summary": {"text": (
            "no telemetry; real D-One verified online."
        )},
    }
    if not _evidence_refuses_real_d_one_claims(
        tampered_distant_negation
    ):
        failures.append(
            "distant negation should not shield a clean un-negated "
            "verb later in the same string"
        )

    # 8. Codex-flagged false negative: a verb-only string at a key
    # whose NAME carries the forbidden noun. ``{"d_one_status":
    # "passed"}`` is a positive D-One claim even though the value
    # alone names no noun. The walker contributes ``key_provides_
    # noun`` so the helper sees both halves of the claim.
    tampered_verb_only_value = {
        "real_d_one_status_flag": "passed",
        "mcp_status_flag": "enabled",
        "qoder_flag": "online",
    }
    if not _evidence_refuses_real_d_one_claims(
        tampered_verb_only_value
    ):
        failures.append(
            "verb-only value at noun-bearing key did not trip the gate"
        )

    # 8a. Second Codex-flagged false negative: BARE ``d_one`` /
    # ``d-one`` keys (no ``real_`` / ``live_`` / ``production_``
    # qualifier prefix) carry the D-One claim too. Without ``d_one``
    # / ``d-one`` in the noun list these slipped through entirely —
    # the previous gate only matched the fully-qualified noun forms.
    tampered_bare_d_one_keys = {
        "d_one_status": "passed",
        "d-one_result": "succeeded",
        "d_one_runtime": "online",
    }
    if not _evidence_refuses_real_d_one_claims(
        tampered_bare_d_one_keys
    ):
        failures.append(
            "verb-only value at bare d_one/d-one key did not trip "
            "the gate"
        )

    # 8b. Same false negative, boolean shape (shape B). Bare d_one
    # keys must trip when set to True.
    for key in ("d_one", "d-one", "d_one_called", "d-one_enabled"):
        if not _evidence_refuses_real_d_one_claims({key: True}):
            failures.append(
                f"boolean tampered (key={key!r}: True) did not trip"
            )

    # 8c. Dict-descendant propagation: when a noun-bearing parent
    # key wraps a nested dict whose inner keys carry no noun of
    # their own, the inner string values must still be checked
    # against the propagated noun-in-scope. Without descendant
    # propagation a shape like ``{"d_one": {"status": "passed"}}``
    # slipped past because the inner key ``status`` carried no
    # noun directly.
    tampered_propagated = {
        "d_one": {"validator_status": "passed"},
    }
    if not _evidence_refuses_real_d_one_claims(tampered_propagated):
        failures.append(
            "verb-only value under noun-bearing parent dict did "
            "not trip (descendant propagation regression)"
        )

    # 8d. Deeper propagation: three levels under a noun-bearing
    # ancestor must still trip.
    tampered_deeply_propagated = {
        "mcp": {"sub": {"deeper": {"result": "succeeded"}}},
    }
    if not _evidence_refuses_real_d_one_claims(
        tampered_deeply_propagated
    ):
        failures.append(
            "verb-only value three levels under noun-bearing "
            "ancestor did not trip"
        )

    # 8e. Codex-flagged false negative: boolean True at a verb-key
    # under a noun-bearing parent. Without the shape-B extension,
    # ``{"mcp": {"called": True}}`` slipped past entirely — the
    # previous shape B only checked the IMMEDIATE key for a noun,
    # missing the "noun in scope from ancestor + verb in current
    # key + value True" composition. Every per-service variant
    # must trip.
    tampered_nested_booleans = {
        "mcp": {"called": True},
        "d_one": {"verified": True},
        "qoder": {"enabled": True},
        "public_network": {"online": True},
        "image_search": {"succeeded": True},
        "model_api": {"reached": True},
    }
    if not _evidence_refuses_real_d_one_claims(
        tampered_nested_booleans
    ):
        failures.append(
            "boolean True at verb-key under noun-bearing parent did "
            "not trip the gate"
        )

    # 8f. Deeper nested boolean (three levels under noun-bearing
    # ancestor).
    tampered_deep_boolean = {
        "d_one": {"sub": {"deeper": {"verified": True}}},
    }
    if not _evidence_refuses_real_d_one_claims(tampered_deep_boolean):
        failures.append(
            "boolean True at verb-key three levels under noun-"
            "bearing ancestor did not trip"
        )

    # 8g. Negated verb-key under noun-bearing parent must NOT trip
    # (an admission of non-call is the OPPOSITE of an attack). The
    # ``_`` / ``-`` normalisation in ``_verb_is_negated`` is what
    # makes the in-key negation visible.
    clean_negated_verb_key = {
        "mcp": {
            "is_not_called": True,
            "was_not_reached": True,
            "is-not-enabled": True,
        },
    }
    if _evidence_refuses_real_d_one_claims(clean_negated_verb_key):
        failures.append(
            "negated verb-key under noun-bearing parent falsely "
            "tripped (these are admissions, not claims)"
        )

    # 8h. Bare True at a non-noun-non-verb key under a noun-bearing
    # parent must NOT trip (the gate is a CLAIM detector, not a
    # blanket noun ban — the canonical
    # ``validate_mock_d_one_adapter_plan.ok=True`` and
    # ``validate_mock_d_one_adapter_plan.vocabulary_gate_used=True``
    # are honest local-validator outcomes, not D-One success claims).
    clean_inner_boolean = {
        "mcp": {"foo": True, "bar": True},
        "d_one": {"validator_metadata": {"recorded_at": True}},
    }
    if _evidence_refuses_real_d_one_claims(clean_inner_boolean):
        failures.append(
            "bare True at non-noun-non-verb key under noun-bearing "
            "parent falsely tripped"
        )

    # 9. Qoder runtime success claim. Must trip even though Qoder is
    # not D-One — the goal lists Qoder among the forbidden services.
    tampered_qoder = {
        "qoder_status": (
            "Qoder runtime online: production call succeeded."
        ),
    }
    if not _evidence_refuses_real_d_one_claims(tampered_qoder):
        failures.append(
            "Qoder runtime success claim did not trip the gate"
        )

    # 10. Sanity: bare noun without any verb must NOT trip (the gate
    # is a CLAIM detector, not a noun ban — the canonical emitter
    # legitimately names "real D-One" inside the UNVERIFIED sentence
    # and inside ``notes.scope`` framing).
    clean_noun_only = {
        "notes": {"scope": "NOT real D-One, NOT MCP, NOT Qoder."},
    }
    if _evidence_refuses_real_d_one_claims(clean_noun_only):
        failures.append(
            "bare noun without any positive verb falsely tripped"
        )

    # 11. Sanity: verb-only value at a NON-noun-bearing key must NOT
    # trip (e.g. an aggregator that reports ``"status": "passed"`` on
    # a non-integration check is not a forbidden claim).
    clean_verb_only = {
        "validators": {"validate_pptx_contract": {"status": "passed"}},
    }
    if _evidence_refuses_real_d_one_claims(clean_verb_only):
        failures.append(
            "verb-only value at non-noun key falsely tripped"
        )

    return _NegativeOutcome(
        "static helper: refuses every tampered evidence JSON that "
        "claims real D-One / MCP / public network / model API / image "
        "search / Qoder success across every shape (status-bearing "
        "keys, non-status keys, list elements, boolean-True at noun "
        "keys, deeply nested, verb-only value at noun-bearing key, "
        "AND distant-negation-shielded shapes); canonical UNVERIFIED "
        "sentence + notes framing stays clean; bare nouns and verb-"
        "only values at non-noun keys also stay clean",
        not failures,
        "; ".join(failures) if failures else "",
    )


def _probe_summary_refuses_malformed_request_evidence(
    td: Path,
) -> _NegativeOutcome:
    """Direct probe on ``_collect_sidecar_evidence`` + ``_summary_ok``:
    a sidecar whose any request drops or corrupts a goal-required
    field (``id`` / ``placement_role`` / ``text_policy`` /
    ``subject_domain`` / ``manifest_local_path``) — or carries a
    non-dict request, or carries an empty requests list — must flip
    ``summary.ok`` to False EVEN WHEN every other gate (validator,
    inventory, PPTX, placement-role coverage) would otherwise be
    green.

    Without ``all_requests_well_formed`` the emitter would happily
    report ``summary.ok=True`` for a sidecar that, say, omits
    ``text_policy`` on one request — the per-request record would
    land in the emitted JSON as ``{"text_policy": null, ...}``
    while the summary still claimed everything was fine. The fix
    re-asserts the goal-required per-request coverage here so the
    summary cannot false-green that shape."""
    failures: list[str] = []

    def _build_evidence(sidecar_doc: dict, tag: str) -> dict:
        sidecar_path = td / f"sidecar_{tag}.json"
        sidecar_path.write_text(json.dumps(sidecar_doc) + "\n")
        sc = _collect_sidecar_evidence(sidecar_path)
        return {
            "real_d_one_status": REAL_D_ONE_STATUS,
            "pptx": {
                "exists": True, "size_bytes": 100, "path": "n/a",
            },
            "validators": {
                "validate_pptx_contract": {"ok": True, "rc": 0},
                "inspect_pptx_inventory": {"ok": True, "rc": 0},
                "validate_mock_d_one_adapter_plan": {
                    "ok": True, "rc": 0,
                    "vocabulary_gate_used": True,
                    "require_both_placement_roles_used": True,
                },
            },
            "inventory": {
                "exists": True, "parses_as_json": True, "ok": True,
                "findings_empty": True,
                "slide_count_matches_plan": True,
                "media_parts_count_min_met": True,
                "evidence_basis_matches": True,
                "no_external_relationships": True,
            },
            "sidecar": sc,
            "notes": {
                "scope": "synthetic probe",
                "embed_surface": "synthetic probe",
            },
        }

    good_sidecar = {
        "schema_version": 4,
        "request_count": 2,
        "requests": [
            {
                "id": "cover_accent", "placement_role": "hero_page",
                "text_policy": "no_text",
                "subject_domain": "abstract_geometry",
                "manifest_local_path": "media/cover_accent.png",
            },
            {
                "id": "system_schematic",
                "placement_role": "local_region",
                "text_policy": "caption_safe",
                "subject_domain": "process_motif",
                "manifest_local_path": "media/system_schematic.png",
            },
        ],
    }

    # Baseline: well-formed sidecar with every other gate green
    # must produce summary.ok=True and all_requests_well_formed=True.
    ev = _build_evidence(good_sidecar, "good")
    if not _summary_ok(ev):
        failures.append(
            "well-formed sidecar should produce summary.ok=True"
        )
    if not ev["sidecar"]["all_requests_well_formed"]:
        failures.append(
            "well-formed sidecar should set "
            "all_requests_well_formed=True"
        )
    if not ev["sidecar"]["covers_multiple_text_policies"]:
        failures.append(
            "well-formed sidecar with 2 distinct text_policy values "
            "should set covers_multiple_text_policies=True"
        )

    def _mutate(mutator, tag) -> dict:
        # Deep-copy via JSON so each probe variant gets its own
        # mutation without aliasing back into ``good_sidecar``.
        copy = json.loads(json.dumps(good_sidecar))
        mutator(copy)
        return _build_evidence(copy, tag)

    # Collapsed text_policy: every request carries the same value.
    # summary.ok MUST flip False, covers_multiple_text_policies MUST
    # be False, and text_policy_coverage MUST contain exactly one
    # entry. This is the diversity gate at the evidence layer.
    def _collapse_text_policy(doc):
        for req in doc["requests"]:
            req["text_policy"] = "no_text"
    ev = _mutate(_collapse_text_policy, "collapsed_text_policy")
    if _summary_ok(ev):
        failures.append(
            "sidecar with text_policy collapsed to a single value "
            "should NOT produce summary.ok=True (diversity gate)"
        )
    if ev["sidecar"]["covers_multiple_text_policies"] is not False:
        failures.append(
            "sidecar with text_policy collapsed should set "
            "covers_multiple_text_policies=False"
        )
    if ev["sidecar"]["text_policy_coverage"] != ["no_text"]:
        failures.append(
            f"sidecar with text_policy collapsed should set "
            f"text_policy_coverage=['no_text'] (got "
            f"{ev['sidecar']['text_policy_coverage']!r})"
        )

    # Missing required field on one request — every variant must
    # flip summary.ok to False.
    for field in _REQUIRED_REQUEST_FIELDS:
        def _drop(doc, *, f=field):
            del doc["requests"][0][f]
        ev = _mutate(_drop, f"missing_{field}")
        if _summary_ok(ev):
            failures.append(
                f"sidecar missing {field} on request[0] should NOT "
                f"produce summary.ok=True"
            )
        if 0 not in ev["sidecar"]["malformed_request_indices"]:
            failures.append(
                f"sidecar missing {field} on request[0] should "
                f"include 0 in malformed_request_indices"
            )

    # Wrong type (integer where string expected).
    def _wrong_type(doc):
        doc["requests"][0]["text_policy"] = 42
    ev = _mutate(_wrong_type, "wrong_type")
    if _summary_ok(ev):
        failures.append(
            "sidecar with non-string text_policy should NOT produce "
            "summary.ok=True"
        )

    # Empty string value.
    def _empty_string(doc):
        doc["requests"][0]["subject_domain"] = ""
    ev = _mutate(_empty_string, "empty_string")
    if _summary_ok(ev):
        failures.append(
            "sidecar with empty subject_domain should NOT produce "
            "summary.ok=True"
        )

    # Non-dict request entry (a string slipped into the requests
    # list — the previous emitter silently skipped these so the
    # record list ended up shorter than the raw requests list).
    def _non_dict(doc):
        doc["requests"][0] = "not a dict"
    ev = _mutate(_non_dict, "non_dict")
    if _summary_ok(ev):
        failures.append(
            "sidecar with a non-dict request should NOT produce "
            "summary.ok=True"
        )
    if 0 not in ev["sidecar"]["malformed_request_indices"]:
        failures.append(
            "sidecar with a non-dict request should include 0 in "
            "malformed_request_indices"
        )

    # Empty requests list — schema-wise this would be unusual but
    # the goal contract requires per-request records, so an empty
    # records list is a vacuous green the summary must refuse.
    empty_requests = {
        "schema_version": 4, "request_count": 0, "requests": [],
    }
    ev = _build_evidence(empty_requests, "empty_requests")
    if _summary_ok(ev):
        failures.append(
            "sidecar with empty requests list should NOT produce "
            "summary.ok=True"
        )

    return _NegativeOutcome(
        "static helpers: summary.ok flips False for any sidecar with "
        "a malformed request (missing/non-string/empty goal-required "
        "field, non-dict request entry, or empty requests list) OR "
        "per-request text_policy collapsed to a single value across "
        "every request (covers_multiple_text_policies=False, "
        "text_policy_coverage=['no_text']); the well-formed baseline "
        "with two distinct text_policy values still produces "
        "summary.ok=True so the gate is not a blanket fail",
        not failures,
        "; ".join(failures) if failures else "",
    )


_NEGATIVE_PROBES = (
    _probe_missing_bundle,
    _probe_forced_downstream_failure,
    _probe_bad_descriptor_vocabulary,
    _probe_summary_refuses_malformed_request_evidence,
    # Probe 5 is a direct helper call — no tempdir needed.
)


# ---------------------------------------------------------------------------
# CLI / self-test entry point.
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    print("=== mock-image bundle trial evidence ===")
    print(
        "  MOCK / local only — NOT real D-One, NOT MCP, NOT Qoder, "
        "NOT public network, NOT model API, NOT image search, NOT "
        "telemetry."
    )

    # Pre-flight: the committed bundle must exist as a real directory.
    # A missing fixture is the user's checkout problem, not a runtime
    # bug; surface a clean diagnostic instead of a noisy subprocess
    # error.
    if COMMITTED_BUNDLE.is_symlink():
        print(
            f"FAIL: committed bundle {COMMITTED_BUNDLE} is a symlink "
            f"(refused).",
            file=sys.stderr,
        )
        return 1
    if not COMMITTED_BUNDLE.is_dir():
        print(
            f"FAIL: committed bundle {COMMITTED_BUNDLE} does not exist.",
            file=sys.stderr,
        )
        return 1

    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    scripts_before = _snapshot_dir(REPO_ROOT / "scripts")

    total_fails = 0
    with tempfile.TemporaryDirectory(
        prefix="szh_mock_image_bundle_trial_evidence_",
    ) as raw_td:
        td = Path(raw_td)
        print(f"  tempdir: {td}")
        print()

        # 1. Happy path: drive the committed bundle through the runner
        # + every validator and emit the evidence JSON.
        happy_td = td / "happy"
        happy_td.mkdir()
        result = _run_trial(happy_td, bundle=COMMITTED_BUNDLE)

        evidence_path = happy_td / EVIDENCE_FILENAME
        evidence_path.write_text(
            json.dumps(result.evidence, indent=2, sort_keys=True) + "\n",
        )

        print()
        print("--- evidence JSON ---")
        print(f"  written: {evidence_path}")
        print(f"  bytes:   {evidence_path.stat().st_size}")
        print()
        print("--- evidence JSON contents ---")
        print(evidence_path.read_text())
        print()

        if not result.evidence["summary"]["ok"]:
            print(
                "FAIL: happy-path evidence summary.ok is False; see the "
                "JSON dump above for the failing fields.",
                file=sys.stderr,
            )
            total_fails += 1

        # 1b. Re-validate the just-written evidence file from a clean
        # process boundary using the standalone schema + semantic +
        # string-safety + real-D-One claim-refusal validator. The
        # validator does NOT import this emitter (no circular fields
        # added to the evidence JSON) so this catches a bug where the
        # in-script summary gate is green but the emitted bytes are
        # internally inconsistent or carry a forbidden shape. The
        # --require-files flag additionally re-checks that the
        # evidence / PPTX / inventory / sidecar paths are regular
        # non-symlink files sharing a common ancestor strictly under
        # the system tempdir (so a future emitter regression that
        # leaks an artifact out of the per-run tempdir is also caught
        # here). The validator runs entirely under the per-run
        # tempdir; the tempdir cleanup at the end of this `with` block
        # removes both the evidence file and the validator's
        # subprocess working state.
        validator_outcome = _run_tool(
            "validate_mock_image_bundle_trial_evidence "
            "(--evidence <happy>/evidence.json --require-files)",
            [
                sys.executable,
                str(
                    SCRIPTS_DIR
                    / "validate_mock_image_bundle_trial_evidence.py"
                ),
                "--evidence", str(evidence_path),
                "--require-files",
            ],
        )
        _print_outcome(validator_outcome)
        if not validator_outcome.ok:
            total_fails += 1

        # 2. Negative probes (subprocess-based).
        print("--- negative probes ---")
        for probe in _NEGATIVE_PROBES:
            probe_td = td / probe.__name__
            probe_td.mkdir()
            outcome = probe(probe_td)
            mark = "PASS" if outcome.ok else "FAIL"
            suffix = (
                f" -- {outcome.detail}"
                if not outcome.ok and outcome.detail else ""
            )
            print(f"  [{mark}] {outcome.name}{suffix}")
            if not outcome.ok:
                total_fails += 1

        # 3. Static helper probe (no subprocess).
        helper_outcome = _probe_evidence_refuses_real_d_one_claims()
        mark = "PASS" if helper_outcome.ok else "FAIL"
        suffix = (
            f" -- {helper_outcome.detail}"
            if not helper_outcome.ok and helper_outcome.detail else ""
        )
        print(f"  [{mark}] {helper_outcome.name}{suffix}")
        if not helper_outcome.ok:
            total_fails += 1
        print()

    # 4. Repo-immutability gate. Runs after the tempdir is cleaned so
    # any artifact the emitter forgot to redirect inside the tempdir
    # would have been forced outside; the diff catches it here.
    examples_after = _snapshot_dir(REPO_ROOT / "examples")
    scripts_after = _snapshot_dir(REPO_ROOT / "scripts")
    examples_diff = _diff_keys(examples_before, examples_after)
    scripts_diff = _diff_keys(scripts_before, scripts_after)
    if examples_diff:
        print(
            f"FAIL: REPO_ROOT/examples mutated by the emitter "
            f"(changed: {examples_diff!r})",
            file=sys.stderr,
        )
        total_fails += 1
    if scripts_diff:
        print(
            f"FAIL: REPO_ROOT/scripts mutated by the emitter "
            f"(changed: {scripts_diff!r})",
            file=sys.stderr,
        )
        total_fails += 1

    if total_fails:
        print(
            f"\nFAIL: {total_fails} mock-image bundle trial evidence "
            f"check(s) did not pass.",
            file=sys.stderr,
        )
        return 1
    print(
        "OK (mock-image bundle trial evidence): the committed "
        "examples/synthetic_mock_image_trial bundle drives "
        "run_mock_image_pipeline.py --bundle to a validated 2-slide "
        "editable PPTX; validate_pptx_contract.py (with "
        "--expected-slide-count 2) passes; inspect_pptx_inventory.py "
        "passes; validate_mock_d_one_adapter_plan.py (with "
        "--require-both-placement-roles AND --descriptor-vocabulary "
        "<bundle/descriptor_vocabulary.json>) passes against the "
        "runner-written sidecar; the emitted evidence JSON carries "
        "summary.ok=True, the fixed UNVERIFIED real_d_one_status "
        "sentence, every required pptx / inventory / validator / "
        "sidecar field including one record per generated request "
        "with id / placement_role / text_policy / subject_domain / "
        "manifest_local_path (plus optional custom_descriptor when "
        "the request carries it), BOTH hero_page AND local_region "
        "placement_role coverage, AND at least two distinct "
        "text_policy values observed across requests[] "
        "(covers_multiple_text_policies=True, text_policy_coverage "
        "size >= EXPECTED_MIN_DISTINCT_TEXT_POLICIES). The five fail-"
        "closed probes (missing bundle, forced downstream failure, "
        "bad descriptor vocabulary, malformed-request summary refusal "
        "with the diversity-gate-triggered text_policy collapse "
        "variant, and static helper refusing real-D-One / MCP / "
        "network / model / image-search / Qoder success claims) all "
        "fire. "
        "REPO_ROOT/examples and REPO_ROOT/scripts are byte-snapshot "
        "unchanged. MOCK / local only — NOT real D-One."
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mock-image bundle trial evidence emitter. Drives the "
            "COMMITTED examples/synthetic_mock_image_trial bundle "
            "through scripts/run_mock_image_pipeline.py --bundle into "
            "a tempfile-owned workspace/output/report directory "
            "OUTSIDE the repo tree, re-runs "
            "scripts/validate_mock_d_one_adapter_plan.py (with "
            "--require-both-placement-roles AND "
            "--descriptor-vocabulary <bundle/descriptor_vocabulary"
            ".json>) against the runner-written "
            "mock_d_one_adapter_plan.json sidecar, runs "
            "scripts/validate_pptx_contract.py (with "
            "--expected-slide-count 2) and "
            "scripts/inspect_pptx_inventory.py against the produced "
            "PPTX, and emits a compact JSON evidence object to "
            "stdout AND to <tempdir>/happy/" + EVIDENCE_FILENAME + ". "
            "The evidence records summary.ok, fixed "
            "real_d_one_status=UNVERIFIED, pptx exists/size, "
            "inventory ok/findings/slide_count/media_parts_count/"
            "evidence_basis/no-external-relationships, validator rc "
            "fields, sidecar schema_version/request_count, and one "
            "record per generated request (id / placement_role / "
            "text_policy / subject_domain / optional "
            "custom_descriptor / manifest_local_path); BOTH "
            "hero_page AND local_region placement_role coverage is "
            "asserted, and the bundle's committed "
            "descriptor_vocabulary.json gate is asserted to have been "
            "used on the sidecar validator command line. --self-test "
            "additionally runs five fail-closed probes (missing "
            "bundle, forced downstream failure forcing no sidecar, "
            "bad descriptor vocabulary, malformed-request summary "
            "refusal flipping summary.ok=False for synthetic "
            "sidecars that drop or corrupt a goal-required per-"
            "request field, and static helper refusing tampered "
            "evidence JSONs claiming real D-One / MCP / public "
            "network / model API / image search / Qoder success). "
            "Stdlib-only. NETWORK-FREE. NO real D-One. NO MCP. NO "
            "Qoder. NO model API. NO image search. NO telemetry. "
            "MOCK / STUB only."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Required: run the trial under "
            "tempfile.TemporaryDirectory(), collect evidence, write "
            "<tempdir>/happy/" + EVIDENCE_FILENAME + ", print PASS + "
            "the evidence path, run the five fail-closed probes, and "
            "assert REPO_ROOT/examples + REPO_ROOT/scripts are "
            "byte-snapshot unchanged. The emitter has no production "
            "CLI surface today; --self-test is required."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: mock_image_bundle_trial_evidence.py requires "
            "--self-test (no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
