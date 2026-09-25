---
module: blame-decisions
date: 2026-07-21
problem_type: performance_issue
component: sha-lookup-pipeline
severity: medium
symptoms:
  - "A 1,200-SHA lookup exceeded SQLite's expression-depth limit"
  - "Unrelated abbreviated links caused unnecessary Git subprocess calls"
  - "Case variants bypassed the resolution cache"
root_cause: a bound at the SQL expression layer did not bound downstream candidate and subprocess work
resolution_type: code_fix
applies_when:
  - "A lookup pipeline crosses database, in-process filtering, and subprocess boundaries"
  - "Equivalent identifiers can differ by case, abbreviation, or representation"
related_components:
  - sqlite-candidate-query
  - git-sha-resolution
tags:
  - complexity-budgets
  - database-queries
  - candidate-filtering
  - subprocess-bounds
  - cache-normalization
---

# Bound cost across lookup pipeline domains

## Problem

SHA means Secure Hash Algorithm. `ec blame --decisions` built one Structured Query Language (SQL) expression. The expression contained one exact match. It also contained one abbreviated-SHA prefix predicate for each blamed SHA. A file with 1,200 distinct SHAs exceeded SQLite's expression-depth limit of 1,000.

## Symptoms

- The 1,200-SHA lookup raised a SQLite expression-depth error.
- The first SQL-only fix still let 1,000 unrelated abbreviated links trigger 1,000 unnecessary `git rev-parse` calls.
- Sixty-four case variants of the same abbreviation bypassed the resolution cache and repeated equivalent work.

## What Didn't Work

Batching the original combined exact-plus-prefix query bounded expression depth. However, it repeated the non-indexable `decision_commits` scan for every batch. The initial split-query implementation fixed SQLite complexity but did not bound downstream Git work. It passed every abbreviated candidate to Git and cached resolutions by the unnormalized stored SHA.

## Solution

Set the exact batch size to 400. Split candidate retrieval into indexed exact `IN` queries. Scan abbreviated candidates once per blamed SHA width. For 1,200 SHA-1 values, this produces exactly three exact queries and one abbreviated query. This is the 3+1 SQL shape.

Before Git resolution, build the normalized set of blamed full SHAs and all valid prefixes. Discard unrelated candidates. Cache resolutions by lowercase SHA. Keep Git verification and canonical `(resolved_sha, decision_id)` deduplication authoritative.

## Why This Works

Each exact query stays below SQLite's expression and variable limits while preserving index use. The implementation scans the abbreviated corpus once, not once per exact batch. Prefix filtering prevents the 1,000 unrelated links from reaching Git. Lowercase cache identities collapse all 64 case variants to one resolution. Exact and abbreviated annotations retain the existing public behavior.

## Prevention

Define an end-to-end complexity budget for every multiplicative boundary in a lookup pipeline. Include database expression size, query count, candidate rows, external-process calls, and cache identities in the budget. Test the budget. Normalize cache keys at the same equivalence boundary used for matching.
