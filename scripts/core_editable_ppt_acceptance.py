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
  - ``scripts/mixed_image_asset_pipeline_smoke.py`` — the
    **mixed d_one_local + local_asset image-asset lane** through
    ``scripts/run_mock_image_pipeline.py --bundle``: builds a
    tempdir-only synthetic bundle with two cover slides (one
    referencing a d_one_local image, one referencing a local_asset
    image staged through ``<bundle>/source_assets/``), runs the
    runner end-to-end into a tempfile-owned workspace / output /
    report directory, and asserts the documented invariants —
    ``validate_pptx_contract.py --expected-slide-count 2`` returns
    rc=0 and every ``minimal_evidence.*`` gate emits ``[PASS]``;
    ``<report-dir>/inventory.json`` exists with ``ok=true`` /
    ``findings=[]`` / ``slide_count=2`` and AT LEAST TWO internal
    ``ppt/media/*`` PNG/JPG/JPEG entries; no external / file:// /
    data: / URI-scheme relationships anywhere in the produced
    PPTX; the caller-staged local_asset PNG sha256 appears in
    ``inventory.media_parts[].sha256``; the generated d_one_local
    media sha is byte-distinct from the local_asset sha (the two
    lanes carry independent bytes end-to-end); and the runner's
    audit sidecar ``<report-dir>/mock_d_one_adapter_plan.json``
    covers ONLY the d_one_local request id (the local_asset id
    MUST NOT leak into the sidecar — caller-staged bytes are not
    a generated artifact). Four fail-closed probes: missing
    ``source_assets/`` directory (runner refuses at its own
    boundary), wrong local_asset magic bytes
    (``_stage_local_assets`` refuses), local_asset id leaked into
    ``d_one_spec`` (``_check_d_one_spec_covers_generated``
    refuses), and a d_one_local / local_asset ``local_path``
    collision in the image_manifest_spec
    (``_check_local_path_collision`` refuses) — each exits
    non-zero AND leaves no ``.pptx`` at the nominated
    ``--output``. MOCK / STUB ONLY — no real D-One / MCP / Qoder /
    network.
  - ``scripts/source_image_asset_pipeline_smoke.py`` — the
    **explicit-input multi-asset pipeline integration** for the
    source-attached image-asset path: drives
    ``scripts/run_explicit_pipeline.py`` (Stage 1-10 + the
    Stage-5.5 materialize step) with TWO caller-staged synthetic
    local image assets — one PNG AND one JPEG — referenced from
    two distinct cover slides, and asserts the embedded
    ``ppt/media/*.png`` part's sha256 equals the PNG source
    asset's sha256 AND the embedded ``ppt/media/*.jpg``/``.jpeg``
    part's sha256 equals the JPEG source asset's sha256
    byte-for-byte (load-bearing per-asset byte-identity proof),
    the on-disk media-part sha set contains BOTH expected source
    shas (no per-format collapse) AND >= 2 distinct media parts
    exist (no per-part collapse), the produced deck still carries
    native editable text (``minimal_evidence.editable_text`` +
    ``not_all_image_slide`` + ``every_slide_has_native_shape``
    PASS), the read-only registry validator G1..G13 passes
    against the pipeline-produced workspace augmented with the
    two-entry source-attached registry, the inventory readback
    names BOTH source shas in ``media_parts[].sha256`` and lists
    >= 2 distinct slide indices across
    ``media_parts[].referencing_slides`` (the two assets land on
    distinct slides), and seventeen fail-closed probes fire —
    single-asset N1..N7 (registry sha mismatch G8 / source
    symlink leaf + parent G6 / unsafe registry path schema + G5
    + G11 for traversal + URI / image_manifest missing declared
    id G13 / unsupported media type G9 / public-upload wording
    G12), multi-asset M1..M7 (duplicate registry id G3 /
    duplicate destination_path smoke-owned multi-asset invariant
    / second registry id missing from image_manifest G13
    per-asset / JPEG bytes declared as ``image/png`` G9
    magic-byte / PNG bytes declared as ``image/jpeg`` G9
    magic-byte / ``.jpg`` declared as ``media_type=image/png`` G9
    extension-vs-media / one-asset sha mismatch G8 with the
    second valid), plus tampered-first-part (N8) and
    tampered-second-part-only (M8) PPTX media-bytes injections —
    the per-part byte-identity gate detects the drift on EITHER
    part. MOCK / STUB ONLY — no real D-One / MCP / Qoder /
    network.
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
  - ``scripts/text_policy_decision_smoke.py`` — proves the
    per-request ``text_policy`` decision invariant for the mockable
    D-One stub chain: a spec with three ``d_one_local`` requests
    carrying distinct ``text_policy`` values (``no_text`` /
    ``decorative_glyphs`` / ``caption_safe``) produces a
    ``d_one_adapter_plan.json`` whose per-request policy values
    survive byte-identical (round-tripped via
    ``done_image_adapter.validate_plan_file``), plus six fail-closed
    probes that catch a global-default regression (flatten-to-no_text
    detection, unknown-policy refusal, in-image-text wording under
    ``no_text`` refused, decorative-glyph wording under
    ``decorative_glyphs`` accepted, ``slide title`` under
    ``caption_safe`` refused by the universal editable-text rule,
    benign artwork under ``caption_safe`` accepted with the per-
    request policy preserved). MOCK / STUB ONLY — no real D-One.
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
  - ``scripts/mock_generated_image_provenance_smoke.py`` —
    tempdir-only generated-image provenance smoke. Drives the
    COMMITTED ``examples/synthetic_mock_image_trial/`` bundle
    through ``run_mock_image_pipeline.py --bundle`` and derives a
    per-request provenance object linking each generated-image
    request id from the bundle's ``d_one_spec.json`` to (a) the
    schema-allowed prompt/request metadata (``placement_role`` /
    ``text_policy`` / ``subject_domain`` / ``manifest_local_path``),
    (b) the runner-written
    ``<report-dir>/mock_d_one_adapter_plan.json`` sidecar
    metadata, (c) the on-disk generated mock asset under the
    tempdir-owned workspace (absolute path, ``byte_count``,
    ``sha256``, ``extension``, conservative ``media_type``), and
    (d) PPTX inventory evidence matching the workspace asset by
    sha256 byte-for-byte under ``ppt/media/*`` with no external
    relationship. Asserts at least two request rows, both
    placement_role values, at least two distinct text_policy
    values, per-id equality with the committed
    ``d_one_spec.json`` + the runner sidecar, asset files exist
    as regular non-symlink PNG/JPG/JPEG, byte_count > 0, sha256
    is lowercase 64 hex, no URI / traversal / absolute-output-
    escape on any path field, no credential / token / public-
    upload / public-hosting / raw-source / confidential / customer
    markers anywhere in the derived object, and no real-D-One /
    MCP / public-network / model-API / image-search / Qoder
    success claim. Eight fail-closed probes (P1..P8) cover
    missing row for a committed request id, mismatched
    text_policy vs the spec, collapsed text_policy coverage,
    tampered ``sha256`` / ``byte_count``, unsafe path / URI-
    shaped asset path, public-hosting wording, confidential /
    raw-source markers, and positive real-D-One success claims.
    The derived provenance object is emitted to stdout AND to a
    per-run tempfile that the tempdir cleanup removes on exit;
    nothing is written under the repo tree and ``REPO_ROOT/dist``
    is left untouched. MOCK / STUB ONLY — no real D-One.
  - ``scripts/generated_image_provenance_handoff_smoke.py`` —
    tempdir-only **generated-image provenance handoff smoke**.
    Reuses the helper functions (``_run_runner`` +
    ``_derive_provenance``) from
    ``mock_generated_image_provenance_smoke.py`` so the runtime
    row taxonomy is not re-implemented here. Drives its OWN
    mock-pipeline subprocess once per self-test — the pipeline
    therefore runs twice end-to-end inside this aggregate (once
    inside this handoff smoke, once inside the sibling mock-
    provenance smoke), with the shared helpers keeping the
    derivation code single-source-of-truth across both smokes.
    Then **sanitizes** the runtime TEMP-ONLY provenance object
    into a committed-safe
    handoff record (workspace-relative / placeholder paths only —
    no leading ``/``, no URI scheme, no ``..``) and validates the
    result through ``scripts/validate_generated_image_provenance.py
    --evidence <tempfile>`` so the same gate stack the committed
    template ships against is what the handoff smoke drives.
    Asserts the runtime runner returns rc=0, the runtime provenance
    carries at least one row with both ``placement_role`` values
    and at least two distinct ``text_policy`` values, the sanitizer
    refuses any input path that does not lexically anchor under
    the expected tempdir root (H1), refuses any committed-safe
    output that does not satisfy the path contract (H2), the
    validator subprocess returns rc=0 on the sanitized baseline
    (H5), and the committed tree under REPO_ROOT is byte-identical
    before and after the run. Eleven fail-closed probes (P1..P11)
    inject the documented regression classes — absolute path leak
    on ``asset.path``, URI / traversal on ``manifest_local_path``,
    credential / public-hosting / confidential wording in
    ``intended_use``, real-D-One success claim in ``notes.scope``,
    ``sidecar.schema_version`` drift, collapsed ``text_policy`` /
    ``placement_role`` coverage, ``asset.sha256`` vs
    ``pptx_media.sha256`` mismatch, and ``pptx_media.part`` outside
    ``ppt/media/`` — and assert the validator subprocess refuses
    each tampered clone with rc=1 plus the documented diagnostic
    substring while the canonical baseline still passes.
    Sanitized record is written to a per-run tempfile that the
    tempdir cleanup removes on exit; nothing is written under the
    repo tree. MOCK / STUB ONLY — no real D-One.
  - ``scripts/mixed_image_asset_provenance_handoff_smoke.py`` —
    tempdir-only **mixed image-asset provenance handoff smoke**.
    Reuses the synthetic mixed-lane bundle materializer +
    runner-args helper from
    ``scripts/mixed_image_asset_pipeline_smoke.py`` so the bundle
    taxonomy stays single-source-of-truth across both smokes.
    Drives its OWN mock-pipeline subprocess once per self-test
    (mixed lane = one d_one_local generated request + one
    local_asset caller-staged PNG, two cover slides); the d_one
    request carries a taxonomy-rich payload (placement_role =
    hero_page, non-default text_policy, subject_domain, AND an
    approved custom_descriptor) plus a paired
    descriptor_vocabulary.json the runner resolves bundle-
    relative, so per-row D-One intent flows spec -> sidecar ->
    sanitized evidence. Derives a runtime per-id provenance
    object (source_class, workspace asset sha256, PPTX-embedded
    media part sha256, per-row generated_intent on d_one_local
    rows only, audit sidecar request id set + per-id
    requests[] taxonomy projection, inventory media_parts
    ``(part, sha256)`` pairs) and
    **sanitizes** it into a committed-safe handoff record
    (workspace-relative / placeholder paths only — no leading
    ``/``, no URI scheme, no ``..``) matching
    ``schemas/mixed_image_asset_provenance.schema.json``.
    Validates the sanitized record through
    ``scripts/validate_mixed_image_asset_provenance.py --evidence
    <tempfile>`` so the same G1..G18 gate stack the committed
    template ships against (including the new G18
    generated_intent / sidecar.requests per-id parity gate) is
    what the handoff smoke drives. Asserts: pipeline rc=0;
    runtime provenance carries exactly two rows with source_class
    coverage equal to {d_one_local, local_asset} AND the
    d_one_local row's generated_intent equals the spec-supplied
    taxonomy byte-for-byte AND the local_asset row carries no
    generated_intent; sanitizer accepts the input AND emits a
    committed-safe record; validator subprocess returns rc=0 on
    the sanitized baseline; committed tree under REPO_ROOT is
    byte-identical before and after the run. Thirteen
    fail-closed probes (P1..P13): missing local_asset row,
    missing d_one_local row, local_asset id leaked into sidecar,
    d_one_local id missing from sidecar, ``asset.sha256`` vs
    ``pptx_media.sha256`` mismatch, absolute path leak on
    ``asset.path``, public-hosting wording (``public hosting
    enabled``) in ``intended_use``, credential token
    (``token=value``) in ``intended_use``, a real-D-One success
    claim (``Real D-One verified online``) in ``notes.scope``,
    AND four new G18-driving probes (d_one_local row stripped of
    generated_intent, local_asset row attached to
    generated_intent, generated_intent.text_policy flipped away
    from the sidecar.requests entry, d_one_local id dropped
    from sidecar.requests). Each probe asserts the validator
    subprocess returns rc=1 with the documented diagnostic
    substring while the canonical sanitized baseline still
    passes. Sanitized record is written to a per-run tempfile
    that the tempdir cleanup removes on exit; nothing is
    written under the repo tree. MOCK / STUB only — no real
    D-One.
  - ``scripts/validate_mock_image_bundle_trial_evidence.py`` —
    stdlib-only, read-only, tempdir-only validator for the JSON
    evidence record emitted by
    ``mock_image_bundle_trial_evidence``. Schema-validates against
    ``schemas/mock_image_bundle_trial_evidence.schema.json``,
    enforces the documented semantic gates (schema_version "1"
    locked, evidence_id locked, real_d_one_status carries
    UNVERIFIED + negated forbidden-service wording, summary.ok
    consistency with every sub-condition the goal pins, per-request
    well-formedness, placement_role coverage = {hero_page,
    local_region}), runs a string-safety scan (URL/URI, traversal,
    credential / token / API-key / sk- shapes, public-upload /
    public-sharing / public-hosting wording, confidential / customer
    / raw-source markers), refuses any positive real-D-One / MCP /
    public-network / model-API / image-search / Qoder success claim
    via the same word-boundary + 15-char-negation-window walker the
    emitter uses, and (when ``--require-files`` is requested)
    re-checks that evidence / PPTX / inventory / sidecar paths are
    regular non-symlink files sharing a common ancestor strictly
    under the system tempdir. The aggregator invokes
    ``--self-test`` only; the matrix covers the committed template
    PASS plus 47+ negative probes (missing required field, wrong
    schema_version / evidence_id, count mismatch, missing
    local_region, vocab flag false, role flag false, failed
    validator with summary.ok=True, real-D-One verified claim,
    sk-/api_key:/token: tokens, external URL, public hosting /
    upload / share, confidential / customer_id / raw-source
    markers, --require-files repo path / URI / traversal /
    missing / directory / symlinked evidence-PPTX-inventory-
    sidecar). Read-only / stdlib-only / tempdir-only — qualifies
    for inclusion in the aggregate.
  - ``scripts/image_placement_readback_smoke.py`` — tempdir-only
    **slide-level image placement / readback smoke**. Drives the
    existing mixed-lane mock pipeline once into a per-run tempdir
    and walks the produced PPTX + report ``inventory.json`` +
    workspace ``render_models`` + runner sidecar to assemble a
    placement-readback object proving each image lane lands on
    its intended slide AND inside the intended ``image_slot``
    bounds (px -> EMU via ``EMU_PER_PX = 9525``, 1-px tolerance).
    Asserts: slide_count == 2; both image lanes carry distinct
    ``ppt/media/*.{png,jpg,jpeg}`` parts; the d_one_local
    workspace sha256 lands on slide 1 exactly; the local_asset
    workspace sha256 lands on slide 2 exactly; each lane's
    intended slide's first ``<p:pic>`` blip embed
    ``r:embed="rIdN"`` resolves via the slide's
    ``_rels/slideN.xml.rels`` file to EXACTLY the lane's
    expected media part (closes the "rel declared but blip
    embeds something else" gap — a slide that merely OWNS a
    rel to a media part isn't proof the slide BODY shows it;
    the blip embed walk is); every media part is referenced
    by at least one slide (no orphan); every relationship is
    internal (no External / ``file://`` / ``data:`` /
    URI-scheme target); every slide carries native editable
    text + shape evidence (no full-slide raster fallback);
    the slide-1 + slide-2 ``<p:pic>`` xfrm ``<a:off>`` +
    ``<a:ext>`` match the matching render_model ``image_slot``
    bounds within 1-px EMU tolerance; the hero_page d_one_local
    request preserves spec-supplied ``placement_role`` /
    ``text_policy`` / ``subject_domain`` / ``custom_descriptor``
    byte-for-byte through the runner sidecar; the local_asset
    row carries NO ``generated_intent``; sidecar requests
    cover ONLY the d_one_local id. Direct fail-closed probes
    (no pipeline re-run): missing d_one_local media reference,
    missing local_asset media reference, swapped slide
    references (d_one on slide 2 / local_asset on slide 1),
    orphan embedded media, External relationship, ``file://``
    relationship, ``data:`` URI relationship, full-slide / all-
    image slide evidence, six positive real-D-One / MCP /
    public network / model API / image search / Qoder success
    claim variants, ``real_d_one_status="VERIFIED"`` drift,
    d_one_local ``generated_intent`` stripped, local_asset
    attached to ``generated_intent``, bounds drift on slide 1
    offset, bounds drift on slide 1 size, slide ``<p:pic>``
    blip embed cross-swap (each lane's
    ``intended_slide_blip_embed_part`` flipped to the OTHER
    lane's part while ``referencing_slides`` stays untouched —
    locks the new blip-embed gate as load-bearing, not
    incidentally redundant), slide ``<p:pic>`` blip embed
    unresolved, AND a defense-in-depth re-check that the
    baseline still passes the truth-checker after every probe
    ran (catches a probe that secretly mutated the shared
    baseline). MOCK / STUB ONLY — no real D-One.
  - ``scripts/core_image_to_editable_ppt_demo.py`` — milestone
    one-command demo with two modes that share one happy path:
    ``--out-dir DIR`` (operator mode — drives the same chain into
    a caller-supplied directory outside the repo and leaves
    inspectable artifacts on disk) AND ``--self-test`` (per-run
    tempdir + every fail-closed probe; the aggregator invokes
    this mode). Drives the existing mixed-lane mock pipeline
    once into the run root, runs the existing validators
    (``validate_pptx_contract`` + ``inspect_pptx_inventory`` +
    ``validate_mixed_image_asset_provenance``), and derives a
    concise demo summary JSON describing the product truth
    (slide_count, PPTX path, report dir, embedded media count,
    editable / native shape / no-external-relationship evidence,
    source_class coverage = {d_one_local, local_asset},
    generated_intent coverage on d_one_local, no
    generated_intent on local_asset, real_d_one_status =
    UNVERIFIED, validator rc values, AND a locked
    ``explicit_boundaries`` list naming the lanes this demo does
    NOT touch — real D-One, MCP, Qoder, model API, image search,
    public network, telemetry, raw prompt-or-report-to-PPT
    automation). Runs twelve direct fail-closed probes: the
    seven existing checks (repo-output refused without ever
    calling unlink() on a repo path; the
    ``_safe_unlink_under_tempdir`` helper no-ops on a REPO_ROOT
    path even with a tempdir root supplied; no stale summary
    after a failed run; zero embedded media refused; missing one
    image lane refused on either side; positive real-D-One / MCP
    / network / model / image-search / Qoder success claim
    refused) PLUS five operator-mode argument-gate probes that
    exercise ``_validate_out_dir_arg`` directly: OP1 URI-shaped
    ``--out-dir`` refused; OP2 symlink ``--out-dir`` refused; OP3
    symlink ancestor of ``--out-dir`` refused; OP4 ``--out-dir``
    under REPO_ROOT refused BEFORE any mkdir; OP5 pre-existing
    non-empty ``--out-dir`` refused with the pre-existing bytes
    byte-identical. The committed-tree snapshot is delegated to
    ``core_editable_ppt_acceptance._snapshot_committed_tree``;
    nothing is written under the repo tree in either mode.
    MOCK / STUB ONLY — no real D-One.
  - ``scripts/operator_local_images_to_editable_ppt.py`` —
    operator-facing **local-image intake** helper. The next operator
    step after ``core_image_to_editable_ppt_demo --out-dir`` for a
    reviewer who has their OWN folder of local PNG / JPG / JPEG bytes
    and wants to prove those bytes flow through the existing local
    image-asset pipeline into a native editable PPTX with inventory
    + provenance evidence. The aggregate invokes ``--self-test``, which
    drives the same happy path inside a per-run tempdir on tiny
    generated PNG + JPEG fixtures (no committed image bytes) and
    exercises every IG / OUT / MAN argument gate (URI / symlink /
    symlink-ancestor / non-directory / empty / unsupported-extension /
    stem-pattern / stem-collision / magic-byte / over-cap / inside-
    REPO_ROOT / non-empty pre-existing OUT, plus the manifest-mode
    structural and safe-string refusals — URL / URI / path separator
    / credential / public-upload / confidential / D-One success-claim
    wording / duplicate filename / orphan filename / missing
    filename). Reuses ``scripts/run_explicit_pipeline.py`` (Stage 1-10
    + the Stage-5.5 ``materialize_image_assets`` step the
    ``--assets-dir`` flag activates) and the existing validator stack
    (``validate_source_image_assets`` G1..G13,
    ``validate_pptx_contract --expected-slide-count N``,
    ``inspect_pptx_inventory``) — no new schema, no new validator, no
    new runtime contract. LOCAL-ONLY — no real D-One.
  - ``scripts/operator_local_images_trial.py`` — operator-facing
    **one-command trial** for the local image-to-editable-PPT lane.
    The quickest first practical command a new operator can run: it
    drives ``scripts/operator_local_images_to_editable_ppt.py`` twice
    — once with ``--plan-out`` to write a reviewer-approved plan,
    once in normal operator mode under ``--approved-plan`` — into a
    caller-supplied directory outside the repo, leaves the produced
    review package on disk for inspection, and writes a concise
    top-level README naming the first files to open. The aggregate
    invokes ``--self-test``, which drives the same happy path inside
    a per-run tempdir on tiny generated PNG + JPEG fixtures (no
    committed image bytes) and exercises the OP1..OP5 ``--out-dir``
    argument gates (URI / symlink / symlink-ancestor / inside-
    REPO_ROOT / non-empty pre-existing) plus a no-external-service-
    claims scan over the trial's stdout, trial README, helper-written
    review-package README, and helper-written ``summary.json``.
    Reuses the helper's own ``_validate_out_dir_arg`` /
    ``_write_synthetic_images`` / ``_EXPLICIT_BOUNDARIES`` — no new
    schema, no new validator, no new runtime contract. LOCAL-ONLY —
    no real D-One.
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
    SCRIPTS_DIR / "source_image_asset_pipeline_smoke.py",
    SCRIPTS_DIR / "mixed_image_asset_pipeline_smoke.py",
    SCRIPTS_DIR / "image_asset_acceptance_smoke.py",
    SCRIPTS_DIR / "image_asset_trial_evidence.py",
    SCRIPTS_DIR / "image_asset_negative_probes_smoke.py",
    SCRIPTS_DIR / "image_taxonomy_acceptance_smoke.py",
    SCRIPTS_DIR / "text_policy_decision_smoke.py",
    SCRIPTS_DIR / "run_mock_image_pipeline.py",
    SCRIPTS_DIR / "mock_image_bundle_acceptance_smoke.py",
    SCRIPTS_DIR / "mock_image_bundle_trial_evidence.py",
    SCRIPTS_DIR / "mock_generated_image_provenance_smoke.py",
    SCRIPTS_DIR / "generated_image_provenance_handoff_smoke.py",
    SCRIPTS_DIR / "mixed_image_asset_provenance_handoff_smoke.py",
    SCRIPTS_DIR / "core_image_to_editable_ppt_demo.py",
    SCRIPTS_DIR / "operator_local_images_to_editable_ppt.py",
    SCRIPTS_DIR / "operator_local_images_trial.py",
    SCRIPTS_DIR / "image_placement_readback_smoke.py",
    SCRIPTS_DIR / "validate_mock_image_bundle_trial_evidence.py",
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
            "source_image_asset_pipeline_smoke + "
            "mixed_image_asset_pipeline_smoke + "
            "image_asset_acceptance_smoke + image_asset_trial_evidence "
            "+ image_asset_negative_probes_smoke + "
            "image_taxonomy_acceptance_smoke + "
            "text_policy_decision_smoke + run_mock_image_pipeline "
            "+ mock_image_bundle_acceptance_smoke + "
            "mock_image_bundle_trial_evidence + "
            "mock_generated_image_provenance_smoke + "
            "generated_image_provenance_handoff_smoke + "
            "mixed_image_asset_provenance_handoff_smoke + "
            "core_image_to_editable_ppt_demo + "
            "operator_local_images_to_editable_ppt + "
            "operator_local_images_trial + "
            "image_placement_readback_smoke + "
            "validate_mock_image_bundle_trial_evidence + "
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
