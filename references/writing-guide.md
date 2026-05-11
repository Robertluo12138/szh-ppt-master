# Writing Guide

Rules for the natural-language content of slides (titles, key points, summaries, notes).

## Source fidelity

- Slide content must trace back to the source bundle. The skill must not fabricate statistics, dates, names, or quotations.
- If a desired slot has no source coverage, leave it empty or mark it as `unverified` rather than inventing content.
- Numbers must match the source. Rounding rules are **TODO**.

## Style

- Titles: short, declarative, no trailing punctuation. Target ≤ 8 words.
- Key points: one idea per bullet. Target ≤ 14 words.
- Body paragraphs (when used): target ≤ 40 words.
- Avoid filler ("In this slide, we will discuss…"). Lead with the point.

These targets are guidance; final thresholds are **TODO**.

## Voice

- Neutral, business-professional by default. Tone may be overridden in `deck_brief.json` (`tone` field). Allowed tones are **TODO**.
- No first-person plural ("we") in slide copy unless the brief specifies otherwise.

## What slides must not contain

- Real customer names, account IDs, or sensitive figures unless the source confirms they are safe to display.
- Speculation framed as fact.
- Marketing language unsupported by the source.

## Notes (presenter notes)

- Notes may expand on a slide but must still trace to the source. Notes are not a place to invent supporting data.

## TODOs

- Decide rounding rules for numbers in titles vs. body.
- Enumerate allowed tones.
- Decide whether the skill ever generates speaker notes by default, or only when asked.
