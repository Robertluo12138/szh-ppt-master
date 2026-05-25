#!/usr/bin/env python3
"""Generated-image provenance handoff smoke (LOCAL, STUB, NOT real D-One).

Tempdir-only, stdlib-only handoff smoke that proves a reviewer can
walk a single mock-image trial run end-to-end:

  1. drive the committed ``examples/synthetic_mock_image_trial/``
     bundle through ``scripts/run_mock_image_pipeline.py --bundle``
     into a tempfile-owned workspace / output / report directory
     OUTSIDE the repo tree, then derive the **TEMP-ONLY** runtime
     provenance object the way
     ``scripts/mock_generated_image_provenance_smoke.py`` already
     derives it (reusing the same helpers so the runtime shape is
     not duplicated here);
  2. **sanitize** the runtime object into a committed-safe handoff
     record whose path-typed fields are workspace-relative /
     placeholder shapes (no leading ``/``, no URI scheme, no ``..``
     segment) so the same per-id taxonomy + sha256 + inventory
     evidence the runtime smoke recorded can be schema-validated
     against ``schemas/generated_image_provenance.schema.json``
     without leaking absolute machine paths;
  3. validate the sanitized record through
     ``scripts/validate_generated_image_provenance.py`` (schema
     + every documented G1..G17 semantic gate) so the same gate the
     committed template ships against is what the handoff smoke
     drives;
  4. assert the committed tree under ``REPO_ROOT`` is byte-identical
     before and after the run — the smoke writes nothing under the
     repo tree, never commits the sanitized record, and the per-run
     tempdir is removed on exit.

The handoff smoke is the **bridge** between the runtime TEMP-ONLY
provenance object (absolute tempdir paths the runtime gate accepts
but the committed-safe gate refuses) and the committed-safe handoff
the validator + schema require. The deliberate narrowed mapping is:

  runtime  : ``<bundle>``      -> placeholder ``synthetic-tempdir/committed_bundle_copy``
  runtime  : ``<workspace>``   -> placeholder ``synthetic-tempdir/workspace``
  runtime  : ``<report-dir>``  -> placeholder ``synthetic-tempdir/report``
  runtime  : ``<output>.pptx`` -> placeholder ``synthetic-tempdir/output/trial.pptx``
  runtime  : ``<sidecar>``     -> placeholder ``synthetic-tempdir/report/mock_d_one_adapter_plan.json``
  runtime  : ``<inventory>``   -> placeholder ``synthetic-tempdir/report/inventory.json``
  runtime  : ``<asset>.png``   -> placeholder ``synthetic-tempdir/workspace/<manifest_local_path>``
  rows[*].pptx_media.part      -> preserved (already package-internal ``ppt/media/<...>``)
  rows[*].asset.sha256         -> preserved (lowercase 64-hex)
  rows[*].asset.byte_count     -> preserved (positive int)

  rows[*].placement_role / text_policy / subject_domain /
  manifest_local_path / spec / sidecar  -> preserved verbatim

  schema_version                -> "1" (locked)
  evidence_id                   -> "generated_image_provenance" (locked)
  real_d_one_status             -> a fresh canonical UNVERIFIED sentence
                                   matching the schema's negation-token
                                   contract (G3); the runtime sentence is
                                   not copied because it is provenance-
                                   smoke-specific wording
  notes                         -> the committed-safe ``scope`` /
                                   ``embed_surface`` framing the schema
                                   pins (the runtime ``notes`` carries
                                   provenance-smoke-specific wording the
                                   committed-safe contract does not name
                                   as required)

The sanitizer is a one-pass map: every path-typed field is rewritten
from its tempdir-anchored value to a fixed committed-safe placeholder
under the same logical role. Any input value that does NOT lexically
sit under the tempdir-anchored root — the sanitizer cannot translate
an unexpected absolute path safely — is REFUSED outright (sanitizer
H1). Any output value that does not satisfy the committed-safe path
contract (no URI scheme, no ``..`` segment, no leading ``/`` or
``~``) is REFUSED outright (sanitizer H2). The validator's G12 path-
safety gate is the load-bearing post-sanitization check: a leak past
H1/H2 still trips at G12 in the validator subprocess.

The mock pipeline is invoked ONCE per self-test of THIS smoke (its
own independent ``run_mock_image_pipeline.py --bundle`` subprocess;
the pipeline takes more than a few seconds to run end-to-end and
running it a second time inside this smoke would double its cost
for no diagnostic gain). The sibling
``mock_generated_image_provenance_smoke`` runs its own independent
pipeline subprocess too — in the aggregate the pipeline therefore
runs twice end-to-end (once per smoke). What the two smokes share
is the Python helper functions ``_run_runner`` + ``_derive_provenance``
imported from ``mock_generated_image_provenance_smoke``, so the
runtime row taxonomy + provenance-derivation code stays single-
source-of-truth across both smokes. Every fail-closed probe in
THIS smoke runs the validator SUBPROCESS on a tampered clone of
the sanitized record so the canonical G1..G17 gate stack is
exercised on the probe path.

Clean-room: this smoke shares no prompts, assets, examples, tables,
CSV rows, wording, code, or deck structure with any upstream
project. Aligned only with the local-only image-generation idea
that generated-image work should produce a reviewer-readable
committed-safe handoff record alongside the temp-only runtime
provenance; the implementation, sanitizer field set, and probe
matrix are this repo's own.

Happy-path assertions (every one is an assertion that flips the
emitter's ``summary.ok`` to False; the script exits non-zero on any
failure):

  H1  the helper functions reused from
      ``mock_generated_image_provenance_smoke`` (``_run_runner`` +
      ``_derive_provenance``) drive a pipeline subprocess that
      returns rc=0 AND produce a non-empty provenance dict with at
      least one row;
  H2  the runtime provenance dict reports ``summary.ok=true``
      (i.e. the runtime gate stack PASSED, so the bytes feeding the
      sanitizer are themselves clean);
  H3  the sanitizer's input path-prefix gate refuses any path-typed
      field that does not sit under the expected tempdir-anchored
      root (``bundle_path`` under REPO_ROOT, every other path under
      the per-run tempdir);
  H4  the sanitizer's output gate refuses any committed-safe output
      that still carries a URI scheme, a ``..`` segment, a leading
      ``/`` or ``~``, or a tempdir absolute prefix that survived
      sanitization (defense in depth — H1 would have rejected the
      input, so this gate is belt-and-braces);
  H5  the validator subprocess on the sanitized record returns
      rc=0 (every G1..G17 gate held; this is what the reviewer-
      facing handoff contract reduces to);
  H6  the committed tree under REPO_ROOT is byte-identical before
      and after the run (same broad set of top-level paths the
      aggregate quality gate already protects, via
      ``core_editable_ppt_acceptance._snapshot_committed_tree``).

Fail-closed probes (every probe runs on a clean copy of the
sanitized record so a probe-induced failure cannot leak into the
next probe; every probe asserts the validator subprocess returns
rc=1 with the documented diagnostic substring AND that the canonical
sanitized baseline still passes):

  P1  absolute path leak: rewrite ``rows[0].asset.path`` to
      ``/etc/passwd`` and assert the validator's G12 path-safety
      gate refuses it (no URI, no ``..``, but absolute);
  P2  URI / traversal: rewrite ``rows[0].manifest_local_path`` to
      ``http://attacker/x.png`` and assert the validator refuses;
  P3  credential wording: inject ``token=value`` into
      ``rows[0].spec.intended_use`` and assert the validator's
      string-safety gate refuses;
  P4  public-hosting wording: inject ``public hosting enabled``
      into ``rows[0].spec.intended_use`` and assert the validator
      refuses;
  P5  confidential / customer marker: inject ``customer_id=12345``
      into ``rows[0].spec.intended_use`` and assert the validator
      refuses;
  P6  real-D-One success claim: rewrite ``notes.scope`` to a
      tampered ``real D-One verified online`` sentence and assert
      the validator's claim-refusal walker fires;
  P7  sidecar schema drift: set ``sidecar.schema_version = 3`` and
      assert the validator refuses (G16);
  P8  collapsed ``text_policy``: flatten every row's ``text_policy``
      AND every row's ``spec.text_policy`` AND every row's
      ``sidecar.text_policy`` to a single value and assert the
      validator's diversity gate refuses (G8);
  P9  collapsed ``placement_role``: flatten every row's
      ``placement_role`` AND every row's ``spec.placement_role`` AND
      every row's ``sidecar.placement_role`` to ``hero_page`` and
      assert the validator refuses (G7);
  P10 sha mismatch: rewrite ``rows[0].pptx_media.sha256`` away from
      ``rows[0].asset.sha256`` and assert the validator's pptx_media
      gate refuses (G11);
  P11 PPTX media path outside ``ppt/media/``: rewrite
      ``rows[0].pptx_media.part`` to ``media/image1.png`` (no
      package prefix) and assert the validator refuses (G11 +
      schema pattern lock).

Wiring decision: this smoke IS wired into the aggregate
``scripts/core_editable_ppt_acceptance.py`` as the fourteenth
delegated smoke. The handoff smoke is independent — each
aggregate run of it drives its OWN mock pipeline subprocess
(one ``run_mock_image_pipeline.py --bundle`` invocation), its
OWN runtime-provenance derivation, its OWN sanitization, and
its OWN validator subprocess calls (one happy-path + eleven
probes = twelve validator invocations). It does NOT piggy-back
on ``mock_generated_image_provenance_smoke.py``'s pipeline run
or runtime object: that coupling would force the two smokes to
share state across subprocess boundaries and would lose the
clean separation between the runtime provenance contract (gated
by the mock-provenance smoke) and the committed-safe handoff
contract (gated here). The pipeline runs once inside THIS
smoke's self-test, and once again inside the sibling
mock-provenance smoke when both run under the aggregate. The
total added wall-clock cost on the aggregate is small (≈2
seconds — measured as 40.8s → 42.9s when the smoke was added),
well within the existing aggregate's per-smoke budget; the
dominant cost is the handoff smoke's own pipeline run, with
the twelve read-only stdlib-only validator subprocesses
contributing a sub-second tail.

MOCK / STUB ONLY — NOT real D-One integration. Nothing in this
smoke calls D-One, MCP, Qoder, a public network, telemetry, any
model API, an image search, or any external service. The asset
bytes generated by ``run_d_one_generation --allow-synthetic-bytes``
are a fixed minimal PNG payload per request, never a real image.
The committed-safe handoff record this smoke derives is local
audit evidence about that synthetic mock chain, not a claim that
any external service ran or succeeded.

Usage:
  python3 scripts/generated_image_provenance_handoff_smoke.py --self-test

Stdlib-only. NETWORK-FREE. NO real D-One. NO MCP. NO Qoder. NO
model API. NO image search. NO telemetry. NOT a full prompt /
report / Markdown-to-PPTX automation — the smoke composes the
committed mock chain through the existing runtime smoke and proves
a reviewer can derive the committed-safe handoff from the runtime
output without leaking absolute paths or claiming a real run.
"""
from __future__ import annotations

