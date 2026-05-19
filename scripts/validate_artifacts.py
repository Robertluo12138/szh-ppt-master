#!/usr/bin/env python3
"""
validate_artifacts.py
=====================

Stdlib-only structural validator for the five core pipeline artifacts:
deck_brief, deck_plan, design_system, slide_plan, image_manifest.

SCOPE TODAY
-----------
This is a scaffold-grade validator. It implements a **subset** of JSON Schema
draft-07 sufficient to validate the synthetic fixtures shipped with this repo:

  Supported keywords:
    type, required, enum, pattern, minLength, maxLength,
    minimum, maximum, exclusiveMinimum, exclusiveMaximum,
    minItems, maxItems, uniqueItems, properties,
    additionalProperties (boolean OR object schema),
    items (single subschema only; tuple-form 'items' is surfaced as an error).

  NOT supported (intentional, TODO):
    $ref, allOf / anyOf / oneOf / not, format, dependencies,
    if/then/else, patternProperties, contains, propertyNames.

If validation needs to grow beyond this subset, switch to a real
JSON-Schema library; do not silently extend this script.

USAGE
-----
    python3 scripts/validate_artifacts.py \\
        --schema schemas/deck_brief.schema.json \\
        path/to/artifact.json

Exit codes:
    0  artifact validated against the supported subset.
    1  artifact failed validation.
    2  invocation / file / parse error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SUPPORTED_KEYWORDS = {
    "type", "required", "enum", "pattern",
    "minLength", "maxLength",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minItems", "maxItems", "uniqueItems",
    "properties", "additionalProperties", "items",
    # Documentation-only keywords we silently allow:
    "$schema", "$id", "title", "description", "default", "examples",
}


def _type_matches(value: Any, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _validate(value: Any, schema: dict, path: str, errors: list[str]) -> None:
    if not isinstance(schema, dict):
        errors.append(f"{path}: schema node is not an object")
        return

    for key in schema:
        if key not in SUPPORTED_KEYWORDS:
            # Honest about scope: surface unsupported keywords once.
            errors.append(
                f"{path}: schema uses keyword '{key}' which this scaffold "
                f"validator does not implement (TODO: switch to a full JSON "
                f"Schema library)."
            )

    expected_type = schema.get("type")
    if expected_type is not None:
        if isinstance(expected_type, list):
            if not any(_type_matches(value, t) for t in expected_type):
                errors.append(f"{path}: expected type in {expected_type}, got {type(value).__name__}")
                return
        elif not _type_matches(value, expected_type):
            errors.append(f"{path}: expected type {expected_type!r}, got {type(value).__name__}")
            return

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} not in enum {schema['enum']!r}")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: string shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: string longer than maxLength {schema['maxLength']}")
        if "pattern" in schema:
            try:
                if re.search(schema["pattern"], value) is None:
                    errors.append(f"{path}: string {value!r} does not match pattern {schema['pattern']!r}")
            except re.error as exc:
                errors.append(f"{path}: invalid regex in schema pattern: {exc}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: value {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: value {value} > maximum {schema['maximum']}")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: value {value} <= exclusiveMinimum {schema['exclusiveMinimum']}")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: value {value} >= exclusiveMaximum {schema['exclusiveMaximum']}")

    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: array has {len(value)} items, minItems is {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: array has {len(value)} items, maxItems is {schema['maxItems']}")
        if schema.get("uniqueItems") is True:
            seen: dict[str, int] = {}
            for i, item in enumerate(value):
                try:
                    key = json.dumps(item, sort_keys=True)
                except (TypeError, ValueError):
                    errors.append(
                        f"{path}[{i}]: cannot canonicalize element for "
                        f"uniqueItems check"
                    )
                    continue
                if key in seen:
                    errors.append(
                        f"{path}[{i}]: duplicate element refused under "
                        f"uniqueItems (already at {path}[{seen[key]}]): "
                        f"{item!r}"
                    )
                else:
                    seen[key] = i
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for i, item in enumerate(value):
                _validate(item, item_schema, f"{path}[{i}]", errors)
        elif isinstance(item_schema, list):
            errors.append(
                f"{path}: schema uses tuple-form 'items' which this scaffold "
                f"validator does not implement (TODO)."
            )

    if isinstance(value, dict):
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}: missing required property '{req}'")
        properties = schema.get("properties", {})
        for prop, subschema in properties.items():
            if prop in value:
                _validate(value[prop], subschema, f"{path}.{prop}", errors)
        additional = schema.get("additionalProperties", True)
        if additional is False:
            for prop in value:
                if prop not in properties:
                    errors.append(f"{path}: additional property '{prop}' not allowed")
        elif isinstance(additional, dict):
            for prop, sub_value in value.items():
                if prop not in properties:
                    _validate(sub_value, additional, f"{path}.{prop}", errors)
        elif additional is not True:
            errors.append(
                f"{path}: 'additionalProperties' has unexpected type "
                f"{type(additional).__name__}; expected bool or object."
            )


def validate_artifact(artifact_path: Path, schema_path: Path) -> list[str]:
    try:
        schema = json.loads(schema_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"error: cannot read schema {schema_path}: {exc}")
    try:
        artifact = json.loads(artifact_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"error: cannot read artifact {artifact_path}: {exc}")
    errors: list[str] = []
    _validate(artifact, schema, "<root>", errors)
    return errors


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Stdlib-only structural validator (subset of JSON Schema draft-07).",
    )
    parser.add_argument("--schema", required=True, type=Path, help="Path to JSON schema file.")
    parser.add_argument("artifact", type=Path, help="Path to JSON artifact to validate.")
    args = parser.parse_args(argv)

    if not args.schema.is_file():
        print(f"error: schema not found: {args.schema}", file=sys.stderr)
        return 2
    if not args.artifact.is_file():
        print(f"error: artifact not found: {args.artifact}", file=sys.stderr)
        return 2

    errors = validate_artifact(args.artifact, args.schema)
    if errors:
        print(f"FAIL: {args.artifact} (against {args.schema})")
        for e in errors:
            print(f"  - {e}")
        print(
            "\nNote: this validator implements only a subset of JSON Schema. "
            "Errors about 'unsupported keyword' mean the schema uses features "
            "this scaffold validator does not check; treat such artifacts as "
            "UNVERIFIED, not as passing."
        )
        return 1

    print(f"OK (subset): {args.artifact} validates against {args.schema}")
    print(
        "Note: full JSON Schema validation is TODO. This check only covers "
        f"the keywords: {sorted(SUPPORTED_KEYWORDS - {'$schema','$id','title','description','default','examples'})}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
