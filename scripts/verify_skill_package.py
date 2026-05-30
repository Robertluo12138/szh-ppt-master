#!/usr/bin/env python3
"""verify_skill_package.py

Stdlib-only packaging-readiness verifier for the internal skill package.

The repo is intended to ship as an internal skill bundle: only source /
docs / schemas / templates / examples reach the package surface, never
generated artifacts. This script verifies that contract before a package
build, *without* changing any runtime behavior.

What this script is:
  - A static, read-only verifier. No file is created or modified except
    self-test tempfixtures under ``tempfile.TemporaryDirectory()``.
  - Pure Python stdlib. No third-party dependency, no network, no MCP, no
    model API, no public network, no Qoder runtime call, no image search,
    no telemetry, no external service.

What this script is NOT:
  - Real Qoder runtime import — live skill loading and live ``qoder``
    package import are explicitly UNVERIFIED here (and remain TODO across
    the wider repo; see ``references/quality-gates.md``).
  - A PPTX exporter / runtime pipeline. It does not change PPTX export
    behavior or any other runtime stage.
  - A package builder. It is verify-only today. The .gitignore permits a
    local ``dist/`` directory, but emitting a zip remains intentionally
    out of scope until the package surface is stable.

Package-surface enumeration:
  Both real-repo and ``--self-test`` modes enumerate the surface as the
  union of
    ``git ls-files`` (tracked or staged-for-tracking) and
    ``git ls-files --others --exclude-standard`` (untracked-not-ignored)
  rooted at ``--root`` (defaulting to the current working directory's
  git repo root, falling back to the script's parent). Gitignored files
  are intentionally excluded because they would not ship in a clean
  package copy. In ``--self-test`` the verifier ``git init``s the
  tempfixture and stages its baseline content so the same enumeration
  applies — synthetic fixtures live in a real (ephemeral) git index.

Gates (all fail-closed; any finding makes the run exit non-zero):

  G1 ``no_generated_artifacts``:
    No file in the package surface may match a forbidden filename /
    path-component pattern: ``__pycache__/`` anywhere; ``*.pyc`` /
    ``*.pyo`` / ``*.pyd``; ``*.pptx`` / ``*.potx`` / ``*.ppsx`` /
    ``*.ppt`` / ``*.pot`` / ``*.pps`` (PPTX-family binary outputs);
    ``pipeline_report.json`` / ``pipeline_report.txt`` / ``inventory.json``
    / ``visual_quality.json`` (pipeline-report artifacts); ``*.log`` /
    ``*.tmp`` (temp output); ``.DS_Store`` (macOS); ``*.pem`` / ``*.key``
    / ``.env`` / ``.env.*`` (credential file shapes); any path component
    in the generated-workspace allow-list ``dist`` / ``build`` / ``out``
    / ``output`` / ``previews`` / ``renders`` / ``exports`` / ``projects``;
    ``.git`` / ``.claude`` / ``.ai`` / ``.codex`` / ``.superset``
    (tooling / harness / local-agent metadata state).

  G2 ``doc_referenced_scripts_exist``:
    Every ``scripts/<name>.py`` reference appearing in ``SKILL.md`` /
    ``README.md`` / ``CLAUDE.md`` / ``references/*.md`` must (a) resolve
    to a regular file on disk and (b) be tracked or staged for tracking
    (i.e. present in ``git ls-files``). A docs-referenced file that
    exists only as untracked-or-gitignored would silently break the
    package: the surface enumerator still picks up untracked-not-ignored
    files, but a downstream ``git archive`` / clean checkout / packaging
    build that drops everything outside the index would ship docs that
    reference missing scripts. Both branches of (a) and (b) are reported
    explicitly so the failure mode is unambiguous; this gate is the
    direct fix for that false-green.

  G3 ``doc_referenced_schemas_exist``:
    Every ``schemas/<name>.schema.json`` reference appearing in the
    same docs must satisfy the same two-part check as G2 — regular file
    on disk AND tracked or staged for tracking.

  G4 ``no_credential_shapes``:
    No runtime DATA file may contain a fully-formed credential shape:
    AWS access key ``AKIA[A-Z0-9]{16}``; PEM ``-----BEGIN ... KEY-----``;
    JWT-shaped triple ``eyJ...[.]eyJ...[.]...``; bearer-token literal
    ``Bearer <long-base64ish>``; inline secret literal
    ``password='...'`` / ``api_key='...'`` / ``secret='...'`` /
    ``private_key='...'``. Scope is the runtime-data surface (schemas/,
    templates/, examples/) — Python scripts under scripts/ are EXEMPT
    because they legitimately ship adversarial deny-list fixtures.

  G5 ``no_external_urls``:
    No runtime DATA file may contain an external URL substring
    (``https?://``, ``s3://``, ``ftp://``, ``file://``, ``data:<lower>``)
    except for a small well-known allow-list: ``$schema`` JSON-Schema
    draft-07 URL inside schemas/*.json, and the W3C SVG / xlink
    namespace URIs inside examples/**/*.svg. Scope is the same runtime-
    data surface as G4 — scripts/*.py are EXEMPT because they
    legitimately ship adversarial URL fixtures and OOXML namespace
    identifiers. For ``schemas/*.json`` ONLY we JSON-parse and walk
    the tree; URL strings that appear under JSON-Schema documentation
    keys (``description`` / ``title`` / ``$comment`` / ``default`` /
    ``examples``) are skipped because those positions document attack
    vectors the schema explicitly refuses (they are never read as
    runtime references — the schema-validation code ignores them). All
    OTHER string positions in a schema are still scanned. This
    JSON-aware skip is INTENTIONALLY scoped to ``schemas/`` because
    those filenames are the only place that vocabulary applies:
    template / example artifacts (``templates/`` / ``examples/``)
    legitimately use ``title`` / ``description`` as real content
    fields (e.g. ``deck_brief.title``, ``deck_plan.sections[].title``,
    ``template.description``). If we applied the doc-key skip there
    too, an attacker could place a runtime URL in a content field
    named ``title`` or ``description`` and pass the gate. For those
    non-schema runtime data files we always text-scan end-to-end so
    every URL surfaces regardless of its surrounding key.

Exit codes:
  0  every gate passed
  1  one or more gates failed
  2  invocation error (bad CLI shape, unreadable file, git not callable)

CLI:
  python3 scripts/verify_skill_package.py             # verify the current repo
  python3 scripts/verify_skill_package.py --root R    # verify a specific root
  python3 scripts/verify_skill_package.py --self-test # run in-script tempfixtures
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


REPO_ROOT_DEFAULT = Path(__file__).resolve().parent.parent

# ----------------------------------------------------------------------
# Forbidden filename / path-component patterns (G1).
# ----------------------------------------------------------------------

FORBIDDEN_NAME_SUFFIXES: tuple[str, ...] = (
    ".pyc", ".pyo", ".pyd",
    ".pptx", ".potx", ".ppsx", ".ppt", ".pot", ".pps",
    ".log", ".tmp",
    ".pem", ".key",
)
FORBIDDEN_BASENAMES: frozenset[str] = frozenset({
    ".DS_Store",
    ".env",
    "pipeline_report.json",
    "pipeline_report.txt",
    "inventory.json",
    "visual_quality.json",
})
FORBIDDEN_BASENAME_PREFIXES: tuple[str, ...] = (
    ".env.",  # .env.local, .env.production, ...
)
# Path components that name forbidden directories anywhere in the surface.
FORBIDDEN_PATH_COMPONENTS: frozenset[str] = frozenset({
    "__pycache__",
    "dist", "build", "out", "output",
    "previews", "renders", "exports", "projects",
    ".git", ".claude", ".ai", ".codex", ".superset",
})

# ----------------------------------------------------------------------
# Doc-referenced reference patterns (G2 / G3).
# ----------------------------------------------------------------------

SCRIPT_REF_RE = re.compile(r"scripts/([A-Za-z0-9_]+)\.py")
SCHEMA_REF_RE = re.compile(r"schemas/([A-Za-z0-9_.\-]+)\.schema\.json")

# Files we treat as documentation sources for doc-referenced scanning.
# These are RELATIVE filenames or globs under --root.
DOC_FILE_BASENAMES: tuple[str, ...] = (
    "SKILL.md", "README.md", "CLAUDE.md", "AGENTS.md",
)
DOC_DIR_NAMES: tuple[str, ...] = (
    "references",
)


# ----------------------------------------------------------------------
# G4 credential-shape regexes. Each pattern is a fully-formed credential
# shape, not a prefix. A prefix-only match (like `AKIA[A-Z0-9]{12,20}` as
# a regex SOURCE string inside a script's deny list) does not satisfy
# these because the script source contains the regex metacharacters
# ``[``, ``]``, ``{``, ``}``, not the literal payload — so the scope of
# this scan is the runtime data surface, where the literal payload is
# the only thing that would appear.
# ----------------------------------------------------------------------

CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("aws_access_key",
        re.compile(r"\bAKIA[A-Z0-9]{16}\b")),
    ("pem_block",
        re.compile(r"-----BEGIN [A-Z ]+ KEY-----")),
    ("jwt_shape",
        re.compile(
            r"\beyJ[A-Za-z0-9_\-]{8,}\.eyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b")),
    ("bearer_token",
        re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.~+/]{20,}\b")),
    ("inline_secret",
        re.compile(
            r"\b(?:password|api[_-]?key|apikey|secret|access[_-]?key|"
            r"client[_-]?secret|private[_-]?key|auth[_-]?token)\s*[:=]\s*"
            r"['\"][^\s'\"]{8,}['\"]",
            flags=re.IGNORECASE)),
)


# ----------------------------------------------------------------------
# G5 external-URL patterns.
# ----------------------------------------------------------------------

EXTERNAL_URL_RE = re.compile(
    r"\b(?:https?|s3|ftp|file)://[^\s\"'<>]+|"
    r"\bdata:[a-z][a-zA-Z0-9+\-/.]*[,;]",
    flags=re.IGNORECASE,
)

# Allow-listed URL substrings — a match that is contained inside one of
# these strings is treated as an XML / JSON-Schema namespace identifier,
# not a runtime-fetched URL. These are NEVER fetched by any code in this
# repo; they are bare schema/namespace identifiers.
URL_ALLOW_SUBSTRINGS: tuple[str, ...] = (
    "http://json-schema.org/draft-07/schema",
    "http://www.w3.org/2000/svg",
    "http://www.w3.org/1999/xlink",
    "http://www.w3.org/XML/1998/namespace",
)


@dataclass
class Finding:
    """One gate violation. Surfaced verbatim in the FAIL output."""
    gate: str
    detail: str
    path: str = ""  # workspace-relative when applicable

    def render(self) -> str:
        if self.path:
            return f"  - [{self.gate}] {self.path}: {self.detail}"
        return f"  - [{self.gate}] {self.detail}"


@dataclass
class GateResult:
    name: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.findings


# ----------------------------------------------------------------------
# Surface enumeration.
# ----------------------------------------------------------------------

def _run_git(root: Path, *args: str) -> list[str]:
    """Call ``git`` with the given args at ``root``. Return stdout lines.

    Raises SystemExit (rc=2) if git is missing or returns non-zero — the
    skill is meant to ship from a git repo; if the caller pointed at a
    non-repo, that is a clean invocation error, not a gate finding.
    """
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"error: 'git' executable not found: {exc}")
    if completed.returncode != 0:
        raise SystemExit(
            f"error: git {' '.join(args)} (cwd={root}) failed rc="
            f"{completed.returncode}: {completed.stderr.strip()}"
        )
    return [line for line in completed.stdout.splitlines() if line]


def enumerate_tracked_or_staged(root: Path) -> set[Path]:
    """Return the set of files tracked or staged-for-tracking at ``root``.

    ``git ls-files`` reports the index, which covers both committed files
    and files added via ``git add`` but not yet committed. So this is
    exactly "tracked or staged for tracking" — the subset of the package
    surface that would survive a clean ``git archive`` / fresh checkout.
    Untracked-not-ignored files (in ``git ls-files --others
    --exclude-standard``) are NOT in this set even though they would be
    in the package surface today, because shipping them would silently
    break the package the moment someone re-derived it from the index.
    """
    return {Path(rel) for rel in _run_git(root, "ls-files")}


def enumerate_package_surface_via_git(root: Path) -> list[Path]:
    """Return the union of tracked and untracked-not-ignored files at
    ``root``, sorted, relative to ``root``."""
    tracked = _run_git(root, "ls-files")
    untracked = _run_git(root, "ls-files", "--others", "--exclude-standard")
    out: set[Path] = set()
    for rel in tracked + untracked:
        out.add(Path(rel))
    return sorted(out)


# ----------------------------------------------------------------------
# G1 — generated-artifact / forbidden-name gate.
# ----------------------------------------------------------------------

def _path_has_forbidden_component(rel: Path) -> str | None:
    for part in rel.parts:
        if part in FORBIDDEN_PATH_COMPONENTS:
            return part
    return None


def _basename_is_forbidden(name: str) -> str | None:
    if name in FORBIDDEN_BASENAMES:
        return f"forbidden filename '{name}'"
    for prefix in FORBIDDEN_BASENAME_PREFIXES:
        if name.startswith(prefix):
            return f"forbidden filename prefix '{prefix}*' ({name})"
    for suffix in FORBIDDEN_NAME_SUFFIXES:
        if name.endswith(suffix):
            return f"forbidden filename suffix '*{suffix}' ({name})"
    return None


def gate_no_generated_artifacts(files: Iterable[Path]) -> GateResult:
    gate = GateResult(name="no_generated_artifacts")
    for rel in files:
        comp = _path_has_forbidden_component(rel)
        if comp is not None:
            gate.findings.append(Finding(
                gate=gate.name,
                detail=f"path contains forbidden component '{comp}'",
                path=str(rel),
            ))
            # A forbidden-component finding is already conclusive for the
            # file; do not also flag the basename — that would be noise.
            continue
        detail = _basename_is_forbidden(rel.name)
        if detail is not None:
            gate.findings.append(Finding(
                gate=gate.name,
                detail=detail,
                path=str(rel),
            ))
    return gate


# ----------------------------------------------------------------------
# G2 / G3 — doc-referenced scripts and schemas.
# ----------------------------------------------------------------------

def _read_text_safely(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _discover_doc_files(root: Path) -> list[Path]:
    """Return the doc files (relative to ``root``) to scan for refs."""
    out: list[Path] = []
    for basename in DOC_FILE_BASENAMES:
        p = root / basename
        if p.is_file() and not p.is_symlink():
            out.append(Path(basename))
    for dirname in DOC_DIR_NAMES:
        d = root / dirname
        if not d.is_dir():
            continue
        for entry in sorted(d.iterdir()):
            if entry.is_symlink():
                continue
            if entry.is_file() and entry.name.endswith(".md"):
                out.append(Path(dirname) / entry.name)
    return out


def _gate_doc_referenced(
    *,
    root: Path,
    tracked_or_staged: set[Path],
    gate_name: str,
    ref_re: re.Pattern[str],
    rel_dir: str,
    rel_suffix: str,
) -> GateResult:
    """Shared G2 / G3 implementation: scan docs for ``<rel_dir>/<stem><rel_suffix>``
    references and require each to (a) exist as a regular file on disk
    and (b) be present in ``tracked_or_staged`` (``git ls-files``)."""
    gate = GateResult(name=gate_name)
    referenced: dict[str, list[str]] = {}
    for rel in _discover_doc_files(root):
        text = _read_text_safely(root / rel)
        if text is None:
            continue
        for match in ref_re.finditer(text):
            stem = match.group(1)
            referenced.setdefault(stem, []).append(str(rel))
    for stem in sorted(referenced):
        rel_target = Path(rel_dir) / f"{stem}{rel_suffix}"
        target = root / rel_target
        sources = sorted(set(referenced[stem]))
        if not target.is_file() or target.is_symlink():
            gate.findings.append(Finding(
                gate=gate.name,
                detail=(
                    f"docs reference {rel_target.as_posix()} but the file "
                    f"is missing or not a regular file (sources: "
                    f"{', '.join(sources)})"
                ),
                path=rel_target.as_posix(),
            ))
            # An on-disk failure already disqualifies the file; do not
            # also report it as untracked — that would be a duplicate
            # finding for the same root cause.
            continue
        if rel_target not in tracked_or_staged:
            gate.findings.append(Finding(
                gate=gate.name,
                detail=(
                    f"docs reference {rel_target.as_posix()} but the file "
                    f"is not tracked or staged for tracking (would drop "
                    f"out of a clean checkout / git archive); run "
                    f"'git add {rel_target.as_posix()}' or remove the "
                    f"reference (sources: {', '.join(sources)})"
                ),
                path=rel_target.as_posix(),
            ))
    return gate


def gate_doc_referenced_scripts(
    root: Path, tracked_or_staged: set[Path]
) -> GateResult:
    return _gate_doc_referenced(
        root=root,
        tracked_or_staged=tracked_or_staged,
        gate_name="doc_referenced_scripts_exist",
        ref_re=SCRIPT_REF_RE,
        rel_dir="scripts",
        rel_suffix=".py",
    )


def gate_doc_referenced_schemas(
    root: Path, tracked_or_staged: set[Path]
) -> GateResult:
    return _gate_doc_referenced(
        root=root,
        tracked_or_staged=tracked_or_staged,
        gate_name="doc_referenced_schemas_exist",
        ref_re=SCHEMA_REF_RE,
        rel_dir="schemas",
        rel_suffix=".schema.json",
    )


# ----------------------------------------------------------------------
# Runtime-data-file scope (G4 / G5 — credentials and URLs).
# ----------------------------------------------------------------------

def _is_runtime_data_file(rel: Path) -> bool:
    """A 'runtime data file' is one that gets read at runtime as DATA —
    not code. The credential and URL scans run only over these because
    Python scripts under scripts/ legitimately ship adversarial deny-list
    fixtures and OOXML namespace identifiers that would otherwise
    false-positive the scans."""
    parts = rel.parts
    if not parts:
        return False
    if parts[0] == "schemas" and rel.suffix == ".json":
        return True
    if parts[0] == "templates":
        # Any file under templates/ is runtime data (theme JSONs, layout
        # JSONs, etc.). Be permissive about extension to also catch any
        # future yaml/toml without changing this gate.
        return True
    if parts[0] == "examples":
        if rel.suffix in (".json", ".md", ".svg", ".txt"):
            return True
        return False
    return False


def _url_match_is_allow_listed(text: str, span: tuple[int, int]) -> bool:
    """Return True iff the matched URL substring is contained inside one
    of the well-known allow-list strings. We check by scanning each
    allow string for a containing occurrence at the same position — a
    full containment, not a prefix match — so a URL that *starts with*
    an allowed prefix but extends past it (e.g. a fake JSON-Schema URL
    with a tail) is still flagged."""
    matched = text[span[0]:span[1]]
    for allowed in URL_ALLOW_SUBSTRINGS:
        if matched == allowed:
            return True
        # Also allow the case where the URL has a trailing fragment '#'
        # that is part of a well-known namespace identifier — e.g.
        # 'http://json-schema.org/draft-07/schema#'. We accept the
        # match only if the matched URL is the allowed substring
        # optionally followed by exactly one '#'.
        if matched == allowed + "#":
            return True
    return False


def gate_no_credential_shapes(root: Path, files: Iterable[Path]) -> GateResult:
    gate = GateResult(name="no_credential_shapes")
    for rel in files:
        if not _is_runtime_data_file(rel):
            continue
        text = _read_text_safely(root / rel)
        if text is None:
            continue
        for label, pat in CREDENTIAL_PATTERNS:
            for match in pat.finditer(text):
                # Compute line for a useful diagnostic.
                line_no = text.count("\n", 0, match.start()) + 1
                gate.findings.append(Finding(
                    gate=gate.name,
                    detail=(
                        f"credential shape '{label}' matched at line "
                        f"{line_no}: '{match.group(0)[:60]}...'"
                        if len(match.group(0)) > 60 else
                        f"credential shape '{label}' matched at line "
                        f"{line_no}: '{match.group(0)}'"
                    ),
                    path=str(rel),
                ))
    return gate


# JSON keys whose string values are documentation, not runtime references.
# Matches the JSON-Schema vocabulary plus a couple of common cousins. A
# URL appearing under one of these keys is treated as security-vector
# documentation (e.g. "the enum lock refuses 'file:///etc/passwd'") and
# is skipped; ALL OTHER positions are still scanned.
JSON_DOC_KEYS: frozenset[str] = frozenset({
    "description", "title", "$comment", "default", "examples",
})


def _scan_text_for_urls(
    text: str,
    rel: Path,
    base_line: int = 1,
) -> list[Finding]:
    findings: list[Finding] = []
    for match in EXTERNAL_URL_RE.finditer(text):
        if _url_match_is_allow_listed(text, match.span()):
            continue
        line_no = base_line + text.count("\n", 0, match.start())
        url = match.group(0)
        findings.append(Finding(
            gate="no_external_urls",
            detail=(
                f"external URL '{url[:80]}...' at line {line_no}"
                if len(url) > 80 else
                f"external URL '{url}' at line {line_no}"
            ),
            path=str(rel),
        ))
    return findings


def _scan_json_for_urls(node, rel: Path, last_key: str | None) -> list[Finding]:
    """Walk a parsed JSON tree. Scan every STRING value with the URL
    regex except those whose containing key is a JSON-Schema doc key.

    The traversal threads ``last_key`` (the key under which ``node`` was
    looked up in its parent dict, or None at the root / inside arrays).
    A string node under a doc key is skipped entirely; arrays inherit
    the parent's last_key so values inside ``examples: [...]`` are also
    skipped. Non-doc keys recurse normally.
    """
    findings: list[Finding] = []
    if isinstance(node, dict):
        for k, v in node.items():
            findings.extend(_scan_json_for_urls(v, rel, last_key=k))
    elif isinstance(node, list):
        for item in node:
            findings.extend(_scan_json_for_urls(item, rel, last_key=last_key))
    elif isinstance(node, str):
        if last_key in JSON_DOC_KEYS:
            return findings
        # Use the small text-scan helper so the same URL regex + allow-
        # list applies. Line numbers are not meaningful inside a JSON
        # value (the original line offset is lost after json.loads), so
        # we report the relative path only with no line; the snippet
        # makes the offending field findable by grep.
        for match in EXTERNAL_URL_RE.finditer(node):
            if _url_match_is_allow_listed(node, match.span()):
                continue
            url = match.group(0)
            findings.append(Finding(
                gate="no_external_urls",
                detail=(
                    f"external URL '{url[:80]}...' under JSON key '{last_key}'"
                    if len(url) > 80 else
                    f"external URL '{url}' under JSON key '{last_key}'"
                ),
                path=str(rel),
            ))
    return findings


def _is_schema_file(rel: Path) -> bool:
    """The JSON-doc-key skip applies ONLY to JSON-Schema files. Those
    live under ``schemas/`` and use ``description`` / ``title`` /
    ``$comment`` / ``default`` / ``examples`` as documentation
    vocabulary. Template / example artifacts (``templates/`` /
    ``examples/``) use those same key names as REAL content fields
    (e.g. ``deck_brief.title``, ``deck_plan.sections[].title``,
    ``template.description``), so applying the skip there would let an
    attacker hide a runtime URL in a content field. Restricting the
    skip to ``schemas/`` closes that hole while still allowing the
    legitimate ``"file:///etc/passwd"`` security-doc strings inside
    schema descriptions."""
    return bool(rel.parts) and rel.parts[0] == "schemas" and rel.suffix == ".json"


def gate_no_external_urls(root: Path, files: Iterable[Path]) -> GateResult:
    gate = GateResult(name="no_external_urls")
    for rel in files:
        if not _is_runtime_data_file(rel):
            continue
        text = _read_text_safely(root / rel)
        if text is None:
            continue
        if _is_schema_file(rel):
            # JSON-aware scan: schema files document attack-vector URLs
            # under description / title / $comment / default / examples.
            # All other key positions are still scanned.
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                # A malformed schema is itself a problem; fall back to
                # the text scan so URLs still surface rather than be
                # silently missed because of a parse error.
                gate.findings.extend(_scan_text_for_urls(text, rel))
            else:
                gate.findings.extend(
                    _scan_json_for_urls(parsed, rel, last_key=None)
                )
        else:
            # Templates and examples: text-scan end-to-end. The
            # doc-key skip does NOT apply because these files use
            # title / description as real content.
            gate.findings.extend(_scan_text_for_urls(text, rel))
    return gate


# ----------------------------------------------------------------------
# Composite verifier.
# ----------------------------------------------------------------------

@dataclass
class VerificationReport:
    root: Path
    files: list[Path]
    gates: list[GateResult]

    @property
    def ok(self) -> bool:
        return all(g.ok for g in self.gates)

    def render(self) -> str:
        lines: list[str] = []
        for g in self.gates:
            tag = "PASS" if g.ok else "FAIL"
            lines.append(f"[{tag}] {g.name}")
            for f in g.findings:
                lines.append(f.render())
        return "\n".join(lines)


def verify(root: Path, files: list[Path]) -> VerificationReport:
    """Run every readiness gate against ``root`` / ``files``.

    ``tracked_or_staged`` is recomputed from ``git ls-files`` here rather
    than passed in so the call site signature stays minimal and so the
    real-repo and self-test paths share one source of truth. The self-
    test ``git init``s its tempfixture before calling, so this works
    uniformly across both paths.
    """
    tracked_or_staged = enumerate_tracked_or_staged(root)
    gates: list[GateResult] = []
    gates.append(gate_no_generated_artifacts(files))
    gates.append(gate_doc_referenced_scripts(root, tracked_or_staged))
    gates.append(gate_doc_referenced_schemas(root, tracked_or_staged))
    gates.append(gate_no_credential_shapes(root, files))
    gates.append(gate_no_external_urls(root, files))
    return VerificationReport(root=root, files=files, gates=gates)


# ----------------------------------------------------------------------
# Real-repo entry point.
# ----------------------------------------------------------------------

def _resolve_root(arg_root: Path | None) -> Path:
    candidate = arg_root.resolve() if arg_root is not None else REPO_ROOT_DEFAULT
    if not candidate.is_dir():
        raise SystemExit(f"error: --root is not a directory: {candidate}")
    return candidate


def _run_real(root: Path) -> int:
    files = enumerate_package_surface_via_git(root)
    if not files:
        # An empty surface is itself a packaging readiness FAIL — every
        # gate would vacuously pass but there is nothing to ship.
        print(f"FAIL: empty package surface under {root}", file=sys.stderr)
        return 1
    report = verify(root, files)
    print(f"Package surface: {len(files)} file(s) under {root}")
    print(report.render())
    print()
    if report.ok:
        print("OK: every readiness gate passed.")
    else:
        fails = sum(1 for g in report.gates if not g.ok)
        print(f"FAIL: {fails} readiness gate(s) failed.", file=sys.stderr)
    print(
        "Note: live Qoder runtime import / runtime packaging is "
        "UNVERIFIED here (and remains TODO across the wider repo). "
        "This verifier only checks the static package surface."
    )
    return 0 if report.ok else 1


# ----------------------------------------------------------------------
# Self-test scenarios.
# ----------------------------------------------------------------------

@dataclass
class ScenarioResult:
    name: str
    ok: bool
    detail: str = ""


def _write(p: Path, content: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def _git_init_quiet(root: Path) -> None:
    """Initialize an ephemeral git repo at ``root`` for the self-test.

    The verifier's real-repo path enumerates the surface via ``git
    ls-files`` and ``git ls-files --others --exclude-standard``, and the
    G2 / G3 tracked-or-staged check requires a real index. Self-test
    fixtures must therefore live in a real (but ephemeral) git index so
    both paths exercise the same code. ``--initial-branch=main`` keeps
    behavior deterministic on hosts whose ``init.defaultBranch`` is
    unset or different. user.email / user.name are pinned locally so a
    later ``commit`` would not require ambient git identity — we do not
    commit here, but we make staging cost-free regardless of host
    config.
    """
    _run_git(root, "init", "--quiet", "--initial-branch=main")
    _run_git(root, "config", "user.email", "selftest@example.invalid")
    _run_git(root, "config", "user.name", "verify_skill_package self-test")


def _baseline_fixture(root: Path) -> None:
    """Write a minimal package surface that passes every gate AND stage
    it into a fresh git index so the G2 / G3 tracked-or-staged check
    has a real ``git ls-files`` to consult.

    Contains: SKILL.md / README.md / one references/*.md naming a real
    scripts/<x>.py + schemas/<y>.schema.json; the corresponding script
    body; the corresponding schema with a $schema URL (allowed by G5);
    a template JSON with no URLs; an example JSON with no URLs / creds;
    an example SVG carrying only the W3C SVG namespace (allowed by G5).

    The git index is staged here so that callers can subsequently write
    "extra" files which remain untracked-not-ignored by default —
    that's how the negative scenarios exercise the new tracked-or-
    staged gate without manual ``git add`` plumbing in every test.
    """
    # Scripts (G2 source).
    _write(root / "scripts" / "real_helper.py", "# stdlib only\n")
    # Schemas (G3 source). One $schema URL (allow-listed).
    _write(root / "schemas" / "fake.schema.json", json.dumps({
        "$schema": "http://json-schema.org/draft-07/schema#",
        "type": "object",
    }, indent=2) + "\n")
    # Templates: no URLs, no credentials.
    _write(root / "templates" / "layouts" / "demo" / "template.json", json.dumps({
        "name": "demo",
        "layouts": ["cover"],
    }, indent=2) + "\n")
    # Examples: an SVG with only the W3C namespace (allow-listed).
    _write(root / "examples" / "demo_workspace" / "svg_previews" / "01_cover.svg",
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"></svg>\n')
    _write(root / "examples" / "demo_workspace" / "deck_brief.json", json.dumps({
        "title": "Demo",
        "audience": "internal",
        "objective": "demo",
        "source_refs": ["demo_id"],
    }, indent=2) + "\n")
    # Top-level docs (G2 / G3 sources).
    _write(root / "SKILL.md",
        "# SKILL\n"
        "Uses scripts/real_helper.py and schemas/fake.schema.json.\n")
    _write(root / "README.md", "# README\n")
    _write(root / "CLAUDE.md", "# CLAUDE\n")
    _write(root / "references" / "verify.md",
        "References scripts/real_helper.py.\n")
    # Stage the baseline so ``git ls-files`` reports it. We don't
    # commit — the index is enough for both surface enumerators and the
    # tracked-or-staged check.
    _git_init_quiet(root)
    _run_git(root, "add", "-A")


def _run_gate_on_fixture(root: Path) -> VerificationReport:
    files = enumerate_package_surface_via_git(root)
    return verify(root, files)


def _scenario_baseline_pass() -> ScenarioResult:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _baseline_fixture(root)
        report = _run_gate_on_fixture(root)
        if not report.ok:
            return ScenarioResult(
                name="baseline_passes",
                ok=False,
                detail="baseline fixture should pass every gate; got: "
                       + "; ".join(
                           f"{f.gate}: {f.detail}"
                           for g in report.gates if not g.ok
                           for f in g.findings),
            )
        return ScenarioResult(name="baseline_passes", ok=True)


def _scenario_neg(
    name: str,
    write_extras,
    expected_gate: str,
) -> ScenarioResult:
    """Build a baseline + extra files, then assert the named gate fails."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        _baseline_fixture(root)
        write_extras(root)
        report = _run_gate_on_fixture(root)
        bad = [g for g in report.gates if not g.ok]
        if not bad:
            return ScenarioResult(
                name=name, ok=False,
                detail=f"expected gate '{expected_gate}' to fail but every "
                       "gate passed",
            )
        bad_names = sorted(g.name for g in bad)
        if expected_gate not in bad_names:
            return ScenarioResult(
                name=name, ok=False,
                detail=f"expected gate '{expected_gate}' to fail but "
                       f"failing gates were {bad_names}",
            )
        # Every OTHER gate must still pass — we don't want a fixture
        # that accidentally trips multiple gates and masks regressions.
        others = [g.name for g in bad if g.name != expected_gate]
        if others:
            return ScenarioResult(
                name=name, ok=False,
                detail=f"expected only '{expected_gate}' to fail; also "
                       f"failed: {sorted(set(others))}",
            )
        return ScenarioResult(name=name, ok=True)


def _scenarios() -> list[ScenarioResult]:
    out: list[ScenarioResult] = []
    out.append(_scenario_baseline_pass())

    # G1 negatives
    out.append(_scenario_neg(
        "g1_pycache",
        lambda r: _write(r / "scripts" / "__pycache__" / "x.cpython-313.pyc", "junk\n"),
        "no_generated_artifacts",
    ))
    out.append(_scenario_neg(
        "g1_pptx",
        lambda r: _write(r / "examples" / "demo_workspace" / "deck.pptx", "PK fake\n"),
        "no_generated_artifacts",
    ))
    out.append(_scenario_neg(
        "g1_pipeline_report",
        lambda r: _write(r / "pipeline_report.json", "{}\n"),
        "no_generated_artifacts",
    ))
    out.append(_scenario_neg(
        "g1_pipeline_report_txt",
        lambda r: _write(r / "pipeline_report.txt", "ok\n"),
        "no_generated_artifacts",
    ))
    out.append(_scenario_neg(
        "g1_inventory_json",
        lambda r: _write(r / "examples" / "demo_workspace" / "inventory.json", "{}\n"),
        "no_generated_artifacts",
    ))
    out.append(_scenario_neg(
        "g1_visual_quality_json",
        lambda r: _write(r / "examples" / "demo_workspace" / "visual_quality.json", "{}\n"),
        "no_generated_artifacts",
    ))
    out.append(_scenario_neg(
        "g1_log",
        lambda r: _write(r / "run.log", "info\n"),
        "no_generated_artifacts",
    ))
    out.append(_scenario_neg(
        "g1_tmp",
        lambda r: _write(r / "draft.tmp", "drafty\n"),
        "no_generated_artifacts",
    ))
    out.append(_scenario_neg(
        "g1_ds_store",
        lambda r: _write(r / "examples" / "demo_workspace" / ".DS_Store", "macjunk\n"),
        "no_generated_artifacts",
    ))
    out.append(_scenario_neg(
        "g1_env_dot",
        lambda r: _write(r / ".env", "FOO=bar\n"),
        "no_generated_artifacts",
    ))
    out.append(_scenario_neg(
        "g1_env_local",
        lambda r: _write(r / ".env.local", "FOO=bar\n"),
        "no_generated_artifacts",
    ))
    out.append(_scenario_neg(
        "g1_pem",
        lambda r: _write(r / "scripts" / "leak.pem", "blob\n"),
        "no_generated_artifacts",
    ))
    out.append(_scenario_neg(
        "g1_key",
        lambda r: _write(r / "leak.key", "blob\n"),
        "no_generated_artifacts",
    ))
    out.append(_scenario_neg(
        "g1_dist_dir",
        lambda r: _write(r / "dist" / "skill.zip", "zipdata\n"),
        "no_generated_artifacts",
    ))
    out.append(_scenario_neg(
        "g1_projects_dir",
        lambda r: _write(r / "projects" / "leakage" / "deck_plan.json", "{}\n"),
        "no_generated_artifacts",
    ))
    # G1 path-component defense for ``.git``. The git-based surface
    # enumerator never reports paths under ``.git/`` (git filters its
    # own internals), so a ``.git/HEAD`` injected into the tempfixture
    # is unreachable via the normal pipeline. The check is kept in
    # FORBIDDEN_PATH_COMPONENTS as defense-in-depth — if any future
    # caller used a non-git enumerator (e.g. walk-based) and leaked a
    # ``.git/`` path into the surface, G1 must still flag it.
    # Exercise the gate function directly with a synthetic file list
    # so that defense remains observable in the self-test.
    def _g1_git_dir_run() -> ScenarioResult:
        synthetic: list[Path] = [Path(".git/HEAD"), Path("SKILL.md")]
        gate = gate_no_generated_artifacts(synthetic)
        for f in gate.findings:
            if ".git" in Path(f.path).parts:
                return ScenarioResult(name="g1_git_dir_defense", ok=True)
        return ScenarioResult(
            name="g1_git_dir_defense",
            ok=False,
            detail=(
                "gate_no_generated_artifacts did not flag '.git/HEAD' as "
                f"a forbidden path component; findings: "
                f"{[(f.path, f.detail) for f in gate.findings]}"
            ),
        )
    out.append(_g1_git_dir_run())

    # G2 negative: doc names a script that doesn't exist on disk.
    def _g2_inject(r: Path) -> None:
        _write(r / "SKILL.md",
               "Uses scripts/real_helper.py AND scripts/missing_one.py.\n")
    out.append(_scenario_neg(
        "g2_missing_script",
        _g2_inject,
        "doc_referenced_scripts_exist",
    ))

    # G3 negative: doc names a schema that doesn't exist on disk.
    def _g3_inject(r: Path) -> None:
        _write(r / "references" / "extra.md",
               "References schemas/ghost.schema.json.\n")
    out.append(_scenario_neg(
        "g3_missing_schema",
        _g3_inject,
        "doc_referenced_schemas_exist",
    ))

    # G4 credential shapes.
    out.append(_scenario_neg(
        "g4_aws_key",
        lambda r: _write(
            r / "examples" / "demo_workspace" / "input" / "source.md",
            "leak AKIA" + "ABCDEFGHIJKLMNOP" + "\n",  # 16 caps after AKIA
        ),
        "no_credential_shapes",
    ))
    out.append(_scenario_neg(
        "g4_pem_block",
        lambda r: _write(
            r / "examples" / "demo_workspace" / "input" / "source.md",
            "embedded:\n-----BEGIN PRIVATE KEY-----\nMIIE...\n",
        ),
        "no_credential_shapes",
    ))
    out.append(_scenario_neg(
        "g4_jwt",
        lambda r: _write(
            r / "examples" / "demo_workspace" / "input" / "source.md",
            "token eyJhbGciOiJIUzI1NiJ.eyJzdWIiOiIxMjM0NTY3.SflKxwR-JSMeKK\n",
        ),
        "no_credential_shapes",
    ))
    out.append(_scenario_neg(
        "g4_bearer",
        lambda r: _write(
            r / "examples" / "demo_workspace" / "input" / "source.md",
            "auth Bearer abcdefghijklmnopqrstuvwxyz\n",
        ),
        "no_credential_shapes",
    ))
    out.append(_scenario_neg(
        "g4_inline_secret",
        lambda r: _write(
            r / "examples" / "demo_workspace" / "input" / "source.md",
            'config password="topsecret9"\n',
        ),
        "no_credential_shapes",
    ))

    # G5 external URLs in runtime data files.
    out.append(_scenario_neg(
        "g5_https_in_template",
        lambda r: _write(
            r / "templates" / "layouts" / "demo" / "config.json",
            json.dumps({"endpoint": "https://api.example.com/v1"}, indent=2),
        ),
        "no_external_urls",
    ))
    out.append(_scenario_neg(
        "g5_file_in_example_json",
        lambda r: _write(
            r / "examples" / "demo_workspace" / "leak.json",
            json.dumps({"local": "file:///etc/passwd"}, indent=2),
        ),
        "no_external_urls",
    ))
    out.append(_scenario_neg(
        "g5_data_uri_in_example_md",
        lambda r: _write(
            r / "examples" / "demo_workspace" / "input" / "source.md",
            "embedded data:text/plain;base64,YWFh\n",
        ),
        "no_external_urls",
    ))
    out.append(_scenario_neg(
        "g5_s3_uri",
        lambda r: _write(
            r / "examples" / "demo_workspace" / "leak.json",
            json.dumps({"src": "s3://bucket/key"}, indent=2),
        ),
        "no_external_urls",
    ))

    # G5 positive ALLOW-LIST regression: an SVG with the canonical W3C
    # namespace plus a JSON $schema URL must NOT fail any gate. Baseline
    # already exercises this; here we add a second SVG file to be sure
    # the allow-list works on multiple files.
    def _g5_allow_extra(r: Path) -> None:
        _write(r / "examples" / "demo_workspace" / "svg_previews" / "02_cover.svg",
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'xmlns:xlink="http://www.w3.org/1999/xlink" '
            'viewBox="0 0 10 10"></svg>\n')

    def _g5_allow_run() -> ScenarioResult:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _baseline_fixture(root)
            _g5_allow_extra(root)
            report = _run_gate_on_fixture(root)
            if not report.ok:
                return ScenarioResult(
                    name="g5_allow_list_w3c_namespaces",
                    ok=False,
                    detail="allow-listed SVG namespace URLs incorrectly flagged: "
                           + "; ".join(
                               f"{f.gate}: {f.path}: {f.detail}"
                               for g in report.gates if not g.ok
                               for f in g.findings),
                )
            return ScenarioResult(name="g5_allow_list_w3c_namespaces", ok=True)
    out.append(_g5_allow_run())

    # G5 JSON-doc-key skip — URLs inside JSON-Schema documentation
    # strings ('description' / 'title' / '$comment' / 'default' /
    # 'examples') are security-vector documentation and must be
    # ignored.
    def _g5_doc_url_run() -> ScenarioResult:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _baseline_fixture(root)
            _write(
                root / "schemas" / "doc_url.schema.json",
                json.dumps({
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "type": "object",
                    "description": (
                        "Unsafe values like 'file:///etc/passwd' or "
                        "'https://attacker.example' are refused."
                    ),
                    "properties": {
                        "src": {
                            "type": "string",
                            "description": "May not be 'data:text/plain'.",
                            "examples": ["file:///etc/passwd"],
                        }
                    },
                }, indent=2) + "\n",
            )
            report = _run_gate_on_fixture(root)
            if not report.ok:
                return ScenarioResult(
                    name="g5_json_doc_keys_skipped",
                    ok=False,
                    detail="URLs inside JSON-Schema doc keys were flagged; "
                           "got: " + "; ".join(
                               f"{f.gate}: {f.path}: {f.detail}"
                               for g in report.gates if not g.ok
                               for f in g.findings),
                )
            return ScenarioResult(name="g5_json_doc_keys_skipped", ok=True)
    out.append(_g5_doc_url_run())

    # G5 negative: same URL value, but placed under a NON-doc key →
    # must still fire. Proves we did not over-broaden the skip list.
    def _g5_value_url(r: Path) -> None:
        _write(
            r / "examples" / "demo_workspace" / "value_url.json",
            json.dumps({"endpoint": "https://attacker.example/v1"}, indent=2),
        )
    out.append(_scenario_neg(
        "g5_value_url_still_caught",
        _g5_value_url,
        "no_external_urls",
    ))

    # G5 negative: URL placed under a key NAMED 'title' / 'description'
    # in a NON-schema (template / example) JSON. The JSON-Schema doc-key
    # skip MUST NOT apply here, because templates and examples use
    # 'title' / 'description' as REAL content fields. Without the
    # _is_schema_file() restriction this regression would false-green
    # the URL.
    def _g5_title_in_example(r: Path) -> None:
        _write(
            r / "examples" / "demo_workspace" / "deck_brief.json",
            json.dumps({
                "title": "https://attacker.example/leak",
                "audience": "internal",
                "objective": "demo",
                "source_refs": ["demo_id"],
            }, indent=2) + "\n",
        )
    out.append(_scenario_neg(
        "g5_title_in_example_still_caught",
        _g5_title_in_example,
        "no_external_urls",
    ))
    def _g5_description_in_template(r: Path) -> None:
        _write(
            r / "templates" / "layouts" / "demo" / "template.json",
            json.dumps({
                "name": "demo",
                "description": "see https://attacker.example/leak",
                "layouts": ["cover"],
            }, indent=2) + "\n",
        )
    out.append(_scenario_neg(
        "g5_description_in_template_still_caught",
        _g5_description_in_template,
        "no_external_urls",
    ))

    # Hostile URL that STARTS WITH an allow-listed prefix but extends
    # past it — must still be flagged.
    def _g5_tail_run() -> ScenarioResult:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _baseline_fixture(root)
            _write(
                root / "examples" / "demo_workspace" / "leak.svg",
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<svg xmlns="http://www.w3.org/2000/svg/EVIL" '
                'viewBox="0 0 1 1"></svg>\n',
            )
            report = _run_gate_on_fixture(root)
            bad = [g for g in report.gates if not g.ok]
            if "no_external_urls" not in [g.name for g in bad]:
                return ScenarioResult(
                    name="g5_allow_list_tail_attack",
                    ok=False,
                    detail="extended-tail URL was not flagged; failing gates "
                           f"were {[g.name for g in bad]}",
                )
            return ScenarioResult(name="g5_allow_list_tail_attack", ok=True)
    out.append(_g5_tail_run())

    # Empty surface → FAIL (real-repo path; covered by the
    # _run_real() return rather than the gate suite, but we still
    # exercise the gate suite against an empty surface here to confirm
    # it reports cleanly). An empty git repo has zero ``ls-files``
    # output, so the surface is [], every gate has nothing to iterate,
    # and the report is vacuously clean.
    def _g_empty_run() -> ScenarioResult:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _git_init_quiet(root)
            report = _run_gate_on_fixture(root)
            if not report.ok:
                return ScenarioResult(
                    name="empty_surface_no_findings",
                    ok=False,
                    detail="empty surface should produce no gate findings; "
                           "got: " + "; ".join(
                               f"{f.gate}: {f.detail}"
                               for g in report.gates if not g.ok
                               for f in g.findings),
                )
            return ScenarioResult(name="empty_surface_no_findings", ok=True)
    out.append(_g_empty_run())

    # --------------------------------------------------------------
    # False-green fix coverage (G2 / G3 tracked-or-staged check).
    # --------------------------------------------------------------
    # Bug pre-fix: ``gate_doc_referenced_scripts`` accepted ANY regular
    # file at scripts/<name>.py, even if it was untracked or
    # gitignored. A clean ``git archive`` / fresh checkout would drop
    # that file, leaving the shipped docs referencing a missing path.
    # These scenarios pin the fix in both directions:
    #   - docs naming an untracked script must FAIL G2;
    #   - docs naming an explicitly staged script must PASS;
    #   - same pair for schemas under G3;
    #   - a gitignored docs-referenced script must also FAIL G2 (the
    #     file is on disk but unshipping — same false-green shape).

    # G2 — docs reference scripts/untracked_one.py; the file is on disk
    # but never ``git add``-ed → must fail G2 (and ONLY G2).
    def _g2_untracked_inject(r: Path) -> None:
        # Write the script AFTER the baseline staged the rest of the
        # tree. Note: we intentionally do NOT ``git add`` it.
        _write(r / "scripts" / "untracked_one.py", "# would not ship\n")
        # Overwrite SKILL.md to reference the new untracked script.
        # SKILL.md itself is already tracked (staged by the baseline);
        # editing it in the working tree without re-staging is fine —
        # the verifier reads docs from disk, not from the index.
        _write(r / "SKILL.md",
               "# SKILL\n"
               "Uses scripts/real_helper.py and schemas/fake.schema.json "
               "and scripts/untracked_one.py.\n")
    out.append(_scenario_neg(
        "g2_untracked_script_present_fails",
        _g2_untracked_inject,
        "doc_referenced_scripts_exist",
    ))

    # G2 — same shape, but the new script IS staged via ``git add``
    # → must pass every gate. Proves the gate accepts shipping files
    # and only rejects unshipping ones.
    def _g2_staged_pass_run() -> ScenarioResult:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _baseline_fixture(root)
            _write(root / "scripts" / "staged_one.py", "# would ship\n")
            _write(root / "SKILL.md",
                   "# SKILL\n"
                   "Uses scripts/real_helper.py and schemas/fake.schema.json "
                   "and scripts/staged_one.py.\n")
            # Stage both the new script and the updated SKILL.md so
            # the working tree matches the index exactly — this is the
            # "did the right thing" path a developer takes after
            # adding a new script.
            _run_git(root, "add", "scripts/staged_one.py", "SKILL.md")
            report = _run_gate_on_fixture(root)
            if not report.ok:
                return ScenarioResult(
                    name="g2_staged_script_present_passes",
                    ok=False,
                    detail="staged docs-referenced script should pass; got: "
                           + "; ".join(
                               f"{f.gate}: {f.path}: {f.detail}"
                               for g in report.gates if not g.ok
                               for f in g.findings),
                )
            return ScenarioResult(
                name="g2_staged_script_present_passes", ok=True)
    out.append(_g2_staged_pass_run())

    # G2 — docs reference scripts/ignored_one.py; the file is on disk
    # but is gitignored via a tracked .gitignore. Like the untracked
    # case, this would not ship from a clean checkout, so G2 must fail.
    def _g2_ignored_run() -> ScenarioResult:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _baseline_fixture(root)
            _write(root / ".gitignore", "scripts/ignored_one.py\n")
            _run_git(root, "add", ".gitignore")
            _write(root / "scripts" / "ignored_one.py",
                   "# locally-built, never shipped\n")
            _write(root / "SKILL.md",
                   "# SKILL\n"
                   "Uses scripts/real_helper.py and schemas/fake.schema.json "
                   "and scripts/ignored_one.py.\n")
            report = _run_gate_on_fixture(root)
            bad = [g for g in report.gates if not g.ok]
            bad_names = sorted(g.name for g in bad)
            if "doc_referenced_scripts_exist" not in bad_names:
                return ScenarioResult(
                    name="g2_gitignored_script_present_fails",
                    ok=False,
                    detail=f"expected G2 to fail on a gitignored docs-"
                           f"referenced script; failing gates: {bad_names}",
                )
            others = [n for n in bad_names if n != "doc_referenced_scripts_exist"]
            if others:
                return ScenarioResult(
                    name="g2_gitignored_script_present_fails",
                    ok=False,
                    detail=f"only G2 should fail; also failed: {others}",
                )
            return ScenarioResult(
                name="g2_gitignored_script_present_fails", ok=True)
    out.append(_g2_ignored_run())

    # G3 — docs reference schemas/untracked.schema.json; the file is on
    # disk but never ``git add``-ed → must fail G3 (and ONLY G3).
    def _g3_untracked_inject(r: Path) -> None:
        _write(
            r / "schemas" / "untracked.schema.json",
            json.dumps({
                "$schema": "http://json-schema.org/draft-07/schema#",
                "type": "object",
            }, indent=2) + "\n",
        )
        _write(r / "SKILL.md",
               "# SKILL\n"
               "Uses scripts/real_helper.py and schemas/fake.schema.json "
               "and schemas/untracked.schema.json.\n")
    out.append(_scenario_neg(
        "g3_untracked_schema_present_fails",
        _g3_untracked_inject,
        "doc_referenced_schemas_exist",
    ))

    # G3 — same shape, schema IS staged → must pass.
    def _g3_staged_pass_run() -> ScenarioResult:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _baseline_fixture(root)
            _write(
                root / "schemas" / "staged.schema.json",
                json.dumps({
                    "$schema": "http://json-schema.org/draft-07/schema#",
                    "type": "object",
                }, indent=2) + "\n",
            )
            _write(root / "SKILL.md",
                   "# SKILL\n"
                   "Uses scripts/real_helper.py and schemas/fake.schema.json "
                   "and schemas/staged.schema.json.\n")
            _run_git(root, "add", "schemas/staged.schema.json", "SKILL.md")
            report = _run_gate_on_fixture(root)
            if not report.ok:
                return ScenarioResult(
                    name="g3_staged_schema_present_passes",
                    ok=False,
                    detail="staged docs-referenced schema should pass; got: "
                           + "; ".join(
                               f"{f.gate}: {f.path}: {f.detail}"
                               for g in report.gates if not g.ok
                               for f in g.findings),
                )
            return ScenarioResult(
                name="g3_staged_schema_present_passes", ok=True)
    out.append(_g3_staged_pass_run())

    return out


def _print_scenarios(results: list[ScenarioResult]) -> int:
    width = max((len(r.name) for r in results), default=0)
    fails = 0
    for r in results:
        tag = "PASS" if r.ok else "FAIL"
        print(f"  [{tag}] {r.name.ljust(width)}  {r.detail}".rstrip())
        if not r.ok:
            fails += 1
    print()
    if fails:
        print(f"FAIL: {fails} self-test scenario(s) did not behave as "
              f"expected.", file=sys.stderr)
        return 1
    print(f"OK: {len(results)} self-test scenario(s) passed.")
    print(
        "Note: live Qoder runtime import / runtime packaging is "
        "UNVERIFIED here (and remains TODO across the wider repo). "
        "The self-test only exercises the static package surface."
    )
    return 0


# ----------------------------------------------------------------------
# CLI.
# ----------------------------------------------------------------------

def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stdlib-only readiness verifier for the internal skill "
            "package. Verify-only — does not build a zip. Does not "
            "import or call Qoder, MCP, public network, telemetry, "
            "model APIs, image search, or any external service."
        ),
    )
    parser.add_argument(
        "--root", type=Path, default=None,
        help="Repo root to verify (default: this script's parent's parent).",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios under TMPDIR.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if args.root is not None:
            print(
                "FAIL: --self-test does not take any other argument "
                "(got --root). Run them as separate invocations.",
                file=sys.stderr,
            )
            return 2
        results = _scenarios()
        return _print_scenarios(results)

    root = _resolve_root(args.root)
    return _run_real(root)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