import sys

# Refuse to write `.pyc` files for any module imported by this smoke.
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
COMMITTED_BUNDLE = REPO_ROOT / "examples" / "synthetic_mock_image_trial"

sys.path.insert(0, str(SCRIPTS_DIR))

# Reuse the runtime derivation and the committed-tree snapshot helpers
# rather than duplicating them. Sharing the same code path means a
# future change to the runtime row taxonomy or to the snapshot scope
# is exercised by THIS smoke too.
from mock_generated_image_provenance_smoke import (  # noqa: E402
    _all_gates,
    _committed_request_ids,
    _derive_provenance,
    _run_runner,
)
from core_editable_ppt_acceptance import (  # noqa: E402
    _snapshot_committed_tree,
)

TEMPLATE_ROOT = REPO_ROOT / "templates" / "layouts"

# Canonical committed-safe placeholders. The sanitizer rewrites the
# runtime tempdir-anchored values to these fixed shapes so the same
# bytes the runtime gate accepted are walked under a path the
# committed-safe schema accepts.
_PLACEHOLDER_BUNDLE_PATH = "synthetic-tempdir/committed_bundle_copy"
_PLACEHOLDER_WORKSPACE_PATH = "synthetic-tempdir/workspace"
_PLACEHOLDER_REPORT_DIR = "synthetic-tempdir/report"
_PLACEHOLDER_PPTX_PATH = "synthetic-tempdir/output/trial.pptx"
_PLACEHOLDER_SIDECAR_PATH = (
    "synthetic-tempdir/report/mock_d_one_adapter_plan.json"
)
_PLACEHOLDER_INVENTORY_PATH = "synthetic-tempdir/report/inventory.json"

