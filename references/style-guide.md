# Style Guide

Defines design tokens and visual conventions consumed by `design_system.json` and downstream SVG / PPTX work.

## Tokens (categories)

- **Palette** — `primary`, `secondary`, `accent`, `background`, `text`, optional extras. All values are 6-digit hex.
- **Typography** — `heading` and `body`, each with `font_family` and `size_pt`. Additional roles (e.g. `caption`, `mono`) may be added but must be enumerated in the schema first.
- **Grid** — slide canvas in pixels (`width_px`, `height_px`) and edge margin (`margin_px`).

## Conventions

- One palette per deck. Per-slide overrides are not supported in the scaffold.
- Body text size must remain readable at the deck's final aspect ratio. Threshold is **TODO** (likely ≥ 12 pt in PPTX terms).
- Heading and body must use the same family family unless explicitly varied via theme override.
- Color contrast minimum is **TODO** (likely WCAG AA for body text against background).

## Fonts

- Fonts must be embeddable or available on the target platform. Web-only fonts are not allowed until a fallback chain is defined.
- The fallback chain for a font is **TODO**; until defined, font choices in themes must be widely available (e.g. system fonts).

## Density

- Slides have a maximum information density; see `svg-design-rules.md` for the on-slide rule, and `writing-guide.md` for the copy rule.

## TODOs

- Confirm minimum readable body size (pt).
- Confirm minimum contrast ratio.
- Define fallback font chains.
- Decide whether dark-mode themes are in scope.
