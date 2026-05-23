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
  - optionally reads an EXPLICIT caller-supplied
    ``--descriptor-vocabulary`` JSON file (the clean-room V2/V3
    contract sketch at ``schemas/d_one_descriptor_vocabulary.schema.json``)
    — required iff any spec request carries one or more of the seven
    taxonomy fields ``rendering_style`` / ``palette_family`` /
    ``image_role`` / ``layout_pattern`` / ``modifier`` /
    ``text_policy`` / ``subject_domain`` OR the optional
    ``custom_descriptor`` escape-hatch field; the file must parse,
    decode to an object, and validate against the vocabulary
    schema; every taxonomy value supplied in a spec request must
    then be a member of the matching
    ``image_taxonomy.<dim>.allowed_values`` list (the same closed
    enumeration the vocabulary schema locks), AND every
    ``custom_descriptor`` value must be a member of the vocab's
    ``custom_descriptors[*].value`` allow-list AND re-pass the full
    prompt safety scan on BOTH the raw value AND a separator-
    normalized form (so compound deny literals like ``slide title``
    / ``body copy`` / ``render the slide`` / ``include text`` fire
    on ``slide_title`` / ``body-copy`` / ``render.the.slide`` /
    ``include_text`` and every separator stacking);
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
      int), optionally any of the seven taxonomy fields
      ``rendering_style`` / ``palette_family`` / ``image_role`` /
      ``layout_pattern`` / ``modifier`` / ``text_policy`` /
      ``subject_domain``, AND optionally the
      ``custom_descriptor`` escape-hatch field; no other keys are
      accepted;
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
      full-slide / screenshot / page-generation wording;
    * a request may carry zero or more of the seven taxonomy fields,
      but every present taxonomy field forces
      ``--descriptor-vocabulary`` to have been supplied AND every
      value must be a member of the matching
      ``image_taxonomy.<dim>.allowed_values`` list;
    * a request may optionally carry one ``custom_descriptor``
      escape-hatch field — present only when
      ``--descriptor-vocabulary`` is supplied AND the vocab's
      ``custom_descriptors[*].value`` allow-list contains an
      explicit approved entry for that exact value AND the value
      re-passes the full prompt safety scan on BOTH the raw value
      AND a separator-normalized form. Missing vocab,
      omitted-or-empty allow-list, unknown value, malformed type,
      or unsafe shape each fail closed before any plan is written.

  --descriptor-vocabulary (optional)
    * when omitted, a spec / plan may not carry any of the seven
      taxonomy fields NOR the ``custom_descriptor`` escape-hatch
      field (any request that does is refused);
    * when supplied, must be an existing regular file; URI-shaped
      values refused; symlinks (broken or resolvable) refused;
    * must parse as JSON, decode to an object, and validate against
      ``schemas/d_one_descriptor_vocabulary.schema.json`` — which
      pattern-locks every descriptor / taxonomy value to a
      lowercase-identifier shape with a forbidden-token deny clause
      (``public`` / ``upload`` / ``raw`` / ``customer`` /
      ``confidential`` / ``screenshot`` / ``credential`` /
      ``password`` / ``secret`` as bounded tokens, plus the compound
      ``full slide`` / ``image search`` / ``web generation`` /
      ``page generation`` / ``slide generation`` phrases across any
      ``.`` / ``_`` / ``-`` separator stacking);
    * is re-validated every run (no in-memory caching across
      invocations), so a tampered vocabulary that drifts from the
      schema is refused immediately.

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
DESCRIPTOR_VOCAB_SCHEMA = SCHEMAS_DIR / "d_one_descriptor_vocabulary.schema.json"

# Optional per-request taxonomy fields. Mirror the seven image_taxonomy
# dimensions declared in schemas/d_one_descriptor_vocabulary.schema.json
# — the original five (rendering_style / palette_family / image_role /
# layout_pattern / modifier) plus the prompt-intent contract extension
# text_policy and subject_domain. A spec / plan request may carry zero
# or more of these; ANY taxonomy field present forces
# --descriptor-vocabulary to have been supplied, and every value must
# be a member of the matching image_taxonomy.<dim>.allowed_values
# list. The tuple order is the spec/plan field order in the on-disk
# artifact (deterministic projection matters because the plan file is
# reread byte-for-byte across runs).
TAXONOMY_FIELDS: tuple[str, ...] = (
    "rendering_style",
    "palette_family",
    "image_role",
    "layout_pattern",
    "modifier",
    "text_policy",
    "subject_domain",
)

# Optional per-request *custom-descriptor escape hatch*. Aligned only
# with upstream ppt-master's ai-image custom rendering / palette / hero-
# composition direction; no upstream code / prompts / examples / assets
# / wording were copied. A request may carry AT MOST this one field, and
# only when --descriptor-vocabulary supplies a non-empty
# custom_descriptors[] allow-list AND the request's value is a member of
# that allow-list. Like the taxonomy fields, the field is OPTIONAL and
# absent fields produce no key in the plan (no null projection).
CUSTOM_DESCRIPTOR_FIELD = "custom_descriptor"

# Vocab-gated request fields — every member forces
# --descriptor-vocabulary to have been supplied and forces the adapter
# to re-check the value against its matching allow-list. Today this is
# TAXONOMY_FIELDS (checked against image_taxonomy.<dim>.allowed_values)
# plus CUSTOM_DESCRIPTOR_FIELD (checked against custom_descriptors[].value).
VOCAB_GATED_FIELDS: tuple[str, ...] = (
    *TAXONOMY_FIELDS,
    CUSTOM_DESCRIPTOR_FIELD,
)

# Only manifest entries whose source == "d_one_local" are eligible for
# D-One generation. local_asset / synthetic entries belong to a
# different lifecycle (local-authored or fixture-only) and the adapter
# refuses to issue a generation request against them so a caller cannot
# smuggle an unrelated request into the D-One channel.
ELIGIBLE_MANIFEST_SOURCE = "d_one_local"

# Schema version of the produced plan file. Bumped if the plan-file
# shape ever changes; lets a future real-D-One step refuse a plan it
# does not recognize.
# Plan-file schema version. 1 was the pre-taxonomy shape; the 1 -> 2
# bump is the paired change for the optional per-request taxonomy
# fields (rendering_style / palette_family / image_role /
# layout_pattern / modifier / text_policy / subject_domain). The 2 -> 3
# bump is the paired change for the new optional per-request
# `custom_descriptor` escape-hatch field. An older reader with
# PLAN_SCHEMA_VERSION = 2 would reject the new property under the
# schema's additionalProperties:false lock, so the shape change is not
# backward-compatible and gets a new version. Plan files without
# `custom_descriptor` written by a current writer still ship with
# schema_version=3 — the version reflects the schema shape, not the
# per-request payload.
PLAN_SCHEMA_VERSION = 3

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

# Wording that asks the generated image to carry text the slide must
# keep exact, editable, searchable, rewordable, or data-faithful.
# Such copy belongs in the native SVG / PPT text layer, never baked
# into the raster the image generator produces — once rasterised the
# text is locked, untrustworthy under reflow, unreadable by screen
# readers, and unsearchable. The check is universal: it fires
# regardless of text_policy, because every policy that gates the
# decorative artwork text layer (decorative_glyphs / caption_safe)
# still forbids editable / data-faithful copy from living in the
# image. The literals describe an intent the local pipeline cannot
# fulfil at all, not a script or language preference — no
# Latin-only / CJK-fails / length-based wording lives here.
_PROMPT_EDITABLE_TEXT_LITERALS: tuple[str, ...] = (
    # Page / slide / section chrome — must be native editable text.
    "slide title",
    "page title",
    "section title",
    "slide chrome",
    "page chrome",
    # Body / native text overlays / SVG overlays — must be native.
    "body copy",
    "body text",
    "native text",
    "native-text overlay",
    "native text overlay",
    "svg text overlay",
    "svg-text overlay",
    "svg overlay text",
    "text overlay",
    # Exact / editable / searchable / rewordable wording.
    "exact text",
    "exact copy",
    "exact wording",
    "editable text",
    "editable copy",
    "editable wording",
    "searchable text",
    "searchable copy",
    "rewordable text",
    "rewordable copy",
    # Data-faithful labels and values.
    "data value",
    "data values",
    "data label",
    "data labels",
    "axis label",
    "axis labels",
    "kpi number",
    "kpi value",
    "kpi figure",
    "legend text",
    # Editable typographic blocks — explicit "<thing> text" phrasing.
    "headline text",
    "subtitle text",
    "callout text",
    "annotation text",
    "caption text",
)

# Wording that explicitly asks the generated image to carry visible
# letters / numerals / words / captions / labels / titles / quotes /
# slogans. Only fires when ``text_policy == 'no_text'`` — the policy
# already says no in-image text, so a prompt that explicitly asks
# for in-image text is self-contradictory. Under decorative_glyphs
# / caption_safe the same wording may describe legitimate stylised
# artwork (a wordmark accent, decorative calligraphy, a stylised
# initial, etc.), so the rule deliberately does NOT fire there. The
# rule is editability-based, not script-based; nothing here mentions
# Latin / CJK / character length.
#
# Matching is boundary-aware (see ``_literal_present_unnegated``):
# every literal must be flanked by word boundaries on each side, so
# the literal ``image text`` matches ``"...image text..."`` but NOT
# the prefix of ``"image texture"`` / ``"image textures"``, and
# ``with text`` matches ``"...with text..."`` but NOT
# ``"with textured paper"``. This closes the prefix / suffix
# substring false positives the earlier plain ``str.find`` scan
# produced on normal image-generation wording like ``image
# texture`` / ``textured paper`` / ``context lighting`` / ``texture
# pattern``.
_PROMPT_NO_TEXT_REQUEST_LITERALS: tuple[str, ...] = (
    # Direct text-request verbs.
    "include text",
    "add text",
    "draw text",
    "render text",
    "show text",
    "with text",
    "visible text",
    "any text",
    "some text",
    # Letter / character / word / numeral requests.
    "include letters",
    "add letters",
    "draw letters",
    "show letters",
    "with letters",
    "visible letters",
    "include words",
    "add words",
    "draw words",
    "show words",
    "with words",
    "include characters",
    "add characters",
    "show characters",
    "include numerals",
    "add numerals",
    "show numerals",
    # Specific kinds of in-image typography requested.
    "include a caption",
    "add a caption",
    "with a caption",
    "draw a caption",
    "include a label",
    "add a label",
    "with a label",
    "include a title",
    "add a title",
    "with a title",
    "include a heading",
    "add a heading",
    "with a heading",
    "include a slogan",
    "with a slogan",
    "add a slogan",
    "include a quote",
    "with a quote",
    "add a quote",
    "include a quotation",
    "include a tagline",
    "with a tagline",
    "add a tagline",
    # Typographic art that bakes text into the image.
    "lettering",
    "typography",
    "typographic",
    "wordmark",
    "monogram",
    "calligraphy",
    "calligraphic",
    # Generic in-image-text framings.
    "in-image text",
    "image text",
    "baked text",
    "text in the image",
    "text on the image",
    "text inside the image",
    "letters in the image",
    "letters on the image",
    "words in the image",
    "writing in the image",
    "writing on the image",
)

# Negation-exemption pattern for the two policy-aware deny lists
# above (``_PROMPT_EDITABLE_TEXT_LITERALS`` and
# ``_PROMPT_NO_TEXT_REQUEST_LITERALS``). A prompt that re-states the
# policy ("no visible text", "do not include text", "without
# lettering", "caption text is forbidden") is NOT a request to bake
# text into the image — it is policy reinforcement, and refusing it
# would force callers to author awkward prompts to talk about what
# the policy already forbids. Strict-adjacency matching mirrors the
# pattern documented at scripts/validate_d_one_live_run_evidence.py:
# BEFORE-side a single negation word immediately adjacent (no
# punctuation between the negation word and the literal — a comma,
# period, semicolon, or ellipsis IS a clause boundary and the
# negation does NOT propagate across it); AFTER-side an optional
# copula + refusal word, or a refusal bigram, with intermediate
# tokens (the copula, the bigram-first half) exact (no punctuation)
# and trailing sentence-end punctuation tolerated only on the FINAL
# refusal token so reinforcement that ends a sentence still exempts.
# Intervening words on the BEFORE side are NOT honored either, so
# "must not have any text" stays refused because `have` sits between
# `not` and the literal. The exemption applies ONLY to the two new
# gates; the existing URL / file-path / credential / PII / full-
# slide / public-distribution scans keep their existing strict-
# substring behavior to avoid widening their blast radius.
_PROMPT_NEGATION_BEFORE_WORDS: frozenset[str] = frozenset({
    "no", "not", "never", "without",
})
_PROMPT_NEGATION_AFTER_COPULAS: frozenset[str] = frozenset({
    "is", "are", "was", "were",
})
_PROMPT_NEGATION_AFTER_REFUSAL_WORDS: frozenset[str] = frozenset({
    "forbidden", "prohibited", "denied", "disabled",
    "blocked", "refused", "banned",
})
_PROMPT_NEGATION_AFTER_REFUSAL_BIGRAMS: frozenset[tuple[str, str]] = (
    frozenset({
        ("not", "used"),
        ("not", "allowed"),
        ("not", "permitted"),
        ("not", "enabled"),
    })
)
# Sentence-end punctuation tolerated ONLY on the FINAL refusal token
# (so "lettering is forbidden." with a trailing period still exempts).
# Comma and semicolon are intentionally absent — they indicate clause
# / compound-sentence boundaries and the negation should not be
# treated as propagating across them.
_PROMPT_NEGATION_TAIL_PUNCT: str = ".!?\"')]"