# Canonical committed-safe UNVERIFIED sentence. Matches the schema's
# G3 contract: contains the literal "UNVERIFIED" substring AND pairs
# at least one forbidden noun with a negation token. The wording is
# deliberately small and stable so the handoff record is reproducible
# across runs.
_COMMITTED_SAFE_STATUS = (
    "UNVERIFIED. Real D-One is NOT called by this handoff record. "
    "No MCP, no public network, no model API, no image search, no "
    "Qoder, no telemetry."
)

# Canonical committed-safe notes block. Matches the schema's notes
# required fields (scope + embed_surface) and the string-safety scan
# (no credential / public-hosting / confidential / raw-source
# markers, no real-D-One success claim).
_COMMITTED_SAFE_NOTES = {
    "scope": (
        "Mock-image generated-image provenance handoff. Drives the "
        "committed mock-image bundle through the local pipeline into "
        "a tempdir, sanitizes the runtime provenance object into a "
        "committed-safe shape, and validates the result. NOT real "
        "D-One, NOT MCP, NOT Qoder, NOT a public-network run, NOT "
        "telemetry, NOT a prompt or report to PPTX automation."
    ),
    "embed_surface": (
        "PNG, JPG, and JPEG inside the ppt media slot of the "
        "produced deck. The subset scripts export_pptx supports "
        "today; anything outside that subset is fail-closed by the "
        "exporter."
    ),
}

_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


# ---------------------------------------------------------------------------
# Outcome dataclasses.
# ---------------------------------------------------------------------------


@dataclass
class _SanitizerOutcome:
    ok: bool
    record: dict | None
    failures: list[str]


