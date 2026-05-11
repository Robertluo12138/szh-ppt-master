# Writing Guide

Rules for the natural-language content of slides (titles, key points, summaries, notes).

## Adaptive content shape

The Brief stage and the Plan stage decide what the deck looks like for that specific request — its length, section structure, and per-slide density all come from the brief, not from a fixed template. The writing rules below apply to whatever slides the planner chose; they do not assume a particular sequence (agenda → sections → KPIs → conclusion) and they do not assume a slide count. A 6-page strategy memo and a 25-page research report use the same writing rules but populate very different layouts.

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
