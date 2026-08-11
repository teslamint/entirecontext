# U5 Candidate Threshold Analysis

- Evaluated: 2026-07-20
- Pending archaeology candidates: 138 across 65 commits
- Confidence distribution: 0.3-0.4=125, 0.4-0.5=8, 0.5-0.6=1, 0.6-0.7=2, 0.7-0.8=2
- Extraction floor: `decisions.candidate_min_confidence = 0.35`
- Structural checks: short titles=0, short rationales=0, missing files=0, invalid source SHAs=0
- Exact-title overlaps with accepted decisions: 0
- Quality sample: deterministic 25/125 candidates from the 0.35 bucket (every fifth candidate ordered by source SHA/title); 25/25 described a durable technical, architecture, release, or process choice with a concrete rationale.

## Chosen threshold

`0.35`

This preserves the extraction pipeline's configured acceptance floor rather than adding a second arbitrary cutoff. The lowest bucket passed the structural checks and the stratified manual sample. Higher cutoffs would discard valid decisions based on the confidence formula rather than observed candidate quality; in particular, `0.40` would retain only 13 candidates and could not build the intended commit-linked corpus.