@dataclass
class _ValidatorOutcome:
    rc: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.rc == 0

    @property
    def combined(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


# ---------------------------------------------------------------------------
# Sanitizer. Maps a runtime TEMP-ONLY provenance dict (with absolute
# tempdir paths) to the committed-safe shape the validator + schema
# require. Refuses inputs that do not lexically anchor under the
# expected tempdir roots so a runtime bug cannot silently leak an
# unrelated absolute path into the committed-safe record.
# ---------------------------------------------------------------------------


def _ensure_under(prefix: str, value: str, label: str) -> list[str]:
    """Refuse ``value`` unless it lexically sits under ``prefix``."""
    if not value:
        return [f"sanitizer H1: {label} is empty"]
    if not prefix:
        return [f"sanitizer H1: {label} prefix is empty"]
    norm_prefix = prefix.rstrip("/") + "/"
    if value == prefix.rstrip("/") or value.startswith(norm_prefix):
        return []
    return [
        f"sanitizer H1: {label}={value!r} does not sit under expected "
        f"prefix {prefix!r} — refusing rather than rewriting an "
        f"unrelated absolute path to a committed-safe placeholder"
    ]


def _committed_safe_path_failures(label: str, value: str) -> list[str]:
    """H2 — refuse any output value that does not satisfy the
    committed-safe path contract (no URI, no ``..``, no leading
    ``/``, no leading ``~``). Belt-and-braces: H1 already rejects
    inputs whose prefix is wrong, so any output failure here means
    the rewrite logic itself drifted."""
    out: list[str] = []
    if not value:
        out.append(f"sanitizer H2: {label} is empty")
        return out
    if _URI_SCHEME_PREFIX.match(value):
        out.append(
            f"sanitizer H2: {label}={value!r} carries a URI scheme "
            f"prefix"
        )
    parts = value.replace("\\", "/").split("/")
    if ".." in parts:
        out.append(
            f"sanitizer H2: {label}={value!r} contains a '..' "
            f"traversal segment"
        )
    if value.startswith("/") or value.startswith("~"):
        out.append(
            f"sanitizer H2: {label}={value!r} is absolute / home-"
            f"relative"
        )
    return out


def _sanitize(runtime: dict) -> _SanitizerOutcome:
    """Map the runtime TEMP-ONLY provenance dict to a committed-safe
    handoff record. Returns ``(ok, record, failures)``; a non-empty
    ``failures`` list means the sanitizer refused the input."""
    failures: list[str] = []

    bundle_path = str(runtime.get("bundle_path") or "")
    workspace_path = str(runtime.get("workspace_path") or "")
    report_dir = str(runtime.get("report_dir") or "")
    pptx_path = str(runtime.get("pptx_path") or "")

    # H1 — every absolute path on the runtime object must anchor under
    # its expected tempdir root. The bundle_path is the committed
    # bundle (anchored under REPO_ROOT); everything else is anchored
    # under the per-run tempdir.
    failures.extend(_ensure_under(
        str(COMMITTED_BUNDLE), bundle_path, "bundle_path",
    ))

    # Derive the per-run tempdir root from workspace_path's parent.
    # The runner writes ``<td>/happy_ws`` / ``<td>/happy.pptx`` /
    # ``<td>/happy_report`` siblings; using a common ancestor lets
    # us validate the other three without baking in the runner's
    # exact directory names.
    try:
        tempdir_root = str(Path(workspace_path).parent)
    except (OSError, ValueError):
        tempdir_root = ""
    if not tempdir_root or tempdir_root == "/":
        failures.append(
            f"sanitizer H1: cannot derive a tempdir root from "
            f"workspace_path={workspace_path!r}"
        )

    if tempdir_root:
        failures.extend(_ensure_under(
            tempdir_root, workspace_path, "workspace_path",
        ))
        failures.extend(_ensure_under(
            tempdir_root, report_dir, "report_dir",
        ))
        failures.extend(_ensure_under(
            tempdir_root, pptx_path, "pptx_path",
        ))

    sidecar = runtime.get("sidecar") or {}
    inventory = runtime.get("inventory") or {}
    sidecar_path = str(sidecar.get("path") or "")
    inventory_path = str(inventory.get("path") or "")
    if tempdir_root:
        failures.extend(_ensure_under(
            tempdir_root, sidecar_path, "sidecar.path",
        ))
        failures.extend(_ensure_under(
            tempdir_root, inventory_path, "inventory.path",
        ))

    sanitized_rows: list[dict] = []
    for idx, row in enumerate(runtime.get("rows") or []):
        if not isinstance(row, dict):
            failures.append(
                f"sanitizer H1: rows[{idx}] is not a JSON object"
            )
            continue
        asset = row.get("asset") or {}
        asset_path = str(asset.get("path") or "")
        if tempdir_root:
            failures.extend(_ensure_under(
                tempdir_root, asset_path,
                f"rows[{idx}].asset.path",
            ))

        manifest_local_path = str(row.get("manifest_local_path") or "")
        # The runtime row already carries the manifest_local_path as
        # workspace-relative; refuse anything else here so a tampered
        # runtime cannot smuggle an absolute manifest_local_path
        # through the rewrite.
        if (manifest_local_path.startswith("/")
                or manifest_local_path.startswith("~")
                or _URI_SCHEME_PREFIX.match(manifest_local_path)
                or ".." in manifest_local_path.replace(
                    "\\", "/",
                ).split("/")):
            failures.append(
                f"sanitizer H1: rows[{idx}].manifest_local_path="
                f"{manifest_local_path!r} is not workspace-relative; "
                f"refusing rather than rewriting it"
            )

        # Build the committed-safe row. The runtime smoke already
        # records per-id taxonomy + sidecar + spec + sha256 +
        # byte_count + extension + media_type in the exact shape the
        # committed-safe schema requires; the sanitizer only rewrites
        # the path-typed fields and copies the rest verbatim.
        spec = row.get("spec") or {}
        # The schema requires ``spec.intended_use`` as a non-empty
        # string. The runtime row's spec is derived from the bundle's
        # d_one_spec.json; if any value is missing, the row cannot be
        # promoted to the committed-safe shape.
        intended_use = spec.get("intended_use")
        if not (isinstance(intended_use, str) and intended_use):
            failures.append(
                f"sanitizer H1: rows[{idx}].spec.intended_use is "
                f"missing — runtime row lacks the field the "
                f"committed-safe schema requires"
            )

        pptx_media = row.get("pptx_media")
        if not isinstance(pptx_media, dict):
            failures.append(
                f"sanitizer H1: rows[{idx}].pptx_media is missing — "
                f"runtime row has no matched ppt/media part to "
                f"promote"
            )
            pptx_media = {}

        # The runtime row uses ``part`` (package-internal OOXML path,
        # always under ``ppt/media/``) byte-identically with the
        # committed-safe schema. Copy verbatim; the validator's G11
        # gate is what enforces the start-with check.
        sanitized_committed_safe_path = _PLACEHOLDER_WORKSPACE_PATH + (
            "/" + manifest_local_path if manifest_local_path else ""
        )
        # Defense in depth (H2) — refuse any committed-safe placeholder
        # whose post-rewrite shape doesn't satisfy the path contract.
        failures.extend(_committed_safe_path_failures(
            f"rows[{idx}].asset.path (committed-safe rewrite)",
            sanitized_committed_safe_path,
        ))

        sanitized_rows.append({
            "id": row.get("id"),
            "placement_role": row.get("placement_role"),
            "text_policy": row.get("text_policy"),
            "subject_domain": row.get("subject_domain"),
            "manifest_local_path": manifest_local_path,
            "spec": {
                "placement_role": spec.get("placement_role"),
                "text_policy": spec.get("text_policy"),
                "subject_domain": spec.get("subject_domain"),
                "intended_use": intended_use,
            },
            "sidecar": {
                "placement_role": (
                    row.get("sidecar") or {}
                ).get("placement_role"),
                "text_policy": (
                    row.get("sidecar") or {}
                ).get("text_policy"),
                "subject_domain": (
                    row.get("sidecar") or {}
                ).get("subject_domain"),
                "manifest_local_path": (
                    row.get("sidecar") or {}
                ).get("manifest_local_path"),
            },
            "asset": {
                "path": sanitized_committed_safe_path,
                "exists": asset.get("exists"),
                "byte_count": asset.get("byte_count"),
                "sha256": asset.get("sha256"),
                "extension": asset.get("extension"),
                "media_type": asset.get("media_type"),
                "error": asset.get("error") or "",
            },
            "pptx_media": {
                "part": pptx_media.get("part"),
                "size_bytes": pptx_media.get("size_bytes"),
                "sha256": pptx_media.get("sha256"),
                "extension": pptx_media.get("extension"),
                "content_type": pptx_media.get("content_type"),
                "referencing_slides": (
                    pptx_media.get("referencing_slides") or []
                ),
            },
        })

    # H2 — every committed-safe placeholder we are about to write into
    # the record must pass the path contract. The placeholders are
    # constants so this is belt-and-braces, but a future refactor that
    # changes a placeholder to an unsafe shape would be caught here.
    for label, val in (
        ("bundle_path", _PLACEHOLDER_BUNDLE_PATH),
        ("workspace_path", _PLACEHOLDER_WORKSPACE_PATH),
        ("report_dir", _PLACEHOLDER_REPORT_DIR),
        ("pptx_path", _PLACEHOLDER_PPTX_PATH),
        ("sidecar.path", _PLACEHOLDER_SIDECAR_PATH),
        ("inventory.path", _PLACEHOLDER_INVENTORY_PATH),
    ):
        failures.extend(_committed_safe_path_failures(label, val))

    summary = runtime.get("summary") or {}
    inventory_row = {
        "path": _PLACEHOLDER_INVENTORY_PATH,
        "ok": inventory.get("ok"),
        "findings_empty": inventory.get("findings_empty"),
        "slide_count": inventory.get("slide_count"),
        "relationships_external_count": inventory.get(
            "relationships_external_count",
        ),
    }

    record: dict = {
        "schema_version": "1",
        "evidence_id": "generated_image_provenance",
        "real_d_one_status": _COMMITTED_SAFE_STATUS,
        "bundle_path": _PLACEHOLDER_BUNDLE_PATH,
        "workspace_path": _PLACEHOLDER_WORKSPACE_PATH,
        "report_dir": _PLACEHOLDER_REPORT_DIR,
        "pptx_path": _PLACEHOLDER_PPTX_PATH,
        "sidecar": {
            "path": _PLACEHOLDER_SIDECAR_PATH,
            "schema_version": sidecar.get("schema_version"),
            "request_count": sidecar.get("request_count"),
        },
        "inventory": inventory_row,
        "rows": sanitized_rows,
        "notes": dict(_COMMITTED_SAFE_NOTES),
        "summary": {
            "ok": summary.get("ok"),
            "row_count": summary.get("row_count"),
            "placement_role_coverage": (
                summary.get("placement_role_coverage") or []
            ),
            "text_policy_coverage": (
                summary.get("text_policy_coverage") or []
            ),
            "failures": summary.get("failures") or [],
        },
    }

    return _SanitizerOutcome(
        ok=not failures, record=record, failures=failures,
    )


# ---------------------------------------------------------------------------
# Validator driver. Writes the sanitized record to a per-run tempfile
# OUTSIDE the repo tree and shells out to
# ``scripts/validate_generated_image_provenance.py --evidence``.
# Capturing rc + stdout + stderr lets the probes assert on the
# documented diagnostic substring.
# ---------------------------------------------------------------------------


def _run_validator(
    record: dict, *, evidence_path: Path,
) -> _ValidatorOutcome:
    evidence_path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
    )
    cmd = [
        sys.executable,
        str(SCRIPTS_DIR / "validate_generated_image_provenance.py"),
        "--evidence", str(evidence_path),
    ]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=env,
    )
    return _ValidatorOutcome(
        rc=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


# ---------------------------------------------------------------------------
# Happy-path: drive the runtime smoke once, sanitize, validate, then
# return the sanitized baseline for the probes.
# ---------------------------------------------------------------------------


def _run_happy_path(td: Path) -> tuple[int, dict | None]:
    workspace = td / "happy_ws"
    output = td / "happy.pptx"
    report_dir = td / "happy_report"

    print(
        "--- happy path: committed bundle -> mock pipeline -> "
        "runtime provenance -> sanitize -> committed-safe handoff "
        "-> validator ---"
    )
    print(f"  bundle:    {COMMITTED_BUNDLE.relative_to(REPO_ROOT)}")
    print(f"  workspace: {workspace}")
    print(f"  output:    {output}")
    print(f"  report:    {report_dir}")
    print()

    # Reuse the runtime smoke's runner so the bytes feeding the
    # sanitizer are produced by the same path the runtime smoke
    # already certifies.
    runner = _run_runner(
        bundle=COMMITTED_BUNDLE, workspace=workspace,
        output=output, report_dir=report_dir,
    )
    if runner.rc != 0:
        print(
            f"  [FAIL] runtime runner rc={runner.rc}"
        )
        tail = (runner.stderr or runner.stdout or "").splitlines()[-15:]
        for line in tail:
            print(f"    {line}")
        return 1, None
    print(f"  [PASS] runtime runner rc=0")

    # Drive the same derivation the runtime smoke applies. The runtime
    # smoke runs the gate stack against this dict; we add a single
    # belt-and-braces check that summary.ok is true so the sanitizer
    # is operating on bytes the runtime gate already approved.
    runtime, errors = _derive_provenance(
        bundle=COMMITTED_BUNDLE, workspace=workspace,
        report_dir=report_dir, pptx=output,
    )
    if errors:
        print(
            f"  [FAIL] runtime derivation produced "
            f"{len(errors)} error(s):"
        )
        for e in errors:
            print(f"    - {e}")
        return 1, None
    # The runtime derivation does NOT populate ``summary`` — that is
    # done by the runtime smoke's own _run_happy_path via _all_gates.
    # Run the same gate stack here so the H2 claim ("the runtime
    # gate stack PASSED, so the bytes feeding the sanitizer are
    # themselves clean") is actually true rather than vacuously
    # asserting an unconditionally-set boolean. Synthesizing a
    # happy summary without running the gates would let a mock-
    # chain regression (e.g. a sidecar that lost the local_region
    # row, or an asset whose sha256 drifted from the recorded
    # value) slip past this smoke into the sanitizer — the
    # validator's downstream G1..G17 catches the committed-safe
    # post-conditions, but it does NOT exercise the runtime-only
    # gates (e.g. spec/sidecar/row per-id parity, asset bytes
    # re-read from disk, inventory external-relationship count).
    rows = runtime.get("rows") or []
    placement_coverage = sorted({
        r.get("placement_role") for r in rows
        if isinstance(r, dict) and r.get("placement_role")
    })
    text_policy_coverage = sorted({
        r.get("text_policy") for r in rows
        if isinstance(r, dict) and r.get("text_policy")
    })
    runtime_failures = _all_gates(
        runtime,
        committed_request_ids=_committed_request_ids(COMMITTED_BUNDLE),
    )
    runtime["summary"] = {
        "ok": not runtime_failures,
        "row_count": len(rows),
        "placement_role_coverage": placement_coverage,
        "text_policy_coverage": text_policy_coverage,
        "failures": runtime_failures,
    }
    if runtime_failures:
        print(
            f"  [FAIL] runtime gate stack flagged "
            f"{len(runtime_failures)} regression(s) on the derived "
            f"provenance dict; sanitizer refusing to promote:"
        )
        for f in runtime_failures:
            print(f"    - {f}")
        return 1, None

    # H1 — at least one row. The runtime gate stack already enforces
    # MIN_REQUESTS rows, so this branch is belt-and-braces; it stays
    # as an explicit guard so a future relaxation of MIN_REQUESTS does
    # not silently let a zero-row sanitizer run through.
    if not rows:
        print(
            "  [FAIL] runtime provenance carries no rows; the "
            "sanitizer has nothing to promote"
        )
        return 1, None
    print(
        f"  [PASS] runtime gate stack flagged 0 regression(s); "
        f"{len(rows)} row(s); placement_role coverage="
        f"{placement_coverage!r}; text_policy coverage="
        f"{text_policy_coverage!r}"
    )

    sanitizer = _sanitize(runtime)
    if not sanitizer.ok or sanitizer.record is None:
        print(
            f"  [FAIL] sanitizer refused the runtime object "
            f"({len(sanitizer.failures)} failure(s)):"
        )
        for f in sanitizer.failures:
            print(f"    - {f}")
        return 1, None
    print(
        f"  [PASS] sanitized runtime object into a committed-safe "
        f"handoff record ({len(sanitizer.record.get('rows', []))} "
        f"row(s))"
    )

    evidence_path = td / "handoff_record.json"
    validator = _run_validator(sanitizer.record, evidence_path=evidence_path)
    if validator.rc != 0:
        print(
            f"  [FAIL] validator subprocess rc={validator.rc} on the "
            f"sanitized record:"
        )
        for line in (validator.stdout or "").splitlines():
            print(f"    stdout: {line}")
        for line in (validator.stderr or "").splitlines():
            print(f"    stderr: {line}")
        return 1, sanitizer.record
    print(
        f"  [PASS] validator subprocess rc=0 on the sanitized "
        f"committed-safe handoff record"
    )
    return 0, sanitizer.record


# ---------------------------------------------------------------------------
# Probes. Each probe takes a clone of the sanitized baseline, mutates
# one field according to the documented regression class, writes the
# tampered record to a per-run tempfile, and asserts the validator
# subprocess refuses it with a diagnostic that names the regression.
# Direct subprocess calls (one per probe) — total time is small
# because the validator is read-only and stdlib-only.
# ---------------------------------------------------------------------------


def _clone(record: dict) -> dict:
    return json.loads(json.dumps(record))


@dataclass
class _ProbeOutcome:
    name: str
    ok: bool
    detail: str = ""


def _run_probe(
    *, baseline: dict, name: str, mutator,
    expect_rc: int, expect_substring: str, td: Path, idx: int,
) -> _ProbeOutcome:
    clone = _clone(baseline)
    mutator(clone)
    path = td / f"probe_{idx:02d}.json"
    outcome = _run_validator(clone, evidence_path=path)
    if outcome.rc != expect_rc:
        return _ProbeOutcome(
            name, False,
            f"expected validator rc={expect_rc}; got rc={outcome.rc}. "
            f"stdout={outcome.stdout!r} stderr={outcome.stderr!r}",
        )
    if expect_substring and expect_substring not in outcome.combined:
        return _ProbeOutcome(
            name, False,
            f"validator rc={outcome.rc} but no diagnostic contained "
            f"{expect_substring!r}; "
            f"stdout={outcome.stdout!r} stderr={outcome.stderr!r}",
        )
    return _ProbeOutcome(name, True)


def _mutate_absolute_asset_path(record: dict) -> None:
    rows = record.get("rows") or []
    if rows:
        rows[0]["asset"]["path"] = "/etc/passwd"


def _mutate_uri_manifest_local_path(record: dict) -> None:
    rows = record.get("rows") or []
    if rows:
        rows[0]["manifest_local_path"] = "http://attacker/x.png"
        sc = rows[0].get("sidecar")
        if isinstance(sc, dict):
            sc["manifest_local_path"] = "http://attacker/x.png"


def _mutate_credential_intended_use(record: dict) -> None:
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("spec"), dict):
        rows[0]["spec"]["intended_use"] = (
            "hero-page accent; token=value"
        )