def _occurrence_is_negated(lower: str, start: int, end: int) -> bool:
    """Return True if the substring at ``lower[start:end]`` sits next
    to negation / refusal wording. See the comment block above for
    the exact pattern. The BEFORE-side last word must be a bare
    negation word with NO trailing punctuation — a comma, period, or
    ellipsis between the negation and the literal is treated as a
    clause boundary (so ``"no, include text"`` is NOT exempted even
    though ``"no"`` precedes the literal — the comma breaks
    adjacency). The AFTER-side allows trailing sentence-end
    punctuation on the FINAL refusal token only; intermediate tokens
    (the copula, the bigram-first half) must be exact, so
    ``"is, forbidden"`` is NOT exempted because the comma after
    ``is`` breaks adjacency."""
    prefix = lower[:start].rstrip()
    if prefix:
        sep = max(
            prefix.rfind(" "),
            prefix.rfind("\t"),
            prefix.rfind("\n"),
        )
        last_word = prefix[sep + 1:] if sep >= 0 else prefix
        if last_word in _PROMPT_NEGATION_BEFORE_WORDS:
            return True
    suffix = lower[end:].lstrip()
    if not suffix:
        return False
    tokens = suffix.split(maxsplit=3)
    if not tokens:
        return False
    # Pattern 1: <refusal>  (e.g. "forbidden", "forbidden.")
    if (
        tokens[0].rstrip(_PROMPT_NEGATION_TAIL_PUNCT)
        in _PROMPT_NEGATION_AFTER_REFUSAL_WORDS
    ):
        return True
    if len(tokens) >= 2:
        # Pattern 2: <copula> <refusal>   (e.g. "is forbidden")
        if (
            tokens[0] in _PROMPT_NEGATION_AFTER_COPULAS
            and tokens[1].rstrip(_PROMPT_NEGATION_TAIL_PUNCT)
                in _PROMPT_NEGATION_AFTER_REFUSAL_WORDS
        ):
            return True
        # Pattern 3: <bigram[0]> <bigram[1]>  (e.g. "not used")
        if (
            tokens[0],
            tokens[1].rstrip(_PROMPT_NEGATION_TAIL_PUNCT),
        ) in _PROMPT_NEGATION_AFTER_REFUSAL_BIGRAMS:
            return True
    if len(tokens) >= 3:
        # Pattern 4: <copula> <bigram[0]> <bigram[1]>
        #   (e.g. "is not used")
        if (
            tokens[0] in _PROMPT_NEGATION_AFTER_COPULAS
            and (
                tokens[1],
                tokens[2].rstrip(_PROMPT_NEGATION_TAIL_PUNCT),
            ) in _PROMPT_NEGATION_AFTER_REFUSAL_BIGRAMS
        ):
            return True
    return False


def _literal_present_unnegated(lower: str, literal: str) -> bool:
    """Return True if ``literal`` appears in ``lower`` at a word /
    phrase boundary AND at least one occurrence is NOT next to a
    documented negation / refusal pattern.

    Boundary-aware matching: each match must have a word boundary
    (``\\b``) on each side, so the literal only fires on whole-token /
    whole-phrase matches and never on a substring of a longer word.
    This closes the substring false positives the earlier plain
    ``str.find`` scan produced — e.g. the literal ``"image text"``
    matching the prefix of ``"image texture"`` under
    ``text_policy='no_text'`` and the literal ``"with text"``
    matching the prefix of ``"with textured paper"``. The full-slide
    / public-distribution / source-marker / credential / personal-id
    gates keep their plain-substring behavior; the boundary rule
    applies only to the two policy-aware text-wording deny lists
    (``_PROMPT_EDITABLE_TEXT_LITERALS`` and
    ``_PROMPT_NO_TEXT_REQUEST_LITERALS``) consulted via this helper.

    If every occurrence sits next to a documented negation pattern,
    return False so the safety scan does not refuse a prompt that
    merely re-states what the policy already forbids."""
    pattern = re.compile(r"\b" + re.escape(literal) + r"\b")
    for match in pattern.finditer(lower):
        if not _occurrence_is_negated(lower, match.start(), match.end()):
            return True
    return False


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


