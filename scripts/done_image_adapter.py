#!/usr/bin/env python3
"""D-One adapter contract stub (NOT D-One integration).

This is the narrow contract a future local D-One asset generator will
have to satisfy before it ships. The adapter today:

  - reads ``<workspace>/image_manifest.json`` (the Stage-6 artifact
    ``scripts/init_image_manifest.py`` writes — or a hand-authored
    equivalent);
  - reads an EXPLICIT caller-supplied ``--spec`` JSON file listing the
    asset ids the caller wants generated plus a safety-scrubbed prompt
    for each;
  - validates every requested ``id`` matches an entry in
    ``image_manifest.images[]`` whose ``source == "d_one_local"`` (so
    a caller cannot smuggle a request for a ``local_asset`` /
    ``synthetic`` entry into the D-One channel);
  - scans every prompt against a defense-in-depth deny list — URI
    schemes, absolute / traversal file paths, raw-source markers
    (``<SOURCE>`` / ``BEGIN SOURCE`` / ...), every 40-character
    substring of ``input/source.md`` (when present in the workspace),
    credential shapes (bearer tokens, JWTs, AWS access keys, long hex
    blobs, ``-----BEGIN`` PEM markers, ``password:`` / ``secret:`` /
    ``api_key:`` / ``token:`` literals), customer / account /
    contact-id shapes (emails, phone numbers, SSN-like strings, UUIDs,
    explicit ``customer_id`` / ``account_id`` literals), AND full-slide
    / page-generation / screenshot wording (a D-One asset is a local
    supporting illustration, never the slide itself), AND public-
    distribution wording (``upload to public`` / ``public upload`` /
    ``share publicly`` / ``public hosting`` / ``publish to web`` /
    ``public url`` / ``public link`` / ``public cdn`` and the
    obvious variants — a D-One asset is local-only and may not be
    uploaded, published, shared, or hosted publicly);
  - writes a deterministic dry-run plan to
    ``<workspace>/d_one_adapter_plan.json`` (or ``--plan-out``)
    recording the validated requests for downstream hand-off.

**This is a contract STUB, not real D-One integration.** The helper
deliberately does NOT:

  - call D-One / Qoder / any image-generation model / any public
    network / any external service — the only thing it writes is the
    deterministic plan file;
  - generate any image bytes (PNG / JPG / JPEG / SVG / GIF / WebP);
  - mutate ``image_manifest.json`` (the manifest bytes must be
    byte-identical before and after a successful run);
  - parse any business content out of ``input/source.md`` (only its
    raw bytes are read, and only for the 40-character shingle check);
  - generate full-slide screenshots or any whole-slide imagery;
  - emit ``render_models/*``, ``svg_previews/*``, or any ``.pptx``;
  - change PPTX export behavior in any way;
  - chain into ``scripts/materialize_image_assets.py`` — that handoff
    is intentionally deferred until a real generator writes asset
    bytes the materialize gate can verify.

When real D-One integration ships, it will plug in UPSTREAM of
``materialize_image_assets.py`` and DOWNSTREAM of this stub: D-One
consumes the validated plan file this stub produces, produces local
PNG / JPG / JPEG bytes under a controlled local directory, and
materialize then either copies those bytes into the workspace or
verifies the pre-existing target in place.

Stdlib-only. Deterministic — given the same workspace + spec + plan
path, the resulting plan-file bytes are byte-identical across runs
(the plan content is a sorted, schema-fixed projection of the spec
plus the manifest cross-references; nothing derived from clock,
environment, or file order ends up in the artifact).

Fail-closed gates (every gate aborts the run; nothing is written
when any gate fires):

  --workspace
    * must be an existing directory; URI-shaped values refused;
      the workspace itself must not be a symlink (broken or
      resolvable);
    * must ship ``image_manifest.json`` as a regular non-symlink
      file that parses as JSON, decodes to an object, and validates
      against ``schemas/image_manifest.schema.json``;
    * no two ``images[*].id`` values may be equal
      (defense-in-depth; ``init_image_manifest`` already refuses
      this on the producer side);
    * every ``images[*].local_path`` must pass
      ``validate_scaffold.local_path_is_safe`` AND resolve inside
      ``--workspace`` (defense-in-depth; the schema +
      ``validate_workspace`` + ``init_image_manifest`` already apply
      the same gate);
    * ``input/source.md`` is read only if it exists as a regular
      non-symlink file under the workspace — a missing source body
      is acceptable (skips the shingle check); a symlinked source
      body aborts the run.

  --spec
    * must be an existing regular file; URI-shaped values refused;
      symlinks (broken or resolvable) refused;
    * must parse as JSON and decode to an object;
    * must contain a non-empty ``requests`` list whose every entry
      is an object with required keys ``id`` (non-empty string) and
      ``prompt`` (non-empty string), optional keys ``intended_use``
      (string), ``width_px`` (positive int), ``height_px`` (positive
      int), and no other keys;
    * no two requests may share an ``id``;
    * every request ``id`` must appear in ``image_manifest.images[*]``
      with ``source == "d_one_local"``;
    * every request ``prompt`` must pass the full forbidden-pattern
      scan (see module-level constants for the exact patterns —
      URIs, file paths, raw-source markers, 40-char input/source.md
      shingles, credentials, customer/account/contact ids,
      full-slide / page / screenshot wording, AND public-distribution
      wording);
    * every request ``intended_use`` (if present) must not contain
      full-slide / screenshot / page-generation wording.

  --plan-out (defaults to ``<workspace>/d_one_adapter_plan.json``)
    * must pass ``local_path_is_safe`` when resolved as a workspace-
      relative path (no leading slash / no URI scheme / no ``..``);
    * must resolve inside ``--workspace`` (defense-in-depth via
      ``_resolves_within`` after ``Path.resolve()``);
    * must NOT already exist as a symlink (broken or resolvable);
    * must NOT already exist as a regular file (caller must remove
      the prior plan to re-run; refusing overwrite is consistent
      with ``init_image_manifest``'s no-overwrite contract);
    * the parent directory inside the workspace must not be a
      symlink at any segment along the path.

  post-condition
    * the plan file exists as a regular non-symlink JSON file whose
      content re-parses to the in-memory candidate that was just
      validated;
    * ``<workspace>/image_manifest.json`` is byte-identical to the
      pre-call state;
    * no other file under ``--workspace`` is created or modified
      (no image asset, no render_model, no SVG preview, no PPTX);
    * a post-condition failure deletes the just-written plan file
      so the workspace returns to its pre-call state.

A second run with identical inputs is refused (the prior plan file
is preserved byte-identical and the second run exits non-zero with
a "pre-existing plan" diagnostic). To re-author, the caller removes
the plan file and re-runs.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "schemas"

sys.path.insert(0, str(SCRIPTS_DIR))

from validate_artifacts import _validate  # noqa: E402
from validate_scaffold import (  # noqa: E402
    local_path_is_safe,
    _resolves_within,
)

IMAGE_MANIFEST_FILENAME = "image_manifest.json"
IMAGE_MANIFEST_SCHEMA = SCHEMAS_DIR / "image_manifest.schema.json"
SOURCE_INPUT_RELPATH = "input/source.md"
DEFAULT_PLAN_FILENAME = "d_one_adapter_plan.json"
PLAN_SCHEMA = SCHEMAS_DIR / "d_one_adapter_plan.schema.json"

# Only manifest entries whose source == "d_one_local" are eligible for
# D-One generation. local_asset / synthetic entries belong to a
# different lifecycle (local-authored or fixture-only) and the adapter
# refuses to issue a generation request against them so a caller cannot
# smuggle an unrelated request into the D-One channel.
ELIGIBLE_MANIFEST_SOURCE = "d_one_local"

# Schema version of the produced plan file. Bumped if the plan-file
# shape ever changes; lets a future real-D-One step refuse a plan it
# does not recognize.
PLAN_SCHEMA_VERSION = 1

# The note we stamp into every plan so an audit of the file is
# self-describing — "this came from a stub, no D-One call happened."
PLAN_NOTE = (
    "D-One adapter contract stub: no D-One call was made; no image "
    "bytes were generated. This plan records the validated requests "
    "for a future generator to consume."
)

# RFC 3986 scheme prefix; same regex the other helpers use.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# ---------------------------------------------------------------------------
# Forbidden-pattern tables. Every pattern is a defense-in-depth check —
# the caller is supposed to scrub prompts before passing them in, and
# the adapter refuses anything that looks unscrubbed. Patterns are
# compiled once at module load.
# ---------------------------------------------------------------------------

# URI scheme detection — matches `scheme:<non-whitespace>` for any
# scheme that starts with a letter, uses only ASCII scheme characters
# (`[A-Za-z][A-Za-z0-9+.\-]*`), and is followed by any non-whitespace
# character. Covers the hierarchical `https://...` / `file://...`
# form; the bare `data:,Hello` / `tel:+1-555` / `magnet:?xt=...` /
# `mailto:user@...` / `sms:+1-555` / `javascript:alert(1)` forms;
# AND single-character schemes like `a:b` / `x:malicious-content`
# (a 1-char "scheme" per RFC 3986 — a downstream URL parser /
# dispatcher would still treat it as a URI). Two earlier regex
# versions left bypasses: (1) requiring `//` or `[A-Za-z0-9]` after
# the colon missed every scheme where the next char was `+`, `,`,
# `?`, `(`, `;`, etc.; (2) requiring at least 2 scheme characters
# left 1-char schemes — including Windows drive letters like `C:/`
# (which the Windows-path pattern below now also catches with
# forward slashes) — bypassable. The cost of the looser pattern is
# false positives on unusual prose like "Section A:apple" (no space
# after the colon); the D-One stub weighs catching all URI shapes
# over preserving such phrasing.
_PROMPT_URI_PATTERN = re.compile(
    r"\b[A-Za-z][A-Za-z0-9+.\-]*:[^\s]"
)

# Absolute / traversal / system file-path shapes.
_PROMPT_FILEPATH_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("Unix absolute path", re.compile(r"(?:^|\s)/(?:etc|var|usr|home|root|tmp|opt|bin|sbin|dev|proc|sys|System|Library)/")),
    ("Windows path", re.compile(r"[A-Za-z]:[\\/]")),
    ("UNC path", re.compile(r"\\\\[A-Za-z]")),
    ("home shortcut", re.compile(r"(?:^|\s)~/")),
    ("path traversal", re.compile(r"\.\./")),
)

# Explicit raw-source-marker literals (case-insensitive substring).
_PROMPT_SOURCE_MARKER_LITERALS: tuple[str, ...] = (
    "<source>",
    "</source>",
    "[source]",
    "[/source]",
    "raw source",
    "begin source",
    "end source",
    "source document:",
    "source text:",
    "from the source",
)

# Credential / secret shapes.
_PROMPT_CREDENTIAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}")),
    ("AWS access key", re.compile(r"\bAKIA[A-Z0-9]{12,20}\b")),
    ("PEM marker", re.compile(r"-----BEGIN\s")),
    ("long hex blob", re.compile(r"\b[a-fA-F0-9]{32,}\b")),
    ("bearer token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{8,}")),
)
_PROMPT_CREDENTIAL_LITERALS: tuple[str, ...] = (
    "password:",
    "passwd:",
    "secret:",
    "api_key:",
    "apikey:",
    "api-key:",
    "token:",
    "access_key:",
    "client_secret:",
    "private_key:",
)

# Customer / account / contact-id shapes.
_PROMPT_PERSONAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("phone-like", re.compile(r"\+?\d{1,3}[-.\s]?\(?\d{3,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}\b")),
    ("SSN-like", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("UUID", re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")),
)
_PROMPT_PERSONAL_LITERALS: tuple[str, ...] = (
    "customer_id",
    "customer id:",
    "account_id",
    "account id:",
    "acct_id",
    "acct id:",
    "cust_id",
    "user_id",
    "user id:",
)

# Public upload / share / hosting wording. A D-One asset is local-only;
# instructing the generator to upload, publish, host, or share the
# result violates the no-public-network constraint at the prompt layer.
# Same scope rationale as the full-slide deny list below — the patterns
# here describe an action the local pipeline is forbidden to take, not
# a description of the image itself. Kept as plain substrings so the
# scan stays cheap; a reviewer can still negate-describe the boundary
# in adjacent prose (e.g. "no public upload") because the negation does
# NOT remove the substring. The longer-form structured-evidence
# validator at scripts/validate_d_one_live_run_evidence.py applies a
# richer regex with negation-exemption logic; this stub catches the
# bare wording before any plan-file write.
_PROMPT_PUBLIC_DISTRIBUTION_LITERALS: tuple[str, ...] = (
    "upload to public",
    "upload to a public",
    "upload to the public",
    "public upload",
    "share publicly",
    "share to public",
    "public hosting",
    "host on a public",
    "host publicly",
    "publish to web",
    "publish to the web",
    "publish publicly",
    "public url",
    "public link",
    "public cdn",
)

# Full-slide / page-generation / screenshot wording. A D-One asset is a
# local supporting illustration — never the slide itself.
_PROMPT_FULL_SLIDE_LITERALS: tuple[str, ...] = (
    "full slide",
    "full-slide",
    "whole slide",
    "entire slide",
    "full page",
    "full-page",
    "whole page",
    "entire page",
    "full deck",
    "whole deck",
    "entire deck",
    "slide background",
    "page background",
    "screenshot",
    "screen shot",
    "screen-shot",
    "render the slide",
    "render this slide",
    "generate the slide",
    "generate this slide",
    "create the slide",
    "create this slide",
    "design the slide",
    "design this slide",
    "render the page",
    "render this page",
    "generate the page",
    "generate this page",
)

# Window size for the input/source.md shingle check. 40 chars is short
# enough to catch a copy-pasted sentence ("The Q3 revenue grew by
# fifteen percent over Q2") but long enough that common stop-phrases
# ("the company", "in the slide") never match.
_SOURCE_SHINGLE_WINDOW = 40


def _has_uri_scheme(s: str) -> bool:
    return bool(_URI_SCHEME_PREFIX.match(s))


def _refuse_symlink(path: Path, label: str) -> tuple[bool, str]:
    """Return (is_symlink, fail_message). Same anti-pattern the other
    helpers reject: ``Path.exists()`` returns False for a dangling link
    and ``Path.is_file()`` / ``Path.is_dir()`` follow links, so an
    explicit ``is_symlink()`` check is the only way to refuse both
    broken and resolvable links."""
    if not path.is_symlink():
        return False, ""
    try:
        target = str(path.readlink())
    except OSError:
        target = "<unreadable>"
    return True, (
        f"FAIL: {path} ({label}) is a symlink (-> {target}); "
        f"done_image_adapter refuses to follow it (broken or not). "
        f"Remove or rename the symlink and re-run."
    )


def _schema_validate(value: dict, schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_text())
    errors: list[str] = []
    _validate(value, schema, "<root>", errors)
    return errors


def _parent_path_has_no_symlink(workspace: Path, target: Path) -> tuple[bool, str]:
    """Walk from ``workspace`` to (but excluding) ``target`` and refuse
    if any intermediate segment is a symlink. ``Path.mkdir(parents=True)``
    would silently follow a symlinked parent to outside the workspace."""
    try:
        rel = target.relative_to(workspace)
    except ValueError:
        return False, (
            f"FAIL: plan output {target} is not relative to workspace {workspace}"
        )
    current = workspace
    for part in rel.parts[:-1]:
        current = current / part
        if current.is_symlink():
            try:
                link_target = str(current.readlink())
            except OSError:
                link_target = "<unreadable>"
            return False, (
                f"FAIL: parent path {current} (for plan output {target}) is "
                f"a symlink (-> {link_target}); done_image_adapter refuses "
                f"to write through a symlinked parent."
            )
    return True, ""


def _scan_prompt_safety(
    prompt: str,
    *,
    source_text: str | None,
) -> list[str]:
    """Return a list of safety violations for ``prompt``. Empty list ->
    safe. Every pattern table is consulted; we collect ALL violations
    in one pass so the caller sees every problem at once rather than
    a one-issue-at-a-time game of whack-a-mole."""
    violations: list[str] = []
    lower = prompt.lower()

    # URI scheme.
    if _PROMPT_URI_PATTERN.search(prompt):
        violations.append("contains a URI scheme (http://, file://, data:, ...)")

    # File-path shapes.
    for label, pattern in _PROMPT_FILEPATH_PATTERNS:
        if pattern.search(prompt):
            violations.append(f"contains a {label}-shaped substring")

    # Source markers (literals).
    for marker in _PROMPT_SOURCE_MARKER_LITERALS:
        if marker in lower:
            violations.append(
                f"contains the raw-source marker {marker!r}"
            )

    # Source-text shingle check (only when input/source.md was present
    # AND both the source and prompt are long enough to slide a 40-char
    # window over). This catches the case where the caller copy-pasted
    # source body into the prompt; the patterns above only catch
    # explicit markers.
    #
    # We slide the 40-char window over the PROMPT (typically a few
    # hundred chars) and check each window for membership in the source
    # string. This is symmetric to "does any 40-char source substring
    # appear in the prompt?" — if S[a..a+40] == P[b..b+40] then
    # P[b..b+40] is in source AND S[a..a+40] is in prompt — but it
    # visits EVERY 40-char alignment without skipping. An earlier
    # version walked the SOURCE side in stride-8 steps; that missed any
    # 40-char source substring beginning at offset (mod 8) != 0, since
    # the offset-5 substring is not equal to the offset-0 or offset-8
    # shingles even though they overlap by 35 / 37 chars (the overlap
    # only matters for source ↔ source comparisons, not for
    # source-shingle ↔ prompt membership).
    if (
        source_text
        and len(source_text) >= _SOURCE_SHINGLE_WINDOW
        and len(prompt) >= _SOURCE_SHINGLE_WINDOW
    ):
        for j in range(len(prompt) - _SOURCE_SHINGLE_WINDOW + 1):
            window = prompt[j:j + _SOURCE_SHINGLE_WINDOW]
            if window in source_text:
                violations.append(
                    f"contains a {_SOURCE_SHINGLE_WINDOW}-char substring "
                    f"of input/source.md (raw-source paste suspected)"
                )
                break

    # Credentials.
    for label, pattern in _PROMPT_CREDENTIAL_PATTERNS:
        if pattern.search(prompt):
            violations.append(f"contains a {label}-shaped substring")
    for literal in _PROMPT_CREDENTIAL_LITERALS:
        if literal in lower:
            violations.append(
                f"contains the credential literal {literal!r}"
            )

    # Personal / customer / account / contact identifiers.
    for label, pattern in _PROMPT_PERSONAL_PATTERNS:
        if pattern.search(prompt):
            violations.append(f"contains a {label}-shaped substring")
    for literal in _PROMPT_PERSONAL_LITERALS:
        if literal in lower:
            violations.append(
                f"contains the personal-id literal {literal!r}"
            )

    # Full-slide / page-generation / screenshot wording.
    for literal in _PROMPT_FULL_SLIDE_LITERALS:
        if literal in lower:
            violations.append(
                f"contains the full-slide/page/screenshot wording "
                f"{literal!r}; D-One assets are local supporting "
                f"illustrations, never whole slides"
            )

    # Public upload / share / hosting wording.
    for literal in _PROMPT_PUBLIC_DISTRIBUTION_LITERALS:
        if literal in lower:
            violations.append(
                f"contains the public-distribution wording {literal!r}; "
                f"D-One assets are local-only and may not be uploaded, "
                f"published, shared, or hosted publicly"
            )

    return violations


def _scan_intended_use(intended_use: str) -> list[str]:
    """Subset of the prompt safety scan applied to ``intended_use``.
    Only the full-slide / screenshot wording matters here — the field
    is short and the manifest schema's description already says
    "never 'full-slide background'", so the helper enforces it."""
    violations: list[str] = []
    lower = intended_use.lower()
    for literal in _PROMPT_FULL_SLIDE_LITERALS:
        if literal in lower:
            violations.append(
                f"intended_use contains forbidden wording {literal!r}"
            )
    return violations


def _validate_spec_requests(
    spec: dict,
    *,
    manifest_by_id: dict[str, dict],
    source_text: str | None,
) -> tuple[list[dict] | None, str]:
    """Validate ``spec['requests']`` against the manifest and the
    safety scans. Returns (validated_requests, error_msg). On error,
    validated_requests is None and error_msg is non-empty."""
    requests = spec.get("requests")
    if not isinstance(requests, list):
        return None, (
            f"FAIL: --spec must contain a 'requests' list "
            f"(got {type(requests).__name__})"
        )
    if not requests:
        return None, (
            "FAIL: --spec.requests is empty; at least one request is "
            "required (this stub does not have a no-op mode)"
        )

    allowed_keys = {"id", "prompt", "intended_use", "width_px", "height_px"}
    required_keys = {"id", "prompt"}

    seen_ids: dict[str, int] = {}
    validated: list[dict] = []
    for i, req in enumerate(requests):
        if not isinstance(req, dict):
            return None, (
                f"FAIL: requests[{i}] is not an object "
                f"(got {type(req).__name__})"
            )
        extra = set(req.keys()) - allowed_keys
        if extra:
            return None, (
                f"FAIL: requests[{i}] has unexpected key(s): "
                + ", ".join(sorted(extra))
                + f"; allowed keys are {sorted(allowed_keys)}"
            )
        missing = required_keys - set(req.keys())
        if missing:
            return None, (
                f"FAIL: requests[{i}] is missing required key(s): "
                + ", ".join(sorted(missing))
            )

        req_id = req["id"]
        if not isinstance(req_id, str) or not req_id:
            return None, (
                f"FAIL: requests[{i}].id must be a non-empty string "
                f"(got {req_id!r})"
            )
        if req_id in seen_ids:
            return None, (
                f"FAIL: requests[{i}].id {req_id!r} duplicates "
                f"requests[{seen_ids[req_id]}].id (each manifest id "
                f"may be requested at most once per plan)"
            )
        seen_ids[req_id] = i

        if req_id not in manifest_by_id:
            return None, (
                f"FAIL: requests[{i}].id {req_id!r} does not match "
                f"any image_manifest.images[].id "
                f"(known ids: {sorted(manifest_by_id.keys()) or '<none>'})"
            )
        manifest_entry = manifest_by_id[req_id]
        manifest_source = manifest_entry.get("source")
        if manifest_source != ELIGIBLE_MANIFEST_SOURCE:
            return None, (
                f"FAIL: requests[{i}].id {req_id!r}: image_manifest "
                f"entry has source={manifest_source!r}, but D-One "
                f"requests are only valid for source="
                f"{ELIGIBLE_MANIFEST_SOURCE!r}. Update the manifest "
                f"or drop the request."
            )

        prompt = req["prompt"]
        if not isinstance(prompt, str) or not prompt.strip():
            return None, (
                f"FAIL: requests[{i}].prompt (id {req_id!r}) must be a "
                f"non-empty string (got {prompt!r})"
            )
        prompt_violations = _scan_prompt_safety(
            prompt, source_text=source_text,
        )
        if prompt_violations:
            return None, (
                f"FAIL: requests[{i}].prompt (id {req_id!r}) failed "
                f"safety scan: " + "; ".join(prompt_violations)
            )

        intended_use = req.get("intended_use")
        if intended_use is not None:
            if not isinstance(intended_use, str) or not intended_use.strip():
                return None, (
                    f"FAIL: requests[{i}].intended_use (id {req_id!r}) "
                    f"must be a non-empty string when present "
                    f"(got {intended_use!r})"
                )
            iu_violations = _scan_intended_use(intended_use)
            if iu_violations:
                return None, (
                    f"FAIL: requests[{i}].intended_use (id {req_id!r}) "
                    f"failed safety scan: " + "; ".join(iu_violations)
                )

        for dim_field in ("width_px", "height_px"):
            if dim_field in req:
                value = req[dim_field]
                if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                    return None, (
                        f"FAIL: requests[{i}].{dim_field} (id {req_id!r}) "
                        f"must be a positive integer (got {value!r})"
                    )

        validated.append({
            "id": req_id,
            "prompt": prompt,
            "intended_use": intended_use,
            "width_px": req.get("width_px"),
            "height_px": req.get("height_px"),
            "manifest_local_path": manifest_entry.get("local_path"),
            "manifest_source": manifest_source,
        })

    return validated, ""


def _build_plan(validated_requests: list[dict]) -> dict:
    """Project the validated request list into the deterministic plan
    file shape. Sorted by id so a re-ordered spec produces an
    identical plan file (the manifest itself is order-sensitive, but
    the plan is an audit projection and benefits from a stable order)."""
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "mode": "dry_run",
        "note": PLAN_NOTE,
        "request_count": len(validated_requests),
        "requests": [
            {
                "id": r["id"],
                "prompt": r["prompt"],
                **({"intended_use": r["intended_use"]} if r["intended_use"] is not None else {}),
                **({"width_px": r["width_px"]} if r["width_px"] is not None else {}),
                **({"height_px": r["height_px"]} if r["height_px"] is not None else {}),
                "manifest_local_path": r["manifest_local_path"],
                "manifest_source": r["manifest_source"],
            }
            for r in sorted(validated_requests, key=lambda x: x["id"])
        ],
    }


def _load_workspace_manifest_and_source(
    workspace: Path,
) -> tuple[
    dict[str, dict] | None,
    bytes | None,
    str | None,
    int,
    str,
]:
    """Load + validate ``<workspace>/image_manifest.json`` and (optionally)
    read ``<workspace>/input/source.md``. Shared by the write path
    (``done_image_adapter``) and the validate path (``validate_plan_file``)
    so the two cannot drift on what counts as a valid workspace.

    Returns ``(manifest_by_id, manifest_bytes, source_text, rc, msg)``.
    On success ``rc == 0`` and the first three values are populated; on
    failure ``rc != 0`` and ``msg`` is non-empty. The caller is expected
    to have already passed ``--workspace`` through the URI-shape gate and
    the workspace symlink / existence / is_dir gates."""
    manifest_path = workspace / IMAGE_MANIFEST_FILENAME
    is_symlink, msg = _refuse_symlink(manifest_path, IMAGE_MANIFEST_FILENAME)
    if is_symlink:
        return None, None, None, 2, msg
    if not manifest_path.is_file():
        return None, None, None, 2, (
            f"FAIL: --workspace {workspace} is missing "
            f"{IMAGE_MANIFEST_FILENAME}; run "
            f"scripts/init_image_manifest.py first to seed Stage-6 "
            f"(this adapter does not write the manifest, it reads it)."
        )
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, None, None, 2, f"FAIL: cannot read {manifest_path}: {exc}"
    if not isinstance(manifest, dict):
        return None, None, None, 2, (
            f"FAIL: {manifest_path} did not decode to an object "
            f"(got {type(manifest).__name__})"
        )
    manifest_errors = _schema_validate(manifest, IMAGE_MANIFEST_SCHEMA)
    if manifest_errors:
        return None, None, None, 1, (
            f"FAIL: {manifest_path} does not validate against "
            f"image_manifest.schema.json: " + "; ".join(manifest_errors)
        )

    images = manifest.get("images") or []
    manifest_by_id: dict[str, dict] = {}
    for i, img in enumerate(images):
        if not isinstance(img, dict):
            return None, None, None, 1, (
                f"FAIL: images[{i}] is not an object "
                f"(got {type(img).__name__})"
            )
        img_id = img.get("id")
        if not isinstance(img_id, str) or not img_id:
            return None, None, None, 1, (
                f"FAIL: images[{i}].id must be a non-empty string "
                f"(got {img_id!r})"
            )
        if img_id in manifest_by_id:
            return None, None, None, 1, (
                f"FAIL: {manifest_path} declares duplicate "
                f"images[].id {img_id!r}"
            )
        # Defense in depth: local_path safety (matches the gate
        # init_image_manifest / materialize_image_assets apply).
        local_path = img.get("local_path")
        if not isinstance(local_path, str) or not local_path:
            return None, None, None, 1, (
                f"FAIL: images[{i}] (id {img_id!r}): local_path must "
                f"be a non-empty string (got {local_path!r})"
            )
        if not local_path_is_safe(local_path):
            return None, None, None, 1, (
                f"FAIL: images[{i}] (id {img_id!r}): local_path "
                f"{local_path!r} is not a safe workspace-relative path"
            )
        if not _resolves_within(workspace, local_path):
            return None, None, None, 1, (
                f"FAIL: images[{i}] (id {img_id!r}): local_path "
                f"{local_path!r} escapes --workspace after resolution"
            )
        manifest_by_id[img_id] = img

    # Read input/source.md if present, ONLY for the shingle check.
    # A missing source body is acceptable (skips the shingle check);
    # a symlinked source body aborts the run.
    source_path = workspace / SOURCE_INPUT_RELPATH
    source_text: str | None = None
    if source_path.is_symlink():
        try:
            link_target = str(source_path.readlink())
        except OSError:
            link_target = "<unreadable>"
        return None, None, None, 1, (
            f"FAIL: {source_path} is a symlink (-> {link_target}); "
            f"done_image_adapter refuses to follow it. Replace it "
            f"with a regular file or remove it (the shingle check is "
            f"skipped when the source body is absent)."
        )
    if source_path.is_file():
        try:
            source_text = source_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return None, None, None, 1, (
                f"FAIL: cannot read {source_path} as UTF-8 for the "
                f"shingle check: {exc}"
            )

    return manifest_by_id, manifest_bytes, source_text, 0, ""


def done_image_adapter(
    *,
    workspace: Path,
    spec: Path,
    plan_out: Path | None = None,
) -> tuple[int, str]:
    """Run the D-One adapter contract stub. Returns (exit_code, message).

    Always operates as dry-run today; no D-One call is issued and no
    image bytes are generated. A successful run produces only the
    deterministic plan file at ``plan_out`` (default
    ``<workspace>/d_one_adapter_plan.json``)."""
    # String-level shape gates run first for BOTH --workspace and
    # --spec (no filesystem syscall). A URI-shaped argument otherwise
    # would slip past the URI guard for whichever input was checked
    # second if the first input happened to fail an earlier
    # filesystem gate (missing / wrong-kind / etc.).
    if _has_uri_scheme(str(workspace)):
        return 2, (
            f"FAIL: --workspace {workspace} looks like a URI; "
            f"done_image_adapter only accepts local directory paths"
        )
    if _has_uri_scheme(str(spec)):
        return 2, (
            f"FAIL: --spec {spec} looks like a URI; "
            f"done_image_adapter only accepts local file paths"
        )

    # Filesystem gates for --workspace.
    if workspace.is_symlink():
        return 2, (
            f"FAIL: --workspace {workspace} is a symlink; refusing to "
            f"follow it. Pass a regular directory path."
        )
    if not workspace.exists():
        return 2, f"FAIL: --workspace {workspace} does not exist"
    if not workspace.is_dir():
        return 2, f"FAIL: --workspace {workspace} is not a directory"

    # Filesystem gates for --spec.
    is_symlink, msg = _refuse_symlink(spec, "--spec")
    if is_symlink:
        return 2, msg
    if not spec.exists():
        return 2, f"FAIL: --spec {spec} does not exist"
    if not spec.is_file():
        return 2, f"FAIL: --spec {spec} is not a regular file"

    # image_manifest.json + input/source.md preflight (shared helper).
    manifest_path = workspace / IMAGE_MANIFEST_FILENAME
    manifest_by_id, manifest_bytes_before, source_text, rc, msg = (
        _load_workspace_manifest_and_source(workspace)
    )
    if rc != 0:
        return rc, msg
    assert manifest_by_id is not None
    assert manifest_bytes_before is not None

    # Parse --spec.
    try:
        spec_bytes = spec.read_bytes()
        spec_doc = json.loads(spec_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return 2, f"FAIL: cannot read --spec {spec}: {exc}"
    if not isinstance(spec_doc, dict):
        return 2, (
            f"FAIL: --spec {spec} did not decode to an object "
            f"(got {type(spec_doc).__name__})"
        )
    extra_top = set(spec_doc.keys()) - {"requests"}
    if extra_top:
        return 2, (
            f"FAIL: --spec {spec} has unexpected top-level key(s): "
            + ", ".join(sorted(extra_top))
            + "; only 'requests' is supported"
        )

    validated, err = _validate_spec_requests(
        spec_doc,
        manifest_by_id=manifest_by_id,
        source_text=source_text,
    )
    if err:
        return 1, err
    assert validated is not None  # for type-checkers

    # --plan-out gates.
    if plan_out is None:
        plan_out = workspace / DEFAULT_PLAN_FILENAME
    try:
        plan_rel = plan_out.relative_to(workspace)
    except ValueError:
        # plan_out is outside the workspace string-wise. Run the same
        # checks the helper applies internally: local_path_is_safe +
        # _resolves_within will catch this.
        # _resolves_within needs a workspace-relative string; if the
        # plan path is absolute and outside the workspace, we fail
        # here directly.
        return 2, (
            f"FAIL: --plan-out {plan_out} is outside --workspace "
            f"{workspace}; done_image_adapter writes only inside the "
            f"workspace"
        )
    plan_rel_str = str(plan_rel)
    if not local_path_is_safe(plan_rel_str):
        return 2, (
            f"FAIL: --plan-out {plan_out} (relative {plan_rel_str!r}) "
            f"is not a safe workspace-relative path "
            f"(URI / leading '/' / leading '\\' / '..' segment)"
        )
    # Leaf-symlink check BEFORE _resolves_within (same anti-pattern as
    # materialize_image_assets): a symlink at the target that points
    # outside the workspace surfaces with the clear "symlink"
    # diagnostic rather than the generic "escapes" one from
    # _resolves_within (which uses Path.resolve() and follows links).
    is_symlink, msg = _refuse_symlink(plan_out, "--plan-out target")
    if is_symlink:
        return 2, msg
    if not _resolves_within(workspace, plan_rel_str):
        return 2, (
            f"FAIL: --plan-out {plan_out} escapes --workspace after "
            f"resolution"
        )
    ok, msg = _parent_path_has_no_symlink(workspace, plan_out)
    if not ok:
        return 2, msg
    if plan_out.exists():
        return 1, (
            f"FAIL: --plan-out {plan_out} already exists; "
            f"done_image_adapter refuses to overwrite a prior plan. "
            f"Remove it and re-run."
        )

    # Build the plan and write it deterministically.
    plan = _build_plan(validated)
    plan_text = json.dumps(plan, indent=2, sort_keys=True) + "\n"
    plan_out.parent.mkdir(parents=True, exist_ok=True)
    try:
        plan_out.write_text(plan_text, encoding="utf-8")
    except OSError as exc:
        # No partial state — write_text either succeeds fully or
        # leaves nothing for us to clean up beyond the file itself,
        # which we remove on a failed write so the workspace returns
        # to its pre-call state.
        try:
            if plan_out.exists() or plan_out.is_symlink():
                plan_out.unlink()
        except OSError:
            pass
        return 1, f"FAIL: cannot write --plan-out {plan_out}: {exc}"

    # Post-conditions: plan file re-parses to the in-memory candidate;
    # manifest bytes unchanged; nothing else written under the
    # workspace beyond the plan itself.
    try:
        plan_bytes_after = plan_out.read_bytes()
        reparsed = json.loads(plan_bytes_after.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        try:
            plan_out.unlink()
        except OSError:
            pass
        return 1, (
            f"FAIL: re-read of {plan_out} failed: {exc}; rolled back."
        )
    if reparsed != plan:
        try:
            plan_out.unlink()
        except OSError:
            pass
        return 1, (
            f"FAIL: re-parsed {plan_out} does not match the in-memory "
            f"plan; rolled back."
        )
    # Defense-in-depth: validate the just-written plan against
    # d_one_adapter_plan.schema.json. The in-memory shape is produced
    # by _build_plan which is the only writer today, but a future
    # generator (or a refactor) that constructs the plan differently
    # would still have to satisfy the schema. Roll back on failure so
    # an unrecognized shape never lands on disk.
    plan_schema_errors = _schema_validate(reparsed, PLAN_SCHEMA)
    if plan_schema_errors:
        try:
            plan_out.unlink()
        except OSError:
            pass
        return 1, (
            f"FAIL: {plan_out} does not validate against "
            f"d_one_adapter_plan.schema.json: "
            + "; ".join(plan_schema_errors)
            + "; rolled back."
        )
    try:
        manifest_bytes_after = manifest_path.read_bytes()
    except OSError as exc:
        try:
            plan_out.unlink()
        except OSError:
            pass
        return 1, (
            f"FAIL: cannot re-read {manifest_path} after apply: {exc}; "
            f"rolled back plan."
        )
    if manifest_bytes_after != manifest_bytes_before:
        try:
            plan_out.unlink()
        except OSError:
            pass
        return 1, (
            f"FAIL: {manifest_path} bytes changed during apply "
            f"(expected byte-identical). Rolled back plan."
        )

    return 0, (
        f"OK: D-One adapter contract stub validated "
        f"{len(validated)} request(s) for {workspace}\n"
        f"  spec: {spec}\n"
        f"  plan: {plan_out}\n"
        f"  mode: dry_run (no D-One call; no image bytes generated)"
    )


def validate_plan_file(
    *,
    workspace: Path,
    plan: Path,
) -> tuple[int, str]:
    """Validate an existing ``d_one_adapter_plan.json``. Returns
    ``(exit_code, message)``.

    The validator is **non-mutating** — it never writes the plan, the
    manifest, or any other workspace file. It applies four layers of
    gates against the candidate plan:

      1. String- and filesystem-layer gates on ``--workspace`` /
         ``--plan`` (URI shape refused, symlink refused, exists,
         regular file / directory).
      2. The same ``image_manifest.json`` + ``input/source.md``
         preflight the write path applies, via
         ``_load_workspace_manifest_and_source`` — so a workspace
         without a schema-valid manifest is refused before the plan
         is even parsed.
      3. ``schemas/d_one_adapter_plan.schema.json`` against the plan
         JSON — catches malformed plans, list-rooted plans, unknown
         top-level / per-request fields, missing required fields,
         ``mode != "dry_run"``, ``schema_version != 1``, ``note``
         missing the dry-run sentinel, ``manifest_source !=
         "d_one_local"``, non-positive ``width_px`` / ``height_px``,
         non-integer ``request_count``, etc.
      4. Cross-checks the schema cannot express: ``request_count ==
         len(requests)``; no duplicate request ``id`` across the
         array; every ``id`` resolves to an ``images[].id`` in the
         manifest whose ``source == "d_one_local"``; ``manifest_source``
         and ``manifest_local_path`` recorded on each request agree
         with the matching manifest entry's current values
         byte-for-byte; ``manifest_local_path`` passes
         ``local_path_is_safe`` AND ``_resolves_within`` against the
         workspace (defense-in-depth, in case the manifest changed
         after the plan was written); every ``prompt`` passes the
         full ``_scan_prompt_safety`` deny list (URIs, file paths,
         raw-source markers, 40-char ``input/source.md`` shingles,
         credential / PII shapes, full-slide / page / screenshot
         wording, AND public-distribution wording — ``upload to
         public`` / ``public upload`` / ``share publicly`` /
         ``public hosting`` / ``publish to web`` / ``public url`` /
         ``public link`` / ``public cdn`` / ``host publicly`` and
         the documented variants); every ``intended_use`` (when
         present) passes the full-slide-wording subset.

    Post-condition: the manifest bytes and the plan bytes are
    byte-identical pre/post the call. A successful run returns
    ``(0, "OK: ...")``; a validation failure returns ``(1, "FAIL:
    ...")``; an invocation / file error returns ``(2, "FAIL: ...")``.
    """
    if _has_uri_scheme(str(workspace)):
        return 2, (
            f"FAIL: --workspace {workspace} looks like a URI; "
            f"done_image_adapter only accepts local directory paths"
        )
    if _has_uri_scheme(str(plan)):
        return 2, (
            f"FAIL: --plan {plan} looks like a URI; "
            f"done_image_adapter only accepts local file paths"
        )

    if workspace.is_symlink():
        return 2, (
            f"FAIL: --workspace {workspace} is a symlink; refusing to "
            f"follow it. Pass a regular directory path."
        )
    if not workspace.exists():
        return 2, f"FAIL: --workspace {workspace} does not exist"
    if not workspace.is_dir():
        return 2, f"FAIL: --workspace {workspace} is not a directory"

    is_symlink, msg = _refuse_symlink(plan, "--plan")
    if is_symlink:
        return 2, msg
    if not plan.exists():
        return 2, f"FAIL: --plan {plan} does not exist"
    if not plan.is_file():
        return 2, f"FAIL: --plan {plan} is not a regular file"

    manifest_path = workspace / IMAGE_MANIFEST_FILENAME
    manifest_by_id, manifest_bytes_before, source_text, rc, msg = (
        _load_workspace_manifest_and_source(workspace)
    )
    if rc != 0:
        return rc, msg
    assert manifest_by_id is not None
    assert manifest_bytes_before is not None

    try:
        plan_bytes_before = plan.read_bytes()
        plan_doc = json.loads(plan_bytes_before.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return 1, f"FAIL: cannot read --plan {plan}: {exc}"

    schema_errors = _schema_validate(plan_doc, PLAN_SCHEMA)
    if schema_errors:
        return 1, (
            f"FAIL: {plan} does not validate against "
            f"d_one_adapter_plan.schema.json: "
            + "; ".join(schema_errors)
        )

    # By this point the schema guarantees plan_doc is a dict with
    # all required top-level fields and that plan_doc["requests"] is
    # a non-empty list of objects each carrying id / prompt /
    # manifest_local_path / manifest_source. The cross-checks below
    # cover what the schema alone cannot express.
    requests = plan_doc["requests"]
    if plan_doc["request_count"] != len(requests):
        return 1, (
            f"FAIL: {plan} request_count={plan_doc['request_count']} "
            f"disagrees with len(requests)={len(requests)}"
        )

    seen_ids: dict[str, int] = {}
    for i, req in enumerate(requests):
        req_id = req["id"]
        if req_id in seen_ids:
            return 1, (
                f"FAIL: {plan} requests[{i}].id {req_id!r} duplicates "
                f"requests[{seen_ids[req_id]}].id (each manifest id "
                f"may appear at most once per plan)"
            )
        seen_ids[req_id] = i

        if req_id not in manifest_by_id:
            return 1, (
                f"FAIL: {plan} requests[{i}].id {req_id!r} does not "
                f"match any image_manifest.images[].id "
                f"(known ids: {sorted(manifest_by_id.keys()) or '<none>'})"
            )
        manifest_entry = manifest_by_id[req_id]

        manifest_source = manifest_entry.get("source")
        if manifest_source != ELIGIBLE_MANIFEST_SOURCE:
            return 1, (
                f"FAIL: {plan} requests[{i}].id {req_id!r}: "
                f"image_manifest entry has source={manifest_source!r}, "
                f"but plan entries are only valid against source="
                f"{ELIGIBLE_MANIFEST_SOURCE!r}"
            )
        if req["manifest_source"] != manifest_source:
            return 1, (
                f"FAIL: {plan} requests[{i}].manifest_source="
                f"{req['manifest_source']!r} disagrees with the "
                f"image_manifest entry's current source="
                f"{manifest_source!r} (the manifest changed after the "
                f"plan was written, or the plan was authored against "
                f"a different manifest)"
            )

        manifest_local_path = manifest_entry.get("local_path")
        if req["manifest_local_path"] != manifest_local_path:
            return 1, (
                f"FAIL: {plan} requests[{i}].manifest_local_path="
                f"{req['manifest_local_path']!r} disagrees with the "
                f"image_manifest entry's local_path="
                f"{manifest_local_path!r}"
            )
        # _load_workspace_manifest_and_source already ran the same
        # checks against the manifest's local_path; re-running them
        # against the plan's recorded copy catches a plan whose
        # value drifted (or whose value was authored by hand and never
        # passed through the write path).
        if not local_path_is_safe(req["manifest_local_path"]):
            return 1, (
                f"FAIL: {plan} requests[{i}].manifest_local_path="
                f"{req['manifest_local_path']!r} is not a safe "
                f"workspace-relative path"
            )
        if not _resolves_within(workspace, req["manifest_local_path"]):
            return 1, (
                f"FAIL: {plan} requests[{i}].manifest_local_path="
                f"{req['manifest_local_path']!r} escapes --workspace "
                f"after resolution"
            )

        prompt_violations = _scan_prompt_safety(
            req["prompt"], source_text=source_text,
        )
        if prompt_violations:
            return 1, (
                f"FAIL: {plan} requests[{i}].prompt (id {req_id!r}) "
                f"failed safety scan: " + "; ".join(prompt_violations)
            )

        intended_use = req.get("intended_use")
        if intended_use is not None:
            iu_violations = _scan_intended_use(intended_use)
            if iu_violations:
                return 1, (
                    f"FAIL: {plan} requests[{i}].intended_use "
                    f"(id {req_id!r}) failed safety scan: "
                    + "; ".join(iu_violations)
                )

    # Post-condition: nothing was written. A mismatch here would mean
    # another process is touching either file while we validated,
    # which is a stronger signal than the validator itself producing
    # a bad outcome.
    try:
        manifest_bytes_after = manifest_path.read_bytes()
        plan_bytes_after = plan.read_bytes()
    except OSError as exc:
        return 1, (
            f"FAIL: cannot re-read workspace state after validate: {exc}"
        )
    if manifest_bytes_after != manifest_bytes_before:
        return 1, (
            f"FAIL: {manifest_path} bytes changed during --validate-plan "
            f"(expected byte-identical)"
        )
    if plan_bytes_after != plan_bytes_before:
        return 1, (
            f"FAIL: {plan} bytes changed during --validate-plan "
            f"(expected byte-identical)"
        )

    return 0, (
        f"OK: {plan} validates against "
        f"d_one_adapter_plan.schema.json AND the workspace's "
        f"image_manifest.json AND the full prompt safety scan.\n"
        f"  workspace: {workspace}\n"
        f"  requests:  {len(requests)}\n"
        f"  mode:      {plan_doc['mode']} "
        f"(NON-MUTATING — no file was written)"
    )


# ---------------------------------------------------------------------------
# Self-test scenarios. Every scenario runs under
# tempfile.TemporaryDirectory(); no fixture leaks into the repo.
# ---------------------------------------------------------------------------


def _seed_workspace(
    ws: Path,
    *,
    images: list[dict] | None = None,
    source_body: str | None = None,
) -> None:
    """Write a minimal image_manifest.json plus optional
    input/source.md at the workspace root."""
    ws.mkdir(parents=True, exist_ok=True)
    body = {"images": images if images is not None else []}
    (ws / IMAGE_MANIFEST_FILENAME).write_text(
        json.dumps(body, indent=2, sort_keys=True) + "\n"
    )
    if source_body is not None:
        (ws / "input").mkdir(parents=True, exist_ok=True)
        (ws / "input" / "source.md").write_text(source_body)


def _write_spec(path: Path, body: dict) -> None:
    path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")


def _expect(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail if not ok else "")


def _list_workspace(ws: Path) -> set[str]:
    """Return the set of relative paths of every file under the
    workspace, used to prove the helper writes nothing besides the
    plan file."""
    out: set[str] = set()
    for p in ws.rglob("*"):
        if p.is_file():
            out.add(str(p.relative_to(ws)))
    return out


def _run_self_tests() -> list[tuple[str, bool, str]]:  # noqa: C901
    import tempfile

    results: list[tuple[str, bool, str]] = []

    # ---- 1. happy path: a single safe request validates and a plan
    # file is written. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_happy"
        _seed_workspace(ws, images=[
            {
                "id": "cover_accent",
                "local_path": "assets/cover_accent.png",
                "source": "d_one_local",
                "intended_use": "spot illustration",
            },
        ], source_body="# A synthetic source body for shingle tests\n")
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "cover_accent",
                    "prompt": (
                        "abstract geometric pattern in the deck primary "
                        "color, soft gradient, no text, no logo"
                    ),
                    "intended_use": "spot illustration",
                    "width_px": 800,
                    "height_px": 600,
                },
            ],
        })
        before = _list_workspace(ws)
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        after = _list_workspace(ws)
        plan_path = ws / DEFAULT_PLAN_FILENAME
        plan_ok = plan_path.is_file() and not plan_path.is_symlink()
        only_new = after - before == {DEFAULT_PLAN_FILENAME}
        try:
            plan_doc = json.loads(plan_path.read_text())
            plan_shape_ok = (
                plan_doc["schema_version"] == PLAN_SCHEMA_VERSION
                and plan_doc["mode"] == "dry_run"
                and plan_doc["request_count"] == 1
                and len(plan_doc["requests"]) == 1
                and plan_doc["requests"][0]["id"] == "cover_accent"
                and plan_doc["requests"][0]["manifest_source"] == "d_one_local"
            )
        except Exception:
            plan_shape_ok = False
        ok = rc == 0 and plan_ok and only_new and plan_shape_ok
        results.append(_expect(
            "happy path: valid safe request validates, deterministic "
            "plan file written, manifest unchanged, no other workspace "
            "files created",
            ok, f"rc={rc}, msg={msg!r}, only_new={after-before}",
        ))

    # ---- 2. determinism: two runs from identical inputs produce
    # byte-identical plan files. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws_a = td / "ws_a"
        ws_b = td / "ws_b"
        for ws in (ws_a, ws_b):
            _seed_workspace(ws, images=[
                {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
            ])
            spec = ws.parent / f"spec_{ws.name}.json"
            _write_spec(spec, {
                "requests": [
                    {"id": "x", "prompt": "a calm abstract texture, no text"},
                ],
            })
            rc, _ = done_image_adapter(workspace=ws, spec=spec)
            if rc != 0:
                results.append(_expect(
                    "determinism: helper succeeded on identical inputs",
                    False, f"workspace {ws} failed",
                ))
                break
        else:
            bytes_a = (ws_a / DEFAULT_PLAN_FILENAME).read_bytes()
            bytes_b = (ws_b / DEFAULT_PLAN_FILENAME).read_bytes()
            results.append(_expect(
                "determinism: two independent runs from identical "
                "inputs produce byte-identical plan-file bytes",
                bytes_a == bytes_b,
                f"len_a={len(bytes_a)}, len_b={len(bytes_b)}",
            ))

    # ---- 3. unknown image id refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_unknown"
        _seed_workspace(ws, images=[
            {"id": "known", "local_path": "a/known.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {"id": "stranger", "prompt": "abstract pattern, no text"},
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = (
            rc == 1
            and "does not match any image_manifest" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "unknown image id refused; no plan file written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 4. manifest entry whose source is local_asset (not
    # d_one_local) refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_wrong_source"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "local_asset"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {"id": "x", "prompt": "abstract pattern, no text"},
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = (
            rc == 1
            and "d_one_local" in msg
            and "local_asset" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "manifest entry with source != 'd_one_local' refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 5. raw source marker (explicit literal) refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_src_marker"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "x",
                    "prompt": (
                        "abstract pattern <SOURCE> verbatim source text "
                        "follows </SOURCE>"
                    ),
                },
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = (
            rc == 1
            and "raw-source marker" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "raw source marker '<SOURCE>' refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 6. raw-source shingle (40-char window) refused. ----
    distinctive = (
        "The Q3 ledger value rose by exactly fourteen and a half basis points"
    )
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_src_shingle"
        _seed_workspace(
            ws,
            images=[
                {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
            ],
            source_body=f"# Heading\n\n{distinctive}\n",
        )
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "x",
                    "prompt": (
                        "an abstract pattern. Context: "
                        + distinctive + "."
                    ),
                },
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = (
            rc == 1
            and "substring of input/source.md" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "40-char substring of input/source.md in prompt refused "
            "(raw-source paste suspected)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 6b. raw-source shingle at a non-stride-aligned source
    # offset refused. Regression for an earlier stride-8 scan that
    # visited only offsets 0, 8, 16, ... on the source side and missed
    # any 40-char source substring beginning at any other offset
    # (offsets 1-7, 9-15, 17-23, ...). The fix walks the PROMPT side
    # in stride-1 instead, so every 40-char alignment is visited. ----
    distinctive_40 = "Q9_synthetic_marker_alphabet_pattern_X20"
    assert len(distinctive_40) == _SOURCE_SHINGLE_WINDOW, (
        f"regression fixture must be exactly {_SOURCE_SHINGLE_WINDOW} chars"
    )
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_src_shingle_offset"
        # Distinctive 40-char block sits at source offset 5 (not a
        # multiple of 8). The earlier stride-8 scan checked source[0:40]
        # = "ABCDE" + distinctive_40[0:35] and source[8:48] =
        # distinctive_40[3:40] + "FGHIJ" — neither equals the
        # distinctive_40 the prompt actually carries.
        _seed_workspace(
            ws,
            images=[
                {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
            ],
            source_body="ABCDE" + distinctive_40 + "FGHIJ",
        )
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "x",
                    "prompt": "an abstract pattern, " + distinctive_40,
                },
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = (
            rc == 1
            and "substring of input/source.md" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "shingle gate catches a 40-char source substring at a "
            "non-stride-aligned source offset (regression: earlier "
            "stride-8 source scan missed offsets that were not "
            "multiples of 8)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 7. URL in prompt refused. ----
    # The first four are the hierarchical / alphanumeric-after-colon
    # forms that any reasonable URI regex catches. The next four are
    # the regression set for an earlier scan that required `//` or
    # `[A-Za-z0-9]` after the colon and bypassed every scheme followed
    # by `+`, `,`, `?`, etc. — even though a URL parser / dispatcher
    # would happily handle the URI (tel: → dialer, sms: → sms app,
    # magnet: → torrent client, bare data:, → inline payload). The
    # last two are the 1-character-scheme regression — an earlier
    # scan required at least 2 scheme characters and bypassed both
    # `a:b` (a 1-char scheme per RFC 3986) and the Windows-drive
    # shape `C:/path` (which slips past the Windows-path pattern's
    # backslash-only check too unless that pattern is widened).
    for url in (
        "https://attacker.example/path",
        "http://example.com/x",
        "file:///etc/passwd",
        "data:text/plain;base64,YWFh",
        "tel:+1-555-555-5555",
        "sms:+1-555-555-5555",
        "data:,malicious-payload",
        "magnet:?xt=urn:btih:abcdef0123456789abcdef0123456789abcdef01",
        "a:malicious-content",
        "x:hidden-payload",
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_url"
            _seed_workspace(ws, images=[
                {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {"id": "x", "prompt": f"abstract pattern, see {url}"},
                ],
            })
            rc, msg = done_image_adapter(workspace=ws, spec=spec)
            ok = (
                rc == 1
                and "URI scheme" in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"URL {url!r} in prompt refused",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- 8. file-path-shaped substring in prompt refused. ----
    # The Windows-path pattern now catches both backslash AND forward
    # slash after the drive letter (an earlier regex `[A-Za-z]:\\`
    # missed `C:/path/to/anything`, which is just as valid a Windows
    # path; the URI scan also catches it now via the 1-char-scheme
    # match, but the Windows-path-shaped diagnostic is clearer).
    for path in (
        "/etc/passwd",
        "/var/log/auth.log",
        "~/secret_keys",
        "../escape/route",
        "C:\\Users\\admin\\.aws\\credentials",
        "C:/Windows/System32/cmd.exe",
        "\\\\server\\share",
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_path"
            _seed_workspace(ws, images=[
                {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {"id": "x", "prompt": f"abstract pattern, ref {path}"},
                ],
            })
            rc, msg = done_image_adapter(workspace=ws, spec=spec)
            ok = (
                rc == 1
                and "shaped substring" in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"file-path-shaped substring {path!r} in prompt refused",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- 9. credential-shaped tokens refused. ----
    credential_cases: tuple[tuple[str, str], ...] = (
        ("AWS access key",
         "an abstract pattern, key AKIA1234567890ABCDEF more text"),
        ("JWT",
         "abstract pattern, token "
         "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.signaturepart_abc"),
        ("PEM marker",
         "abstract pattern, see -----BEGIN PRIVATE KEY-----"),
        ("long hex",
         "abstract pattern, hash deadbeefcafef00d1234567890abcdef0123456789abcdef"),
        ("bearer token",
         "abstract pattern, Bearer abcdefghijklmnopqrstuvwxyz"),
        ("password literal",
         "abstract pattern, password: hunter2"),
        ("api_key literal",
         "abstract pattern, api_key: AKIAabcdef"),
    )
    for label, prompt in credential_cases:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / f"ws_cred_{label.replace(' ', '_')}"
            _seed_workspace(ws, images=[
                {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [{"id": "x", "prompt": prompt}],
            })
            rc, msg = done_image_adapter(workspace=ws, spec=spec)
            ok = (
                rc == 1
                and "safety scan" in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"credential-shaped {label!r} in prompt refused",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- 10. customer / account / contact-id-shaped tokens refused. ----
    personal_cases: tuple[tuple[str, str], ...] = (
        ("email", "abstract pattern, contact alice@example.com"),
        ("SSN", "abstract pattern, id 123-45-6789"),
        ("UUID", "abstract pattern, id 12345678-1234-1234-1234-123456789abc"),
        ("customer_id literal", "abstract pattern, customer_id ABC123"),
        ("account_id literal", "abstract pattern, account_id XYZ"),
    )
    for label, prompt in personal_cases:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / f"ws_pi_{label.replace(' ', '_')}"
            _seed_workspace(ws, images=[
                {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [{"id": "x", "prompt": prompt}],
            })
            rc, msg = done_image_adapter(workspace=ws, spec=spec)
            ok = (
                rc == 1
                and "safety scan" in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"personal-id-shaped {label!r} in prompt refused",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- 11. full-slide / page-generation / screenshot wording
    # refused. ----
    for phrase in (
        "full slide",
        "full-slide",
        "whole slide",
        "entire slide",
        "screenshot of the deck",
        "render the slide",
        "generate the page",
        "slide background image",
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_fullslide"
            _seed_workspace(ws, images=[
                {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {"id": "x", "prompt": f"abstract pattern, do not {phrase}"},
                ],
            })
            rc, msg = done_image_adapter(workspace=ws, spec=spec)
            ok = (
                rc == 1
                and "full-slide" in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"full-slide/page/screenshot wording {phrase!r} refused",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- 11b. public-distribution wording (upload / publish / host /
    # share / public URL) refused. Each phrase here lives in
    # _PROMPT_PUBLIC_DISTRIBUTION_LITERALS and is the bare-substring
    # form the stub scan refuses; the richer negation-aware regex lives
    # in scripts/validate_d_one_live_run_evidence.py for trace-level
    # evidence. We trip the stub form here. ----
    for phrase in (
        "upload to public",
        "public upload",
        "share publicly",
        "public hosting",
        "publish to web",
        "public url",
        "public link",
        "public cdn",
        "host on a public",
        "host publicly",
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_public_distribution"
            _seed_workspace(ws, images=[
                {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "x",
                        "prompt": f"abstract pattern, then {phrase} after build",
                    },
                ],
            })
            rc, msg = done_image_adapter(workspace=ws, spec=spec)
            ok = (
                rc == 1
                and "public-distribution wording" in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"public-distribution wording {phrase!r} refused",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- 12. intended_use containing forbidden wording refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_iu"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "x",
                    "prompt": "an abstract pattern, no text",
                    "intended_use": "full-slide background",
                },
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = (
            rc == 1
            and "intended_use" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "intended_use containing 'full-slide background' refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 13. output path outside workspace refused (--plan-out). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_out"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {"id": "x", "prompt": "abstract pattern, no text"},
            ],
        })
        # Plan path outside the workspace.
        outside = td / "outside_plan.json"
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, plan_out=outside,
        )
        ok = (
            rc == 2
            and "outside --workspace" in msg
            and not outside.exists()
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "--plan-out outside --workspace refused; nothing written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 14. symlink at --workspace refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        real_ws = td / "real_ws"
        _seed_workspace(real_ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
        ])
        link_ws = td / "link_ws"
        link_ws.symlink_to(real_ws)
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {"id": "x", "prompt": "abstract pattern, no text"},
            ],
        })
        rc, msg = done_image_adapter(workspace=link_ws, spec=spec)
        ok = (
            rc == 2
            and "symlink" in msg
            and not (real_ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "symlink at --workspace refused; no plan written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 15. symlink at --spec refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_spec_link"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
        ])
        real_spec = td / "real_spec.json"
        _write_spec(real_spec, {
            "requests": [
                {"id": "x", "prompt": "abstract pattern, no text"},
            ],
        })
        link_spec = td / "link_spec.json"
        link_spec.symlink_to(real_spec)
        rc, msg = done_image_adapter(workspace=ws, spec=link_spec)
        ok = (
            rc == 2
            and "symlink" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "symlink at --spec refused; no plan written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 16. symlink at --plan-out refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_plan_link"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {"id": "x", "prompt": "abstract pattern, no text"},
            ],
        })
        outside = td / "outside_target.json"
        plan_link = ws / "plan_link.json"
        plan_link.symlink_to(outside)  # dangling symlink is fine
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, plan_out=plan_link,
        )
        ok = (
            rc == 2
            and "symlink" in msg
            and not outside.exists()
            and plan_link.is_symlink()  # link itself preserved
        )
        results.append(_expect(
            "symlink at --plan-out refused; nothing written through it",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 17. symlink at input/source.md refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_src_link"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
        ])
        outside_src = td / "outside_source.md"
        outside_src.write_text("# secret\n")
        (ws / "input").mkdir(parents=True, exist_ok=True)
        (ws / "input" / "source.md").symlink_to(outside_src)
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {"id": "x", "prompt": "abstract pattern, no text"},
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = (
            rc == 1
            and "symlink" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "symlink at input/source.md refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 18. URI-shaped --workspace / --spec refused at the string
    # layer (before any filesystem call). ----
    rc, msg = done_image_adapter(
        workspace=Path("https://attacker.example/ws"),
        spec=Path("/tmp/spec.json"),
    )
    ok = rc == 2 and "URI" in msg
    results.append(_expect(
        "URI-shaped --workspace refused at the string layer",
        ok, f"rc={rc}, msg={msg!r}",
    ))
    rc, msg = done_image_adapter(
        workspace=Path("/tmp/ws"),
        spec=Path("data:application/json,{}"),
    )
    ok = rc == 2 and "URI" in msg
    results.append(_expect(
        "URI-shaped --spec refused at the string layer",
        ok, f"rc={rc}, msg={msg!r}",
    ))

    # ---- 19. pre-existing --plan-out refused (no overwrite). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_preexisting"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
        ])
        prior_plan = ws / DEFAULT_PLAN_FILENAME
        prior_bytes = (
            json.dumps({"prior": "do not overwrite"}, indent=2) + "\n"
        ).encode("utf-8")
        prior_plan.write_bytes(prior_bytes)
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {"id": "x", "prompt": "abstract pattern, no text"},
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = (
            rc == 1
            and "already exists" in msg
            and prior_plan.read_bytes() == prior_bytes
        )
        results.append(_expect(
            "pre-existing --plan-out refused; prior bytes preserved",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 20. malformed manifest JSON refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_bad_manifest"
        ws.mkdir()
        (ws / IMAGE_MANIFEST_FILENAME).write_text("{not json")
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {"id": "x", "prompt": "abstract pattern, no text"},
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = rc == 2 and not (ws / DEFAULT_PLAN_FILENAME).exists()
        results.append(_expect(
            "malformed image_manifest.json refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 21. schema-invalid manifest refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_schema_invalid"
        ws.mkdir()
        # Missing required "source" on the only entry.
        (ws / IMAGE_MANIFEST_FILENAME).write_text(json.dumps({
            "images": [{"id": "x", "local_path": "a/x.png"}],
        }))
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {"id": "x", "prompt": "abstract pattern, no text"},
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = (
            rc == 1
            and "image_manifest.schema.json" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "schema-invalid image_manifest.json refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 22. spec missing 'requests' refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_requests"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {})
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = rc == 1 and "requests" in msg and not (ws / DEFAULT_PLAN_FILENAME).exists()
        results.append(_expect(
            "spec missing 'requests' refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 23. spec with extra top-level key refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_extra_top"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [{"id": "x", "prompt": "abstract pattern, no text"}],
            "unexpected": True,
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = (
            rc == 2
            and "unexpected top-level key" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "spec with extra top-level key refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 24. duplicate request id in spec refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_dup_req"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {"id": "x", "prompt": "abstract pattern, no text"},
                {"id": "x", "prompt": "another abstract pattern"},
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = (
            rc == 1
            and "duplicates" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "duplicate request id in spec refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 25. empty prompt refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_empty_prompt"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [{"id": "x", "prompt": "   "}],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = rc == 1 and "non-empty string" in msg
        results.append(_expect(
            "empty / whitespace-only prompt refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 26. no image bytes are EVER generated (whole-workspace
    # before/after comparison after a successful run + a failing run).
    # ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_image_bytes"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {"id": "x", "prompt": "an abstract pattern, no text"},
            ],
        })
        before = _list_workspace(ws)
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        after = _list_workspace(ws)
        # Only the plan should be new; no image file under media/.
        new = after - before
        no_image = not (ws / "media" / "x.png").exists()
        ok = (
            rc == 0
            and new == {DEFAULT_PLAN_FILENAME}
            and no_image
        )
        results.append(_expect(
            "successful run produces ONLY the plan file (no image "
            "bytes generated; no media/* asset created)",
            ok, f"rc={rc}, new={new}, no_image={no_image}",
        ))

    # ---- 27. mid-write rollback: a monkey-patched write_text raises;
    # the workspace returns to the pre-call state. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_rollback"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {"id": "x", "prompt": "abstract pattern, no text"},
            ],
        })
        original_write_text = Path.write_text

        def fake_write_text(self: Path, *args, **kwargs) -> int:
            if self.name == DEFAULT_PLAN_FILENAME:
                raise OSError("simulated disk-full")
            return original_write_text(self, *args, **kwargs)

        Path.write_text = fake_write_text  # type: ignore[assignment]
        try:
            rc, msg = done_image_adapter(workspace=ws, spec=spec)
        finally:
            Path.write_text = original_write_text  # type: ignore[assignment]
        ok = (
            rc == 1
            and "cannot write" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "mid-write failure leaves no plan file on disk",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 28. helper never opens input/source.md for content extraction
    # (the source body never appears in the plan file, on stdout/stderr,
    # or in the manifest after a successful run). ----
    distinctive_marker = "ZQZQZQ_distinctive_source_marker_ZQZQ"
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_no_leak"
        _seed_workspace(
            ws,
            images=[
                {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
            ],
            source_body=(
                f"# Heading\n\n{distinctive_marker} private body line\n"
            ),
        )
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {"id": "x", "prompt": "an abstract pattern, no text"},
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        plan_text = (ws / DEFAULT_PLAN_FILENAME).read_text()
        manifest_text = (ws / IMAGE_MANIFEST_FILENAME).read_text()
        ok = (
            rc == 0
            and distinctive_marker not in plan_text
            and distinctive_marker not in manifest_text
            and distinctive_marker not in msg
        )
        results.append(_expect(
            "no content leak: input/source.md marker never appears in "
            "the plan file, the manifest, or the helper's stdout",
            ok, f"rc={rc}",
        ))

    # ---- 29. self-consistency: the plan file we just wrote re-parses
    # to a structure we can iterate. Acts as a regression for the
    # post-condition re-read check. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_reparse"
        _seed_workspace(ws, images=[
            {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
            {"id": "y", "local_path": "a/y.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {"id": "y", "prompt": "second abstract pattern"},
                {"id": "x", "prompt": "first abstract pattern"},
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        plan_doc = json.loads((ws / DEFAULT_PLAN_FILENAME).read_text())
        ordered_ids = [r["id"] for r in plan_doc["requests"]]
        ok = rc == 0 and ordered_ids == ["x", "y"]  # sorted by id
        results.append(_expect(
            "plan file is deterministic: requests sorted by id "
            "regardless of spec order",
            ok, f"rc={rc}, ordered_ids={ordered_ids}",
        ))

    # =========================================================================
    # validate_plan_file scenarios.
    # =========================================================================

    def _seed_validate_workspace(td: Path) -> tuple[Path, Path]:
        """Seed a workspace + write a fresh plan via the writing path.
        Returns (workspace, plan_path). Used as the happy-path fixture
        for the validate-plan scenarios."""
        ws = td / "ws"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "media/a.png", "source": "d_one_local"},
            {"id": "b", "local_path": "media/b.png", "source": "d_one_local"},
        ])
        spec_path = td / "spec.json"
        _write_spec(spec_path, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract geometric pattern, no text",
                    "intended_use": "spot illustration",
                    "width_px": 800,
                    "height_px": 600,
                },
                {
                    "id": "b",
                    "prompt": "soft gradient texture, no text",
                },
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec_path)
        assert rc == 0, f"happy-path writer failed: rc={rc} msg={msg!r}"
        return ws, ws / DEFAULT_PLAN_FILENAME

    def _overwrite_plan(plan_path: Path, body: object) -> None:
        plan_path.write_text(
            json.dumps(body, indent=2, sort_keys=True) + "\n"
        )

    # ---- 30. validate-plan happy path: a plan freshly written by the
    # writing path validates clean. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = rc == 0 and "validates against" in msg
        results.append(_expect(
            "validate-plan: a plan freshly written by done_image_adapter "
            "round-trips through --validate-plan with rc=0",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 31. validate-plan is non-mutating: manifest + plan bytes
    # byte-identical pre/post a successful validate. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        manifest_path = ws / IMAGE_MANIFEST_FILENAME
        before_manifest = manifest_path.read_bytes()
        before_plan = plan_path.read_bytes()
        before_files = _list_workspace(ws)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        after_manifest = manifest_path.read_bytes()
        after_plan = plan_path.read_bytes()
        after_files = _list_workspace(ws)
        ok = (
            rc == 0
            and after_manifest == before_manifest
            and after_plan == before_plan
            and after_files == before_files
        )
        results.append(_expect(
            "validate-plan: NON-MUTATING — manifest bytes, plan bytes, "
            "and workspace file set all byte-identical pre/post",
            ok, f"rc={rc}",
        ))

    # ---- 32. schema gate: list-rooted plan refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        _overwrite_plan(plan_path, [])
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = rc == 1 and "d_one_adapter_plan.schema.json" in msg
        results.append(_expect(
            "validate-plan: list-rooted plan refused by schema "
            "(type: object)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 33. schema gate: unknown top-level field refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["unexpected_key"] = "anything"
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = (
            rc == 1
            and "additional property 'unexpected_key' not allowed" in msg
        )
        results.append(_expect(
            "validate-plan: unknown top-level field refused by schema "
            "(additionalProperties: false)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 34. schema gate: missing required top-level field refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        del plan_body["mode"]
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = rc == 1 and "missing required property 'mode'" in msg
        results.append(_expect(
            "validate-plan: missing required top-level field 'mode' "
            "refused by schema",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 35. schema gate: mode != 'dry_run' refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["mode"] = "live"
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = rc == 1 and "not in enum" in msg
        results.append(_expect(
            "validate-plan: mode != 'dry_run' refused by schema enum "
            "(evidence of dry-run is mandatory)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 36. schema gate: wrong schema_version refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["schema_version"] = 2
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = rc == 1 and "schema_version" in msg and "not in enum" in msg
        results.append(_expect(
            "validate-plan: schema_version != 1 refused by schema enum "
            "(version drift must be a paired script change)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 37. schema gate: note missing the dry-run sentinel refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["note"] = "An unsigned note."
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = (
            rc == 1
            and "does not match pattern" in msg
            and "D-One adapter contract stub" in msg
        )
        results.append(_expect(
            "validate-plan: note missing the 'D-One adapter contract "
            "stub' sentinel refused by schema pattern",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 38. schema gate: manifest_source != 'd_one_local' on a
    # request refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["requests"][0]["manifest_source"] = "local_asset"
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = (
            rc == 1
            and "manifest_source" in msg
            and "not in enum" in msg
        )
        results.append(_expect(
            "validate-plan: request.manifest_source != 'd_one_local' "
            "refused by schema enum",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 39. schema gate: unknown per-request field refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["requests"][0]["extra_field"] = "x"
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = (
            rc == 1
            and "additional property 'extra_field' not allowed" in msg
        )
        results.append(_expect(
            "validate-plan: unknown per-request field refused by schema "
            "(per-item additionalProperties: false)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 40. schema gate: missing required per-request field refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        del plan_body["requests"][0]["prompt"]
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = rc == 1 and "missing required property 'prompt'" in msg
        results.append(_expect(
            "validate-plan: missing required per-request field 'prompt' "
            "refused by schema",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 41. cross-check: duplicate request id refused (the schema
    # cannot express this; the validator's seen_ids check catches it). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        # Re-use the first request's body under id 'a' twice.
        first = dict(plan_body["requests"][0])
        plan_body["requests"] = [first, dict(first)]
        plan_body["request_count"] = 2
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = rc == 1 and "duplicates" in msg
        results.append(_expect(
            "validate-plan: duplicate request id refused by cross-check",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 42. cross-check: request_count != len(requests) refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["request_count"] = 999
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = (
            rc == 1
            and "request_count=999" in msg
            and "len(requests)=2" in msg
        )
        results.append(_expect(
            "validate-plan: request_count != len(requests) refused by "
            "cross-check",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 43. cross-check: request id not present in manifest refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["requests"][0]["id"] = "ghost"
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = rc == 1 and "does not match any image_manifest" in msg
        results.append(_expect(
            "validate-plan: request id not present in image_manifest "
            "refused by cross-check",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 44. cross-check: manifest_local_path disagrees with the
    # manifest entry refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["requests"][0]["manifest_local_path"] = "media/elsewhere.png"
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = (
            rc == 1
            and "manifest_local_path" in msg
            and "disagrees" in msg
        )
        results.append(_expect(
            "validate-plan: manifest_local_path disagreement with the "
            "manifest entry refused by cross-check",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 45. cross-check: prompt containing URL refused (re-runs the
    # full _scan_prompt_safety deny list against each prompt). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["requests"][0]["prompt"] = (
            "abstract pattern, see https://attacker.example/x"
        )
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = (
            rc == 1
            and "URI scheme" in msg
            and "safety scan" in msg
        )
        results.append(_expect(
            "validate-plan: URL in a plan prompt refused by cross-check "
            "safety scan",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 46. cross-check: prompt containing a 40-char input/source.md
    # shingle refused (raw-source paste suspected). ----
    distinctive = "Q9_validate_plan_distinctive_marker_QQQQQ"
    assert len(distinctive) >= _SOURCE_SHINGLE_WINDOW
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws"
        _seed_workspace(
            ws,
            images=[
                {"id": "a", "local_path": "media/a.png", "source": "d_one_local"},
            ],
            source_body=f"# Heading\n\n{distinctive}\n",
        )
        spec_path = td / "spec.json"
        _write_spec(spec_path, {
            "requests": [
                {"id": "a", "prompt": "abstract pattern, no text"},
            ],
        })
        rc, _ = done_image_adapter(workspace=ws, spec=spec_path)
        assert rc == 0
        plan_path = ws / DEFAULT_PLAN_FILENAME
        plan_body = json.loads(plan_path.read_text())
        plan_body["requests"][0]["prompt"] = (
            "abstract pattern, context: " + distinctive
        )
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = (
            rc == 1
            and "substring of input/source.md" in msg
            and "safety scan" in msg
        )
        results.append(_expect(
            "validate-plan: 40-char shingle of input/source.md inside a "
            "plan prompt refused by cross-check safety scan",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 47. cross-check: prompt containing credential refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["requests"][0]["prompt"] = (
            "abstract pattern, key AKIA1234567890ABCDEF more text"
        )
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = rc == 1 and "safety scan" in msg
        results.append(_expect(
            "validate-plan: credential-shaped substring in prompt "
            "refused by cross-check safety scan",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 48. cross-check: prompt containing full-slide wording
    # refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["requests"][0]["prompt"] = (
            "abstract pattern, render the slide as background"
        )
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = (
            rc == 1
            and "safety scan" in msg
            and "full-slide" in msg
        )
        results.append(_expect(
            "validate-plan: full-slide wording in prompt refused by "
            "cross-check safety scan",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 48b. cross-check: prompt containing public-distribution
    # wording refused. Mirrors scenario 47 (credentials) and 48
    # (full-slide) — the validate-plan path re-runs _scan_prompt_safety,
    # so the new public-distribution deny list must trip the cross-check
    # gate too. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["requests"][0]["prompt"] = (
            "abstract pattern, then upload to public hosting after build"
        )
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = (
            rc == 1
            and "safety scan" in msg
            and "public-distribution wording" in msg
        )
        results.append(_expect(
            "validate-plan: public-distribution wording in prompt "
            "refused by cross-check safety scan",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 49. cross-check: intended_use containing forbidden wording
    # refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["requests"][0]["intended_use"] = "full-slide background"
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = rc == 1 and "intended_use" in msg and "safety scan" in msg
        results.append(_expect(
            "validate-plan: intended_use containing full-slide wording "
            "refused by cross-check safety scan",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 50. malformed plan JSON refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_path.write_text("{not json")
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = rc == 1 and "cannot read --plan" in msg
        results.append(_expect(
            "validate-plan: malformed plan JSON refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 51. missing plan file refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_missing_plan"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        missing_plan = ws / "does_not_exist.json"
        rc, msg = validate_plan_file(workspace=ws, plan=missing_plan)
        ok = rc == 2 and "does not exist" in msg
        results.append(_expect(
            "validate-plan: missing --plan refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 52. symlink at --plan refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, real_plan = _seed_validate_workspace(td)
        link_plan = ws / "linked_plan.json"
        link_plan.symlink_to(real_plan)
        rc, msg = validate_plan_file(workspace=ws, plan=link_plan)
        ok = (
            rc == 2
            and "symlink" in msg
            and real_plan.read_bytes() == real_plan.read_bytes()  # tautology guard
        )
        results.append(_expect(
            "validate-plan: symlink at --plan refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- 53. URI-shaped --plan refused at the string layer. ----
    rc, msg = validate_plan_file(
        workspace=Path("/tmp/ws"),
        plan=Path("https://attacker.example/plan.json"),
    )
    ok = rc == 2 and "URI" in msg
    results.append(_expect(
        "validate-plan: URI-shaped --plan refused at the string layer",
        ok, f"rc={rc}, msg={msg!r}",
    ))

    # ---- 54. write-path post-write schema validation rolls back when
    # the in-memory plan does not satisfy the schema (regression for the
    # post-write _schema_validate step). Monkey-patches _build_plan to
    # drop a required field, then verifies the plan file is not left
    # on disk. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_writepath_schema"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "media/a.png", "source": "d_one_local"},
        ])
        spec_path = td / "spec.json"
        _write_spec(spec_path, {
            "requests": [{"id": "a", "prompt": "abstract pattern, no text"}],
        })
        import sys as _sys
        _module = _sys.modules[__name__]
        original_build = _module._build_plan

        def fake_build_plan(validated_requests: list[dict]) -> dict:
            plan = original_build(validated_requests)
            del plan["mode"]  # schema requires it; should trigger rollback
            return plan

        _module._build_plan = fake_build_plan  # type: ignore[attr-defined]
        try:
            rc, msg = done_image_adapter(workspace=ws, spec=spec_path)
        finally:
            _module._build_plan = original_build  # type: ignore[attr-defined]
        ok = (
            rc == 1
            and "d_one_adapter_plan.schema.json" in msg
            and "rolled back" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "write path: post-write schema-validation failure rolls back "
            "the plan file (regression for the new _schema_validate "
            "post-condition step)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "D-One adapter contract STUB (NOT D-One integration). "
            "Reads a workspace's image_manifest.json plus a caller-"
            "supplied --spec JSON of D-One generation requests, "
            "validates that every id matches a manifest entry with "
            "source='d_one_local', scans every prompt for URIs, file "
            "paths, raw-source markers, raw-source shingles, "
            "credentials, customer/account/contact ids, full-slide/"
            "page/screenshot wording, AND public-distribution wording "
            "('upload to public', 'public upload', 'share publicly', "
            "'public hosting', 'publish to web', 'public url', "
            "'public link', 'public cdn', 'host publicly' and the "
            "documented variants), and writes a deterministic "
            "dry-run plan file. Does NOT call D-One / Qoder / any "
            "public network / any image-generation model / any "
            "external service. Does NOT generate any image bytes. "
            "Does NOT mutate image_manifest.json. Does NOT produce "
            "render_models, svg_previews, or any .pptx. Does NOT "
            "change PPTX export behavior."
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help="Workspace directory containing image_manifest.json.",
    )
    parser.add_argument(
        "--spec", type=Path, default=None,
        help="JSON file of D-One generation requests. Top-level "
             "object with a non-empty 'requests' list whose every "
             "entry has 'id' (matching an images[].id with "
             "source='d_one_local'), 'prompt' (non-empty, safe), and "
             "optionally 'intended_use', 'width_px', 'height_px'.",
    )
    parser.add_argument(
        "--plan-out", type=Path, default=None,
        help="Where to write the deterministic plan file. Defaults to "
             "<workspace>/" + DEFAULT_PLAN_FILENAME + ". Must resolve "
             "inside --workspace and must not pre-exist.",
    )
    parser.add_argument(
        "--validate-plan", action="store_true",
        help="Validate an EXISTING d_one_adapter_plan.json instead of "
             "writing a new one. Requires --workspace and --plan. The "
             "validator is NON-MUTATING: it applies the schema "
             "(d_one_adapter_plan.schema.json — covers list-rooted, "
             "unknown fields, missing required fields, mode != "
             "'dry_run', schema_version drift, manifest_source != "
             "'d_one_local', non-positive dimensions), the workspace + "
             "image_manifest preflight (manifest schema-valid; no "
             "duplicate ids; every local_path safe), and the full set "
             "of cross-checks the schema cannot express (request_count "
             "== len(requests); no duplicate request ids; every id "
             "resolves in the manifest with source='d_one_local'; "
             "manifest_local_path / manifest_source agree with the "
             "manifest entry byte-for-byte; every prompt re-passes the "
             "full URL / file-path / raw-source marker / 40-char source "
             "shingle / credential / PII / full-slide wording / "
             "public-distribution wording deny list, and every "
             "intended_use re-passes the full-slide wording subset of "
             "that list — the same scope the write path applies).",
    )
    parser.add_argument(
        "--plan", type=Path, default=None,
        help="Path to the existing plan file to validate. Required "
             "with --validate-plan. Refused if it is a symlink, missing, "
             "not a regular file, or URI-shaped.",
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help="Run in-script tempfixture scenarios covering the happy "
             "path, determinism, unknown id, wrong manifest source, "
             "raw-source markers and shingles, URIs, file paths, "
             "credential/PII shapes, full-slide wording, public-"
             "distribution wording, intended_use wording, output-path-"
             "outside-workspace, symlinks at "
             "workspace/spec/plan/source, pre-existing plan, malformed "
             "/schema-invalid manifest, malformed spec, duplicate "
             "request ids, empty prompts, no-image-bytes guarantee, "
             "mid-write rollback, no-source-leak, plan determinism, "
             "plus the standalone --validate-plan path covering "
             "schema gates, cross-checks, and the non-mutating "
             "post-condition. Exits non-zero if any scenario does not "
             "behave as expected. Mutually exclusive with --workspace "
             "/ --spec / --plan-out / --plan / --validate-plan.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if any(
            v is not None for v in (
                args.workspace, args.spec, args.plan_out, args.plan,
            )
        ) or args.validate_plan:
            print(
                "FAIL: --self-test does not take any other argument",
                file=sys.stderr,
            )
            return 2
        results = _run_self_tests()
        fails = 0
        for name, ok, detail in results:
            mark = "PASS" if ok else "FAIL"
            suffix = f" -- {detail}" if not ok and detail else ""
            print(f"  [{mark}] {name}{suffix}")
            if not ok:
                fails += 1
        print()
        if fails:
            print(
                f"FAIL: {fails} self-test scenario(s) did not behave "
                f"as expected."
            )
            return 1
        print(
            "OK (self-test): D-One adapter contract stub behaves as "
            "expected on every fail-closed scenario plus the happy "
            "paths."
        )
        return 0

    if args.validate_plan:
        rejected = [
            name for name, value in (
                ("--spec", args.spec),
                ("--plan-out", args.plan_out),
            )
            if value is not None
        ]
        if rejected:
            print(
                f"FAIL: --validate-plan does not accept "
                f"{', '.join(rejected)}; use --workspace and --plan only",
                file=sys.stderr,
            )
            return 2
        missing = [
            name for name, value in (
                ("--workspace", args.workspace),
                ("--plan", args.plan),
            )
            if value is None
        ]
        if missing:
            print(
                f"FAIL: --validate-plan requires {', '.join(missing)}",
                file=sys.stderr,
            )
            return 2
        rc, msg = validate_plan_file(
            workspace=args.workspace,
            plan=args.plan,
        )
        if rc == 0:
            print(msg)
        else:
            print(msg, file=sys.stderr)
        return rc

    if args.plan is not None:
        print(
            "FAIL: --plan is only valid with --validate-plan",
            file=sys.stderr,
        )
        return 2

    missing = [
        name for name, value in (
            ("--workspace", args.workspace),
            ("--spec", args.spec),
        )
        if value is None
    ]
    if missing:
        print(
            f"FAIL: missing required argument(s): "
            f"{', '.join(missing)} (use --self-test for the in-script "
            f"scenarios)",
            file=sys.stderr,
        )
        return 2

    rc, msg = done_image_adapter(
        workspace=args.workspace,
        spec=args.spec,
        plan_out=args.plan_out,
    )
    if rc == 0:
        print(msg)
    else:
        print(msg, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
