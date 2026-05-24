#!/usr/bin/env python3
"""Top-level acceptance gate for the committed mock-image bundle path.

Runs ``scripts/run_mock_image_pipeline.py --bundle
examples/synthetic_mock_image_trial`` into a tempfile-owned workspace /
output / report directory OUTSIDE the repo tree, then asserts (not
prints — every check is an assertion that flips a non-zero exit) the
documented invariants on the produced artifacts:

  * the runner exits 0;
  * the output ``.pptx`` exists as a regular non-symlink file and is
    non-empty;
  * ``scripts/validate_pptx_contract.py --pptx <out>
    --expected-slide-count 2`` passes (the slide_count.expected gate
    is active — a deck the exporter silently truncated would fail
    here);
  * ``<report-dir>/inventory.json`` (written by run_explicit_pipeline
    via inspect_pptx_inventory) carries ``ok == True``, ``findings
    == []``, ``slide_count == 2``, ``evidence_basis`` exactly equal
    to ``"OOXML structure only; not proof of full PowerPoint
    editability"``, every relationship is internal (no
    ``TargetMode='External'`` and no URI-scheme Target), and at
    least one ``ppt/media/`` part with extension ``.png`` / ``.jpg``
    / ``.jpeg`` is embedded;
  * stdout contains the ``[PASS] taxonomy preservation check``
    marker (proves the runner's plan re-parse gate fired against the
    bundle's taxonomy-bearing ``d_one_spec.json``);
  * the smoke writes nothing under the repo tree — flat-bytes
    snapshots of ``REPO_ROOT/examples`` and ``REPO_ROOT/scripts``
    are byte-identical before and after the happy-path run;
  * ``scripts/__pycache__/`` is byte-identical before and after the
    happy-path run EVEN WHEN the smoke's subprocess env explicitly
    omits ``PYTHONDONTWRITEBYTECODE`` — proves the runner's in-
    script ``sys.dont_write_bytecode = True`` flip closes the
    .pyc-leak hole without the env-var prefix.

``--self-test`` also runs four tempfixture fail-closed probes; each
asserts the runner exits non-zero AND the output PPTX is never
created:

  1. missing bundle directory;
  2. symlinked bundle parent (the Codex-review repro:
     ``link_parent -> real_parent`` reached through a path under
     ``link_parent/<copy>``);
  3. parent-traversal ``..`` bundle path (the second Codex-review
     finding: a path like ``<td>/parent_dir/link/../atk_bundle``
     collapses LEXICALLY but POSIX-resolves through the symlink);
  4. bad ``image_manifest_spec.images[].local_path`` (URI-shaped
     value such as ``http://attacker/x.png``) — copied from the
     committed bundle then perturbed.

MOCK / STUB acceptance ONLY — NOT real D-One integration. Nothing in
this smoke calls D-One, MCP, Qoder, a public network, telemetry, any
model API, an image search, or any external service. The committed
bundle's ``d_one_spec.json`` carries the seven-dimensional taxonomy
plus ``placement_role='hero_page'``, but the bytes generated end up
as a fixed minimal PNG payload — never a real image.

Stdlib-only. NETWORK-FREE.
"""
from __future__ import annotations

import sys

# Refuse to write `.pyc` files for any module imported by this smoke.
# The smoke contract says it writes nothing under the repo tree; this
# flip closes a regression where a first-party import would leak
# `scripts/__pycache__/<mod>.cpython-*.pyc` on a clean checkout.
# Must come BEFORE any first-party import — the interpreter checks
# the flag at bytecode-write time.
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
PYCACHE_DIR = SCRIPTS_DIR / "__pycache__"

# The committed bundle is a 2-slide deck (cover + conclusion).
EXPECTED_SLIDE_COUNT = 2

# Substring emitted by run_mock_image_pipeline's `_format_result` on a
# successful taxonomy preservation check — proves the runner's plan
# re-parse gate fired against the bundle's taxonomy-bearing
# d_one_spec.json. NOT printed unless `result.plan_check_ok` is True.
TAXONOMY_PRESERVATION_MARKER = "[PASS] taxonomy preservation check"

# Must match scripts/inspect_pptx_inventory.py::EVIDENCE_BASIS verbatim.
EXPECTED_EVIDENCE_BASIS = (
    "OOXML structure only; not proof of full PowerPoint editability"
)

