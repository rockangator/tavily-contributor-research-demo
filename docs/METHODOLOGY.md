# Contributor Lens methodology

## Purpose

Contributor Lens creates a reproducible public-evidence packet for human software-supply-chain review. It does not identify malicious actors, make employment decisions, or collect, infer, or export protected or legally defined status.

## Inputs

- Public GitHub repository metadata
- Named, non-bot contributors returned by the GitHub REST API
- Public GitHub profile fields
- Tavily search results anchored to a GitHub handle, a display name, and repository context
- Optional Tavily extraction from already accepted public sources

The prototype deliberately avoids emails and automated LinkedIn extraction.

Live reports preserve the GitHub facts, Tavily results, search queries, and request IDs when they are available. This repository does not include saved contributor profiles or report snapshots.

## Identity matching

Every Tavily result receives one of three labels:

- **Exact:** the source contains the GitHub handle and either the full name or repository context.
- **Probable:** the source contains the handle, the full name, or a name-plus-repository combination, but not the stronger pair of anchors.
- **Weak:** the source lacks enough identity anchors. The pipeline discards it.

Tavily's relevance score answers “how relevant is this page to the query?” It does not answer “is this the same person?” Contributor Lens keeps those concepts separate.

## Identity confidence (internal)

Identity confidence is a deterministic 0–100 measure:

- 35 points per exact match;
- 18 points per probable match;
- up to 15 additional points for independent source domains.

The score caps at 100. It describes the retained result set, not the human being. The app does not present or export this internal score as a contributor finding.

## Evidence coverage (internal)

Evidence coverage is a deterministic 0–100 measure built from:

- up to 25 points for populated public GitHub profile fields;
- up to 15 points for account maturity;
- up to 20 points for public activity context such as repositories and followers;
- up to 40 points for corroborating external evidence and source diversity.

These weights are a prototype rubric used for deterministic processing order. The app exports its methodology version, but it does not present or export this internal score as a contributor finding.

## Public-source outcomes

- **Exact match found:** at least one retained source contains the GitHub handle plus a full name or repository reference.
- **Probable match only:** sources were retained with fewer identity details and require manual confirmation.
- **No retained matches:** searches completed, but no result contained enough identity detail to retain. This is not a negative finding about the contributor.
- **Search incomplete:** at least one public-source search request failed, so the retained source set may be incomplete.

These outcomes describe the search process and retained sources, not a contributor's behavior, intent, trustworthiness, or eligibility.

## Internal processing order

The prototype retains its original priority calculation so live analyses complete and sort deterministically:

- High when evidence coverage is below 40 or identity confidence is below 30.
- Medium when evidence coverage is below 70 or identity confidence is below 65.
- Low when both internal measures meet the higher thresholds.

This priority is internal queueing logic. It is not a public-source outcome and is not included in the exported report.

## Legal and ethical boundary

The app does not collect, infer, or export citizenship, nationality, immigration status, U.S.-person eligibility, or another legal-status determination. A public location, employer, school, domain name, language, or name is not an acceptable substitute for an authorized legal-status verification.

If a workflow needs legal eligibility, it should use a separate authorized verification process with notice, consent, correction, access control, and human oversight. That process is outside this prototype and outside the exported contributor-evidence report.

## Validation proposal

1. Create a sponsor-approved benchmark of public identity links.
2. Include hard negatives and cases where the correct answer is “unknown.”
3. Measure precision, abstention rate, reviewer disagreement, latency, and API credits.
4. Compare the enriched result with a GitHub-only baseline.
5. Record every reviewer correction and re-run the benchmark after any rubric change.

## SBOM integration

Contributor Lens exports a versioned companion JSON report. The report can be referenced from an SPDX or CycloneDX workflow without pretending that a custom person-risk score is a standard SBOM property. It keeps repository identity, contributor evidence, method version, decision limits, and request trace together; it contains no legal-eligibility field or determination.