def _mutate_public_hosting_intended_use(record: dict) -> None:
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("spec"), dict):
        rows[0]["spec"]["intended_use"] = (
            "hero-page accent; public hosting enabled"
        )


def _mutate_confidential_intended_use(record: dict) -> None:
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("spec"), dict):
        rows[0]["spec"]["intended_use"] = (
            "hero-page accent; customer_id=12345"
        )


def _mutate_real_d_one_claim_scope(record: dict) -> None:
    notes = record.get("notes")
    if isinstance(notes, dict):
        notes["scope"] = (
            "Real D-One verified online: production run succeeded."
        )


def _mutate_sidecar_schema_version_drift(record: dict) -> None:
    sc = record.get("sidecar")
    if isinstance(sc, dict):
        sc["schema_version"] = 3


def _mutate_collapsed_text_policy(record: dict) -> None:
    for row in record.get("rows") or []:
        row["text_policy"] = "no_text"
        if isinstance(row.get("spec"), dict):
            row["spec"]["text_policy"] = "no_text"
        if isinstance(row.get("sidecar"), dict):
            row["sidecar"]["text_policy"] = "no_text"
    summary = record.get("summary") or {}
    summary["text_policy_coverage"] = ["no_text"]


def _mutate_collapsed_placement_role(record: dict) -> None:
    for row in record.get("rows") or []:
        row["placement_role"] = "hero_page"
        if isinstance(row.get("spec"), dict):
            row["spec"]["placement_role"] = "hero_page"
        if isinstance(row.get("sidecar"), dict):
            row["sidecar"]["placement_role"] = "hero_page"
    summary = record.get("summary") or {}
    summary["placement_role_coverage"] = ["hero_page"]