# Embed surface scripts/export_pptx.py supports today. Mirrors the
# constant in scripts/image_asset_acceptance_smoke.py and
# scripts/run_mock_image_pipeline.py — the gate is a presence check on
# at least one ppt/media part whose lower-cased extension is one of
# these. Finding none would mean the mock D-One bytes never embedded
# as native PowerPoint media.
_EMBEDDABLE_MEDIA_EXTS: tuple[str, ...] = (".png", ".jpg", ".jpeg")

# Any string with a leading RFC-3986 scheme followed by ':' counts as
# an external Target (http://, https://, file://, data:, ftp://, ...).
# Internal package targets carry no scheme prefix.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")


# ---------------------------------------------------------------------------
# Subprocess invocation helpers. The smoke shells out to the runner +
# validator so each downstream tool's argparse + fail-closed gates +
# stdout/stderr cascade is exercised verbatim.
# ---------------------------------------------------------------------------


@dataclass
class StageOutcome:
    name: str
    cmd: list[str]
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def combined(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


def _run_stage(
    name: str, cmd: list[str], *, env: dict[str, str] | None = None,
) -> StageOutcome:
    """Run ``cmd`` from ``REPO_ROOT`` with the supplied ``env``. When
    ``env`` is None, the smoke's own environment is forwarded (with
    ``PYTHONDONTWRITEBYTECODE=1`` so the validator subprocess can't
    leak its own .pyc files). The happy-path runner invocation
    deliberately strips ``PYTHONDONTWRITEBYTECODE`` to prove the in-
    script flip in run_mock_image_pipeline.py closes the leak; see
    ``_no_pyc_env_for_runner``."""
    proc_env = (
        env if env is not None
        else {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    )
    proc = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, env=proc_env,
    )
    return StageOutcome(
        name=name, cmd=cmd, exit_code=proc.returncode,
        stdout=proc.stdout, stderr=proc.stderr,
    )


def _print_stage(stage: StageOutcome) -> None:
    mark = "PASS" if stage.ok else "FAIL"
    print(f"  [{mark}] {stage.name} (rc={stage.exit_code})")
    if not stage.ok:
        for label, text in (
            ("stdout", stage.stdout), ("stderr", stage.stderr),
        ):
            tail = (text or "").splitlines()[-15:]
            if tail:
                print(f"    {label} tail:")
                for line in tail:
                    print(f"      {line}")


def _no_pyc_env_for_runner() -> dict[str, str]:
    """Return a subprocess env with ``PYTHONDONTWRITEBYTECODE`` removed.
    Used for the happy-path invocation so the no-pyc-leak invariant is
    actually testable — the runner's own ``sys.dont_write_bytecode =
    True`` flip is the only thing standing between an inadvertent
    first-party import and a fresh ``scripts/__pycache__/*.pyc`` file
    landing under the repo tree."""
    return {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}


# ---------------------------------------------------------------------------
# Snapshot helpers — flat path -> bytes maps used to prove the smoke
# writes nothing under the repo tree.
# ---------------------------------------------------------------------------


def _snapshot_dir(dir_path: Path) -> dict[str, bytes]:
    """Flat ``rel_path -> bytes`` map of every regular non-symlink file
    under ``dir_path``. Mirrors the snapshot helpers in the other
    acceptance smokes (image_asset_acceptance_smoke.py,
    image_taxonomy_acceptance_smoke.py) so the no-mutation invariant
    is asserted with the same gate everywhere. Symlinks are not
    followed (recording them by readlink target is unnecessary here —
    none of the snapshotted directories committed to the repo contain
    symlinks today, and a smoke-planted symlink under the repo tree
    is already a contract violation independent of its content)."""
    snapshot: dict[str, bytes] = {}
    if not dir_path.is_dir():
        return snapshot
    for p in sorted(dir_path.rglob("*")):
        if p.is_symlink() or not p.is_file():
            continue
        rel = p.relative_to(dir_path)
        snapshot[str(rel)] = p.read_bytes()
    return snapshot


def _diff_snapshot(
    before: dict[str, bytes], after: dict[str, bytes],
) -> list[str]:
    """Return a sorted list of changed relative paths between the two
    snapshots. Empty list means byte-identical."""
    changed: list[str] = []
    for key in sorted(set(before) | set(after)):
        if before.get(key) != after.get(key):
            changed.append(key)
    return changed


# ---------------------------------------------------------------------------
# Inventory / PPTX assertions. The runner already invokes
# `validate_pptx_contract` + `inspect_pptx_inventory` inside
# `run_pipeline.py`; the smoke re-runs the contract validator with
# `--expected-slide-count 2` as belt-and-braces and re-reads the
# inventory JSON to assert the documented post-conditions.
# ---------------------------------------------------------------------------


@dataclass
class PostCondition:
    name: str
    ok: bool
    detail: str = ""


def _load_inventory(inventory_path: Path) -> tuple[dict | None, str]:
    if not inventory_path.is_file() or inventory_path.is_symlink():
        return None, (
            f"path={inventory_path}, is_file={inventory_path.is_file()}, "
            f"is_symlink={inventory_path.is_symlink()}"
        )
    try:
        return json.loads(inventory_path.read_text()), ""
    except (json.JSONDecodeError, OSError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _check_inventory_invariants(
    *, inventory_path: Path, expected_slide_count: int,
) -> list[PostCondition]:
    """Assert every documented inventory invariant the goal lists:
    ``slide_count`` matches, ``findings`` is empty, no relationship
    carries an external TargetMode or URI-scheme Target, and at least
    one ``ppt/media/`` part with an embeddable extension is present.
    Each invariant becomes a separate PostCondition so a partial
    failure surfaces exactly which assertion did not hold."""
    results: list[PostCondition] = []
    inv, err = _load_inventory(inventory_path)
    results.append(PostCondition(
        "inventory.json exists as a regular non-symlink file and parses",
        inv is not None, err,
    ))
    if inv is None:
        return results
    results.append(PostCondition(
        "inventory.ok is True",
        inv.get("ok") is True,
        f"got: {inv.get('ok')!r}",
    ))
    results.append(PostCondition(
        "inventory.findings == []",
        inv.get("findings") == [],
        f"got: {inv.get('findings')!r}",
    ))
    results.append(PostCondition(
        f"inventory.slide_count == {expected_slide_count}",
        inv.get("slide_count") == expected_slide_count,
        f"got: {inv.get('slide_count')!r}",
    ))
    results.append(PostCondition(
        "inventory.evidence_basis matches the documented line",
        inv.get("evidence_basis") == EXPECTED_EVIDENCE_BASIS,
        (f"expected: {EXPECTED_EVIDENCE_BASIS!r}; "
         f"got: {inv.get('evidence_basis')!r}"),
    ))
    # Relationships: every entry must be internal (no External
    # TargetMode, no URI-scheme Target). The findings-empty assertion
    # above already covers this in the aggregate, but the goal asks
    # explicitly for "no external/file/data relationships" so we walk
    # the list and surface the offending Target verbatim.
    relationships = inv.get("relationships")
    if not isinstance(relationships, list):
        results.append(PostCondition(
            "inventory.relationships is a list",
            False, f"got: type={type(relationships).__name__}",
        ))
    else:
        external: list[str] = []
        for rel in relationships:
            if not isinstance(rel, dict):
                continue
            target = rel.get("target") or ""
            mode = (rel.get("target_mode") or "").lower()
            if mode and mode != "internal":
                external.append(
                    f"id={rel.get('id')!r} TargetMode={mode!r} "
                    f"Target={target!r}"
                )
            elif isinstance(target, str) and _URI_SCHEME_PREFIX.match(target):
                external.append(
                    f"id={rel.get('id')!r} Target={target!r} (URI scheme)"
                )
        results.append(PostCondition(
            "inventory.relationships carries no external / file:// / "
            "data: / scheme-shaped Target and no External TargetMode",
            not external,
            "; ".join(external) if external else "",
        ))
    # Media parts: at least one PNG/JPG/JPEG embedded.
    media_parts = inv.get("media_parts")
    if not isinstance(media_parts, list):
        results.append(PostCondition(
            "inventory.media_parts is a list",
            False, f"got: type={type(media_parts).__name__}",
        ))
    else:
        embedded = [
            m for m in media_parts
            if isinstance(m, dict)
            and isinstance(m.get("extension"), str)
            and "." + m["extension"].lower() in _EMBEDDABLE_MEDIA_EXTS
        ]
        results.append(PostCondition(
            f"inventory.media_parts carries at least one entry with "
            f"extension in {_EMBEDDABLE_MEDIA_EXTS}",
            len(embedded) > 0,
            (f"media_parts={media_parts!r}" if not embedded else ""),
        ))
    return results


def _run_contract_validator(
    *, pptx: Path, expected_slide_count: int,
) -> StageOutcome:
    """Re-run scripts/validate_pptx_contract.py directly with the
    expected-slide-count gate active. This is belt-and-braces — the
    pipeline runner inside run_explicit_pipeline.py already runs the
    same validator, but the smoke re-invokes it from the smoke's own
    process so the contract surface stays visible in the smoke's
    output even if the upstream stage's log is truncated."""
    return _run_stage(
        "validate_pptx_contract (belt-and-braces, --expected-slide-count "
        f"{expected_slide_count})",
        [
            sys.executable, str(SCRIPTS_DIR / "validate_pptx_contract.py"),
            "--pptx", str(pptx),
            "--expected-slide-count", str(expected_slide_count),
        ],
    )


# ---------------------------------------------------------------------------
# Happy-path runner. Drives the committed bundle through
# scripts/run_mock_image_pipeline.py and asserts every invariant.
# ---------------------------------------------------------------------------


def _runner_cmd(
    *, bundle: Path, workspace: Path, output: Path, report_dir: Path,
) -> list[str]:
    return [
        sys.executable, str(SCRIPTS_DIR / "run_mock_image_pipeline.py"),
        "--bundle", str(bundle),
        "--workspace", str(workspace),
        "--template-root", str(TEMPLATE_ROOT),
        "--output", str(output),
        "--report-dir", str(report_dir),
        "--allow-synthetic-bytes",
    ]


def _run_happy_path(td: Path) -> tuple[int, list[PostCondition]]:
    """Drive the committed bundle through the runner and return
    (fail_count, post_conditions). All assertions are PostCondition
    records so a partial regression surfaces exactly which invariant
    did not hold."""
    workspace = td / "happy_ws"
    output = td / "happy.pptx"
    report_dir = td / "happy_report"

    print("--- happy path: committed bundle via run_mock_image_pipeline.py ---")
    print(f"  bundle:    {COMMITTED_BUNDLE.relative_to(REPO_ROOT)}")
    print(f"  workspace: {workspace}")
    print(f"  output:    {output}")
    print(f"  report:    {report_dir}")
    print()

    # Snapshot scripts/__pycache__/ before the runner subprocess so
    # the no-pyc-leak invariant is testable EVEN with
    # PYTHONDONTWRITEBYTECODE stripped from the env.
    pycache_before = _snapshot_dir(PYCACHE_DIR)
    runner_env = _no_pyc_env_for_runner()

    outcome = _run_stage(
        "run_mock_image_pipeline (--bundle examples/synthetic_mock_image_trial)",
        _runner_cmd(
            bundle=COMMITTED_BUNDLE, workspace=workspace,
            output=output, report_dir=report_dir,
        ),
        env=runner_env,
    )
    _print_stage(outcome)
    pycache_after = _snapshot_dir(PYCACHE_DIR)
    print()

    results: list[PostCondition] = []
    results.append(PostCondition(
        "run_mock_image_pipeline exits 0",
        outcome.ok,
        (f"rc={outcome.exit_code}; stderr tail: "
         f"{outcome.stderr.splitlines()[-10:]!r}; "
         f"stdout tail: {outcome.stdout.splitlines()[-10:]!r}")
        if not outcome.ok else "",
    ))
    results.append(PostCondition(
        "run_mock_image_pipeline stdout contains the taxonomy "
        f"preservation marker {TAXONOMY_PRESERVATION_MARKER!r}",
        TAXONOMY_PRESERVATION_MARKER in outcome.stdout,
        (f"marker not found; stdout tail: "
         f"{outcome.stdout.splitlines()[-15:]!r}")
        if TAXONOMY_PRESERVATION_MARKER not in outcome.stdout else "",
    ))

    pptx_is_file = output.is_file() and not output.is_symlink()
    results.append(PostCondition(
        "output PPTX exists as a regular non-symlink file",
        pptx_is_file,
        f"path={output}, is_file={output.is_file()}, "
        f"is_symlink={output.is_symlink()}",
    ))
    if pptx_is_file:
        size = output.stat().st_size
        results.append(PostCondition(
            "output PPTX is non-empty",
            size > 0, f"size={size}",
        ))
        contract = _run_contract_validator(
            pptx=output, expected_slide_count=EXPECTED_SLIDE_COUNT,
        )
        _print_stage(contract)
        results.append(PostCondition(
            "validate_pptx_contract --pptx <out> --expected-slide-count "
            f"{EXPECTED_SLIDE_COUNT} exits 0",
            contract.ok,
            (f"rc={contract.exit_code}; tail: "
             f"{(contract.stdout + contract.stderr).splitlines()[-10:]!r}")
            if not contract.ok else "",
        ))

    results.extend(_check_inventory_invariants(
        inventory_path=report_dir / "inventory.json",
        expected_slide_count=EXPECTED_SLIDE_COUNT,
    ))

    pycache_diff = _diff_snapshot(pycache_before, pycache_after)
    results.append(PostCondition(
        "scripts/__pycache__/ is byte-identical before and after the "
        "happy-path runner subprocess EVEN when PYTHONDONTWRITEBYTECODE "
        "is stripped from the env",
        not pycache_diff,
        f"changed: {pycache_diff!r}" if pycache_diff else "",
    ))

    print("--- happy-path post-conditions ---")
    fails = 0
    for pc in results:
        mark = "PASS" if pc.ok else "FAIL"
        suffix = f" -- {pc.detail}" if not pc.ok and pc.detail else ""
        print(f"  [{mark}] {pc.name}{suffix}")
        if not pc.ok:
            fails += 1
    print()
    return fails, results


# ---------------------------------------------------------------------------
# Tempfixture negative probes. Each probe must:
#   * make the runner exit non-zero (boundary refusal or chain
#     failure);
#   * leave no PPTX at --output.
# Bundle inputs are built under the per-probe tempdir; nothing is
# written under the committed repo tree.
# ---------------------------------------------------------------------------


@dataclass
class _NegativeOutcome:
    name: str
    ok: bool
    detail: str


def _copy_committed_bundle(dest: Path) -> None:
    """Materialize a fresh non-symlinked copy of the committed bundle
    under ``dest``. Uses ``symlinks=False`` so any committed symlink
    (none today, but belt-and-braces) is dereferenced — the negative
    probes need a plain non-symlink bundle as the baseline."""
    shutil.copytree(COMMITTED_BUNDLE, dest, symlinks=False)


def _assert_no_pptx(output: Path, label: str) -> tuple[bool, str]:
    if not output.exists():
        return True, ""
    return False, (
        f"{label}: output PPTX unexpectedly exists at {output} "
        f"(size={output.stat().st_size if output.is_file() else 'n/a'})"
    )


def _probe_missing_bundle(td: Path) -> _NegativeOutcome:
    """Point --bundle at a path that does not exist. The runner's
    bundle-resolver refuses with exit 2 before any subprocess fires."""
    bundle = td / "missing_bundle"
    workspace = td / "missing_ws"
    output = td / "missing.pptx"
    report_dir = td / "missing_report"
    outcome = _run_stage(
        "negative: missing bundle directory",
        _runner_cmd(
            bundle=bundle, workspace=workspace,
            output=output, report_dir=report_dir,
        ),
    )
    _print_stage(outcome)
    pptx_ok, pptx_msg = _assert_no_pptx(output, "missing-bundle probe")
    ok = (not outcome.ok) and pptx_ok
    detail = ""
    if not ok:
        detail = (
            f"rc={outcome.exit_code}, output_exists={output.exists()}, "
            f"pptx_msg={pptx_msg!r}, "
            f"stderr_tail={outcome.stderr.splitlines()[-5:]!r}"
        )
    return _NegativeOutcome(
        "negative: missing bundle directory aborts the runner; no PPTX",
        ok, detail,
    )


def _probe_symlinked_bundle_parent(td: Path) -> _NegativeOutcome:
    """Reproduce the Codex-review symlinked-parent finding: a real
    bundle copy lives under a real parent directory, but the --bundle
    path reaches it through a symlinked parent
    (``link_parent -> real_parent``). The runner's
    ``_refuse_symlinked_bundle_ancestor`` walks every lexical-absolute
    ancestor and refuses any symlink that is not the macOS ``/tmp ->
    private/tmp`` exemption."""
    probe_dir = td / "probe_symlinked_parent"
    probe_dir.mkdir()
    real_parent = probe_dir / "real_parent"
    real_parent.mkdir()
    bundle = real_parent / "synthetic_mock_image_trial"
    _copy_committed_bundle(bundle)
    link_parent = probe_dir / "link_parent"
    link_parent.symlink_to(real_parent)
    # The bundle is reached through the symlinked parent — same shape
    # the Codex review caught. The resolver should refuse before any
    # subprocess fires.
    bundle_via_link = link_parent / "synthetic_mock_image_trial"

    workspace = td / "symlinked_parent_ws"
    output = td / "symlinked_parent.pptx"
    report_dir = td / "symlinked_parent_report"
    outcome = _run_stage(
        "negative: symlinked bundle parent",
        _runner_cmd(
            bundle=bundle_via_link, workspace=workspace,
            output=output, report_dir=report_dir,
        ),
    )
    _print_stage(outcome)
    pptx_ok, pptx_msg = _assert_no_pptx(output, "symlinked-parent probe")
    ok = (not outcome.ok) and pptx_ok
    detail = ""
    if not ok:
        detail = (
            f"rc={outcome.exit_code}, output_exists={output.exists()}, "
            f"pptx_msg={pptx_msg!r}, "
            f"stderr_tail={outcome.stderr.splitlines()[-5:]!r}"
        )
    return _NegativeOutcome(
        "negative: symlinked bundle parent aborts the runner; no PPTX",
        ok, detail,
    )


def _probe_parent_traversal_bundle_path(td: Path) -> _NegativeOutcome:
    """Reproduce the parent-traversal `..` bypass: a path like
    ``<td>/probe/parent_dir/link/../atk_bundle`` collapses LEXICALLY
    to ``<td>/probe/parent_dir/atk_bundle`` (no symlink in the lexical
    chain -> the symlinked-ancestor walk passes) while POSIX-resolving
    through ``link`` to ``<td>/probe/attacker_zone/atk_bundle``. The
    runner refuses any ``..`` segment outright.

    To avoid a false green (Codex stop-time review): a REAL valid
    bundle is planted at the POSIX-resolved location. Without that,
    the runner's bundle-existence check would fail on its own — the
    probe would pass even if the ``..`` gate were silently demoted.
    With the planted bundle in place, a demoted gate would let the
    runner read the attacker-controlled bundle and produce a PPTX,
    flipping ``output.exists()`` to True and failing the probe; the
    extra ``contains a ``..`` segment`` stderr-substring assertion is
    belt-and-braces so a future regression that swaps the diagnostic
    (e.g., a generic "bundle missing" if cwd / fixture state shifts)
    surfaces explicitly rather than masquerading as a `..` refusal."""
    probe_dir = td / "probe_parent_traversal"
    probe_dir.mkdir()
    parent_dir = probe_dir / "parent_dir"
    parent_dir.mkdir()
    # The attacker zone lives in a SIBLING of parent_dir so that
    # POSIX resolution of `link/..` lands in `attacker_zone`, diverging
    # from the lexical collapse `parent_dir/atk_bundle`. Without this
    # divergence, the `..` gate and the symlinked-ancestor gate would
    # be testing the same surface.
    attacker_zone = probe_dir / "attacker_zone"
    attacker_zone.mkdir()
    real_target = attacker_zone / "real_target"
    real_target.mkdir()
    _copy_committed_bundle(attacker_zone / "atk_bundle")
    link = parent_dir / "link"
    link.symlink_to(real_target)
    # Lexical collapse: parent_dir/atk_bundle (does NOT exist).
    # POSIX resolution: attacker_zone/atk_bundle (full valid bundle).
    bundle = link / ".." / "atk_bundle"

    workspace = td / "parent_traversal_ws"
    output = td / "parent_traversal.pptx"
    report_dir = td / "parent_traversal_report"
    outcome = _run_stage(
        "negative: parent-traversal `..` bundle path",
        _runner_cmd(
            bundle=bundle, workspace=workspace,
            output=output, report_dir=report_dir,
        ),
    )
    _print_stage(outcome)
    pptx_ok, pptx_msg = _assert_no_pptx(output, "parent-traversal probe")
    diag_substring = "contains a `..` segment"
    diag_ok = diag_substring in outcome.stderr
    ok = (not outcome.ok) and pptx_ok and diag_ok
    detail = ""
    if not ok:
        detail = (
            f"rc={outcome.exit_code}, output_exists={output.exists()}, "
            f"pptx_msg={pptx_msg!r}, "
            f"diagnostic_substring_found={diag_ok}, "
            f"stderr_tail={outcome.stderr.splitlines()[-5:]!r}"
        )
    return _NegativeOutcome(
        "negative: parent-traversal `..` bundle path aborts the "
        "runner with the ``..``-refusal diagnostic (with a real bundle "
        "planted at the POSIX-resolved location so a gate demotion "
        "would let the runner read it and produce a PPTX); no PPTX",
        ok, detail,
    )


def _probe_bad_image_manifest_local_path(td: Path) -> _NegativeOutcome:
    """Copy the committed bundle into a tempdir, overwrite
    ``image_manifest_spec.images[0].local_path`` with a URI-shaped
    value (``http://attacker/x.png``), and assert the chain aborts
    with no PPTX. The runner's image-manifest check covers d_one_local
    source-tag enforcement; the unsafe local_path is rejected
    downstream (``materialize_image_assets`` /
    ``init_image_manifest`` / ``local_path_is_safe``)."""
    bundle = td / "probe_bad_local_path_bundle"
    _copy_committed_bundle(bundle)
    manifest_path = bundle / "image_manifest_spec.json"
    body = json.loads(manifest_path.read_text())
    body["images"][0]["local_path"] = "http://attacker/x.png"
    manifest_path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")

    workspace = td / "bad_local_path_ws"
    output = td / "bad_local_path.pptx"
    report_dir = td / "bad_local_path_report"
    outcome = _run_stage(
        "negative: bad image_manifest_spec local_path (URI scheme)",
        _runner_cmd(
            bundle=bundle, workspace=workspace,
            output=output, report_dir=report_dir,
        ),
    )
    _print_stage(outcome)
    pptx_ok, pptx_msg = _assert_no_pptx(output, "bad-local-path probe")
    ok = (not outcome.ok) and pptx_ok
    detail = ""
    if not ok:
        detail = (
            f"rc={outcome.exit_code}, output_exists={output.exists()}, "
            f"pptx_msg={pptx_msg!r}, "
            f"stderr_tail={outcome.stderr.splitlines()[-5:]!r}"
        )
    return _NegativeOutcome(
        "negative: bad image_manifest_spec local_path (URI scheme) "
        "aborts the chain; no PPTX",
        ok, detail,
    )


_NEGATIVE_PROBES = (
    _probe_missing_bundle,
    _probe_symlinked_bundle_parent,
    _probe_parent_traversal_bundle_path,
    _probe_bad_image_manifest_local_path,
)


# ---------------------------------------------------------------------------
# Self-test entry point.
# ---------------------------------------------------------------------------


def _run_self_test() -> int:
    print("=== mock-image bundle acceptance smoke ===")
    print(
        "  MOCK / STUB only — NOT real D-One integration; nothing "
        "calls D-One, MCP, Qoder, a public network, telemetry, any "
        "model API, an image search, or any external service."
    )
    print()

    # Pre-flight: the committed bundle must exist as a real directory
    # (not a symlink, not missing) before the smoke proceeds. A user
    # who deleted the fixture by accident should see a clear
    # diagnostic instead of a noisy subprocess error.
    if COMMITTED_BUNDLE.is_symlink():
        print(
            f"FAIL: committed bundle {COMMITTED_BUNDLE} is a symlink "
            f"(refused); the smoke targets the canonical committed "
            f"bundle path only.",
            file=sys.stderr,
        )
        return 1
    if not COMMITTED_BUNDLE.is_dir():
        print(
            f"FAIL: committed bundle {COMMITTED_BUNDLE} does not exist "
            f"as a regular directory; the synthetic fixture is required "
            f"for this smoke.",
            file=sys.stderr,
        )
        return 1

    # No-repo-write snapshot of examples + scripts. Mirrors the
    # gate used by image_asset_acceptance_smoke /
    # image_taxonomy_acceptance_smoke / run_mock_image_pipeline.
    examples_before = _snapshot_dir(REPO_ROOT / "examples")
    scripts_before = _snapshot_dir(REPO_ROOT / "scripts")

    total_fails = 0
    with tempfile.TemporaryDirectory(
        prefix="szh_mock_image_bundle_acceptance_smoke_",
    ) as raw_td:
        td = Path(raw_td)
        print(f"  tempdir: {td}")
        print()

        # 1. Happy path.
        happy_fails, _ = _run_happy_path(td)
        total_fails += happy_fails
        if happy_fails:
            print(
                f"FAIL: {happy_fails} happy-path post-condition(s) did "
                f"not hold."
            )

        # 2. Negative probes.
        print("--- negative probes ---")
        for probe in _NEGATIVE_PROBES:
            outcome = probe(td)
            mark = "PASS" if outcome.ok else "FAIL"
            suffix = (
                f" -- {outcome.detail}"
                if not outcome.ok and outcome.detail else ""
            )
            print(f"  [{mark}] {outcome.name}{suffix}")
            if not outcome.ok:
                total_fails += 1
        print()

    # 3. No-repo-write check (after the tempdir is cleaned up).
    examples_after = _snapshot_dir(REPO_ROOT / "examples")
    scripts_after = _snapshot_dir(REPO_ROOT / "scripts")
    examples_diff = _diff_snapshot(examples_before, examples_after)
    scripts_diff = _diff_snapshot(scripts_before, scripts_after)
    if examples_diff:
        print(
            f"FAIL: REPO_ROOT/examples mutated by the smoke "
            f"(changed: {examples_diff!r})",
            file=sys.stderr,
        )
        total_fails += 1
    if scripts_diff:
        print(
            f"FAIL: REPO_ROOT/scripts mutated by the smoke "
            f"(changed: {scripts_diff!r})",
            file=sys.stderr,
        )
        total_fails += 1

    if total_fails:
        print(
            f"\nFAIL: {total_fails} mock-image bundle acceptance "
            f"check(s) did not pass.",
            file=sys.stderr,
        )
        return 1
    print(
        "OK (mock-image bundle acceptance smoke): the committed "
        "examples/synthetic_mock_image_trial/ bundle drives "
        "run_mock_image_pipeline.py to a validated 2-slide editable "
        "PPTX whose ppt/media/ carries an internal PNG/JPG/JPEG, "
        "inventory.json reports ok=true with findings=[] and no "
        "external relationships, the taxonomy preservation marker "
        "fires, and scripts/__pycache__/ is byte-identical even "
        "without PYTHONDONTWRITEBYTECODE in the subprocess env. "
        "All four negative probes (missing bundle, symlinked bundle "
        "parent, parent-traversal `..`, bad image_manifest_spec "
        "local_path) aborted the runner with no PPTX written. "
        "MOCK / STUB only — NOT real D-One integration."
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Top-level acceptance gate for the committed mock-image "
            "bundle path. Runs scripts/run_mock_image_pipeline.py "
            "--bundle examples/synthetic_mock_image_trial into a "
            "tempfile-owned workspace/output/report directory OUTSIDE "
            "the repo tree, then asserts: rc==0; PPTX exists as a "
            "regular non-symlink non-empty file; "
            "scripts/validate_pptx_contract.py --pptx <out> "
            "--expected-slide-count 2 passes; "
            "<report-dir>/inventory.json reports ok=true, findings=[], "
            "slide_count=2, the exact evidence_basis line, no external "
            "/ file:// / data: / scheme-shaped relationships, and at "
            "least one ppt/media/<name>.<png|jpg|jpeg> part; stdout "
            "carries the [PASS] taxonomy preservation check marker; "
            "scripts/__pycache__/ is byte-identical before and after "
            "the runner subprocess EVEN when PYTHONDONTWRITEBYTECODE "
            "is stripped from the subprocess env; and no committed "
            "repo path (examples/ or scripts/) is mutated. --self-test "
            "additionally runs four tempfixture fail-closed probes "
            "(missing bundle, symlinked bundle parent, parent-traversal "
            "`..` bundle path, bad image_manifest_spec local_path) and "
            "asserts each aborts the runner with no PPTX produced. "
            "MOCK / STUB only — NOT real D-One integration; no MCP, "
            "no public network, no model API, no image search, no "
            "Qoder, no telemetry, no external service. Stdlib-only."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run the happy path + four tempfixture negative probes "
            "under a single tempfile.TemporaryDirectory(). The smoke "
            "has no other mode today; --self-test is required."
        ),
    )
    args = parser.parse_args(argv)
    if not args.self_test:
        print(
            "FAIL: mock_image_bundle_acceptance_smoke.py requires "
            "--self-test (no production CLI surface exists today).",
            file=sys.stderr,
        )
        return 2
    return _run_self_test()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
