#!/usr/bin/env python3
"""Local validator for source_image_assets.json.

Stdlib-only, NETWORK-FREE, NO-D-ONE. Given an explicit
``--workspace <dir>`` plus optional ``--registry <path>`` (default
``<workspace>/source_image_assets.json``), this script schema-validates
the registry against ``schemas/source_image_asset.schema.json`` AND
enforces the wire-side cross-checks listed in
``references/source-image-asset-policy.md`` under "Validator":

  G1 readable_json_object
    - registry must exist as a regular non-symlink file;
    - bytes must parse as JSON;
    - the parsed JSON must be a top-level OBJECT (list / scalar root is
      refused; the schema's ``type: object`` rule fires on a non-object
      root, but a hard refusal up front gives a clearer diagnostic and
      avoids spurious "missing required" follow-ups).

  G2 schema_subset_valid
    - validates against ``schemas/source_image_asset.schema.json`` under
      the same stdlib subset that ``scripts/validate_artifacts.py``
      applies.

  G3 unique_assets_ids
    - no two ``assets[*].id`` values may be equal. The schema's
      ``uniqueItems: false`` is on the array shape (asset records are
      not byte-comparable across two equal ids); id-uniqueness is a
      semantic check the validator owns.

  G4 source_ref_matches_manifest
    - if a sibling ``source_manifest.json`` exists at the workspace
      root, every ``assets[*].source_ref`` MUST equal
      ``source_manifest.source.id``. Workspaces without an intake
      manifest skip this gate (single-source extension; multi-source is
      out of scope and explicitly documented in the policy reference).

  G5 paths_safe_and_within_workspace
    - both ``local_path`` and ``destination_path`` MUST pass
      ``validate_scaffold.local_path_is_safe`` AND
      ``_resolves_within(workspace, path)``. The schema patterns already
      lock the workspace-relative shape; this gate is the filesystem-
      level belt-and-braces against schema drift (a future schema
      relaxation MUST NOT silently open a path-traversal hole).

  G6 no_symlink_at_source_or_destination_parent
    - the source asset (``<workspace>/<local_path>``) MUST NOT be a
      symlink (broken or resolvable);
    - every directory segment from ``<workspace>`` down to (but
      excluding) the source asset leaf MUST NOT be a symlink (broken or
      resolvable);
    - the destination's parent directory chain inside the workspace
      (``<workspace>/<destination_path>``'s parent and every segment
      above it down to ``<workspace>``) MUST NOT contain a symlink. The
      leaf at ``destination_path`` may or may not exist; this validator
      neither writes nor materialises it.

  G7 source_asset_is_regular_file
    - ``<workspace>/<local_path>`` MUST exist as a regular non-symlink
      file. Zero-length files are independently refused by G8
      (``byte_count >= 1`` from the schema; the on-disk byte_count check
      below mirrors it).

  G8 byte_count_and_sha256_match
    - the on-disk byte length of ``<workspace>/<local_path>`` MUST equal
      the declared ``byte_count``;
    - the lowercase-hex sha256 of those bytes MUST equal the declared
      ``sha256``.

  G9 media_type_matches_extension_and_magic_bytes
    - declared ``media_type`` MUST agree with the lower-cased extension
      on the declared ``local_path`` / ``destination_path``:
        * ``image/png``  <-> ``.png``;
        * ``image/jpeg`` <-> ``.jpg`` OR ``.jpeg``;
    - the first bytes of the on-disk asset MUST match the magic-byte
      signature for the declared ``media_type``. Mirrors the same
      signatures ``scripts/materialize_image_assets.py`` (and the PPTX
      exporter) already enforce — a future divergence between this
      validator and materialize would be a contract bug.

  G10 image_manifest_alignment (optional)
    - if a sibling ``image_manifest.json`` exists at the workspace root,
      for every registry asset whose ``id`` appears as
      ``image_manifest.images[*].id``, the matching manifest entry MUST
      satisfy ``source == "local_asset"`` AND
      ``local_path == registry destination_path``. Registry assets that
      the manifest does not reference are silently allowed BY G10 — the
      separate G13 gate handles that completeness case. G10's scope is
      intentionally narrow: *alignment quality of matched id pairs*.
      Splitting alignment (G10) from completeness (G13) preserves the
      original G10 contract while giving the new declaration-required
      strictness its own deterministic citation.

  G11 string_field_shapes_runtime
    - ``id``, ``source_ref``, ``local_path``, ``destination_path``, and
      ``sha256`` MUST be byte-identical to themselves after a
      ``str.strip()`` round-trip (the schema patterns reject most
      whitespace shapes already; this gate is the belt-and-braces);
    - no string field may carry a URI-scheme prefix matching the same
      RFC 3986 shape ``validate_scaffold.local_path_is_safe`` refuses
      (defense-in-depth for any free-form field a future schema might
      relax).

  G12 no_public_propagation_intent_wording
    - no ``id`` / ``source_ref`` / ``local_path`` / ``destination_path``
      string field may, once lower-cased AND stripped of every non-
      alphanumeric character (``_``, ``.``, ``-``, ``/``, etc.), contain
      the marker ``public`` AND ALSO contain any of the propagation-verb
      / surface markers ``upload``, ``share``, ``sharing``, ``url``,
      ``link``, ``post``, ``publish``, or ``distribut``. The deny fires
      on the COMBINATION of marker + verb; either alone is allowed.
      Normalization plus combined-marker matching is mandatory because
      the schema permits ``_``, ``.``, AND ``-`` as separators inside an
      id (and the locked path patterns carry the same set), so a
      literal-substring scan on the un-normalized value — or even a
      canonical-form scan against a fixed list of pre-baked compound
      tokens like ``publicupload`` / ``sharepublicly`` — would refuse
      ``public_upload`` while letting schema-equivalent variants slip
      past:

        * separator permutations: ``public-upload`` / ``public.upload``
          / ``publicupload`` / ``Public_Upload`` / ``public__upload`` /
          ``public_-_upload`` etc.;
        * word-order permutations: ``share_public`` / ``share_to_public``
          / ``upload_to_public`` / ``publish_to_public`` /
          ``link_to_public`` / ``distribute_public`` / ``post_to_public``
          etc.;
        * morphology permutations: ``public_sharing`` /
          ``publicly_shared`` / ``shared_publicly`` /
          ``share_with_public`` / ``public_distribution`` /
          ``publish_public`` / ``public_publishing`` /
          ``public_linking`` / ``public_posting`` etc.;
        * intervening tokens: ``public_share_url`` /
          ``public_chart_link`` / ``share_image_publicly`` /
          ``upload_chart_to_public`` etc.;
        * the five identifiers the policy explicitly enumerates:
          ``public_upload``, ``public_upload_asset``, ``share_publicly``,
          ``public_url_for_assets``, ``upload_to_public_bucket``.

      Every one of those collapses to a canonical form containing
      ``public`` plus at least one verb marker and is refused under one
      rule. The deny mirrors the "No public upload, no telemetry, no
      model API" rule in
      ``references/source-image-asset-policy.md``: this registry is
      local-only and any wording that implies a public-upload /
      public-share / public-URL / public-post / public-publish /
      public-distribute / public-link propagation intent is
      policy-violating by construction. ``public`` on its own is
      allowed (so ``public_chart`` / ``public_domain_marker`` /
      ``publication_meta`` / ``republican_emblem`` keep passing — the
      bare word ``public`` is ambiguous and not propagation intent on
      its own), and propagation-verb markers on their own are allowed
      (so ``share_image`` / ``upload_chart`` / ``permalink_marker`` /
      ``post_meta`` / ``publish_run`` / ``shared_team_data`` keep
      passing — internal sharing is not in scope). Safe synthetic ids
      (``source_hero``, ``product_marker``, ``local_chart_asset``, etc.)
      collapse to canonical forms that contain neither the public
      marker nor a verb marker, so they pass.

  G13 image_manifest_declaration_required (optional)
    - if a sibling ``image_manifest.json`` exists at the workspace root,
      every registry ``assets[*].id`` MUST appear as
      ``image_manifest.images[*].id`` — a registry id the manifest
      does not declare fails closed. Rationale: once the deck has been
      committed to an ``image_manifest.json``, a registry that names
      an attached asset the manifest never references is propagation
      drift (the asset would never reach the deck) and must be refused
      so the author either adds the manifest entry or removes the
      registry entry. G13 is the *completeness* gate; G10 is the
      *alignment* gate. Keeping the two concerns under separate gate
      ids preserves G10's original contract (silently allow registry-
      not-in-manifest) and gives the completeness strictness its own
      deterministic citation, so a future change that wants to relax
      one direction without touching the other can flip exactly one
      gate.
    - structural precondition (fail-closed): if ``image_manifest.json``
      is present and readable but its ``images`` field is missing OR
      is not a JSON list (``null``, string, number, object, etc.),
      both G10 alignment and G13 completeness become un-runnable.
      Silently skipping both checks would let a malformed manifest
      (e.g. an author who wrote ``{"foo": "bar"}`` or omitted
      ``images`` entirely) mask propagation drift fail-OPEN — every
      registry asset would be undeclared and the validator would
      return OK. G13 refuses this case fail-closed with a structural
      diagnostic, distinct from the per-asset
      "missing declaration" diagnostic that fires when ``images: []``
      is empty (an empty list is structurally valid, just incomplete
      — the per-asset failures point the author at the specific
      missing entries). The G10 alignment check also depends on the
      same structural precondition; the diagnostic cites G13 because
      G13 is the gate that pinned the precondition.

Out of scope (and explicitly refused, not implemented):

  - calling D-One / Qoder / MCP / any image generator / model API /
    image search / public network / external service;
  - mutating the registry or any workspace file (read-only validator);
  - any pipeline propagation behavior (no copy, no rewrite, no manifest
    field is touched — that is what
    ``scripts/materialize_image_assets.py`` is for);
  - any SVG / GIF / WebP / TIFF / BMP / ICO media path. The schema's
    ``media_type`` enum and the extension lock both refuse them.

Exit codes:
  0  every gate passed (or --self-test scenarios all behaved as expected).
  1  one or more gates failed.
  2  invocation / file / parse error.

CLI:
  python3 scripts/validate_source_image_assets.py \
      --workspace <ws> [--registry <ws>/source_image_assets.json]
  python3 scripts/validate_source_image_assets.py --self-test
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
SCHEMAS_DIR = REPO_ROOT / "schemas"

sys.path.insert(0, str(SCRIPTS_DIR))

from validate_artifacts import _validate  # noqa: E402
from validate_scaffold import (  # noqa: E402
    _resolves_within,
    local_path_is_safe,
)

REGISTRY_FILENAME = "source_image_assets.json"
SOURCE_MANIFEST_FILENAME = "source_manifest.json"
IMAGE_MANIFEST_FILENAME = "image_manifest.json"
REGISTRY_SCHEMA = SCHEMAS_DIR / "source_image_asset.schema.json"

# Mirrors scripts/materialize_image_assets.py and scripts/export_pptx.py.
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE_PREFIX = b"\xff\xd8\xff"

# Lock the media_type <-> extension agreement. The schema enum already
# refuses anything else; the runtime gate mirrors it so the diagnostic
# is the same regardless of which side detects the divergence.
_MEDIA_TYPE_TO_EXTS: dict[str, tuple[str, ...]] = {
    "image/png": ("png",),
    "image/jpeg": ("jpg", "jpeg"),
}

# RFC 3986 scheme: same shape validate_scaffold._URI_SCHEME_PREFIX uses.
_URI_SCHEME_PREFIX = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*:")

# G12 — public-propagation intent deny markers. The match runs against
# the canonical form (lower-cased + non-alphanumeric stripped), so every
# schema-permitted separator variant collapses to the same form. A
# field is refused when its canonical form contains the ``public``
# marker AND ALSO contains any of the propagation-verb / surface
# markers below — catching the COMBINATION (rather than a fixed list
# of pre-baked compound phrases like ``publicupload`` /
# ``sharepublicly``) is what closes the schema-permitted bypass surface.
# Every word-order permutation (``public_share`` / ``share_public``),
# morphology permutation (``shared_publicly`` / ``publicly_shared`` /
# ``public_sharing`` / ``public_distribution``), and intervening-token
# permutation (``public_chart_link`` / ``upload_chart_to_public``)
# collapses to ``public`` + at least one verb marker in canonical form
# and trips the deny.
#
# Each marker on its own is allowed:
#  - ``public`` alone (``public_chart`` / ``public_domain_marker`` /
#    ``publication_meta`` / ``republican_emblem``) is ambiguous — not
#    propagation intent on its own;
#  - each verb alone (``share_image`` / ``upload_chart`` /
#    ``permalink_marker`` / ``post_meta`` / ``publish_run`` /
#    ``shared_team_data``) does not imply public propagation by itself.
#
# The verb set is intentionally narrow — each is an unambiguous
# propagation action or web-surface noun. Cloud-channel words
# (``bucket`` / ``cdn`` / ``s3``) are NOT in the set: they would
# false-positive plausibly-internal labels like ``internal_bucket``,
# and the required identifier ``upload_to_public_bucket`` already trips
# on the ``upload`` verb without needing ``bucket`` separately.
# ``distribut`` is a deliberate 8-character root that covers
# ``distribute`` / ``distributed`` / ``distributing`` /
# ``distribution`` / ``distributor`` in one entry (their suffixes
# diverge in the canonical form so substring-matching the full word
# would miss morphology variants).
_PUBLIC_MARKER = "public"

_PROPAGATION_VERB_MARKERS: tuple[str, ...] = (
    "upload",
    "share",
    "sharing",
    "url",
    "link",
    "post",
    "publish",
    "distribut",
)

# Strips every char that is not [a-z0-9] AFTER lower-casing — so ``_``,
# ``.``, ``-``, ``/``, plus any future separator a schema relaxation
# might admit all collapse to the empty string. Anchored on the
# lower-cased value, so the regex character class only needs the
# lowercase letters and digits.
_NON_ALPHANUM = re.compile(r"[^a-z0-9]")


def _has_uri_scheme(s: str) -> bool:
    return bool(_URI_SCHEME_PREFIX.match(s))


def _canonical(value: str) -> str:
    """Lower-case ``value`` and drop every non-alphanumeric character.
    The result is the canonical form used by G12 — see
    ``_PUBLIC_MARKER`` / ``_PROPAGATION_VERB_MARKERS``."""
    return _NON_ALPHANUM.sub("", value.lower())


def _public_deny_hits(value: str) -> list[str]:
    """Return the deny markers triggered by ``value``. If the canonical
    (lower-cased + non-alphanumeric-stripped) form of ``value``
    contains the ``public`` marker AND at least one propagation-verb
    marker, return ``[_PUBLIC_MARKER, *verb_hits]`` with ``verb_hits``
    in ``_PROPAGATION_VERB_MARKERS`` declaration order (deterministic).
    Otherwise return ``[]`` — either marker on its own is allowed."""
    canonical = _canonical(value)
    if _PUBLIC_MARKER not in canonical:
        return []
    verb_hits = [v for v in _PROPAGATION_VERB_MARKERS if v in canonical]
    if not verb_hits:
        return []
    return [_PUBLIC_MARKER, *verb_hits]


def _schema_validate(value: Any, schema_path: Path) -> list[str]:
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    _validate(value, schema, "<root>", errors)
    return errors


def _matches_signature(media_type: str, payload: bytes) -> bool:
    if media_type == "image/png":
        return payload.startswith(_PNG_SIGNATURE)
    if media_type == "image/jpeg":
        return payload.startswith(_JPEG_SIGNATURE_PREFIX)
    return False


def _parent_chain_has_symlink(
    workspace: Path, relative: str
) -> tuple[bool, str]:
    """Walk from ``workspace`` to (but excluding) the leaf of
    ``relative`` and return ``(True, msg)`` if any intermediate segment
    is itself a symlink. ``relative`` is the workspace-relative path the
    registry declares; the workspace root itself is NOT inspected (the
    caller has already refused a symlinked workspace)."""
    rel = Path(relative)
    current = workspace
    for part in rel.parts[:-1]:
        current = current / part
        if current.is_symlink():
            try:
                target = str(current.readlink())
            except OSError:
                target = "<unreadable>"
            return True, (
                f"parent segment {current} (for {relative}) is a "
                f"symlink (-> {target})"
            )
    return False, ""


def _hash_file(path: Path) -> tuple[int, str, bytes]:
    """Return (byte_count, lowercase-hex sha256, first-8-byte prefix)
    for the file at ``path``. Read in chunks so a large fixture does
    not pin the whole payload in memory; the magic-byte gate only needs
    the first 8 bytes, so the first chunk is split off and retained."""
    h = hashlib.sha256()
    total = 0
    first: bytes = b""
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(65536)
            if not chunk:
                break
            if not first:
                first = chunk[:8]
            h.update(chunk)
            total += len(chunk)
    return total, h.hexdigest(), first


def _read_json_object(path: Path, label: str) -> tuple[dict, list[str]]:
    """Return ``(parsed_object, errors)``. ``errors`` is empty iff the
    file is a regular non-symlink JSON object."""
    errors: list[str] = []
    if path.is_symlink():
        try:
            target = str(path.readlink())
        except OSError:
            target = "<unreadable>"
        errors.append(
            f"{label} at {path} is a symlink (-> {target}); refusing to follow"
        )
        return {}, errors
    if not path.exists():
        errors.append(f"{label} not found at {path}")
        return {}, errors
    if not path.is_file():
        errors.append(f"{label} at {path} is not a regular file")
        return {}, errors
    try:
        raw = path.read_bytes()
    except OSError as exc:
        errors.append(f"{label} at {path} could not be read: {exc}")
        return {}, errors
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        errors.append(f"{label} at {path} is not valid UTF-8: {exc}")
        return {}, errors
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        errors.append(f"{label} at {path} is not valid JSON: {exc}")
        return {}, errors
    if not isinstance(parsed, dict):
        errors.append(
            f"{label} at {path} is not a JSON object at the root "
            f"(got {type(parsed).__name__})"
        )
        return {}, errors
    return parsed, errors


def validate_registry(
    *,
    workspace: Path,
    registry_path: Path,
) -> list[str]:
    """Run every gate against the registry at ``registry_path`` resolved
    relative to ``workspace``. Returns the (possibly empty) list of
    failure messages. The list is empty iff every gate passed."""
    errors: list[str] = []

    # --- workspace shape gates (string-level FIRST, then filesystem) ---
    ws_str = str(workspace)
    if _has_uri_scheme(ws_str):
        errors.append(
            f"--workspace {workspace} looks like a URI; only local "
            f"directory paths are accepted"
        )
        return errors
    if workspace.is_symlink():
        try:
            target = str(workspace.readlink())
        except OSError:
            target = "<unreadable>"
        errors.append(
            f"--workspace {workspace} is a symlink (-> {target}); "
            f"refusing to follow it"
        )
        return errors
    if not workspace.exists():
        errors.append(f"--workspace {workspace} does not exist")
        return errors
    if not workspace.is_dir():
        errors.append(f"--workspace {workspace} is not a directory")
        return errors

    # G1 readable_json_object
    registry, g1_errors = _read_json_object(registry_path, "registry")
    if g1_errors:
        errors.extend(g1_errors)
        return errors

    # G2 schema_subset_valid
    schema_errors = _schema_validate(registry, REGISTRY_SCHEMA)
    if schema_errors:
        errors.extend(
            f"schema: {e}" for e in schema_errors
        )
        # A schema-invalid registry can still have well-shaped enough
        # fields for the cross-checks; we keep going so the caller sees
        # every issue in one pass.

    assets = registry.get("assets")
    if not isinstance(assets, list):
        # Schema gate already fired above; nothing useful to cross-check.
        return errors

    # G3 unique_assets_ids
    seen_ids: dict[str, int] = {}
    for i, asset in enumerate(assets):
        if not isinstance(asset, dict):
            continue
        aid = asset.get("id")
        if not isinstance(aid, str):
            continue
        if aid in seen_ids:
            errors.append(
                f"assets[{i}].id {aid!r} duplicates "
                f"assets[{seen_ids[aid]}].id (G3 unique ids)"
            )
        else:
            seen_ids[aid] = i

    # G4 source_ref_matches_manifest (optional)
    manifest_source_id: str | None = None
    manifest_path = workspace / SOURCE_MANIFEST_FILENAME
    if manifest_path.exists() or manifest_path.is_symlink():
        manifest, m_errors = _read_json_object(
            manifest_path, SOURCE_MANIFEST_FILENAME
        )
        if m_errors:
            errors.extend(m_errors)
        else:
            source = manifest.get("source")
            if isinstance(source, dict):
                candidate = source.get("id")
                if isinstance(candidate, str):
                    manifest_source_id = candidate
            if manifest_source_id is None:
                errors.append(
                    f"{SOURCE_MANIFEST_FILENAME} is present but "
                    f"source.id is missing or not a string; "
                    f"source_ref cross-check skipped"
                )

    if manifest_source_id is not None:
        for i, asset in enumerate(assets):
            if not isinstance(asset, dict):
                continue
            sref = asset.get("source_ref")
            if isinstance(sref, str) and sref != manifest_source_id:
                errors.append(
                    f"assets[{i}].source_ref {sref!r} does not equal "
                    f"source_manifest.source.id {manifest_source_id!r} "
                    f"(G4)"
                )

    # G5 / G6 / G7 / G8 / G9 / G11 — per-asset filesystem gates.
    for i, asset in enumerate(assets):
        if not isinstance(asset, dict):
            continue
        aid = asset.get("id")
        local_path = asset.get("local_path")
        dest_path = asset.get("destination_path")
        media_type = asset.get("media_type")
        declared_bytes = asset.get("byte_count")
        declared_sha = asset.get("sha256")
        source_ref = asset.get("source_ref")

        # G11 — string shapes (whitespace + URI). These mirror what the
        # schema already enforces; running them at runtime catches any
        # field a future schema relaxation might widen.
        for field_name, field_value in (
            ("id", aid),
            ("source_ref", source_ref),
            ("local_path", local_path),
            ("destination_path", dest_path),
            ("sha256", declared_sha),
        ):
            if not isinstance(field_value, str):
                continue
            if field_value != field_value.strip():
                errors.append(
                    f"assets[{i}].{field_name} carries surrounding "
                    f"whitespace (G11)"
                )
            if _has_uri_scheme(field_value):
                errors.append(
                    f"assets[{i}].{field_name} {field_value!r} starts "
                    f"with a URI scheme (G11 — no URLs / file:// / "
                    f"data: / mailto: / ... allowed)"
                )

        # G12 — public-propagation intent deny. The match is done
        # against the canonical form (lower-cased + non-alphanumeric
        # stripped) and refuses the COMBINATION of the ``public`` marker
        # plus any propagation-verb marker, so every schema-permitted
        # separator / word-order / morphology / intervening-token
        # variant collapses to the same form. sha256 is skipped: it is
        # lowercase hex (0-9a-f) and cannot contain the ``public``
        # marker (the letters ``p``, ``u``, ``l``, ``i`` are all
        # outside the hex alphabet).
        for field_name, field_value in (
            ("id", aid),
            ("source_ref", source_ref),
            ("local_path", local_path),
            ("destination_path", dest_path),
        ):
            if not isinstance(field_value, str):
                continue
            hits = _public_deny_hits(field_value)
            if hits:
                errors.append(
                    f"assets[{i}].{field_name} {field_value!r} "
                    f"(canonical form {_canonical(field_value)!r}) "
                    f"combines the {_PUBLIC_MARKER!r} marker with "
                    f"propagation-verb marker(s) {hits[1:]!r} (G12 — "
                    f"public-upload / public-share / public-URL / "
                    f"public-post / public-publish / public-distribute / "
                    f"public-link propagation intent is refused; this "
                    f"registry is local-only)"
                )

        # G5 — path-safety + within-workspace.
        if isinstance(local_path, str):
            if not local_path_is_safe(local_path):
                errors.append(
                    f"assets[{i}].local_path {local_path!r} fails "
                    f"local_path_is_safe (G5)"
                )
            elif not _resolves_within(workspace, local_path):
                errors.append(
                    f"assets[{i}].local_path {local_path!r} resolves "
                    f"outside --workspace (G5)"
                )
            elif not local_path.startswith("input/assets/"):
                # Schema pattern already locks this; report at runtime
                # for clarity if the schema gate was somehow bypassed.
                errors.append(
                    f"assets[{i}].local_path {local_path!r} is not "
                    f"under 'input/assets/' (G5)"
                )

        if isinstance(dest_path, str):
            if not local_path_is_safe(dest_path):
                errors.append(
                    f"assets[{i}].destination_path {dest_path!r} fails "
                    f"local_path_is_safe (G5)"
                )
            elif not _resolves_within(workspace, dest_path):
                errors.append(
                    f"assets[{i}].destination_path {dest_path!r} "
                    f"resolves outside --workspace (G5)"
                )
            elif not dest_path.startswith("assets/"):
                errors.append(
                    f"assets[{i}].destination_path {dest_path!r} is "
                    f"not under 'assets/' (G5)"
                )

        # G6 — no symlink at source leaf or any parent segment of either
        # the source or the destination.
        if (
            isinstance(local_path, str)
            and local_path_is_safe(local_path)
            and _resolves_within(workspace, local_path)
        ):
            leaf = workspace / local_path
            if leaf.is_symlink():
                try:
                    t = str(leaf.readlink())
                except OSError:
                    t = "<unreadable>"
                errors.append(
                    f"assets[{i}].local_path {local_path!r} resolves "
                    f"to a symlink (-> {t}); refusing to follow (G6)"
                )
            bad, msg = _parent_chain_has_symlink(workspace, local_path)
            if bad:
                errors.append(
                    f"assets[{i}].local_path: {msg} (G6)"
                )

        if (
            isinstance(dest_path, str)
            and local_path_is_safe(dest_path)
            and _resolves_within(workspace, dest_path)
        ):
            bad, msg = _parent_chain_has_symlink(workspace, dest_path)
            if bad:
                errors.append(
                    f"assets[{i}].destination_path: {msg} (G6)"
                )

        # G7 / G8 / G9 — only meaningful when the source path is safe
        # and inside the workspace.
        leaf_ok = (
            isinstance(local_path, str)
            and local_path_is_safe(local_path)
            and _resolves_within(workspace, local_path)
        )
        if not leaf_ok:
            continue
        leaf = workspace / local_path
        if leaf.is_symlink():
            # Already reported under G6.
            continue
        if not leaf.exists():
            errors.append(
                f"assets[{i}].local_path {local_path!r}: file not "
                f"present at {leaf} (G7)"
            )
            continue
        if not leaf.is_file():
            errors.append(
                f"assets[{i}].local_path {local_path!r}: not a regular "
                f"file at {leaf} (G7)"
            )
            continue

        # G8 — byte_count + sha256 must match on-disk bytes.
        try:
            actual_bytes, actual_sha, first = _hash_file(leaf)
        except OSError as exc:
            errors.append(
                f"assets[{i}].local_path {local_path!r}: cannot read "
                f"{leaf}: {exc} (G7)"
            )
            continue
        if isinstance(declared_bytes, int) and actual_bytes != declared_bytes:
            errors.append(
                f"assets[{i}].byte_count {declared_bytes} does not "
                f"equal on-disk length {actual_bytes} at {leaf} (G8)"
            )
        if isinstance(declared_sha, str) and actual_sha != declared_sha:
            errors.append(
                f"assets[{i}].sha256 {declared_sha!r} does not equal "
                f"on-disk sha256 {actual_sha!r} at {leaf} (G8)"
            )

        # G9 — media_type vs extension vs magic bytes.
        if isinstance(media_type, str):
            allowed_exts = _MEDIA_TYPE_TO_EXTS.get(media_type)
            if allowed_exts is None:
                # Schema enum already refuses, but be explicit.
                errors.append(
                    f"assets[{i}].media_type {media_type!r} is not in "
                    f"the supported set "
                    f"{sorted(_MEDIA_TYPE_TO_EXTS)} (G9)"
                )
            else:
                for path_field_name, path_value in (
                    ("local_path", local_path),
                    ("destination_path", dest_path),
                ):
                    if not isinstance(path_value, str):
                        continue
                    ext = Path(path_value).suffix.lower().lstrip(".")
                    if ext not in allowed_exts:
                        errors.append(
                            f"assets[{i}].{path_field_name} extension "
                            f".{ext!r} does not agree with media_type "
                            f"{media_type!r} (allowed: "
                            f"{sorted(allowed_exts)}) (G9)"
                        )
                if not _matches_signature(media_type, first):
                    errors.append(
                        f"assets[{i}].local_path {local_path!r}: "
                        f"first bytes do not match the magic-byte "
                        f"signature for media_type {media_type!r} "
                        f"(got first 8 bytes {first!r}) (G9)"
                    )

    # G10 (alignment of matched ids) + G13 (declaration required of
    # every registry id) — both optional, both gated on the presence of
    # a sibling image_manifest.json. G10 silently allows registry ids
    # the manifest does not name (a workspace may legitimately declare
    # more attached assets than the current deck cites — that toleration
    # is the original G10 contract). G13 is the separate completeness
    # gate that refuses the same case fail-closed: once the deck has
    # committed to an image_manifest.json, a registry that names an
    # attached asset the manifest never references is propagation drift
    # (the asset would never reach the deck) and must be refused so the
    # author either adds the manifest entry or removes the registry
    # entry. Keeping the two concerns under separate gate ids preserves
    # G10's original behavior unchanged and gives the completeness
    # strictness its own deterministic citation.
    image_manifest_path = workspace / IMAGE_MANIFEST_FILENAME
    if image_manifest_path.exists() or image_manifest_path.is_symlink():
        manifest, im_errors = _read_json_object(
            image_manifest_path, IMAGE_MANIFEST_FILENAME
        )
        if im_errors:
            errors.extend(im_errors)
            # Cannot run G10 / G13 — the underlying read failure has
            # already failed the run fail-closed. (Symlink, missing
            # file, malformed JSON, non-object root, etc. all land
            # here; _read_json_object owns the diagnostic.)
        else:
            # G13 structural precondition — image_manifest.json must
            # carry an ``images`` array. Without it, neither G10
            # (alignment of matched ids) nor G13 (completeness across
            # every registry id) can run, and silently skipping both
            # checks would let a malformed manifest mask propagation
            # drift fail-open: an author who wrote ``{"foo": "bar"}``
            # (or omitted ``images`` entirely, or stored a non-list
            # value under ``images``) would get a green validator
            # result while every registry asset was undeclared.
            # Refuse fail-closed under G13 so the author either makes
            # the manifest structurally valid or removes the file.
            if "images" not in manifest:
                errors.append(
                    f"{IMAGE_MANIFEST_FILENAME} at "
                    f"{image_manifest_path}: required 'images' field "
                    f"is missing; G10 alignment AND G13 declaration "
                    f"checks require a well-formed images[] list, "
                    f"refusing fail-closed (G13)"
                )
            elif not isinstance(manifest["images"], list):
                errors.append(
                    f"{IMAGE_MANIFEST_FILENAME} at "
                    f"{image_manifest_path}: 'images' is not a list "
                    f"(got {type(manifest['images']).__name__}); "
                    f"G10 alignment AND G13 declaration checks "
                    f"require a well-formed images[] list, refusing "
                    f"fail-closed (G13)"
                )
            else:
                images = manifest["images"]
                by_id: dict[str, dict] = {}
                for img in images:
                    if isinstance(img, dict):
                        iid = img.get("id")
                        if isinstance(iid, str):
                            by_id[iid] = img
                for i, asset in enumerate(assets):
                    if not isinstance(asset, dict):
                        continue
                    aid = asset.get("id")
                    if not isinstance(aid, str):
                        continue
                    img = by_id.get(aid)
                    if img is None:
                        # G13 completeness — registry id missing from
                        # manifest. G10 (alignment) is a no-op here:
                        # there is nothing to align with. G10's
                        # original contract silently tolerates this
                        # case; G13 refuses it.
                        errors.append(
                            f"assets[{i}].id {aid!r}: "
                            f"image_manifest.json is present but does "
                            f"not declare an images[] entry with this "
                            f"id; every registry asset must be declared "
                            f"in image_manifest.images[].id (G13)"
                        )
                        continue
                    # G10 alignment — for matched ids only. Behavior
                    # unchanged from the original G10 contract.
                    if img.get("source") != "local_asset":
                        errors.append(
                            f"assets[{i}].id {aid!r}: image_manifest "
                            f"entry has source={img.get('source')!r}, "
                            f"expected 'local_asset' (G10)"
                        )
                    declared_dest = asset.get("destination_path")
                    manifest_local_path = img.get("local_path")
                    if (
                        isinstance(declared_dest, str)
                        and isinstance(manifest_local_path, str)
                        and declared_dest != manifest_local_path
                    ):
                        errors.append(
                            f"assets[{i}].destination_path "
                            f"{declared_dest!r} does not equal "
                            f"image_manifest entry local_path "
                            f"{manifest_local_path!r} for id {aid!r} "
                            f"(G10)"
                        )

    return errors


# ---------------------------------------------------------------------------
# Self-test scenarios. Every fixture is built in a fresh tempdir; no
# repo file is mutated, no network is touched.
# ---------------------------------------------------------------------------


# Smallest PNG / JPEG payloads that pass the magic-byte gate. They are
# NOT valid full images (no IHDR / EOI), just the minimum bytes the
# materialize gate accepts. The validator only checks the signature
# prefix; the byte_count + sha256 gates do their own thing against the
# actual bytes on disk.
_PNG_TEST_BYTES = _PNG_SIGNATURE + b"\x00" * 8
_JPEG_TEST_BYTES = _JPEG_SIGNATURE_PREFIX + b"\xe0\x00" + b"\x00" * 8


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _write_registry(
    workspace: Path, assets: list[dict]
) -> Path:
    registry = {"schema_version": "1", "assets": assets}
    p = workspace / REGISTRY_FILENAME
    p.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return p


def _write_source_manifest(workspace: Path, source_id: str) -> Path:
    manifest = {
        "schema_version": "1",
        "source": {
            "id": source_id,
            "local_path": "input/source.md",
            "kind": "markdown",
            "byte_count": 1,
            "line_count": 1,
            "sha256": _sha256(b"x"),
        },
        "tool": {"name": "init_workspace.py", "version": "0"},
    }
    p = workspace / SOURCE_MANIFEST_FILENAME
    p.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return p


def _write_image_manifest(workspace: Path, images: list[dict]) -> Path:
    p = workspace / IMAGE_MANIFEST_FILENAME
    p.write_text(
        json.dumps({"images": images}, indent=2), encoding="utf-8"
    )
    return p


def _put_asset(
    workspace: Path, rel: str, payload: bytes
) -> tuple[int, str]:
    """Materialize asset bytes inside the workspace and return
    ``(byte_count, sha256)`` for the registry."""
    leaf = workspace / rel
    leaf.parent.mkdir(parents=True, exist_ok=True)
    leaf.write_bytes(payload)
    return len(payload), _sha256(payload)


def _good_png_asset(
    workspace: Path,
    *,
    asset_id: str = "synthetic_alpha",
    source_ref: str = "synthetic_src",
) -> dict:
    rel_local = f"input/assets/{asset_id}.png"
    rel_dest = f"assets/{asset_id}.png"
    bc, sh = _put_asset(workspace, rel_local, _PNG_TEST_BYTES)
    return {
        "id": asset_id,
        "source_ref": source_ref,
        "local_path": rel_local,
        "destination_path": rel_dest,
        "media_type": "image/png",
        "byte_count": bc,
        "sha256": sh,
    }


def _good_jpeg_asset(
    workspace: Path,
    *,
    asset_id: str = "synthetic_beta",
    source_ref: str = "synthetic_src",
    ext: str = "jpg",
) -> dict:
    rel_local = f"input/assets/{asset_id}.{ext}"
    rel_dest = f"assets/{asset_id}.{ext}"
    bc, sh = _put_asset(workspace, rel_local, _JPEG_TEST_BYTES)
    return {
        "id": asset_id,
        "source_ref": source_ref,
        "local_path": rel_local,
        "destination_path": rel_dest,
        "media_type": "image/jpeg",
        "byte_count": bc,
        "sha256": sh,
    }


def _expect(name: str, ok: bool, detail: str = "") -> tuple[str, bool, str]:
    return (name, ok, detail)


def _run_validator(workspace: Path, registry_path: Path) -> list[str]:
    return validate_registry(
        workspace=workspace, registry_path=registry_path
    )


def _run_self_tests() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    # T1 happy path: single PNG asset, no source_manifest, no image_manifest.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        asset = _good_png_asset(td)
        rp = _write_registry(td, [asset])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T1: single PNG asset, no manifests -> PASS",
            errs == [],
            f"errs={errs!r}",
        ))

    # T2 happy path: PNG + JPG with source_manifest matching source_ref.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        _write_source_manifest(td, source_id="synthetic_src")
        a1 = _good_png_asset(td, asset_id="png_one")
        a2 = _good_jpeg_asset(td, asset_id="jpg_one")
        a3 = _good_jpeg_asset(td, asset_id="jpeg_one", ext="jpeg")
        rp = _write_registry(td, [a1, a2, a3])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T2: PNG + JPG + JPEG with matching source_manifest -> PASS",
            errs == [],
            f"errs={errs!r}",
        ))

    # T3 happy path: empty assets list is valid.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rp = _write_registry(td, [])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T3: empty assets list -> PASS",
            errs == [],
            f"errs={errs!r}",
        ))

    # T4 happy path: image_manifest aligned on id + destination + source.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td, asset_id="hero")
        _write_image_manifest(td, [{
            "id": "hero",
            "local_path": a["destination_path"],
            "source": "local_asset",
        }])
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T4: aligned image_manifest -> PASS",
            errs == [],
            f"errs={errs!r}",
        ))

    # T5 G1: registry is missing.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rp = td / REGISTRY_FILENAME  # not written
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T5: missing registry -> FAIL (G1)",
            any("not found" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T6 G1: registry is malformed JSON.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rp = td / REGISTRY_FILENAME
        rp.write_text("{ not valid json", encoding="utf-8")
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T6: malformed JSON -> FAIL (G1)",
            any("not valid JSON" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T7 G1: registry root is a list, not an object.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rp = td / REGISTRY_FILENAME
        rp.write_text("[]", encoding="utf-8")
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T7: list-root JSON -> FAIL (G1)",
            any("not a JSON object" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T8 G1: registry is a symlink.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        real = td / "real_registry.json"
        real.write_text("{}", encoding="utf-8")
        rp = td / REGISTRY_FILENAME
        try:
            rp.symlink_to(real.name)
        except (OSError, NotImplementedError):
            results.append(_expect(
                "T8: registry-is-symlink scenario skipped on this OS",
                True,
            ))
        else:
            errs = _run_validator(td, rp)
            results.append(_expect(
                "T8: symlink at registry -> FAIL (G1)",
                any("symlink" in e for e in errs),
                f"errs={errs!r}",
            ))

    # T9 G2: schema-invalid (missing schema_version).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rp = td / REGISTRY_FILENAME
        rp.write_text(
            json.dumps({"assets": []}), encoding="utf-8"
        )
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T9: missing schema_version -> FAIL (G2)",
            any("missing required property 'schema_version'" in e
                for e in errs),
            f"errs={errs!r}",
        ))

    # T10 G3: duplicate ids.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a1 = _good_png_asset(td, asset_id="dup")
        # Build a second asset that shares id but lives at a different
        # local_path so we are not also tripping a schema gate first.
        a2 = _good_png_asset(td, asset_id="other")
        a2["id"] = "dup"
        rp = _write_registry(td, [a1, a2])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T10: duplicate assets[].id -> FAIL (G3)",
            any("duplicates" in e and "G3" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T11 G4: source_ref does not match source_manifest.source.id.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        _write_source_manifest(td, source_id="real_src")
        a = _good_png_asset(td, source_ref="wrong_src")
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T11: source_ref mismatch with source_manifest -> FAIL (G4)",
            any("does not equal source_manifest.source.id" in e
                for e in errs),
            f"errs={errs!r}",
        ))

    # T12 G4: no source_manifest -> source_ref cross-check is skipped.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td, source_ref="anything_goes")
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T12: no source_manifest -> G4 skipped, PASS",
            errs == [],
            f"errs={errs!r}",
        ))

    # T13 G5: local_path with '..' segment is refused at runtime. The
    # schema pattern already refuses this; we still verify the runtime
    # gate fires (defense-in-depth).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        a["local_path"] = "input/assets/../escape.png"
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T13: local_path with '..' -> FAIL (G5)",
            any("G5" in e for e in errs)
            or any("does not match pattern" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T14 G5: destination_path starts with absolute slash.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        a["destination_path"] = "/abs/cover.png"
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T14: destination_path absolute -> FAIL",
            errs != [],
            f"errs={errs!r}",
        ))

    # T15 G5: local_path is a URI scheme.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        a["local_path"] = "https://example.com/x.png"
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T15: local_path with URI scheme -> FAIL",
            errs != [],
            f"errs={errs!r}",
        ))

    # T16 G6: source asset is a symlink.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        # Build a real asset, then replace it with a symlink to another
        # file (still inside the workspace).
        a = _good_png_asset(td)
        real = workspace_real_target = td / "input" / "assets" / "real.png"
        real.write_bytes(_PNG_TEST_BYTES)
        leaf = td / a["local_path"]
        leaf.unlink()
        try:
            leaf.symlink_to(real.name)
        except (OSError, NotImplementedError):
            results.append(_expect(
                "T16: source-asset-is-symlink scenario skipped on this OS",
                True,
            ))
        else:
            rp = _write_registry(td, [a])
            errs = _run_validator(td, rp)
            results.append(_expect(
                "T16: symlink at source asset -> FAIL (G6)",
                any("symlink" in e and "G6" in e for e in errs),
                f"errs={errs!r}",
            ))

    # T17 G6: destination parent is a symlink. The destination leaf is
    # never written by this validator, but the PARENT chain must be
    # symlink-free.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        real_dir = td / "real_assets"
        real_dir.mkdir()
        symlinked_dir = td / "assets"
        if symlinked_dir.exists():
            # Some earlier helper may have created assets/ implicitly;
            # remove it to make room for the symlink.
            try:
                for child in symlinked_dir.iterdir():
                    child.unlink()
                symlinked_dir.rmdir()
            except OSError:
                pass
        try:
            symlinked_dir.symlink_to(real_dir, target_is_directory=True)
        except (OSError, NotImplementedError):
            results.append(_expect(
                "T17: destination-parent-symlink scenario skipped on "
                "this OS",
                True,
            ))
        else:
            rp = _write_registry(td, [a])
            errs = _run_validator(td, rp)
            results.append(_expect(
                "T17: symlink at destination parent -> FAIL (G6)",
                any("symlink" in e and "G6" in e for e in errs),
                f"errs={errs!r}",
            ))

    # T18 G7: declared asset file is absent.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        (td / a["local_path"]).unlink()
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T18: missing source asset file -> FAIL (G7)",
            any("G7" in e and "file not present" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T19 G8: byte_count mismatch.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        a["byte_count"] = a["byte_count"] + 1
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T19: byte_count mismatch -> FAIL (G8)",
            any("byte_count" in e and "G8" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T20 G8: sha256 mismatch.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        a["sha256"] = "0" * 64
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T20: sha256 mismatch -> FAIL (G8)",
            any("sha256" in e and "G8" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T21 G9: media_type does not match extension. Put PNG-ish bytes
    # under a .jpg extension and claim image/jpeg — the magic-byte gate
    # fails (PNG signature != JPEG signature). Also ensures the
    # extension agreement gate exercises a real divergence.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rel_local = "input/assets/wrong.jpg"
        rel_dest = "assets/wrong.jpg"
        bc, sh = _put_asset(td, rel_local, _PNG_TEST_BYTES)
        a = {
            "id": "wrong",
            "source_ref": "synthetic_src",
            "local_path": rel_local,
            "destination_path": rel_dest,
            "media_type": "image/jpeg",
            "byte_count": bc,
            "sha256": sh,
        }
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T21: media_type/magic-byte mismatch -> FAIL (G9)",
            any("magic-byte signature" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T22 G9: media_type vs extension disagreement (bytes match the
    # declared media_type but the extension is wrong). We rewrite the
    # local_path to .png while declaring image/jpeg.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_jpeg_asset(td, ext="jpg")
        # Move the asset under a .png leaf so the path extension and
        # media_type disagree. We re-place the bytes on disk so G7/G8
        # don't fire.
        new_local = "input/assets/" + a["id"] + ".png"
        new_dest = "assets/" + a["id"] + ".png"
        bc, sh = _put_asset(td, new_local, _JPEG_TEST_BYTES)
        a["local_path"] = new_local
        a["destination_path"] = new_dest
        a["byte_count"] = bc
        a["sha256"] = sh
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T22: media_type=jpeg with .png extension -> FAIL (G9)",
            any("does not agree with media_type" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T23 G9: schema enum refuses image/svg+xml. The schema fires;
    # the runtime mirror also catches it if a future schema relaxation
    # widens the enum.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        a["media_type"] = "image/svg+xml"
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T23: unsupported media_type image/svg+xml -> FAIL",
            errs != [],
            f"errs={errs!r}",
        ))

    # T24 G10: image_manifest entry has source != "local_asset".
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td, asset_id="hero")
        _write_image_manifest(td, [{
            "id": "hero",
            "local_path": a["destination_path"],
            "source": "synthetic",
        }])
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T24: image_manifest source != local_asset -> FAIL (G10)",
            any("'local_asset'" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T25 G10: image_manifest local_path does not equal destination_path.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td, asset_id="hero")
        _write_image_manifest(td, [{
            "id": "hero",
            "local_path": "assets/different.png",
            "source": "local_asset",
        }])
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T25: image_manifest local_path differs from "
            "registry destination_path -> FAIL (G10)",
            any("does not equal image_manifest entry local_path" in e
                for e in errs),
            f"errs={errs!r}",
        ))

    # T26 G13: registry asset the image_manifest does not name now
    # fails fail-closed under G13 (the new completeness gate; G10's
    # original alignment contract is unchanged — it still silently
    # tolerates this case, and the failure is attributed to G13 alone
    # so a future relaxation of completeness can flip exactly one gate
    # without disturbing alignment).
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a1 = _good_png_asset(td, asset_id="cited")
        a2 = _good_png_asset(td, asset_id="extra")
        _write_image_manifest(td, [{
            "id": "cited",
            "local_path": a1["destination_path"],
            "source": "local_asset",
        }])
        rp = _write_registry(td, [a1, a2])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T26: registry asset not in image_manifest -> FAIL (G13)",
            any(
                "every registry asset must be declared" in e and "G13" in e
                for e in errs
            )
            # The G10 alignment gate must NOT fire for the missing id
            # ("extra"). Either zero G10 errors, or any G10 error refers
            # only to the matched id ("cited"). For this scenario there
            # are no alignment problems so G10 fires zero times.
            and not any("G10" in e and "extra" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T27 G11: id with surrounding whitespace. The schema pattern
    # already refuses this; we still verify the runtime mirror fires so
    # a future schema relaxation cannot silently open a hole.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        a["id"] = " " + a["id"]
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T27: id with leading whitespace -> FAIL",
            errs != [],
            f"errs={errs!r}",
        ))

    # T28 workspace shape: --workspace is a symlink.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        real_ws = td / "real_ws"
        real_ws.mkdir()
        link_ws = td / "link_ws"
        try:
            link_ws.symlink_to(real_ws, target_is_directory=True)
        except (OSError, NotImplementedError):
            results.append(_expect(
                "T28: workspace-is-symlink scenario skipped on this OS",
                True,
            ))
        else:
            errs = validate_registry(
                workspace=link_ws,
                registry_path=link_ws / REGISTRY_FILENAME,
            )
            results.append(_expect(
                "T28: --workspace is a symlink -> FAIL",
                any("symlink" in e for e in errs),
                f"errs={errs!r}",
            ))

    # T29 workspace shape: URI-shaped --workspace value.
    errs = validate_registry(
        workspace=Path("https://example.com/ws"),
        registry_path=Path("https://example.com/ws") / REGISTRY_FILENAME,
    )
    results.append(_expect(
        "T29: URI-shaped --workspace -> FAIL",
        any("URI" in e for e in errs),
        f"errs={errs!r}",
    ))

    # T30 default registry path: validator picks
    # <workspace>/source_image_assets.json when --registry is omitted.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        _write_registry(td, [a])
        errs = validate_registry(
            workspace=td,
            registry_path=td / REGISTRY_FILENAME,
        )
        results.append(_expect(
            "T30: default registry path resolution -> PASS",
            errs == [],
            f"errs={errs!r}",
        ))

    # T31 G10 + G13: image_manifest is present and declares the
    # registry id -> PASS. Both the alignment gate (G10) and the
    # completeness gate (G13) are satisfied.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td, asset_id="source_hero")
        _write_image_manifest(td, [{
            "id": "source_hero",
            "local_path": a["destination_path"],
            "source": "local_asset",
        }])
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T31: image_manifest declares registry id -> PASS "
            "(G10 + G13)",
            errs == [],
            f"errs={errs!r}",
        ))

    # T32 G13: image_manifest is present and does NOT declare the
    # registry id -> FAIL fail-closed under G13 alone. G10 (alignment)
    # is a no-op for the missing id (nothing to align against). G10's
    # original "silently tolerate registry-not-in-manifest" contract
    # is unchanged; the failure is attributed to G13.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td, asset_id="undeclared_asset")
        # Manifest lists a different id; the registry id is missing.
        _write_image_manifest(td, [{
            "id": "some_other_id",
            "local_path": "assets/some_other_id.png",
            "source": "local_asset",
        }])
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T32: image_manifest missing declared id -> FAIL (G13)",
            any(
                "every registry asset must be declared" in e and "G13" in e
                for e in errs
            )
            and not any(
                "G10" in e and "undeclared_asset" in e for e in errs
            ),
            f"errs={errs!r}",
        ))

    # T33 G12: each documented public-upload / public-share /
    # public-URL identifier fails. The schema patterns accept these as
    # well-shaped ids; G12 is the language-level deny that closes the
    # hole.
    public_deny_id_cases = (
        "public_upload",
        "public_upload_asset",
        "share_publicly",
        "public_url_for_assets",
        "upload_to_public_bucket",
    )
    for bad_id in public_deny_id_cases:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            a = _good_png_asset(td, asset_id=bad_id)
            rp = _write_registry(td, [a])
            errs = _run_validator(td, rp)
            results.append(_expect(
                f"T33[{bad_id}]: public-* id -> FAIL (G12)",
                any("G12" in e for e in errs),
                f"errs={errs!r}",
            ))

    # T34 G12: safe synthetic ids (source_hero, product_marker,
    # local_chart_asset) do NOT trip G12. They are policy-clean labels
    # and must continue to validate when every other gate passes.
    safe_id_cases = ("source_hero", "product_marker", "local_chart_asset")
    for safe_id in safe_id_cases:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            a = _good_png_asset(td, asset_id=safe_id)
            rp = _write_registry(td, [a])
            errs = _run_validator(td, rp)
            results.append(_expect(
                f"T34[{safe_id}]: safe synthetic id -> PASS (G12 clean)",
                errs == [],
                f"errs={errs!r}",
            ))

    # T35 G12: deny scan applies to source_ref as well as id. The schema
    # pattern for source_ref is the same shape as id, so the same
    # public-* wording can leak through if G12 only checks id.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td, source_ref="share_publicly")
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T35: source_ref=share_publicly -> FAIL (G12)",
            any("G12" in e and "source_ref" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T36 G12: case-insensitive matching — a schema-permitted uppercase
    # variant (``Public_Upload``) must not bypass the deny.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td, asset_id="Public_Upload")
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T36: id with uppercase Public_Upload -> FAIL (G12)",
            any("G12" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T37 G12: schema-permitted SEPARATOR variants of the same wording
    # must not bypass the deny. The schema id pattern permits ``_``,
    # ``.``, AND ``-`` as separators (and the locked path patterns
    # carry the same set), so a literal-substring scan that only knew
    # about ``public_upload`` would refuse it while letting
    # ``public-upload`` / ``public.upload`` / ``publicupload`` /
    # ``share-publicly`` / ``share.publicly`` / ``sharepublicly`` /
    # ``public-url-for-assets`` / ``upload-to-public-bucket`` slip
    # past. The canonical-form check folds every separator permutation
    # to the same form and refuses them as one rule.
    separator_bypass_ids = (
        # Hyphen variants
        "public-upload",
        "public-upload-asset",
        "share-publicly",
        "public-url-for-assets",
        "upload-to-public-bucket",
        # Dot variants
        "public.upload",
        "public.upload.asset",
        "share.publicly",
        "public.url.for.assets",
        "upload.to.public.bucket",
        # Run-together (no separator)
        "publicupload",
        "publicuploadasset",
        "sharepublicly",
        "publicurlforassets",
        "uploadtopublicbucket",
        # Mixed separator
        "public-upload_asset",
        "public.upload-asset",
        "share-publicly.asset",
        # Multiple consecutive separators
        "public__upload",
        "public..upload",
        "public--upload",
        "public_-_upload",
        # Case + separator mix
        "Public-Upload",
        "Share.Publicly",
        "Public-URL-For-Assets",
        "Upload.To.Public.Bucket",
    )
    for bad_id in separator_bypass_ids:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            a = _good_png_asset(td, asset_id=bad_id)
            rp = _write_registry(td, [a])
            errs = _run_validator(td, rp)
            results.append(_expect(
                f"T37[{bad_id}]: schema-permitted separator variant "
                f"-> FAIL (G12)",
                any("G12" in e for e in errs),
                f"errs={errs!r}",
            ))

    # T38 G12: schema-permitted separator bypasses must also fail when
    # they show up inside a path (local_path / destination_path), not
    # just id / source_ref. The locked path patterns admit the same
    # ``_`` / ``.`` / ``-`` set inside the filename portion, so a path
    # like ``input/assets/public-upload.png`` is schema-valid but must
    # be refused by G12.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        rel_local = "input/assets/public-upload.png"
        rel_dest = "assets/public-upload.png"
        bc, sh = _put_asset(td, rel_local, _PNG_TEST_BYTES)
        a = {
            "id": "synthetic_alpha",
            "source_ref": "synthetic_src",
            "local_path": rel_local,
            "destination_path": rel_dest,
            "media_type": "image/png",
            "byte_count": bc,
            "sha256": sh,
        }
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T38: local_path containing 'public-upload' -> FAIL (G12)",
            any(
                "G12" in e and "local_path" in e for e in errs
            ),
            f"errs={errs!r}",
        ))

    # T39 G12: schema-permitted public-SHARE wording variants. A fixed
    # canonical-token list like ``sharepublicly`` would refuse
    # ``share_publicly`` while letting ``public_share`` /
    # ``share_public`` / ``publicly_shared`` / ``shared_publicly`` /
    # ``share_with_public`` / ``public_sharing`` / ``sharing_public``
    # slip past — they are policy-violations identical to
    # ``share_publicly``. The combined ``public`` + verb marker check
    # refuses every word-order / morphology / separator permutation
    # under one rule.
    share_class_bypass_ids = (
        "public_share",
        "public-share",
        "public.share",
        "publicshare",
        "share_public",
        "share-public",
        "sharepublic",
        "publicly_shared",
        "publiclyshared",
        "shared_publicly",
        "sharedpublicly",
        "share_with_public",
        "share_to_public",
        "public_sharing",
        "sharing_public",
        "Public_Share",
        "Public-Sharing",
        "Shared.Publicly",
    )
    for bad_id in share_class_bypass_ids:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            a = _good_png_asset(td, asset_id=bad_id)
            rp = _write_registry(td, [a])
            errs = _run_validator(td, rp)
            results.append(_expect(
                f"T39[{bad_id}]: public-share wording variant "
                f"-> FAIL (G12)",
                any("G12" in e for e in errs),
                f"errs={errs!r}",
            ))

    # T40 G12: other propagation-verb combinations with ``public`` also
    # fail. The policy is symmetric across verbs — refusing only
    # ``public + share`` while allowing ``public + post`` /
    # ``public + publish`` / ``public + link`` / ``public + distribute``
    # would be incoherent.
    other_verb_bypass_ids = (
        "public_post",
        "public_publish",
        "public_publishing",
        "public_link",
        "public_linking",
        "public_distribute",
        "public_distribution",
        "public_distributing",
        "publish_to_public",
        "link_to_public",
        "post_to_public",
        "distribute_public",
        "distribute_to_public",
        "public-post",
        "public.publish",
        "Public-Distribution",
    )
    for bad_id in other_verb_bypass_ids:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            a = _good_png_asset(td, asset_id=bad_id)
            rp = _write_registry(td, [a])
            errs = _run_validator(td, rp)
            results.append(_expect(
                f"T40[{bad_id}]: public + {{post,publish,link,"
                f"distribute}} wording -> FAIL (G12)",
                any("G12" in e for e in errs),
                f"errs={errs!r}",
            ))

    # T41 G12 invariant: ``public`` alone (without a propagation verb)
    # MUST keep passing. The deny targets propagation INTENT, not the
    # bare presence of the word ``public``. Without this invariant the
    # deny would false-positive on benign labels like ``public_chart``
    # / ``public_domain_marker`` / ``publication_meta`` and ids whose
    # canonical form happens to contain ``public`` as a substring of
    # ``republic`` / ``republican`` / etc.
    public_alone_safe_ids = (
        "public_chart",
        "public_marker",
        "public_domain_asset",
        "publication_meta",
        "republican_emblem",  # canonical 'republicanemblem' contains 'public'
    )
    for safe_id in public_alone_safe_ids:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            a = _good_png_asset(td, asset_id=safe_id)
            rp = _write_registry(td, [a])
            errs = _run_validator(td, rp)
            results.append(_expect(
                f"T41[{safe_id}]: 'public' alone without verb "
                f"-> PASS (G12 invariant)",
                errs == [],
                f"errs={errs!r}",
            ))

    # T42 G12 invariant: propagation-verb markers alone (without
    # ``public``) MUST keep passing. An asset id may legitimately say
    # ``share_image`` / ``upload_chart`` / ``permalink_marker`` /
    # ``post_meta`` / ``publish_run`` / ``shared_team_data`` without
    # implying public propagation. The deny is on the COMBINATION; a
    # verb alone is too ambiguous to refuse.
    verb_alone_safe_ids = (
        "share_image",
        "upload_chart",
        "url_meta",
        "permalink_marker",
        "post_meta",
        "publish_run",
        "distribute_internal",
        "shared_team_data",
        "sharing_internal_only",
    )
    for safe_id in verb_alone_safe_ids:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            a = _good_png_asset(td, asset_id=safe_id)
            rp = _write_registry(td, [a])
            errs = _run_validator(td, rp)
            results.append(_expect(
                f"T42[{safe_id}]: verb alone without 'public' "
                f"-> PASS (G12 invariant)",
                errs == [],
                f"errs={errs!r}",
            ))

    # T43 G10 / G13 separation invariant: with TWO registry assets
    # ("matched" + "extra") and a manifest that DECLARES only
    # "matched" but with a WRONG source, G10 must fire on the matched
    # pair AND G13 must fire on the extra. Verifying both citations
    # appear independently confirms the split is clean — G10 still
    # carries its original alignment contract on the matched id, and
    # G13 carries the new completeness contract on the missing id.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a_matched = _good_png_asset(td, asset_id="matched")
        a_extra = _good_png_asset(td, asset_id="extra")
        # Manifest lists "matched" but with the WRONG source (not
        # "local_asset") — should fire G10. Does not list "extra" —
        # should fire G13.
        _write_image_manifest(td, [{
            "id": "matched",
            "local_path": a_matched["destination_path"],
            "source": "d_one_local",
        }])
        rp = _write_registry(td, [a_matched, a_extra])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T43: G10 (alignment of 'matched') AND G13 ('extra' "
            "missing) fire independently",
            any(
                "matched" in e and "G10" in e and "local_asset" in e
                for e in errs
            )
            and any(
                "extra" in e and "G13" in e for e in errs
            ),
            f"errs={errs!r}",
        ))

    # T44 G10 silently-tolerates-extra invariant: when the manifest
    # entry for a matched id is FULLY ALIGNED (source=local_asset,
    # local_path=destination_path), an EXTRA registry asset not named
    # by the manifest fires G13 alone — G10 must produce zero errors
    # for that scenario. This is the test that pins the
    # "G10 alignment contract preserved" guarantee.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a_matched = _good_png_asset(td, asset_id="matched")
        a_extra = _good_png_asset(td, asset_id="extra")
        _write_image_manifest(td, [{
            "id": "matched",
            "local_path": a_matched["destination_path"],
            "source": "local_asset",
        }])
        rp = _write_registry(td, [a_matched, a_extra])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T44: G10 fires ZERO times on a clean alignment, G13 "
            "alone fires for the extra registry asset",
            any("G13" in e and "extra" in e for e in errs)
            and not any("G10" in e for e in errs),
            f"errs={errs!r}",
        ))

    # T45 G13 fail-closed on structurally invalid image_manifest:
    # ``{"foo": "bar"}`` — present, parses as a JSON object, but the
    # required ``images`` field is absent. Previously G13 silently
    # skipped this case (fail-OPEN); the structural precondition gate
    # now refuses it fail-closed.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        # Write a manifest that has NO 'images' key.
        (td / IMAGE_MANIFEST_FILENAME).write_text(
            json.dumps({"foo": "bar"}), encoding="utf-8"
        )
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T45: image_manifest with no 'images' key -> FAIL (G13 "
            "structural precondition)",
            any(
                "'images' field is missing" in e and "G13" in e
                for e in errs
            ),
            f"errs={errs!r}",
        ))

    # T46 G13 fail-closed on structurally invalid image_manifest:
    # ``{"images": null}`` — present, parses, but ``images`` is null
    # rather than a list.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        (td / IMAGE_MANIFEST_FILENAME).write_text(
            json.dumps({"images": None}), encoding="utf-8"
        )
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T46: image_manifest with 'images': null -> FAIL (G13 "
            "structural precondition)",
            any(
                "'images' is not a list" in e and "G13" in e
                for e in errs
            ),
            f"errs={errs!r}",
        ))

    # T47 G13 fail-closed on structurally invalid image_manifest:
    # ``{"images": "not a list"}`` — present, parses, but ``images``
    # is a string.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        (td / IMAGE_MANIFEST_FILENAME).write_text(
            json.dumps({"images": "not a list"}), encoding="utf-8"
        )
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T47: image_manifest with 'images': string -> FAIL (G13 "
            "structural precondition)",
            any(
                "'images' is not a list" in e and "G13" in e
                for e in errs
            ),
            f"errs={errs!r}",
        ))

    # T48 G13 fail-closed on structurally invalid image_manifest:
    # ``{"images": 42}`` — present, parses, but ``images`` is an int.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        (td / IMAGE_MANIFEST_FILENAME).write_text(
            json.dumps({"images": 42}), encoding="utf-8"
        )
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T48: image_manifest with 'images': int -> FAIL (G13 "
            "structural precondition)",
            any(
                "'images' is not a list" in e and "G13" in e
                for e in errs
            ),
            f"errs={errs!r}",
        ))

    # T49 G13 fail-closed on structurally invalid image_manifest:
    # ``{"images": {}}`` — present, parses, but ``images`` is an
    # object instead of a list. JSON schema would refuse this, but
    # the registry validator must not depend on a separate schema run
    # — it must catch this defensively under G13.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td)
        (td / IMAGE_MANIFEST_FILENAME).write_text(
            json.dumps({"images": {"id": "hero"}}), encoding="utf-8"
        )
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T49: image_manifest with 'images': object -> FAIL (G13 "
            "structural precondition)",
            any(
                "'images' is not a list" in e and "G13" in e
                for e in errs
            ),
            f"errs={errs!r}",
        ))

    # T50 G13 invariant: empty ``images: []`` is structurally VALID
    # (it is a list, just empty). For a non-empty registry, this
    # means every registry asset is missing from the manifest — G13
    # fires for each asset. The diagnostic must be the per-asset
    # "missing declaration" message, NOT the structural-precondition
    # error: an empty list is well-formed, just incomplete.
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        a = _good_png_asset(td, asset_id="lone_asset")
        _write_image_manifest(td, [])  # explicit empty list
        rp = _write_registry(td, [a])
        errs = _run_validator(td, rp)
        results.append(_expect(
            "T50: image_manifest with empty images:[] -> FAIL "
            "(G13 per-asset declaration, NOT structural precondition)",
            any(
                "every registry asset must be declared" in e
                and "G13" in e
                and "lone_asset" in e
                for e in errs
            )
            and not any(
                "'images' is not a list" in e for e in errs
            )
            and not any(
                "'images' field is missing" in e for e in errs
            ),
            f"errs={errs!r}",
        ))

    return results


# ---------------------------------------------------------------------------
# CLI entry point.
# ---------------------------------------------------------------------------


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Stdlib-only validator for source_image_assets.json. "
            "Schema-validates the registry against "
            "schemas/source_image_asset.schema.json AND enforces the "
            "wire-side cross-checks listed in "
            "references/source-image-asset-policy.md. NETWORK-FREE, "
            "NO-D-ONE, read-only — no file is mutated, no pipeline "
            "propagation is performed."
        ),
    )
    parser.add_argument(
        "--workspace", type=Path, default=None,
        help=(
            "Workspace directory the registry resolves against. "
            "Default registry path is <workspace>/"
            f"{REGISTRY_FILENAME}; override with --registry."
        ),
    )
    parser.add_argument(
        "--registry", type=Path, default=None,
        help=(
            "Path to the registry JSON file. Defaults to "
            f"<workspace>/{REGISTRY_FILENAME} when --workspace is "
            "supplied."
        ),
    )
    parser.add_argument(
        "--self-test", action="store_true",
        help=(
            "Run in-script tempfixture scenarios covering every gate "
            "G1-G13 plus the happy paths and the G10/G13 separation "
            "invariants. Exits non-zero if any scenario does not behave "
            "as expected. Mutually exclusive with --workspace / "
            "--registry."
        ),
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if args.workspace is not None or args.registry is not None:
            print(
                "FAIL: --self-test is mutually exclusive with "
                "--workspace / --registry",
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
            f"OK (self-test): {len(results)} scenarios behaved as "
            f"expected. This validator does NOT call D-One / any "
            f"network / any model API; PASS here is a schema + "
            f"wire-side contract check, not a deck-level approval."
        )
        return 0

    if args.workspace is None:
        print(
            "FAIL: --workspace is required (or pass --self-test)",
            file=sys.stderr,
        )
        return 2

    workspace = args.workspace
    registry_path = (
        args.registry
        if args.registry is not None
        else workspace / REGISTRY_FILENAME
    )

    if not REGISTRY_SCHEMA.is_file():
        print(
            f"FAIL: registry schema not found at {REGISTRY_SCHEMA}",
            file=sys.stderr,
        )
        return 2

    errors = validate_registry(
        workspace=workspace, registry_path=registry_path
    )
    if errors:
        print(f"FAIL: {registry_path}")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(
        f"OK: {registry_path} validates against "
        f"{REGISTRY_SCHEMA.name} and every wire-side cross-check "
        f"(unique ids, source_manifest backlink if present, "
        f"path safety, no symlinks, on-disk byte_count + sha256, "
        f"media_type / extension / magic bytes, image_manifest "
        f"alignment of matched ids (G10), every registry id declared "
        f"in image_manifest.images[] when image_manifest is present "
        f"(G13), no public-upload / public-share / public-URL "
        f"wording in id / source_ref / paths (G12))."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