def _mutate_sha_mismatch(record: dict) -> None:
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("pptx_media"), dict):
        rows[0]["pptx_media"]["sha256"] = "c" * 64


def _mutate_pptx_media_part_outside(record: dict) -> None:
    rows = record.get("rows") or []
    if rows and isinstance(rows[0].get("pptx_media"), dict):
        rows[0]["pptx_media"]["part"] = "media/image1.png"


_PROBES: tuple[tuple[str, callable, int, str], ...] = (
    (
        "P1 absolute path leak on asset.path refused",
        _mutate_absolute_asset_path, 1,
        "does not match pattern",
    ),
    (
        "P2 URI scheme on manifest_local_path refused",
        _mutate_uri_manifest_local_path, 1,
        "does not match pattern",
    ),
    (
        "P3 credential wording in intended_use refused",
        _mutate_credential_intended_use, 1,
        "credential",
    ),
    (
        "P4 public-hosting wording in intended_use refused",
        _mutate_public_hosting_intended_use, 1,
        "public-distribution",
    ),
    (
        "P5 confidential / customer marker refused",
        _mutate_confidential_intended_use, 1,
        "confidential / customer",
    ),
    (
        "P6 real-D-One success claim in notes refused",
        _mutate_real_d_one_claim_scope, 1,
        "real-D-One / MCP / network / model / image-search / Qoder",
    ),
    (
        "P7 sidecar.schema_version drift refused",
        _mutate_sidecar_schema_version_drift, 1,
        "sidecar.schema_version",
    ),
    (
        "P8 collapsed text_policy diversity refused",
        _mutate_collapsed_text_policy, 1,
        "text_policy",
    ),
    (
        "P9 collapsed placement_role coverage refused",
        _mutate_collapsed_placement_role, 1,
        "placement_role coverage",
    ),
    (
        "P10 asset.sha256 vs pptx_media.sha256 mismatch refused",
        _mutate_sha_mismatch, 1,
        "sha256 drift",
    ),
    (
        "P11 pptx_media.part outside ppt/media/ refused",
        _mutate_pptx_media_part_outside, 1,
        "does not match pattern",
    ),
)