def _load_descriptor_vocabulary(
    vocab_path: Path,
) -> tuple[
    dict[str, set[str]] | None,
    set[str] | None,
    bytes | None,
    int,
    str,
]:
    """Validate ``vocab_path`` and project its ``image_taxonomy`` plus
    its optional ``custom_descriptors`` allow-list into membership sets.

    The helper runs the same string / filesystem / schema gates the rest
    of the adapter applies: URI-shape refused, symlink refused, exists,
    regular file, parses as JSON, decodes to an object, and validates
    against ``schemas/d_one_descriptor_vocabulary.schema.json``. Returns
    ``(allowed_per_dim, allowed_custom, vocab_bytes, rc, msg)``; on
    success ``rc == 0``, ``allowed_per_dim`` is keyed by every member of
    ``TAXONOMY_FIELDS``, ``allowed_custom`` is the set of approved
    ``custom_descriptors[*].value`` strings (EMPTY set when the
    vocabulary omits / declares an empty ``custom_descriptors`` list —
    in that case the adapter refuses any request that carries
    ``custom_descriptor``, mirroring the same "no allow-list, no
    permission" gate the taxonomy fields use), and ``vocab_bytes`` is
    the exact byte content the loader read (used by callers as the
    canonical "before" snapshot for the byte-identical post-condition);
    on failure ``rc != 0``, ``msg`` is non-empty, and every other return
    value is None.

    No in-memory caching across calls: a tampered file is caught every
    run, and the helper is small (a few-KB JSON parse) so the cost is
    negligible.
    """
    if _has_uri_scheme(str(vocab_path)):
        return None, None, None, 2, (
            f"FAIL: --descriptor-vocabulary {vocab_path} looks like a URI; "
            f"done_image_adapter only accepts local file paths"
        )
    is_symlink, msg = _refuse_symlink(vocab_path, "--descriptor-vocabulary")
    if is_symlink:
        return None, None, None, 2, msg
    if not vocab_path.exists():
        return None, None, None, 2, (
            f"FAIL: --descriptor-vocabulary {vocab_path} does not exist"
        )
    if not vocab_path.is_file():
        return None, None, None, 2, (
            f"FAIL: --descriptor-vocabulary {vocab_path} is not a regular file"
        )
    try:
        vocab_bytes = vocab_path.read_bytes()
        vocab_doc = json.loads(vocab_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, None, None, 1, (
            f"FAIL: cannot read --descriptor-vocabulary {vocab_path}: {exc}"
        )
    if not isinstance(vocab_doc, dict):
        return None, None, None, 1, (
            f"FAIL: --descriptor-vocabulary {vocab_path} did not decode to "
            f"an object (got {type(vocab_doc).__name__})"
        )
    vocab_errors = _schema_validate(vocab_doc, DESCRIPTOR_VOCAB_SCHEMA)
    if vocab_errors:
        return None, None, None, 1, (
            f"FAIL: --descriptor-vocabulary {vocab_path} does not validate "
            f"against d_one_descriptor_vocabulary.schema.json: "
            + "; ".join(vocab_errors)
        )
    # By this point the schema guarantees image_taxonomy is a dict with
    # each of the seven required dimensions, each carrying an
    # allowed_values list pinned to the canonical count and enum-locked
    # to canonical tokens. We project to a per-dimension set for cheap
    # membership checks at the request layer.
    allowed_per_dim: dict[str, set[str]] = {}
    for dim in TAXONOMY_FIELDS:
        dim_block = vocab_doc["image_taxonomy"][dim]
        allowed_per_dim[dim] = set(dim_block["allowed_values"])
    # custom_descriptors is OPTIONAL on the vocab file (schema allows it
    # to be absent for backward compatibility). When absent or empty,
    # the resulting allow-list is the empty set; the adapter then
    # refuses any request that carries the custom_descriptor field.
    allowed_custom: set[str] = set()
    for entry in vocab_doc.get("custom_descriptors", []) or []:
        if isinstance(entry, dict):
            value = entry.get("value")
            if isinstance(value, str) and value:
                allowed_custom.add(value)
    return allowed_per_dim, allowed_custom, vocab_bytes, 0, ""


def _scan_prompt_safety(
    prompt: str,
    *,
    source_text: str | None,
    text_policy: str | None = None,
) -> list[str]:
    """Return a list of safety violations for ``prompt``. Empty list ->
    safe. Every pattern table is consulted; we collect ALL violations
    in one pass so the caller sees every problem at once rather than
    a one-issue-at-a-time game of whack-a-mole.

    When ``text_policy`` is the request's ``text_policy`` taxonomy
    value (``no_text`` / ``decorative_glyphs`` / ``caption_safe``)
    the scan also applies the policy-aware in-image-text rule (only
    fires when ``text_policy == 'no_text'``). ``text_policy=None`` is
    the safe default — no policy-aware check is run, only the
    universal rules.
    """
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

    # Always-on editable-text rule. Any wording that asks the
    # generated image to carry exact / editable / searchable /
    # rewordable / data-faithful text is refused regardless of
    # text_policy: such copy belongs in the native SVG / PPT text
    # layer where it can be edited, reflowed, and indexed. The
    # match is negation-exempt — see ``_occurrence_is_negated`` —
    # so policy-reinforcement phrasings such as
    # ``"no slide title in this image"`` or
    # ``"body copy is forbidden"`` are NOT refused.
    for literal in _PROMPT_EDITABLE_TEXT_LITERALS:
        if _literal_present_unnegated(lower, literal):
            violations.append(
                f"contains the editable-text wording {literal!r}; "
                f"text that must remain exact, editable, searchable, "
                f"rewordable, or data-faithful belongs in the native "
                f"SVG / PPT text layer, not in the generated image"
            )

    # Policy-aware in-image-text rule. When the request declares
    # text_policy == 'no_text', the prompt may not ask for visible
    # in-image letters / numerals / words / captions / labels /
    # titles / quotes / slogans. The rule is editability-based, not
    # script-based: decorative artwork text under decorative_glyphs
    # / caption_safe is unaffected (including non-Latin / CJK
    # glyphs). The match is negation-exempt — see
    # ``_occurrence_is_negated`` — so policy-reinforcement phrasings
    # such as ``"no visible text"`` / ``"do not include text"`` /
    # ``"without lettering"`` / ``"calligraphy is not allowed"`` are
    # NOT refused.
    if text_policy == "no_text":
        for literal in _PROMPT_NO_TEXT_REQUEST_LITERALS:
            if _literal_present_unnegated(lower, literal):
                violations.append(
                    f"contains the in-image-text wording {literal!r} "
                    f"under text_policy='no_text'; the policy forbids "
                    f"any visible letters / numerals / words / "
                    f"captions / labels / titles in the generated "
                    f"image — move the copy to the native SVG / PPT "
                    f"text layer or pick a text_policy that permits "
                    f"decorative artwork text"
                )

    return violations


def _scan_custom_descriptor_safety(
    value: str,
    *,
    source_text: str | None,
    text_policy: str | None,
) -> list[str]:
    """Defense-in-depth safety scan for the ``custom_descriptor``
    escape-hatch value.

    The schema regex pattern-locks ``custom_descriptor`` to a
    lowercase identifier with `.` / `_` / `-` separators, and refuses
    the 9 bounded forbidden tokens (``public`` / ``upload`` / ... /
    ``secret``) plus the 5 compound deny phrases (``full_slide`` /
    ``image_search`` / ``web_generation`` / ``page_generation`` /
    ``slide_generation``) across every separator stacking. That
    closes the obvious-shape gap.

    But ``_scan_prompt_safety``'s remaining compound literals are
    SPACE-separated (`slide title` / `body copy` / `render the slide`
    / `include text` / ...), so a schema-shape-valid value that
    encodes the same compound with a separator stacking — e.g.
    ``slide_title`` / ``body-copy`` / ``render.the.slide`` — slips
    past the substring scan. The schema does not cover those
    phrases (they are not in its closed 5-compound deny list), and
    a reviewer who adds such a value to ``custom_descriptors[]`` by
    mistake would have it pass every other gate.

    We close that gap here by scanning BOTH the raw lowercased value
    AND a separator-normalized form (every run of `.` / `_` / `-`
    collapsed to a single space), then unioning the violations. The
    raw scan catches single-word literals (``screenshot`` /
    ``lettering`` / ``calligraphy`` / ``typography`` / ``wordmark``
    / ``monogram`` / ``calligraphic``); the normalized scan catches
    compound literals (``slide title`` / ``body copy`` / ``render
    the slide`` / ``include text`` / ...) regardless of whether the
    caller wrote them with `_`, `-`, `.`, or a mix.
    """
    raw_violations = _scan_prompt_safety(
        value, source_text=source_text, text_policy=text_policy,
    )
    normalized = re.sub(r"[._\-]+", " ", value).strip()
    if not normalized or normalized == value:
        return raw_violations
    normalized_violations = _scan_prompt_safety(
        normalized, source_text=source_text, text_policy=text_policy,
    )
    if not normalized_violations:
        return raw_violations
    seen = set(raw_violations)
    out = list(raw_violations)
    for v in normalized_violations:
        if v not in seen:
            out.append(v)
            seen.add(v)
    return out


def _scan_intended_use(intended_use: str) -> list[str]:
    """Subset of the prompt safety scan applied to ``intended_use``.
    Only the full-slide / screenshot wording and the universal
    editable-text rule matter here — the field is short and the
    manifest schema's description already says "never 'full-slide
    background'", so the helper enforces it. The editable-text rule
    fires when ``intended_use`` claims the image will hold a slide
    title, body copy, native-text overlay, or other copy that must
    remain editable / data-faithful — wording the manifest could
    never honour because such text must live in the native SVG /
    PPT text layer, not in the generated raster."""
    violations: list[str] = []
    lower = intended_use.lower()
    for literal in _PROMPT_FULL_SLIDE_LITERALS:
        if literal in lower:
            violations.append(
                f"intended_use contains forbidden wording {literal!r}"
            )
    for literal in _PROMPT_EDITABLE_TEXT_LITERALS:
        if _literal_present_unnegated(lower, literal):
            violations.append(
                f"intended_use contains the editable-text wording "
                f"{literal!r}; text that must remain exact, editable, "
                f"searchable, rewordable, or data-faithful belongs in "
                f"the native SVG / PPT text layer, not in the "
                f"generated image"
            )
    return violations


def _validate_spec_requests(
    spec: dict,
    *,
    manifest_by_id: dict[str, dict],
    source_text: str | None,
    taxonomy_allowed: dict[str, set[str]] | None,
    custom_descriptor_allowed: set[str] | None,
) -> tuple[list[dict] | None, str]:
    """Validate ``spec['requests']`` against the manifest, the safety
    scans, and (when supplied) the descriptor vocabulary taxonomy +
    custom-descriptor allow-list.
    Returns (validated_requests, error_msg). On error, validated_requests
    is None and error_msg is non-empty.

    ``taxonomy_allowed`` is the per-dimension allowed_values set
    projection produced by ``_load_descriptor_vocabulary``. When
    ``taxonomy_allowed is None``, any spec request that carries one or
    more of ``TAXONOMY_FIELDS`` is refused — the user must pass
    ``--descriptor-vocabulary``. When ``taxonomy_allowed`` is supplied,
    every present taxonomy field's value must be in the matching
    ``taxonomy_allowed[<dim>]`` set.

    ``custom_descriptor_allowed`` is the allow-list set produced by
    ``_load_descriptor_vocabulary`` from the vocab's
    ``custom_descriptors[*].value`` list. When ``None`` (no vocab
    supplied) OR ``set()`` (vocab supplied but no allow-list entries),
    any spec request that carries ``custom_descriptor`` is refused — the
    escape hatch is only usable when an explicit approved entry exists."""
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

    allowed_keys = (
        {"id", "prompt", "intended_use", "width_px", "height_px"}
        | set(TAXONOMY_FIELDS)
        | {CUSTOM_DESCRIPTOR_FIELD}
    )
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
        # Peek at text_policy for the policy-aware prompt scan. The
        # full taxonomy validation runs below (refuses unknown values,
        # missing vocab, etc.); the peek only enables the no_text
        # in-image-text gate when the value is a non-empty string,
        # so a malformed text_policy stays caught by the taxonomy
        # block — it just does not trigger the policy-aware scan.
        text_policy_peek = req.get("text_policy")
        if not isinstance(text_policy_peek, str) or not text_policy_peek.strip():
            text_policy_peek = None
        prompt_violations = _scan_prompt_safety(
            prompt, source_text=source_text, text_policy=text_policy_peek,
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

        # Taxonomy fields. Each field is OPTIONAL; ANY present field
        # forces --descriptor-vocabulary to have been supplied, and
        # every value must be in the matching image_taxonomy
        # allowed_values set. Defense in depth: the plan schema
        # additionally pattern-locks every taxonomy field at the
        # lowercase-identifier + forbidden-token shape, so the
        # post-write _schema_validate gate catches any unsafe value
        # the runtime check missed (it should not — allowed_values is
        # a closed enumeration of canonical tokens — but the layered
        # check matters if the runtime allowed_values set ever drifts).
        present_taxonomy: dict[str, str] = {}
        for dim in TAXONOMY_FIELDS:
            if dim not in req:
                continue
            value = req[dim]
            if not isinstance(value, str) or not value.strip():
                return None, (
                    f"FAIL: requests[{i}].{dim} (id {req_id!r}) must be "
                    f"a non-empty string when present (got {value!r})"
                )
            present_taxonomy[dim] = value
        if present_taxonomy and taxonomy_allowed is None:
            return None, (
                f"FAIL: requests[{i}] (id {req_id!r}) carries taxonomy "
                f"field(s) {sorted(present_taxonomy.keys())} but no "
                f"--descriptor-vocabulary was supplied; taxonomy fields "
                f"are only accepted when --descriptor-vocabulary points "
                f"at a schema-valid d_one_descriptor_vocabulary JSON."
            )
        if present_taxonomy:
            assert taxonomy_allowed is not None  # for type-checkers
            for dim, value in present_taxonomy.items():
                if value not in taxonomy_allowed[dim]:
                    return None, (
                        f"FAIL: requests[{i}].{dim} (id {req_id!r}) "
                        f"value {value!r} is not in "
                        f"image_taxonomy.{dim}.allowed_values "
                        f"({sorted(taxonomy_allowed[dim])})."
                    )

        # custom_descriptor escape hatch. Optional; when present, the
        # request must satisfy four gates in this order:
        #   (1) the value is a non-empty string;
        #   (2) --descriptor-vocabulary must have been supplied — without
        #       it the runtime has no allow-list to certify the value;
        #   (3) the supplied vocab's custom_descriptors[] allow-list
        #       must be non-empty AND the value must be a member;
        #   (4) the value re-passes the full prompt safety scan (URI /
        #       file-path / source-marker / source-shingle / credential /
        #       PII / full-slide / public-distribution / editable-text
        #       and — under text_policy='no_text' — visible-text wording).
        # The plan schema additionally pattern-locks the field shape at
        # the lowercase-identifier + forbidden-token layer, so an
        # unsafe shape that somehow slipped past the runtime scan is
        # still caught by the post-write _schema_validate gate.
        custom_descriptor: str | None = None
        if CUSTOM_DESCRIPTOR_FIELD in req:
            raw_cd = req[CUSTOM_DESCRIPTOR_FIELD]
            if not isinstance(raw_cd, str) or not raw_cd.strip():
                return None, (
                    f"FAIL: requests[{i}].{CUSTOM_DESCRIPTOR_FIELD} "
                    f"(id {req_id!r}) must be a non-empty string when "
                    f"present (got {raw_cd!r})"
                )
            if custom_descriptor_allowed is None:
                return None, (
                    f"FAIL: requests[{i}] (id {req_id!r}) carries "
                    f"{CUSTOM_DESCRIPTOR_FIELD} but no "
                    f"--descriptor-vocabulary was supplied; the "
                    f"custom-descriptor escape hatch is only accepted "
                    f"when --descriptor-vocabulary points at a "
                    f"schema-valid d_one_descriptor_vocabulary JSON "
                    f"whose custom_descriptors[] allow-list contains "
                    f"an explicit approved entry for that exact value."
                )
            if not custom_descriptor_allowed:
                return None, (
                    f"FAIL: requests[{i}].{CUSTOM_DESCRIPTOR_FIELD} "
                    f"(id {req_id!r}) value {raw_cd!r}: the supplied "
                    f"--descriptor-vocabulary declares no "
                    f"custom_descriptors[] entries, so no value is "
                    f"approved. Add an explicit allow-list entry under "
                    f"the documented vocabulary approval review and "
                    f"re-run."
                )
            if raw_cd not in custom_descriptor_allowed:
                return None, (
                    f"FAIL: requests[{i}].{CUSTOM_DESCRIPTOR_FIELD} "
                    f"(id {req_id!r}) value {raw_cd!r} is not in the "
                    f"supplied --descriptor-vocabulary "
                    f"custom_descriptors[].value allow-list "
                    f"({sorted(custom_descriptor_allowed)}). The "
                    f"escape hatch requires an explicit approved entry "
                    f"for that exact descriptor."
                )
            # Defense in depth: re-run the FULL prompt safety scan
            # against the custom_descriptor value, on BOTH the raw
            # lowercased form AND a separator-normalized form (`_` /
            # `-` / `.` collapsed to spaces) so compound deny-list
            # literals like `slide title` / `render the slide` /
            # `body copy` / `include text` (under
            # text_policy='no_text') fire on `slide_title` /
            # `render_the_slide` / `body-copy` / `include.text` etc.
            # The schema regex already refuses URI / file-path /
            # credential / full-slide-compound / public-distribution
            # shapes at the identifier level, and the allow-list
            # certification means a reviewer approved this value — but
            # without the separator-normalized pass, a compound that
            # is NOT in the schema's 5-compound deny list (e.g.
            # `slide title` / `body copy`) would slip past the
            # substring scan because the raw value uses `_` / `-` /
            # `.` while the deny literal uses spaces.
            cd_violations = _scan_custom_descriptor_safety(
                raw_cd,
                source_text=source_text,
                text_policy=text_policy_peek,
            )
            if cd_violations:
                return None, (
                    f"FAIL: requests[{i}].{CUSTOM_DESCRIPTOR_FIELD} "
                    f"(id {req_id!r}) value {raw_cd!r} failed the "
                    f"safety re-scan: " + "; ".join(cd_violations)
                )
            custom_descriptor = raw_cd

        validated.append({
            "id": req_id,
            "prompt": prompt,
            "intended_use": intended_use,
            "width_px": req.get("width_px"),
            "height_px": req.get("height_px"),
            "manifest_local_path": manifest_entry.get("local_path"),
            "manifest_source": manifest_source,
            "taxonomy": present_taxonomy,
            "custom_descriptor": custom_descriptor,
        })

    return validated, ""


def _build_plan(validated_requests: list[dict]) -> dict:
    """Project the validated request list into the deterministic plan
    file shape. Sorted by id so a re-ordered spec produces an
    identical plan file (the manifest itself is order-sensitive, but
    the plan is an audit projection and benefits from a stable order).

    Taxonomy fields (TAXONOMY_FIELDS) are projected in the canonical
    order — the same tuple order TAXONOMY_FIELDS declares — only when
    the validated request carries them. The optional
    ``custom_descriptor`` escape-hatch field is projected only when the
    validated request carries a non-None value. Absent fields stay
    absent (no null projection), so a spec without taxonomy / without
    custom_descriptor produces a plan-file body byte-identical to the
    pre-extension shape (modulo the schema_version field), preserving
    the schema's `additionalProperties: false` and the existing
    fixture set."""
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
                **{
                    dim: r["taxonomy"][dim]
                    for dim in TAXONOMY_FIELDS
                    if dim in r.get("taxonomy", {})
                },
                **(
                    {CUSTOM_DESCRIPTOR_FIELD: r["custom_descriptor"]}
                    if r.get("custom_descriptor") is not None
                    else {}
                ),
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
    descriptor_vocabulary: Path | None = None,
) -> tuple[int, str]:
    """Run the D-One adapter contract stub. Returns (exit_code, message).

    Always operates as dry-run today; no D-One call is issued and no
    image bytes are generated. A successful run produces only the
    deterministic plan file at ``plan_out`` (default
    ``<workspace>/d_one_adapter_plan.json``)."""
    # String-level shape gates run first for --workspace, --spec, AND
    # --descriptor-vocabulary (no filesystem syscall). A URI-shaped
    # argument otherwise would slip past the URI guard for whichever
    # input was checked later if an earlier input happened to fail a
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
    if descriptor_vocabulary is not None and _has_uri_scheme(
        str(descriptor_vocabulary)
    ):
        return 2, (
            f"FAIL: --descriptor-vocabulary {descriptor_vocabulary} "
            f"looks like a URI; done_image_adapter only accepts local "
            f"file paths"
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

    # Optional --descriptor-vocabulary preflight. Re-validated every run
    # (no caching across invocations) so a tampered file is caught even
    # if a prior process wrote a different version to the same path. The
    # loader returns the exact bytes it read, which we keep as the
    # canonical "before" snapshot for the byte-identical post-condition
    # below — the write path must NOT mutate the supplied vocabulary
    # file (the README states this explicitly), so the post-condition
    # re-reads and compares against this snapshot, rolling back the
    # just-written plan on a mismatch.
    taxonomy_allowed: dict[str, set[str]] | None = None
    custom_descriptor_allowed: set[str] | None = None
    vocab_bytes_before: bytes | None = None
    if descriptor_vocabulary is not None:
        (
            taxonomy_allowed,
            custom_descriptor_allowed,
            vocab_bytes_before,
            rc,
            msg,
        ) = _load_descriptor_vocabulary(descriptor_vocabulary)
        if rc != 0:
            return rc, msg
        assert taxonomy_allowed is not None
        assert custom_descriptor_allowed is not None
        assert vocab_bytes_before is not None

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
        taxonomy_allowed=taxonomy_allowed,
        custom_descriptor_allowed=custom_descriptor_allowed,
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
    # Vocabulary byte-identical post-condition. Mirrors the manifest
    # byte-identical check above and the same check on the validate
    # path. The write path is documented as non-mutating with respect
    # to the supplied vocabulary file (the README states the vocab is
    # byte-identical pre/post a successful run); the post-condition
    # closes that contract by re-reading the file and rolling the
    # just-written plan back on any mismatch.
    if descriptor_vocabulary is not None and vocab_bytes_before is not None:
        try:
            vocab_bytes_after = descriptor_vocabulary.read_bytes()
        except OSError as exc:
            try:
                plan_out.unlink()
            except OSError:
                pass
            return 1, (
                f"FAIL: cannot re-read --descriptor-vocabulary "
                f"{descriptor_vocabulary} after apply: {exc}; rolled "
                f"back plan."
            )
        if vocab_bytes_after != vocab_bytes_before:
            try:
                plan_out.unlink()
            except OSError:
                pass
            return 1, (
                f"FAIL: {descriptor_vocabulary} bytes changed during "
                f"apply (expected byte-identical). Rolled back plan."
            )

    vocab_line = (
        f"\n  vocab: {descriptor_vocabulary} (byte-identical)"
        if descriptor_vocabulary is not None
        else ""
    )
    return 0, (
        f"OK: D-One adapter contract stub validated "
        f"{len(validated)} request(s) for {workspace}\n"
        f"  spec: {spec}\n"
        f"  plan: {plan_out}{vocab_line}\n"
        f"  mode: dry_run (no D-One call; no image bytes generated)"
    )


def validate_plan_file(
    *,
    workspace: Path,
    plan: Path,
    descriptor_vocabulary: Path | None = None,
) -> tuple[int, str]:
    """Validate an existing ``d_one_adapter_plan.json``. Returns
    ``(exit_code, message)``.

    The validator is **non-mutating** — it never writes the plan, the
    manifest, or any other workspace file. It applies four layers of
    gates against the candidate plan:

      1. String- and filesystem-layer gates on ``--workspace`` /
         ``--plan`` / (optional) ``--descriptor-vocabulary`` (URI
         shape refused, symlink refused, exists, regular file /
         directory).
      2. The same ``image_manifest.json`` + ``input/source.md``
         preflight the write path applies, via
         ``_load_workspace_manifest_and_source`` — so a workspace
         without a schema-valid manifest is refused before the plan
         is even parsed. When ``--descriptor-vocabulary`` is supplied,
         the file is additionally schema-validated against
         ``schemas/d_one_descriptor_vocabulary.schema.json``, its
         ``image_taxonomy`` projected into a per-dimension
         allowed_values set, AND its ``custom_descriptors[].value``
         list projected into the custom-descriptor allow-list set.
      3. ``schemas/d_one_adapter_plan.schema.json`` against the plan
         JSON — catches malformed plans, list-rooted plans, unknown
         top-level / per-request fields, missing required fields,
         ``mode != "dry_run"``, ``schema_version != 3``, ``note``
         missing the dry-run sentinel, ``manifest_source !=
         "d_one_local"``, non-positive ``width_px`` / ``height_px``,
         taxonomy values that fail the lowercase-identifier +
         forbidden-token pattern lock, AND ``custom_descriptor``
         values that fail the same pattern lock.
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
         present) passes the full-slide-wording subset; when ANY
         plan request carries one or more of ``TAXONOMY_FIELDS``,
         ``--descriptor-vocabulary`` MUST have been supplied AND every
         present taxonomy value MUST be a member of the matching
         ``image_taxonomy.<dim>.allowed_values`` projected at gate (2)
         — drift detection: a plan whose taxonomy value is regex-shape
         valid but no longer in the vocabulary's allowed_values is
         refused here; AND when ANY plan request carries the
         ``custom_descriptor`` escape-hatch field,
         ``--descriptor-vocabulary`` MUST have been supplied AND the
         value MUST be a member of the vocab's
         ``custom_descriptors[].value`` allow-list AND re-pass the
         full ``_scan_prompt_safety`` deny list on BOTH the raw
         lowercased form AND a separator-normalized form (every run
         of ``.`` / ``_`` / ``-`` collapsed to a single space) — the
         same dual-form safety scan the write path applies.

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
    if descriptor_vocabulary is not None and _has_uri_scheme(
        str(descriptor_vocabulary)
    ):
        return 2, (
            f"FAIL: --descriptor-vocabulary {descriptor_vocabulary} "
            f"looks like a URI; done_image_adapter only accepts local "
            f"file paths"
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

    # Optional descriptor vocabulary preflight. Loaded eagerly (before
    # the plan is parsed) so a malformed vocabulary fails BEFORE the
    # validator inspects the plan — that matches the write path's order
    # so the two paths surface the same diagnostic for the same input.
    # The loader returns the vocab bytes it actually read; we keep
    # those as the canonical "before" snapshot for the byte-identical
    # post-condition below (no separate read here — sharing the loader's
    # bytes guarantees the two paths cannot drift on what counts as
    # "before").
    taxonomy_allowed: dict[str, set[str]] | None = None
    custom_descriptor_allowed: set[str] | None = None
    vocab_bytes_before: bytes | None = None
    if descriptor_vocabulary is not None:
        (
            taxonomy_allowed,
            custom_descriptor_allowed,
            vocab_bytes_before,
            rc,
            msg,
        ) = _load_descriptor_vocabulary(descriptor_vocabulary)
        if rc != 0:
            return rc, msg
        assert taxonomy_allowed is not None
        assert custom_descriptor_allowed is not None
        assert vocab_bytes_before is not None

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

        # Peek at text_policy for the policy-aware prompt scan; the
        # full taxonomy validation against the descriptor vocabulary
        # runs below. Mirrors the live spec path so a plan whose
        # text_policy says ``no_text`` is held to the same in-image-
        # text refusal the spec writer applied.
        plan_text_policy_peek = req.get("text_policy")
        if not isinstance(plan_text_policy_peek, str) or not plan_text_policy_peek.strip():
            plan_text_policy_peek = None
        prompt_violations = _scan_prompt_safety(
            req["prompt"], source_text=source_text,
            text_policy=plan_text_policy_peek,
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

        # Taxonomy cross-check. The schema already pattern-locked the
        # shape of every taxonomy value; the runtime additionally
        # requires --descriptor-vocabulary AND that every present value
        # is in image_taxonomy.<dim>.allowed_values. A plan whose
        # taxonomy value drifted away from the vocabulary's
        # allowed_values is refused here (the schema regex would still
        # pass on a regex-shape valid token like 'blueprint_style' that
        # is not in the canonical five rendering_style values).
        plan_taxonomy: dict[str, str] = {
            dim: req[dim] for dim in TAXONOMY_FIELDS if dim in req
        }
        if plan_taxonomy and taxonomy_allowed is None:
            return 1, (
                f"FAIL: {plan} requests[{i}] (id {req_id!r}) carries "
                f"taxonomy field(s) {sorted(plan_taxonomy.keys())} but "
                f"--descriptor-vocabulary was not supplied; "
                f"--validate-plan refuses to certify a plan whose "
                f"taxonomy values cannot be re-checked against "
                f"image_taxonomy.<dim>.allowed_values. Re-run with "
                f"--descriptor-vocabulary <path>."
            )
        if plan_taxonomy:
            assert taxonomy_allowed is not None
            for dim, value in plan_taxonomy.items():
                if value not in taxonomy_allowed[dim]:
                    return 1, (
                        f"FAIL: {plan} requests[{i}].{dim} "
                        f"(id {req_id!r}) value {value!r} is not in "
                        f"image_taxonomy.{dim}.allowed_values "
                        f"({sorted(taxonomy_allowed[dim])}); the plan "
                        f"taxonomy drifted from the supplied "
                        f"--descriptor-vocabulary."
                    )

        # custom_descriptor cross-check. The schema already pattern-
        # locked the field shape (lowercase-identifier + forbidden-token
        # deny clause); the runtime additionally requires
        # --descriptor-vocabulary AND that the value is present in the
        # vocab's custom_descriptors[] allow-list AND that the value
        # passes the full safety scan. A plan whose custom_descriptor
        # value drifted away from the vocab's allow-list (e.g. the
        # reviewer removed an entry and the plan was not re-authored)
        # is refused here. The plan-prompt safety scan above already
        # ran with the peeked text_policy; the same peeked value
        # applies to the custom_descriptor re-scan so an in-image-text
        # literal like 'calligraphy' under text_policy='no_text' is
        # caught symmetrically with the write path.
        plan_custom = req.get(CUSTOM_DESCRIPTOR_FIELD)
        if isinstance(plan_custom, str) and plan_custom:
            if custom_descriptor_allowed is None:
                return 1, (
                    f"FAIL: {plan} requests[{i}] (id {req_id!r}) "
                    f"carries {CUSTOM_DESCRIPTOR_FIELD} but "
                    f"--descriptor-vocabulary was not supplied; "
                    f"--validate-plan refuses to certify a plan whose "
                    f"custom-descriptor value cannot be re-checked "
                    f"against the vocab's custom_descriptors[] allow-"
                    f"list. Re-run with --descriptor-vocabulary <path>."
                )
            if not custom_descriptor_allowed:
                return 1, (
                    f"FAIL: {plan} requests[{i}].{CUSTOM_DESCRIPTOR_FIELD} "
                    f"(id {req_id!r}) value {plan_custom!r}: the "
                    f"supplied --descriptor-vocabulary declares no "
                    f"custom_descriptors[] entries, so no value can "
                    f"be approved. The plan custom_descriptor drifted "
                    f"from the supplied --descriptor-vocabulary."
                )
            if plan_custom not in custom_descriptor_allowed:
                return 1, (
                    f"FAIL: {plan} requests[{i}].{CUSTOM_DESCRIPTOR_FIELD} "
                    f"(id {req_id!r}) value {plan_custom!r} is not in "
                    f"the supplied --descriptor-vocabulary "
                    f"custom_descriptors[].value allow-list "
                    f"({sorted(custom_descriptor_allowed)}); the plan "
                    f"custom_descriptor drifted from the supplied "
                    f"--descriptor-vocabulary."
                )
            cd_violations = _scan_custom_descriptor_safety(
                plan_custom,
                source_text=source_text,
                text_policy=plan_text_policy_peek,
            )
            if cd_violations:
                return 1, (
                    f"FAIL: {plan} requests[{i}].{CUSTOM_DESCRIPTOR_FIELD} "
                    f"(id {req_id!r}) value {plan_custom!r} failed the "
                    f"safety re-scan: " + "; ".join(cd_violations)
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
    # Vocabulary byte-identical post-condition (when supplied). The
    # validator is non-mutating; a vocab-bytes change during the run
    # would mean another process is touching the file while we
    # validated, which is the same stronger signal we emit for the
    # manifest / plan.
    if descriptor_vocabulary is not None and vocab_bytes_before is not None:
        try:
            vocab_bytes_after = descriptor_vocabulary.read_bytes()
        except OSError as exc:
            return 1, (
                f"FAIL: cannot re-read --descriptor-vocabulary "
                f"{descriptor_vocabulary} after validate: {exc}"
            )
        if vocab_bytes_after != vocab_bytes_before:
            return 1, (
                f"FAIL: {descriptor_vocabulary} bytes changed during "
                f"--validate-plan (expected byte-identical)"
            )

    vocab_suffix = (
        f"\n  vocab:     {descriptor_vocabulary} "
        f"(image_taxonomy re-checked)"
        if descriptor_vocabulary is not None
        else ""
    )
    return 0, (
        f"OK: {plan} validates against "
        f"d_one_adapter_plan.schema.json AND the workspace's "
        f"image_manifest.json AND the full prompt safety scan"
        + (
            f" AND --descriptor-vocabulary "
            f"image_taxonomy.allowed_values."
            if descriptor_vocabulary is not None
            else "."
        )
        + f"\n  workspace: {workspace}\n"
        f"  requests:  {len(requests)}\n"
        f"  mode:      {plan_doc['mode']} "
        f"(NON-MUTATING — no file was written)"
        + vocab_suffix
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

    # ---- 11c. editable-text wording in prompt refused (universal —
    # fires regardless of text_policy because text that must remain
    # exact / editable / searchable / rewordable / data-faithful
    # belongs in the native SVG / PPT text layer, never in the
    # generated raster). Each phrase lives in
    # _PROMPT_EDITABLE_TEXT_LITERALS. NO descriptor-vocabulary is
    # supplied here — proves the rule fires without taxonomy. ----
    for phrase in (
        # Page / slide / section chrome wording.
        "slide title",
        "page title",
        "page chrome",
        # Body / overlay wording.
        "body copy",
        "body text",
        "native text",
        "svg text overlay",
        "text overlay",
        # Exact / editable / searchable / rewordable wording.
        "exact text",
        "editable copy",
        "searchable text",
        "rewordable copy",
        # Data-faithful wording.
        "data value",
        "data label",
        "axis label",
        "kpi number",
        "legend text",
        # Editable typographic blocks.
        "headline text",
        "subtitle text",
        "callout text",
        "annotation text",
        "caption text",
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_editable_text"
            _seed_workspace(ws, images=[
                {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "x",
                        "prompt": (
                            f"abstract pattern that holds the {phrase}"
                        ),
                    },
                ],
            })
            rc, msg = done_image_adapter(workspace=ws, spec=spec)
            ok = (
                rc == 1
                and "editable-text wording" in msg
                and "native SVG / PPT text layer" in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"editable-text wording {phrase!r} in prompt refused "
                f"(universal — no text_policy)",
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

    # ---- 12b. intended_use containing editable-text wording refused
    # (universal — proves the editable-text rule applies symmetrically
    # to the intended_use field, not just the prompt). ----
    for phrase in (
        "slide title",
        "body copy",
        "native text",
        "data value",
        "headline text",
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_iu_editable"
            _seed_workspace(ws, images=[
                {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "x",
                        "prompt": "an abstract pattern, no text",
                        "intended_use": (
                            f"raster that holds the {phrase} of the deck"
                        ),
                    },
                ],
            })
            rc, msg = done_image_adapter(workspace=ws, spec=spec)
            ok = (
                rc == 1
                and "intended_use" in msg
                and "editable-text wording" in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"intended_use containing editable-text wording "
                f"{phrase!r} refused",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- 12c. intended_use with NEGATED editable-text wording
    # PASSES — proves the negation exemption also applies on the
    # intended_use path, so a manifest description that re-states the
    # policy ("no slide title in this image", "body copy is
    # forbidden") is not refused. ----
    for label, iu_body in (
        ("no slide title in this image",
         "decorative accent, no slide title in this image"),
        ("body copy is forbidden",
         "decorative accent, body copy is forbidden here"),
        ("without body copy",
         "decorative accent, without body copy of any kind"),
        ("native text is prohibited",
         "decorative accent, native text is prohibited in this asset"),
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_iu_negated"
            _seed_workspace(ws, images=[
                {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "x",
                        "prompt": "an abstract pattern, no text",
                        "intended_use": iu_body,
                    },
                ],
            })
            rc, msg = done_image_adapter(workspace=ws, spec=spec)
            ok = (
                rc == 0
                and (ws / DEFAULT_PLAN_FILENAME).is_file()
            )
            results.append(_expect(
                f"intended_use ACCEPTS negated editable-text wording "
                f"{label!r} (BEFORE / AFTER negation exemption)",
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

    # ---- 36. schema gate: wrong schema_version refused. Probe with
    # 4 — the locked enum is currently [3] (the 2 -> 3 bump landed
    # alongside the optional per-request custom_descriptor escape-hatch
    # field), so 4 is a future unrecognized shape that the schema must
    # refuse. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws, plan_path = _seed_validate_workspace(td)
        plan_body = json.loads(plan_path.read_text())
        plan_body["schema_version"] = 4
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = rc == 1 and "schema_version" in msg and "not in enum" in msg
        results.append(_expect(
            "validate-plan: schema_version != 3 refused by schema enum "
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

    # =========================================================================
    # --descriptor-vocabulary taxonomy scenarios.
    #
    # Every scenario uses a small in-memory canonical descriptor
    # vocabulary written to a tempfile inside the temp directory. This
    # mirrors the on-disk template at
    # examples/d_one_descriptor_vocabulary_template.json but is
    # in-script-only so the probes do not depend on on-disk template
    # bytes (and so a future schema/template drift is still surfaced
    # by `python3 scripts/validate_artifacts.py --schema ... <template>`
    # independently).
    # =========================================================================

    def _canonical_vocab() -> dict:
        return {
            "schema_version": 1,
            "note": (
                "Synthetic in-script D-One descriptor vocabulary for "
                "adapter taxonomy probes."
            ),
            "kind_enum": [
                "color_token",
                "geometric_noun",
                "mood_adjective",
                "composition_adjective",
            ],
            "descriptors": [
                {"kind": "color_token", "value": "palette.accent"},
                {"kind": "geometric_noun", "value": "circle"},
                {"kind": "mood_adjective", "value": "calm"},
                {"kind": "composition_adjective", "value": "centered"},
            ],
            "image_taxonomy": {
                "rendering_style": {
                    "allowed_values": [
                        "flat_vector",
                        "line_diagram",
                        "isometric_lite",
                        "low_poly",
                        "solid_shape",
                    ],
                },
                "palette_family": {
                    "allowed_values": [
                        "neutral_grey",
                        "accent_only",
                        "dual_tone",
                        "mono_brand",
                        "palette_default",
                    ],
                },
                "image_role": {
                    "allowed_values": [
                        "decorative_accent",
                        "metaphor_icon",
                        "divider_motif",
                        "kpi_emblem",
                        "cover_motif",
                    ],
                },
                "layout_pattern": {
                    "allowed_values": [
                        "single_center",
                        "left_anchor",
                        "right_anchor",
                        "top_band",
                        "bottom_band",
                    ],
                },
                "modifier": {
                    "allowed_values": [
                        "low_contrast",
                        "soft_edges",
                        "grid_aligned",
                        "negative_space",
                    ],
                },
                "text_policy": {
                    "allowed_values": [
                        "no_text",
                        "decorative_glyphs",
                        "caption_safe",
                    ],
                },
                "subject_domain": {
                    "allowed_values": [
                        "abstract_geometry",
                        "process_motif",
                        "metric_emblem",
                        "concept_diagram",
                    ],
                },
            },
            # Approved custom-descriptor allow-list for the escape-hatch
            # probes. Same shape as descriptors[] (kind + value +
            # optional approved_in_review_ref); the adapter projects the
            # value strings into a set and refuses any request whose
            # custom_descriptor field is not a member.
            "custom_descriptors": [
                {
                    "kind": "composition_adjective",
                    "value": "hero_centered_motif",
                    "approved_in_review_ref": "synthetic_review.001",
                },
                {
                    "kind": "color_token",
                    "value": "palette.accent_pair",
                    "approved_in_review_ref": "synthetic_review.002",
                },
            ],
        }

    def _write_vocab(path: Path, body: dict) -> None:
        path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n")

    # ---- T1. valid taxonomy (write path): a spec carrying the five
    # original V6 taxonomy fields with canonical values + a vocab
    # pointer writes a
    # plan whose requests carry the same taxonomy fields. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_tax_valid"
        _seed_workspace(ws, images=[
            {"id": "cover", "local_path": "media/cover.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "cover",
                    "prompt": "an abstract geometric pattern, no text",
                    "rendering_style": "flat_vector",
                    "palette_family": "neutral_grey",
                    "image_role": "cover_motif",
                    "layout_pattern": "single_center",
                    "modifier": "negative_space",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        plan_doc = json.loads((ws / DEFAULT_PLAN_FILENAME).read_text()) if rc == 0 else {}
        req = plan_doc.get("requests", [{}])[0]
        ok = (
            rc == 0
            and req.get("rendering_style") == "flat_vector"
            and req.get("palette_family") == "neutral_grey"
            and req.get("image_role") == "cover_motif"
            and req.get("layout_pattern") == "single_center"
            and req.get("modifier") == "negative_space"
        )
        results.append(_expect(
            "taxonomy: spec with valid taxonomy + --descriptor-vocabulary "
            "succeeds; plan requests carry the same taxonomy fields",
            ok, f"rc={rc}, msg={msg!r}, req={req!r}",
        ))

    # ---- T2. omitted taxonomy (write path): a spec with no taxonomy
    # field is accepted with OR without --descriptor-vocabulary; the
    # plan does not gain any taxonomy field. ----
    for use_vocab in (False, True):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / f"ws_tax_omitted_{int(use_vocab)}"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [{"id": "a", "prompt": "abstract pattern"}],
            })
            vocab = td / "vocab.json"
            if use_vocab:
                _write_vocab(vocab, _canonical_vocab())
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec,
                descriptor_vocabulary=vocab if use_vocab else None,
            )
            plan_doc = json.loads(
                (ws / DEFAULT_PLAN_FILENAME).read_text()
            ) if rc == 0 else {}
            req = plan_doc.get("requests", [{}])[0]
            no_taxonomy = all(dim not in req for dim in TAXONOMY_FIELDS)
            ok = rc == 0 and no_taxonomy
            results.append(_expect(
                f"taxonomy: spec without taxonomy fields succeeds "
                f"(--descriptor-vocabulary {'supplied' if use_vocab else 'omitted'}); "
                f"plan stays taxonomy-free",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- T3. unknown taxonomy value (write path): a spec with a
    # rendering_style not in image_taxonomy.rendering_style.allowed_values
    # is refused with a clear allowed_values diagnostic. The value
    # 'blueprint_style' is regex-shape valid (lowercase identifier, no
    # forbidden tokens) so the schema regex would NOT trip; the
    # runtime allowed_values check must close that gap. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_tax_unknown"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern",
                    "rendering_style": "blueprint_style",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        ok = (
            rc == 1
            and "rendering_style" in msg
            and "blueprint_style" in msg
            and "image_taxonomy.rendering_style.allowed_values" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "taxonomy: unknown rendering_style refused with "
            "allowed_values diagnostic; no plan file written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- T4. unsafe taxonomy value (write path): values whose shape
    # carries a forbidden token (public / upload / raw / customer /
    # confidential / screenshot / credential / password / secret) OR a
    # forbidden compound (full slide / image search / web generation /
    # page generation / slide generation) cannot land in the plan. The
    # runtime allowed_values check already refuses them (none of the
    # canonical values matches an unsafe shape), so they fail FIRST at
    # the allowed_values gate; the post-write schema regex remains a
    # belt-and-braces defense. We parametrize across the original five
    # V6 dimensions to prove the gate is consistent (the two
    # prompt-intent dimensions text_policy + subject_domain are
    # exercised in the separate TPI5 block below). ----
    unsafe_cases: tuple[tuple[str, str], ...] = (
        ("rendering_style", "public_render"),
        ("palette_family", "upload_palette"),
        ("image_role", "raw_motif"),
        ("layout_pattern", "customer_anchor"),
        ("modifier", "confidential_modifier"),
        ("rendering_style", "screenshot_diagram"),
        ("rendering_style", "credential_motif"),
        ("rendering_style", "password_motif"),
        ("rendering_style", "secret_render"),
        ("rendering_style", "full_slide"),
        ("rendering_style", "image_search"),
        ("rendering_style", "web_generation"),
        ("rendering_style", "page_generation"),
        ("rendering_style", "slide_generation"),
    )
    for dim, unsafe_value in unsafe_cases:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / f"ws_tax_unsafe_{dim}"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "a",
                        "prompt": "abstract pattern",
                        dim: unsafe_value,
                    },
                ],
            })
            vocab = td / "vocab.json"
            _write_vocab(vocab, _canonical_vocab())
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 1
                and dim in msg
                and unsafe_value in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"taxonomy: unsafe {dim}={unsafe_value!r} refused; no "
                f"plan file written",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- T5. missing --descriptor-vocabulary (write path): a spec
    # request carrying a taxonomy field is refused when no
    # --descriptor-vocabulary was supplied. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_tax_no_vocab"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern",
                    "rendering_style": "flat_vector",
                },
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = (
            rc == 1
            and "--descriptor-vocabulary" in msg
            and "rendering_style" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "taxonomy: spec with taxonomy field but no "
            "--descriptor-vocabulary refused; no plan file written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- T6. plan drift (validate-plan path): a plan was written
    # with a valid taxonomy value, then the plan file was rewritten
    # by hand to carry a regex-shape-valid value that is NOT in the
    # vocabulary's allowed_values. --validate-plan refuses it. This
    # is the realistic drift mode the runtime gate exists to catch
    # (schema pattern alone passes a value like 'blueprint_style').
    # ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_drift"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern",
                    "rendering_style": "flat_vector",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        rc, msg_seed = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        assert rc == 0, f"T6 seed failed: rc={rc} msg={msg_seed!r}"
        plan_path = ws / DEFAULT_PLAN_FILENAME
        plan_body = json.loads(plan_path.read_text())
        plan_body["requests"][0]["rendering_style"] = "blueprint_style"
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(
            workspace=ws, plan=plan_path, descriptor_vocabulary=vocab,
        )
        ok = (
            rc == 1
            and "rendering_style" in msg
            and "blueprint_style" in msg
            and "drifted" in msg
        )
        results.append(_expect(
            "taxonomy: validate-plan refuses a plan whose taxonomy value "
            "drifted from --descriptor-vocabulary "
            "image_taxonomy.allowed_values",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- T7. validate-plan path: missing --descriptor-vocabulary
    # when the plan carries taxonomy fields is refused. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_validate_no_vocab"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern",
                    "rendering_style": "flat_vector",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        rc, _ = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        assert rc == 0
        plan_path = ws / DEFAULT_PLAN_FILENAME
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = (
            rc == 1
            and "--descriptor-vocabulary" in msg
            and "rendering_style" in msg
        )
        results.append(_expect(
            "taxonomy: validate-plan refuses a taxonomy-carrying plan "
            "when --descriptor-vocabulary was not supplied",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- T8. validate-plan path: a plan written WITHOUT taxonomy
    # fields validates clean with OR without --descriptor-vocabulary
    # (the optional vocab is still schema-checked when supplied). ----
    for use_vocab in (False, True):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / f"ws_validate_no_tax_{int(use_vocab)}"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [{"id": "a", "prompt": "abstract pattern"}],
            })
            rc, _ = done_image_adapter(workspace=ws, spec=spec)
            assert rc == 0
            plan_path = ws / DEFAULT_PLAN_FILENAME
            vocab = td / "vocab.json"
            if use_vocab:
                _write_vocab(vocab, _canonical_vocab())
            rc, msg = validate_plan_file(
                workspace=ws, plan=plan_path,
                descriptor_vocabulary=vocab if use_vocab else None,
            )
            ok = rc == 0 and "validates against" in msg
            results.append(_expect(
                f"taxonomy: validate-plan accepts a taxonomy-free plan "
                f"(--descriptor-vocabulary "
                f"{'supplied' if use_vocab else 'omitted'})",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- T9. malformed / schema-invalid --descriptor-vocabulary
    # refused (write path). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_bad_vocab"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern",
                    "rendering_style": "flat_vector",
                },
            ],
        })
        # Missing kind_enum -> schema-invalid.
        bad_vocab = td / "vocab.json"
        bad_vocab.write_text(json.dumps({
            "schema_version": 1,
            "note": "D-One descriptor vocabulary, broken on purpose",
            "descriptors": [],
            "image_taxonomy": _canonical_vocab()["image_taxonomy"],
        }))
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=bad_vocab,
        )
        ok = (
            rc == 1
            and "d_one_descriptor_vocabulary.schema.json" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "taxonomy: schema-invalid --descriptor-vocabulary refused; "
            "no plan file written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- T10. symlinked / URI-shaped / missing --descriptor-vocabulary
    # refused at the string + filesystem layers (write path). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_vocab_link"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern",
                    "rendering_style": "flat_vector",
                },
            ],
        })
        real_vocab = td / "vocab.json"
        _write_vocab(real_vocab, _canonical_vocab())
        link_vocab = td / "vocab_link.json"
        link_vocab.symlink_to(real_vocab)
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=link_vocab,
        )
        ok = (
            rc == 2
            and "symlink" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "taxonomy: symlink at --descriptor-vocabulary refused; no "
            "plan file written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    rc, msg = done_image_adapter(
        workspace=Path("/tmp/ws"),
        spec=Path("/tmp/spec.json"),
        descriptor_vocabulary=Path("https://attacker.example/v.json"),
    )
    ok = rc == 2 and "URI" in msg
    results.append(_expect(
        "taxonomy: URI-shaped --descriptor-vocabulary refused at the "
        "string layer",
        ok, f"rc={rc}, msg={msg!r}",
    ))

    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_vocab_missing"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern",
                    "rendering_style": "flat_vector",
                },
            ],
        })
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec,
            descriptor_vocabulary=td / "does_not_exist.json",
        )
        ok = (
            rc == 2
            and "does not exist" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "taxonomy: missing --descriptor-vocabulary file refused",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- T11. determinism: with taxonomy fields, two independent runs
    # from identical inputs produce byte-identical plan-file bytes. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bodies: list[bytes] = []
        for ws_name in ("ws_a", "ws_b"):
            ws = td / ws_name
            _seed_workspace(ws, images=[
                {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
                {"id": "y", "local_path": "media/y.png", "source": "d_one_local"},
            ])
            spec = td / f"spec_{ws_name}.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "y",
                        "prompt": "second abstract pattern",
                        "rendering_style": "low_poly",
                        "image_role": "kpi_emblem",
                    },
                    {
                        "id": "x",
                        "prompt": "first abstract pattern",
                        "rendering_style": "flat_vector",
                        "modifier": "soft_edges",
                    },
                ],
            })
            vocab = td / f"vocab_{ws_name}.json"
            _write_vocab(vocab, _canonical_vocab())
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            assert rc == 0, f"determinism seed failed: rc={rc} msg={msg!r}"
            bodies.append((ws / DEFAULT_PLAN_FILENAME).read_bytes())
        ok = bodies[0] == bodies[1]
        results.append(_expect(
            "taxonomy: two independent runs with identical taxonomy "
            "inputs produce byte-identical plan-file bytes",
            ok, f"len_a={len(bodies[0])}, len_b={len(bodies[1])}",
        ))

    # ---- T12. write-path vocab byte-identical post-condition: a
    # successful write leaves the supplied --descriptor-vocabulary file
    # byte-identical pre/post. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_vocab_post"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern",
                    "rendering_style": "flat_vector",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        vocab_bytes_before = vocab.read_bytes()
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        ok = (
            rc == 0
            and vocab.read_bytes() == vocab_bytes_before
            and (ws / DEFAULT_PLAN_FILENAME).is_file()
        )
        results.append(_expect(
            "taxonomy: write-path leaves --descriptor-vocabulary bytes "
            "byte-identical pre/post a successful run",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- T13. write-path vocab post-condition rolls back: a mutation
    # of the vocab file between the loader's read and the post-condition
    # re-read trips the gate and unlinks the just-written plan file.
    # Monkey-patches the loader to return a "before" snapshot that
    # disagrees with the disk bytes at post-condition time. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_vocab_rollback"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern",
                    "rendering_style": "flat_vector",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        import sys as _sys2
        _mod2 = _sys2.modules[__name__]
        original_loader = _mod2._load_descriptor_vocabulary

        def fake_loader(vocab_path: Path):
            allowed, allowed_custom, real_bytes, rc, msg = (
                original_loader(vocab_path)
            )
            if rc != 0:
                return allowed, allowed_custom, real_bytes, rc, msg
            # Return a doctored "before" snapshot that disagrees with
            # the bytes currently on disk. The post-condition re-reads
            # the real bytes and compares to this — they cannot match,
            # so the gate must fire and the plan must be rolled back.
            return allowed, allowed_custom, real_bytes + b"X", rc, msg

        _mod2._load_descriptor_vocabulary = fake_loader  # type: ignore[attr-defined]
        try:
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
        finally:
            _mod2._load_descriptor_vocabulary = original_loader  # type: ignore[attr-defined]
        ok = (
            rc == 1
            and "bytes changed during apply" in msg
            and "Rolled back plan" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "taxonomy: write-path post-condition rolls the plan back "
            "when the vocab bytes disagree at re-read (regression for "
            "the new vocab byte-identical post-condition)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # =========================================================================
    # Prompt-intent contract scenarios: text_policy + subject_domain.
    #
    # These extend the taxonomy with two clean-room dimensions aligned
    # idea-level with the upstream ai-image work, but no upstream code
    # / text / assets were copied. Each new field is gated through the
    # SAME machinery the original five V6 dimensions use (so the
    # taxonomy is seven dimensions total), and the bulk of the existing
    # taxonomy probes also cover them. The scenarios below pin down the
    # specific behaviors the new contract requires:
    # valid round-trip, drift, missing vocabulary, and the full
    # forbidden-token deny list at the schema layer.
    # =========================================================================

    # ---- TPI1. valid text_policy + subject_domain (write path):
    # canonical values for both new fields land in the plan. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_tpi_valid"
        _seed_workspace(ws, images=[
            {"id": "spot", "local_path": "a/spot.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "spot",
                    "prompt": "abstract pattern",
                    "text_policy": "no_text",
                    "subject_domain": "abstract_geometry",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        plan_doc = json.loads(
            (ws / DEFAULT_PLAN_FILENAME).read_text()
        ) if rc == 0 else {}
        req = plan_doc.get("requests", [{}])[0]
        ok = (
            rc == 0
            and req.get("text_policy") == "no_text"
            and req.get("subject_domain") == "abstract_geometry"
        )
        results.append(_expect(
            "prompt-intent: valid text_policy + subject_domain land in "
            "the plan via the write path",
            ok, f"rc={rc}, msg={msg!r}, req={req!r}",
        ))

    # ---- TPI2. validate-plan round-trip for a text_policy /
    # subject_domain plan. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_tpi_validate"
        _seed_workspace(ws, images=[
            {"id": "spot", "local_path": "a/spot.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "spot",
                    "prompt": "abstract pattern",
                    "text_policy": "caption_safe",
                    "subject_domain": "concept_diagram",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        rc, _ = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        assert rc == 0, "TPI2 seed failed"
        plan_path = ws / DEFAULT_PLAN_FILENAME
        rc, msg = validate_plan_file(
            workspace=ws, plan=plan_path, descriptor_vocabulary=vocab,
        )
        ok = rc == 0 and "validates against" in msg
        results.append(_expect(
            "prompt-intent: validate-plan accepts a plan carrying "
            "text_policy + subject_domain when the vocab matches",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- TPI3. missing --descriptor-vocabulary refuses a spec
    # carrying text_policy / subject_domain. ----
    for field, value in (
        ("text_policy", "no_text"),
        ("subject_domain", "abstract_geometry"),
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / f"ws_tpi_no_vocab_{field}"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "a",
                        "prompt": "abstract pattern",
                        field: value,
                    },
                ],
            })
            rc, msg = done_image_adapter(workspace=ws, spec=spec)
            ok = (
                rc == 1
                and "--descriptor-vocabulary" in msg
                and field in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"prompt-intent: missing --descriptor-vocabulary refuses "
                f"a spec carrying {field}={value!r}",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- TPI4. unknown values refused: text_policy and subject_domain
    # values that are regex-shape valid but not in allowed_values. ----
    for field, unknown_value in (
        ("text_policy", "mystery_policy"),
        ("subject_domain", "mystery_domain"),
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / f"ws_tpi_unknown_{field}"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "a",
                        "prompt": "abstract pattern",
                        field: unknown_value,
                    },
                ],
            })
            vocab = td / "vocab.json"
            _write_vocab(vocab, _canonical_vocab())
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 1
                and field in msg
                and unknown_value in msg
                and f"image_taxonomy.{field}.allowed_values" in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"prompt-intent: unknown {field}={unknown_value!r} "
                f"refused with allowed_values diagnostic",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- TPI5. unsafe-token values refused at the schema layer.
    # Every value here matches the forbidden-token deny clause in the
    # adapter plan schema's pattern lock (`public_*` / `upload_*` /
    # `raw_*` / `customer_*` / `confidential_*` / `screenshot_*` /
    # `credential_*` / `password_*` / `secret_*` / `full_slide` /
    # `image_search` / `web_generation`), so the runtime allowed_values
    # check rejects it first AND the post-write schema validation would
    # reject the value if it ever slipped through. We parametrize across
    # both new dimensions and the full deny list so a future relaxation
    # of either trips the regression. ----
    unsafe_intent_cases: tuple[tuple[str, str], ...] = (
        ("text_policy", "public_caption"),
        ("text_policy", "upload_text"),
        ("text_policy", "raw_text"),
        ("text_policy", "customer_caption"),
        ("text_policy", "confidential_caption"),
        ("text_policy", "screenshot_text"),
        ("text_policy", "credential_text"),
        ("text_policy", "password_text"),
        ("text_policy", "secret_text"),
        ("text_policy", "full_slide"),
        ("text_policy", "image_search"),
        ("text_policy", "web_generation"),
        ("text_policy", "page_generation"),
        ("text_policy", "slide_generation"),
        ("subject_domain", "public_domain"),
        ("subject_domain", "upload_motif"),
        ("subject_domain", "raw_subject"),
        ("subject_domain", "customer_brand"),
        ("subject_domain", "confidential_motif"),
        ("subject_domain", "screenshot_motif"),
        ("subject_domain", "credential_emblem"),
        ("subject_domain", "password_motif"),
        ("subject_domain", "secret_emblem"),
        ("subject_domain", "full_slide"),
        ("subject_domain", "image_search"),
        ("subject_domain", "web_generation"),
        ("subject_domain", "page_generation"),
        ("subject_domain", "slide_generation"),
    )
    for field, unsafe_value in unsafe_intent_cases:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / f"ws_tpi_unsafe_{field}"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "a",
                        "prompt": "abstract pattern",
                        field: unsafe_value,
                    },
                ],
            })
            vocab = td / "vocab.json"
            _write_vocab(vocab, _canonical_vocab())
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 1
                and field in msg
                and unsafe_value in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"prompt-intent: unsafe {field}={unsafe_value!r} "
                f"refused; no plan file written",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- TPI6. validate-plan drift on text_policy + subject_domain.
    # A plan written with canonical values then hand-mutated to a
    # regex-shape-valid but not-in-allowed_values value is refused by
    # --validate-plan. ----
    for field, drifted_value in (
        ("text_policy", "drifted_policy"),
        ("subject_domain", "drifted_domain"),
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / f"ws_tpi_drift_{field}"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            canonical = {
                "text_policy": "no_text",
                "subject_domain": "abstract_geometry",
            }
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "a",
                        "prompt": "abstract pattern",
                        **canonical,
                    },
                ],
            })
            vocab = td / "vocab.json"
            _write_vocab(vocab, _canonical_vocab())
            rc, _ = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            assert rc == 0, f"TPI6/{field} seed failed"
            plan_path = ws / DEFAULT_PLAN_FILENAME
            plan_body = json.loads(plan_path.read_text())
            plan_body["requests"][0][field] = drifted_value
            _overwrite_plan(plan_path, plan_body)
            rc, msg = validate_plan_file(
                workspace=ws, plan=plan_path, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 1
                and field in msg
                and drifted_value in msg
                and "drifted" in msg
            )
            results.append(_expect(
                f"prompt-intent: validate-plan refuses a plan whose "
                f"{field} value drifted from allowed_values",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- TPI7. text_policy='no_text' + a prompt asking for visible
    # in-image text refused. Each phrase lives in
    # _PROMPT_NO_TEXT_REQUEST_LITERALS. The vocab IS supplied so the
    # taxonomy value is valid; the only thing refusing the request is
    # the policy-aware in-image-text scan. ----
    for phrase in (
        "include text",
        "with text",
        "visible text",
        "add letters",
        "show numerals",
        "include a caption",
        "with a label",
        "with a title",
        "include a slogan",
        "with a quote",
        "lettering",
        "typography",
        "wordmark",
        "calligraphy",
        "monogram",
        "text in the image",
        "letters on the image",
        "writing in the image",
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_tpi_no_text_request"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "a",
                        "prompt": f"abstract pattern, please {phrase}",
                        "text_policy": "no_text",
                        "subject_domain": "abstract_geometry",
                    },
                ],
            })
            vocab = td / "vocab.json"
            _write_vocab(vocab, _canonical_vocab())
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 1
                and "in-image-text wording" in msg
                and "text_policy='no_text'" in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"prompt-intent: text_policy='no_text' refuses prompt "
                f"asking for in-image text via {phrase!r}",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- TPI8. decorative artwork text wording in prompt PASSES
    # under text_policy='decorative_glyphs' (the policy permits
    # artwork-style letterforms). Same prompt that TPI7 would refuse
    # under no_text is accepted here — proves the gate is policy-
    # aware, not a blanket ban on letter-related wording. ----
    for phrase in ("lettering", "calligraphy", "wordmark", "monogram"):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_tpi_decorative_glyphs"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "a",
                        "prompt": (
                            f"decorative {phrase} accent, "
                            f"stylised artwork only"
                        ),
                        "text_policy": "decorative_glyphs",
                        "subject_domain": "metric_emblem",
                    },
                ],
            })
            vocab = td / "vocab.json"
            _write_vocab(vocab, _canonical_vocab())
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            plan_doc = json.loads(
                (ws / DEFAULT_PLAN_FILENAME).read_text()
            ) if rc == 0 else {}
            ok = (
                rc == 0
                and plan_doc.get("requests", [{}])[0].get(
                    "text_policy",
                ) == "decorative_glyphs"
            )
            results.append(_expect(
                f"prompt-intent: text_policy='decorative_glyphs' "
                f"accepts decorative artwork wording {phrase!r} "
                f"(policy-aware, not a blanket ban)",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- TPI9. non-Latin / CJK decorative artwork text in the
    # prompt PASSES under text_policy='decorative_glyphs'. Proves
    # the validator is editability-based, not script-based: nothing
    # in _scan_prompt_safety rejects a prompt SOLELY because it
    # contains non-Latin characters. The fixture is synthetic — a
    # generic decorative-pattern adjective followed by a short
    # non-sensitive non-Latin string. ----
    for label, non_latin_snippet in (
        # Synthetic stand-in for a CJK calligraphy accent.
        ("CJK calligraphy", "水火"),
        # Synthetic stand-in for a Cyrillic decorative initial.
        ("Cyrillic initial", "Я"),
        # Synthetic stand-in for an Arabic decorative ornament.
        ("Arabic ornament", "فج"),
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_tpi_non_latin_artwork"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "a",
                        "prompt": (
                            f"decorative geometric accent, "
                            f"stylised motif {non_latin_snippet}"
                        ),
                        "text_policy": "decorative_glyphs",
                        "subject_domain": "metric_emblem",
                    },
                ],
            })
            vocab = td / "vocab.json"
            _write_vocab(vocab, _canonical_vocab())
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 0
                and (ws / DEFAULT_PLAN_FILENAME).is_file()
            )
            results.append(_expect(
                f"prompt-intent: non-Latin decorative wording "
                f"({label}) accepted under "
                f"text_policy='decorative_glyphs' (editability-based "
                f"gate, NOT a script-based ban)",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- TPI10. universal editable-text rule fires EVEN when
    # text_policy permits decorative artwork text. A prompt asking
    # for the slide title under text_policy='decorative_glyphs' is
    # still refused: the artwork-text policy permits stylised
    # letterforms, not editable chrome. Proves the universal rule
    # and the policy-aware rule are independent. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_tpi_editable_vs_decorative"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": (
                        "decorative letterform that holds the slide title"
                    ),
                    "text_policy": "decorative_glyphs",
                    "subject_domain": "metric_emblem",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        ok = (
            rc == 1
            and "editable-text wording" in msg
            and "'slide title'" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "prompt-intent: universal editable-text rule still fires "
            "under text_policy='decorative_glyphs' (slide-title chrome "
            "refused even when artwork letterforms are permitted)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- TPI11. text_policy='no_text' + a prompt that NEGATES the
    # in-image-text wording PASSES. Proves the policy-aware scan is
    # negation-exempt, so a prompt that simply re-states the policy
    # ("no visible text", "do not include text", "without lettering",
    # "calligraphy is not allowed") is accepted instead of refused.
    # Mirrors the BEFORE / AFTER adjacency pattern documented at
    # scripts/validate_d_one_live_run_evidence.py. ----
    for label, prompt_body in (
        ("BEFORE-side 'no'", "abstract pattern, no visible text"),
        ("BEFORE-side 'not'",
         "abstract pattern, do not include text in the asset"),
        ("BEFORE-side 'never'",
         "abstract pattern, never show numerals please"),
        ("BEFORE-side 'without'",
         "abstract pattern, without any text"),
        ("BEFORE-side 'without' applied to typographic-art literal",
         "abstract pattern, without lettering"),
        ("AFTER-side 'is forbidden'",
         "abstract pattern, lettering is forbidden in this image"),
        ("AFTER-side 'is not allowed'",
         "abstract pattern, calligraphy is not allowed here"),
        ("AFTER-side bare refusal 'refused'",
         "abstract pattern, typography refused for this asset"),
        ("AFTER-side 'is prohibited'",
         "abstract pattern, wordmark is prohibited here"),
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_tpi_negated_no_text"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "a",
                        "prompt": prompt_body,
                        "text_policy": "no_text",
                        "subject_domain": "abstract_geometry",
                    },
                ],
            })
            vocab = td / "vocab.json"
            _write_vocab(vocab, _canonical_vocab())
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 0
                and (ws / DEFAULT_PLAN_FILENAME).is_file()
            )
            results.append(_expect(
                f"prompt-intent: text_policy='no_text' ACCEPTS "
                f"negated reinforcement wording ({label}) — the "
                f"in-image-text scan exempts policy-reinforcement "
                f"phrasings",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- TPI12. universal editable-text rule + NEGATED prompt
    # wording PASSES (no text_policy supplied; the universal rule is
    # checked regardless). Proves the universal rule honors the same
    # negation exemption — "no slide title", "without body copy",
    # "caption text is forbidden" all describe what the image must
    # NOT carry and should not trip the gate. ----
    for label, prompt_body in (
        ("BEFORE-side 'no'",
         "abstract pattern, no slide title in the artwork"),
        ("BEFORE-side 'without'",
         "abstract pattern, without body copy of any kind"),
        ("BEFORE-side 'never' (strict adjacency)",
         "abstract pattern, never legend text baked in"),
        ("AFTER-side 'is forbidden'",
         "abstract pattern, caption text is forbidden here"),
        ("AFTER-side 'is not used'",
         "abstract pattern, native text is not used in this asset"),
        ("AFTER-side bare 'prohibited'",
         "abstract pattern, body copy prohibited in this raster"),
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_universal_negated"
            _seed_workspace(ws, images=[
                {"id": "x", "local_path": "a/x.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {"id": "x", "prompt": prompt_body},
                ],
            })
            rc, msg = done_image_adapter(workspace=ws, spec=spec)
            ok = (
                rc == 0
                and (ws / DEFAULT_PLAN_FILENAME).is_file()
            )
            results.append(_expect(
                f"universal editable-text rule ACCEPTS negated "
                f"wording ({label}) — policy-reinforcement is "
                f"exempted regardless of text_policy",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- TPI13. mixed prompt — a negated reinforcement AND an
    # unnegated request — STILL FAILS. Proves the negation exemption
    # is per-occurrence, not per-prompt: if any unnegated request
    # phrase appears, the gate fires. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_mixed_negation"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": (
                        "abstract pattern, do not include text, "
                        "but please add a caption"
                    ),
                    "text_policy": "no_text",
                    "subject_domain": "abstract_geometry",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        ok = (
            rc == 1
            and "in-image-text wording" in msg
            and "'add a caption'" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "prompt-intent: mixed prompt with a NEGATED reinforcement "
            "AND an UNNEGATED request — the unnegated request still "
            "trips the in-image-text gate (negation exemption is "
            "per-occurrence, not per-prompt)",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- TPI14. BEFORE-side false-green probe (regression for the
    # Codex stop-time review): a comma / period / ellipsis between
    # the negation word and the literal breaks strict adjacency, so
    # the in-image-text request still fires. Comma is a clause
    # boundary in English; if it were exempted, a caller could write
    # ``"no, include text"`` and sneak an unnegated request past the
    # gate. ----
    for label, prompt_body in (
        ("'no,' comma break",
         "abstract pattern. no, include text in this image"),
        ("'not.' period break",
         "abstract pattern. not. include text everywhere"),
        ("'without...' ellipsis break",
         "abstract pattern. without... lettering required"),
        ("'no;' semicolon break",
         "abstract pattern. no; show text"),
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_tpi_before_punct_break"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "a",
                        "prompt": prompt_body,
                        "text_policy": "no_text",
                        "subject_domain": "abstract_geometry",
                    },
                ],
            })
            vocab = td / "vocab.json"
            _write_vocab(vocab, _canonical_vocab())
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 1
                and "in-image-text wording" in msg
                and "text_policy='no_text'" in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"prompt-intent: BEFORE-side punctuation BREAKS "
                f"adjacency ({label}) — the in-image-text request "
                f"still fires (negation does NOT propagate across "
                f"a clause boundary)",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- TPI15. AFTER-side false-green probe: a comma immediately
    # after the literal OR after the copula breaks strict adjacency
    # to the refusal phrase. Closes a parallel false-green where a
    # caller could write ``"include text is, forbidden later"`` and
    # have the ``"is, forbidden"`` sequence treated as a refusal
    # phrase even though the comma between subject and verb means
    # this is two unrelated clauses, not one reinforcement. ----
    for label, prompt_body in (
        ("comma between literal and refusal",
         "abstract pattern, include text, forbidden everywhere"),
        ("comma between copula and refusal",
         "abstract pattern, include text is, forbidden later"),
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_tpi_after_punct_break"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "a",
                        "prompt": prompt_body,
                        "text_policy": "no_text",
                        "subject_domain": "abstract_geometry",
                    },
                ],
            })
            vocab = td / "vocab.json"
            _write_vocab(vocab, _canonical_vocab())
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 1
                and "in-image-text wording" in msg
                and "text_policy='no_text'" in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"prompt-intent: AFTER-side punctuation BREAKS "
                f"adjacency ({label}) — the in-image-text request "
                f"still fires (refusal phrase belongs to a later "
                f"clause)",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # =========================================================================
    # custom_descriptor escape-hatch scenarios.
    #
    # The custom_descriptor field is a conservative escape hatch aligned
    # only with the upstream ai-image custom rendering/palette/hero-
    # composition direction — no upstream code/prompts/examples/assets
    # were copied. The field is OPTIONAL on every spec / plan request
    # and may appear only when --descriptor-vocabulary is supplied AND
    # the vocab's custom_descriptors[] allow-list carries an explicit
    # approved entry for the exact value. Missing vocab, missing
    # allow-list, unknown value, unsafe shape, malformed type, or plan
    # drift each fail closed before any plan / asset / workspace / PPTX
    # is produced.
    # =========================================================================

    # ---- CD1. approved custom_descriptor (write path): a spec carrying
    # a custom_descriptor that matches the vocab allow-list lands on the
    # plan request byte-identical to the spec. The plan re-parses to a
    # schema-valid body whose schema_version is the locked 3. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_cd_valid"
        _seed_workspace(ws, images=[
            {"id": "cover", "local_path": "media/cover.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "cover",
                    "prompt": "an abstract geometric pattern, no text",
                    "custom_descriptor": "hero_centered_motif",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        plan_doc = (
            json.loads((ws / DEFAULT_PLAN_FILENAME).read_text())
            if rc == 0 else {}
        )
        req = plan_doc.get("requests", [{}])[0] if plan_doc else {}
        ok = (
            rc == 0
            and plan_doc.get("schema_version") == PLAN_SCHEMA_VERSION
            and req.get("custom_descriptor") == "hero_centered_motif"
        )
        results.append(_expect(
            "custom_descriptor: approved value + vocab allow-list "
            "succeeds; plan carries the value byte-identically and "
            f"schema_version == {PLAN_SCHEMA_VERSION}",
            ok, f"rc={rc}, msg={msg!r}, req={req!r}",
        ))

    # ---- CD2. missing --descriptor-vocabulary (write path): a spec
    # carrying custom_descriptor with no vocab supplied is refused with
    # a clear "--descriptor-vocabulary" diagnostic; no plan written. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_cd_no_vocab"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern, no text",
                    "custom_descriptor": "hero_centered_motif",
                },
            ],
        })
        rc, msg = done_image_adapter(workspace=ws, spec=spec)
        ok = (
            rc == 1
            and "--descriptor-vocabulary" in msg
            and CUSTOM_DESCRIPTOR_FIELD in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "custom_descriptor: missing --descriptor-vocabulary refused; "
            "no plan file written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- CD3. empty allow-list refused (write path): a vocab whose
    # custom_descriptors[] is empty cannot certify any value. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_cd_empty_list"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern, no text",
                    "custom_descriptor": "hero_centered_motif",
                },
            ],
        })
        empty_vocab = _canonical_vocab()
        empty_vocab["custom_descriptors"] = []
        vocab = td / "vocab.json"
        _write_vocab(vocab, empty_vocab)
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        ok = (
            rc == 1
            and "no custom_descriptors[] entries" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "custom_descriptor: empty custom_descriptors[] allow-list "
            "refuses any value; no plan file written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- CD4. omitted allow-list refused (write path): a vocab that
    # does NOT declare custom_descriptors[] (backward-compatible older
    # vocabulary) cannot certify any value. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_cd_omitted_list"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern, no text",
                    "custom_descriptor": "hero_centered_motif",
                },
            ],
        })
        omitted_vocab = _canonical_vocab()
        del omitted_vocab["custom_descriptors"]
        vocab = td / "vocab.json"
        _write_vocab(vocab, omitted_vocab)
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        ok = (
            rc == 1
            and "no custom_descriptors[] entries" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "custom_descriptor: vocab WITHOUT a custom_descriptors[] "
            "list refuses any value (backward-compat older vocab); no "
            "plan file written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- CD5. unknown value refused (write path): the value is
    # regex-shape valid (lowercase identifier, no forbidden tokens) but
    # not in the supplied vocab's custom_descriptors[] allow-list. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_cd_unknown"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern, no text",
                    "custom_descriptor": "unapproved_motif",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        ok = (
            rc == 1
            and "unapproved_motif" in msg
            and "custom_descriptors[].value allow-list" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "custom_descriptor: unknown value (regex-shape valid but not "
            "in the vocab allow-list) refused with a clear allow-list "
            "diagnostic; no plan file written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- CD6. malformed type refused (write path): a non-string
    # custom_descriptor (number, list, dict, empty / whitespace-only
    # string) is refused with a non-empty-string diagnostic. ----
    malformed_cases: tuple[object, ...] = (
        42, [], {}, "", "   ",
    )
    for bad_value in malformed_cases:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_cd_malformed"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "a",
                        "prompt": "abstract pattern, no text",
                        "custom_descriptor": bad_value,
                    },
                ],
            })
            vocab = td / "vocab.json"
            _write_vocab(vocab, _canonical_vocab())
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 1
                and "non-empty string" in msg
                and CUSTOM_DESCRIPTOR_FIELD in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"custom_descriptor: malformed type {bad_value!r} refused "
                f"with non-empty-string diagnostic",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- CD7. unsafe-token allow-list value refused at the schema
    # layer (write path). Every value here matches the forbidden-token
    # deny clause in the descriptor-vocabulary schema's pattern lock; a
    # vocab that ships such a value as a custom_descriptors[].value
    # fails closed at the schema layer when the adapter loads it. We
    # exercise the same 9-token + 5-compound deny list used elsewhere
    # so a regression in either family is caught. ----
    unsafe_cd_cases: tuple[str, ...] = (
        "public_motif",
        "upload_motif",
        "raw_motif",
        "customer_motif",
        "confidential_motif",
        "screenshot_motif",
        "credential_motif",
        "password_motif",
        "secret_motif",
        "full_slide",
        "image_search",
        "web_generation",
        "page_generation",
        "slide_generation",
    )
    for unsafe_value in unsafe_cd_cases:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_cd_unsafe_vocab"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "a",
                        "prompt": "abstract pattern, no text",
                        "custom_descriptor": unsafe_value,
                    },
                ],
            })
            unsafe_vocab = _canonical_vocab()
            unsafe_vocab["custom_descriptors"].append({
                "kind": "geometric_noun", "value": unsafe_value,
            })
            vocab = td / "vocab.json"
            _write_vocab(vocab, unsafe_vocab)
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 1
                and "d_one_descriptor_vocabulary.schema.json" in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"custom_descriptor: unsafe vocab allow-list value "
                f"{unsafe_value!r} refused at the vocabulary schema "
                f"layer; no plan file written",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- CD8. policy-aware in-image-text scan: the allow-list entry
    # "calligraphic_glyph" passes the schema regex (no forbidden token)
    # but the safety re-scan refuses it as in-image-text wording when
    # the request also declares text_policy='no_text'. Proves the
    # custom_descriptor value is held to the SAME safety scan the
    # prompt is held to, so an approved value that drifts into an
    # in-image-text shape under a no_text request still fails closed.
    # ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_cd_policy_aware"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern, no text",
                    "custom_descriptor": "calligraphy",
                    "text_policy": "no_text",
                    "subject_domain": "abstract_geometry",
                },
            ],
        })
        policy_aware_vocab = _canonical_vocab()
        policy_aware_vocab["custom_descriptors"].append({
            "kind": "composition_adjective", "value": "calligraphy",
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, policy_aware_vocab)
        rc, msg = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        ok = (
            rc == 1
            and CUSTOM_DESCRIPTOR_FIELD in msg
            and "in-image-text wording" in msg
            and "text_policy='no_text'" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "custom_descriptor: an allow-list value that hits the "
            "in-image-text safety scan under text_policy='no_text' is "
            "refused by the value re-scan; no plan file written",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- CD9. determinism: two independent runs with identical inputs
    # (including the custom_descriptor field) produce byte-identical
    # plan-file bytes. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        bodies: list[bytes] = []
        for ws_name in ("ws_a", "ws_b"):
            ws = td / ws_name
            _seed_workspace(ws, images=[
                {"id": "x", "local_path": "media/x.png", "source": "d_one_local"},
            ])
            spec = td / f"spec_{ws_name}.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "x",
                        "prompt": "abstract pattern, no text",
                        "rendering_style": "flat_vector",
                        "custom_descriptor": "hero_centered_motif",
                    },
                ],
            })
            vocab = td / f"vocab_{ws_name}.json"
            _write_vocab(vocab, _canonical_vocab())
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            assert rc == 0, (
                f"CD9 seed failed: rc={rc} msg={msg!r}"
            )
            bodies.append((ws / DEFAULT_PLAN_FILENAME).read_bytes())
        ok = bodies[0] == bodies[1]
        results.append(_expect(
            "custom_descriptor: two independent runs with identical "
            "custom_descriptor inputs produce byte-identical plan-file "
            "bytes",
            ok, f"len_a={len(bodies[0])}, len_b={len(bodies[1])}",
        ))

    # ---- CD10. validate-plan drift: a plan written with an approved
    # custom_descriptor is hand-mutated to a regex-shape-valid but
    # not-in-allow-list value; --validate-plan refuses it. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_cd_drift"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern, no text",
                    "custom_descriptor": "hero_centered_motif",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        rc, _ = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        assert rc == 0
        plan_path = ws / DEFAULT_PLAN_FILENAME
        plan_body = json.loads(plan_path.read_text())
        plan_body["requests"][0]["custom_descriptor"] = "drifted_value"
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(
            workspace=ws, plan=plan_path, descriptor_vocabulary=vocab,
        )
        ok = (
            rc == 1
            and "drifted_value" in msg
            and "drifted from the supplied" in msg
        )
        results.append(_expect(
            "custom_descriptor: validate-plan refuses a plan whose "
            "custom_descriptor value drifted from the supplied vocab's "
            "custom_descriptors[] allow-list",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- CD11. validate-plan: missing --descriptor-vocabulary refuses
    # a plan carrying custom_descriptor. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_cd_validate_no_vocab"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern, no text",
                    "custom_descriptor": "hero_centered_motif",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        rc, _ = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        assert rc == 0
        plan_path = ws / DEFAULT_PLAN_FILENAME
        rc, msg = validate_plan_file(workspace=ws, plan=plan_path)
        ok = (
            rc == 1
            and CUSTOM_DESCRIPTOR_FIELD in msg
            and "--descriptor-vocabulary" in msg
        )
        results.append(_expect(
            "custom_descriptor: validate-plan refuses a "
            "custom_descriptor-carrying plan when "
            "--descriptor-vocabulary was not supplied",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- CD12. plan-schema regex defense (post-write): a plan that
    # carries an unsafe-shape custom_descriptor (forbidden token at the
    # identifier boundary) is refused by the post-write _schema_validate
    # gate even when the in-memory allow-list would have certified the
    # value AND the safety re-scan does not catch the specific token
    # shape. ``public_motif`` is chosen because it (a) trips the
    # schema's bounded-``public`` deny clause and (b) does NOT match any
    # single-word or multi-word literal in the runtime safety scan
    # (every safety-scan ``public`` literal is multi-word — ``public
    # upload`` / ``public hosting`` / ``public url`` etc.). We
    # monkey-patch the loader to claim the unsafe value is approved, so
    # the only remaining defense is the post-write schema pattern lock.
    # Mirrors the existing post-write _schema_validate regression
    # (scenario 54). ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_cd_schema_post"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "media/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern, no text",
                    "custom_descriptor": "public_motif",
                },
            ],
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, _canonical_vocab())
        import sys as _sys_cd
        _mod_cd = _sys_cd.modules[__name__]
        original_loader_cd = _mod_cd._load_descriptor_vocabulary

        def fake_loader_cd(vocab_path: Path):
            allowed, allowed_custom, real_bytes, rc, msg = (
                original_loader_cd(vocab_path)
            )
            if rc != 0:
                return allowed, allowed_custom, real_bytes, rc, msg
            assert allowed_custom is not None
            # Pretend the unsafe-shape value is on the allow-list so the
            # runtime gate accepts the request. The post-write schema
            # pattern-lock must still refuse it.
            return (
                allowed,
                allowed_custom | {"public_motif"},
                real_bytes,
                rc,
                msg,
            )

        _mod_cd._load_descriptor_vocabulary = fake_loader_cd  # type: ignore[attr-defined]
        try:
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
        finally:
            _mod_cd._load_descriptor_vocabulary = original_loader_cd  # type: ignore[attr-defined]
        ok = (
            rc == 1
            and "d_one_adapter_plan.schema.json" in msg
            and "rolled back" in msg
            and not (ws / DEFAULT_PLAN_FILENAME).exists()
        )
        results.append(_expect(
            "custom_descriptor: an unsafe-shape value that bypasses the "
            "runtime allow-list (loader monkey-patched) is still "
            "refused by the post-write schema pattern lock; plan rolls "
            "back",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- CD13. separator-token safety gap (regression for the Codex
    # stop-time review): a vocab whose custom_descriptors[] approves
    # ``slide_title`` / ``body_copy`` / ``render_the_slide`` (each
    # regex-shape valid — neither the 9 bounded forbidden tokens nor
    # the 5 compound deny phrases in the schema match these — and a
    # naive substring safety scan would also miss them, because its
    # compound literals (``slide title`` / ``body copy`` / ``render
    # the slide``) are space-separated while the value uses `_`).
    # The separator-normalized safety re-scan in
    # _scan_custom_descriptor_safety must catch them BEFORE any plan
    # file is written. We probe every separator variant (`_`, `-`,
    # `.`, and a mixed run) to prove the normalization fires across
    # all stacking shapes, AND we probe both editable-text and
    # full-slide compounds so the regression covers more than one
    # deny family. The text_policy='no_text' variant additionally
    # probes the policy-aware in-image-text scan via the normalized
    # form (`include_text` → ``include text``). ----
    cd_separator_cases: tuple[tuple[str, str | None, str], ...] = (
        # Editable-text wording, universal — fires regardless of
        # text_policy. Every separator stacking maps to the same
        # space-separated literal.
        ("slide_title", None, "editable-text wording"),
        ("slide-title", None, "editable-text wording"),
        ("slide.title", None, "editable-text wording"),
        ("slide_-title", None, "editable-text wording"),
        ("body_copy", None, "editable-text wording"),
        ("body-copy", None, "editable-text wording"),
        ("body.copy", None, "editable-text wording"),
        # Full-slide / page / screenshot wording — fires regardless
        # of text_policy. The schema's 5-compound deny list does NOT
        # include "render the slide" (only `full[._\-]*slide` etc.),
        # so without the separator-normalized re-scan this would
        # slip past both the schema regex AND the substring scan.
        ("render_the_slide", None, "full-slide/page/screenshot wording"),
        ("render-the-slide", None, "full-slide/page/screenshot wording"),
        ("render.the.slide", None, "full-slide/page/screenshot wording"),
        # Policy-aware in-image-text wording. Only fires under
        # text_policy='no_text'. `include_text` → "include text".
        ("include_text", "no_text", "in-image-text wording"),
        ("include-text", "no_text", "in-image-text wording"),
        ("include.text", "no_text", "in-image-text wording"),
    )
    for unsafe_cd, policy, diagnostic_fragment in cd_separator_cases:
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_cd_sep_token"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            request_body: dict = {
                "id": "a",
                "prompt": "abstract pattern, no text",
                "custom_descriptor": unsafe_cd,
            }
            if policy is not None:
                request_body["text_policy"] = policy
                request_body["subject_domain"] = "abstract_geometry"
            _write_spec(spec, {"requests": [request_body]})
            # Add the unsafe-shape value to the vocab's allow-list so
            # the runtime allow-list check accepts it; the safety
            # re-scan is the ONLY remaining gate.
            sep_vocab = _canonical_vocab()
            sep_vocab["custom_descriptors"].append({
                "kind": "composition_adjective",
                "value": unsafe_cd,
            })
            vocab = td / "vocab.json"
            _write_vocab(vocab, sep_vocab)
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 1
                and CUSTOM_DESCRIPTOR_FIELD in msg
                and unsafe_cd in msg
                and diagnostic_fragment in msg
                and not (ws / DEFAULT_PLAN_FILENAME).exists()
            )
            results.append(_expect(
                f"custom_descriptor: separator-token value {unsafe_cd!r} "
                f"(policy={policy!r}) is refused by the separator-"
                f"normalized safety re-scan with the "
                f"{diagnostic_fragment!r} diagnostic; no plan file "
                f"written",
                ok, f"rc={rc}, msg={msg!r}",
            ))

    # ---- CD14. validate-plan path: separator-token drift on
    # ``custom_descriptor`` is refused. A plan written with an
    # approved-and-safe value is hand-mutated to a separator-token
    # value that the vocab also approves (so the allow-list check
    # passes), and the safety re-scan on the validate path must
    # close the gap symmetrically with the write path. ----
    with tempfile.TemporaryDirectory() as raw_td:
        td = Path(raw_td)
        ws = td / "ws_cd_sep_validate"
        _seed_workspace(ws, images=[
            {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
        ])
        spec = td / "spec.json"
        _write_spec(spec, {
            "requests": [
                {
                    "id": "a",
                    "prompt": "abstract pattern, no text",
                    "custom_descriptor": "hero_centered_motif",
                },
            ],
        })
        sep_vocab = _canonical_vocab()
        # The vocab also approves ``slide_title`` so the validate-
        # path allow-list check passes and the separator-normalized
        # safety re-scan is the only gate left.
        sep_vocab["custom_descriptors"].append({
            "kind": "composition_adjective",
            "value": "slide_title",
        })
        vocab = td / "vocab.json"
        _write_vocab(vocab, sep_vocab)
        rc, _ = done_image_adapter(
            workspace=ws, spec=spec, descriptor_vocabulary=vocab,
        )
        assert rc == 0, "CD14 seed failed"
        plan_path = ws / DEFAULT_PLAN_FILENAME
        plan_body = json.loads(plan_path.read_text())
        plan_body["requests"][0]["custom_descriptor"] = "slide_title"
        _overwrite_plan(plan_path, plan_body)
        rc, msg = validate_plan_file(
            workspace=ws, plan=plan_path, descriptor_vocabulary=vocab,
        )
        ok = (
            rc == 1
            and CUSTOM_DESCRIPTOR_FIELD in msg
            and "slide_title" in msg
            and "editable-text wording" in msg
        )
        results.append(_expect(
            "custom_descriptor: validate-plan refuses a "
            "separator-token value (``slide_title``) on the plan path "
            "via the separator-normalized safety re-scan, even when "
            "the vocab's custom_descriptors[] allow-list approves it",
            ok, f"rc={rc}, msg={msg!r}",
        ))

    # ---- TPI16. boundary-aware text-policy probe (regression for
    # the Codex stop-time review): normal image-generation wording
    # whose substring happens to overlap a deny-list literal must
    # PASS under text_policy='no_text'. The reported false positive
    # is ``"image text"`` matching the prefix of ``"image texture"``
    # — and the same prefix-substring class catches ``"with text"``
    # in ``"with textured paper"``. The boundary-aware match in
    # ``_literal_present_unnegated`` only fires on whole-word /
    # whole-phrase matches, so these prompts are accepted without
    # weakening the gate for real text-bearing requests (covered by
    # TPI7 / TPI13 / TPI14 / TPI15 / 11c / 12 / 12b above). ----
    for label, prompt_body in (
        ("'image texture' (was: 'image text' prefix false positive)",
         "abstract image texture with soft grain"),
        ("'with textured paper' (was: 'with text' prefix false positive)",
         "clean abstract shapes with textured paper background"),
        ("'context lighting' (normal scene-setup wording)",
         "soft context lighting on neutral background"),
        ("'texture pattern' (normal artwork wording)",
         "abstract design featuring simple texture pattern, even tones"),
    ):
        with tempfile.TemporaryDirectory() as raw_td:
            td = Path(raw_td)
            ws = td / "ws_tpi_boundary_aware"
            _seed_workspace(ws, images=[
                {"id": "a", "local_path": "a/a.png", "source": "d_one_local"},
            ])
            spec = td / "spec.json"
            _write_spec(spec, {
                "requests": [
                    {
                        "id": "a",
                        "prompt": prompt_body,
                        "text_policy": "no_text",
                        "subject_domain": "abstract_geometry",
                    },
                ],
            })
            vocab = td / "vocab.json"
            _write_vocab(vocab, _canonical_vocab())
            rc, msg = done_image_adapter(
                workspace=ws, spec=spec, descriptor_vocabulary=vocab,
            )
            ok = (
                rc == 0
                and (ws / DEFAULT_PLAN_FILENAME).is_file()
            )
            results.append(_expect(
                f"prompt-intent: text_policy='no_text' ACCEPTS "
                f"boundary-aware wording {label} — deny-list literal "
                f"only fires on whole-word / whole-phrase matches, "
                f"never on a prefix / suffix substring of a longer "
                f"word",
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
            "dry-run plan file. Optional --descriptor-vocabulary "
            "unlocks the seven clean-room taxonomy fields "
            "(rendering_style / palette_family / image_role / "
            "layout_pattern / modifier / text_policy / "
            "subject_domain) per request, validated "
            "against image_taxonomy.<dim>.allowed_values in the "
            "supplied d_one_descriptor_vocabulary JSON, AND the "
            "optional custom_descriptor escape-hatch field, validated "
            "against the vocab's custom_descriptors[].value allow-list "
            "with the full prompt safety scan re-applied on BOTH the "
            "raw value AND a separator-normalized form. Does NOT "
            "call D-One / Qoder / any public network / any "
            "image-generation model / any external service. Does "
            "NOT generate any image bytes. Does NOT mutate "
            "image_manifest.json. Does NOT produce render_models, "
            "svg_previews, or any .pptx. Does NOT change PPTX export "
            "behavior."
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
             "optionally 'intended_use', 'width_px', 'height_px', plus "
             "any subset of the taxonomy fields 'rendering_style', "
             "'palette_family', 'image_role', 'layout_pattern', "
             "'modifier', 'text_policy', 'subject_domain', AND "
             "optionally the 'custom_descriptor' escape-hatch field. "
             "Each present taxonomy field requires "
             "--descriptor-vocabulary AND must match a value declared "
             "in image_taxonomy.<dim>.allowed_values. The "
             "custom_descriptor field similarly requires "
             "--descriptor-vocabulary AND must match an explicit "
             "approved entry in the vocab's custom_descriptors[] "
             "allow-list AND re-pass the full prompt safety scan on "
             "BOTH the raw value AND a separator-normalized form.",
    )
    parser.add_argument(
        "--plan-out", type=Path, default=None,
        help="Where to write the deterministic plan file. Defaults to "
             "<workspace>/" + DEFAULT_PLAN_FILENAME + ". Must resolve "
             "inside --workspace and must not pre-exist.",
    )
    parser.add_argument(
        "--descriptor-vocabulary", type=Path, default=None,
        dest="descriptor_vocabulary",
        help="Optional. Path to a d_one_descriptor_vocabulary JSON file "
             "(see schemas/d_one_descriptor_vocabulary.schema.json). "
             "Required iff a --spec request (write path) or plan "
             "request (--validate-plan path) carries any of the seven "
             "taxonomy fields (rendering_style / palette_family / "
             "image_role / layout_pattern / modifier / text_policy / "
             "subject_domain) OR the optional custom_descriptor "
             "escape-hatch field. The file is re-validated every run, "
             "every present taxonomy value must be a member of "
             "the matching image_taxonomy.<dim>.allowed_values list, "
             "and every present custom_descriptor value must be a "
             "member of the vocab's custom_descriptors[].value "
             "allow-list AND re-pass the full prompt safety scan on "
             "BOTH the raw value AND a separator-normalized form. "
             "Refused if URI-shaped, symlinked, missing, or "
             "schema-invalid.",
    )
    parser.add_argument(
        "--validate-plan", action="store_true",
        help="Validate an EXISTING d_one_adapter_plan.json instead of "
             "writing a new one. Requires --workspace and --plan; "
             "additionally requires --descriptor-vocabulary whenever "
             "the plan carries one or more taxonomy fields OR the "
             "optional custom_descriptor escape-hatch field. The "
             "validator is NON-MUTATING: it applies the schema "
             "(d_one_adapter_plan.schema.json — covers list-rooted, "
             "unknown fields, missing required fields, mode != "
             "'dry_run', schema_version drift, manifest_source != "
             "'d_one_local', non-positive dimensions, and the "
             "lowercase-identifier + forbidden-token pattern lock on "
             "every taxonomy value AND on every custom_descriptor "
             "value), the workspace + image_manifest "
             "preflight (manifest schema-valid; no duplicate ids; "
             "every local_path safe), the optional descriptor "
             "vocabulary preflight (vocab schema-valid; image_taxonomy "
             "projected to per-dimension allowed_values sets; the "
             "vocab's custom_descriptors[].value list projected to the "
             "custom-descriptor allow-list set), and the "
             "full set of cross-checks the schema cannot express "
             "(request_count == len(requests); no duplicate request "
             "ids; every id resolves in the manifest with "
             "source='d_one_local'; manifest_local_path / "
             "manifest_source agree with the manifest entry "
             "byte-for-byte; every prompt re-passes the full URL / "
             "file-path / raw-source marker / 40-char source shingle "
             "/ credential / PII / full-slide wording / "
             "public-distribution wording deny list; every "
             "intended_use re-passes the full-slide wording subset of "
             "that list; AND every taxonomy value is in the matching "
             "image_taxonomy.<dim>.allowed_values list, AND every "
             "custom_descriptor value is in the vocab's "
             "custom_descriptors[].value allow-list AND re-passes the "
             "full prompt safety scan on BOTH the raw value AND a "
             "separator-normalized form — the same scope the write "
             "path applies).",
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
             "the optional --descriptor-vocabulary taxonomy gates "
             "(valid taxonomy, omitted taxonomy, unknown taxonomy "
             "value, fourteen unsafe-token taxonomy values refused "
             "across the original five V6 dimensions and the full "
             "9-token + 5-compound deny list, missing vocabulary, "
             "plan drift, vocab byte-identical pre/post a successful "
             "write, vocab post-condition rollback regression), the "
             "standalone --validate-plan path covering schema gates, "
             "cross-checks, and the non-mutating post-condition, AND "
             "the prompt-intent contract probes for the two extension "
             "dimensions text_policy + subject_domain (valid values "
             "round-trip, missing vocab refused, unknown values "
             "refused with allowed_values diagnostic, twenty-eight "
             "unsafe-token values refused across both new dimensions "
             "and the full 9-token + 5-compound deny list — every "
             "bounded token (public, upload, raw, customer, "
             "confidential, screenshot, credential, password, secret) "
             "AND every compound (full_slide, image_search, "
             "web_generation, page_generation, slide_generation) is "
             "exercised against both new dimensions, with no "
             "overclaim, and validate-plan drift). Exits non-zero if "
             "any scenario does not behave as expected. Mutually "
             "exclusive with --workspace / --spec / --plan-out / "
             "--plan / --validate-plan / --descriptor-vocabulary.",
    )
    args = parser.parse_args(argv)

    if args.self_test:
        if any(
            v is not None for v in (
                args.workspace, args.spec, args.plan_out, args.plan,
                args.descriptor_vocabulary,
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
                f"{', '.join(rejected)}; use --workspace, --plan, and "
                f"optionally --descriptor-vocabulary only",
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
            descriptor_vocabulary=args.descriptor_vocabulary,
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
        descriptor_vocabulary=args.descriptor_vocabulary,
    )
    if rc == 0:
        print(msg)
    else:
        print(msg, file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