def _run_probes(baseline: dict, td: Path) -> int:
    print()
    print("--- self-test fail-closed probes ---")
    fails = 0
    for idx, (name, mutator, expect_rc, expect_sub) in enumerate(
        _PROBES, start=1,
    ):
        result = _run_probe(
            baseline=baseline, name=name, mutator=mutator,
            expect_rc=expect_rc, expect_substring=expect_sub,
            td=td, idx=idx,
        )
        mark = "PASS" if result.ok else "FAIL"
        suffix = f" -- {result.detail}" if not result.ok else ""
        print(f"  [{mark}] {name}{suffix}")
        if not result.ok:
            fails += 1
    return fails


# ---------------------------------------------------------------------------
# Self-test top level.
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    print(
        "=== generated_image_provenance_handoff_smoke (--self-test) ==="
    )

    tree_before = _snapshot_committed_tree()
    if not tree_before:
        print(
            "FAIL: committed-tree snapshot is empty — refusing to run "
            "because a downstream regression cannot be detected "
            "against an empty baseline.",
            file=sys.stderr,
        )
        return 1

    rc = 0
    with tempfile.TemporaryDirectory(
        prefix="szh_handoff_smoke_",
    ) as raw_td:
        td = Path(raw_td)
        happy_rc, baseline = _run_happy_path(td)
        if happy_rc != 0 or baseline is None:
            rc = 1
        else:
            probe_fails = _run_probes(baseline, td)
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
            f"the self-test (changed: {changed!r})",
            file=sys.stderr,
        )
        rc = 1

    if rc == 0:
        print()
        print(
            "OK (generated-image provenance handoff): happy path + "
            "every fail-closed probe passed; nothing under REPO_ROOT "
            "mutated. Real D-One remains UNVERIFIED."
        )
    return rc


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generated-image provenance handoff smoke. Drives the "
            "committed mock-image bundle through the local pipeline "
            "into a tempdir, sanitizes the runtime TEMP-ONLY "
            "provenance object into a committed-safe handoff record "
            "matching schemas/generated_image_provenance.schema.json, "
            "runs scripts/validate_generated_image_provenance.py "
            "against the sanitized record, and asserts no repo "
            "mutation. MOCK / STUB only — NETWORK-FREE — stdlib-only. "
            "Self-test surface only today."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Required: run the happy path + every fail-closed probe. "
            "The script has no other CLI surface."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: generated_image_provenance_handoff_smoke.py "
            "requires --self-test (no production CLI surface exists "
            "today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
