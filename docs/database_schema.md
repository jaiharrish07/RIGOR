# RIGOR — Database Schema

**Version:** 1.0
**Last updated:** August 26, 2026
**Owner:** Backend team
**Status:** Locked for Week 1 implementation

---

## Overview

RIGOR stores every uploaded research paper across **five tables**. Each table represents a distinct kind of information, and together they capture a paper's entire lifecycle — from upload, through parsing, to audit results.

| Table       | What it stores                                     | Rows per paper (typical) |
| ----------- | -------------------------------------------------- | ------------------------ |
| `papers`    | The uploaded PDF's identity and bibliographic data | 1                        |
| `sections`  | The paper's body text, chunked by section          | 10–15                    |
| `references`| The paper's bibliography (works it cites)          | 30–80                    |
| `audits`    | A single audit run over a paper                    | 0 to many                |
| `findings`  | One verdict per checklist item within an audit     | ~25 per audit            |

Total: **78 fields** across the 5 tables (excluding relationships) — 23 + 13 + 13 + 12 + 17.

## Design principles

1. **Metadata lives on Paper.** Body text lives on Section. Citations live on Reference. LLM-extracted knowledge lives on Finding. Never mix these categories.
2. **Findings are keyed by `item_id`**, not stored as fixed columns. New checklist items require no schema changes.
3. **Cascading deletes** — deleting a Paper deletes all its Sections, References, Audits, and (transitively) Findings.
4. **JSONB for bundled data** (authors, keywords) — flexible structure without a separate join table.
5. **All primary keys are UUIDs**, not auto-increment integers, to allow safe cross-environment merging.
6. **Timestamps are timezone-aware** (`DateTime with timezone`) everywhere.
7. **Status columns are strings, not enums**, so adding new statuses doesn't require migration.

---

## 1. `papers` — uploaded PDFs

**Purpose:** Store one row per uploaded PDF. Contains file identity (hash, filename), bibliographic metadata (title, authors, DOI, year), parsing state, and retraction status. This is the anchor row every other table connects to.

**Populated in three phases:**
1. **At upload:** `id`, `sha256_hash`, `filename`, `file_size_bytes`, `page_count`, `status="parsing"`, `uploaded_at`.
2. **After GROBID:** `title`, `authors`, `abstract`, `keywords`, `doi`, `publication_year`, `venue`, `journal_ref`, `raw_tei_xml`, `status="parsed"`, `parsed_at`.
3. **At retraction check (Week 4):** `retraction_status`, `retraction_source_url`, `retraction_reason`, `retraction_checked_at`.

### Fields

| Field                    | Type            | Nullable | Purpose |
| ------------------------ | --------------- | -------- | ------- |
| `id`                     | UUID (PK)       | No       | Unique identifier for the paper; referenced by all other tables. |
| `sha256_hash`            | String(64), unique, indexed | No | PDF fingerprint. Enables duplicate-upload detection and integrity checks. |
| `filename`               | String(500)     | No       | Original filename user uploaded. For frontend display only. |
| `file_size_bytes`        | BigInteger      | No       | Raw byte count. Used for UI display and to enforce upload size limits. |
| `page_count`             | Integer         | Yes      | Number of pages. Validates LLM location claims and flags workshop-length papers. |
| `title`                  | Text            | Yes      | Paper title from PDF header. Nullable because scanned PDFs may lack extractable titles. |
| `authors`                | JSONB           | No       | List of `{full_name, affiliation, email, orcid}` objects. Bundled together because they're always read as a unit. |
| `abstract`               | Text            | Yes      | Full abstract text. Fed to the LLM for topic classification. |
| `keywords`               | JSONB           | No       | List of keyword strings. Used for search and LLM prompt context. |
| `doi`                    | String(255), indexed | Yes | Digital Object Identifier. Indexed because retraction lookups query by DOI. |
| `publication_year`       | Integer         | Yes      | Year published. Powers age-based audit heuristics (e.g. flag outdated methodology). |
| `venue`                  | String(500)     | Yes      | Conference or journal name (e.g. "NeurIPS"). Shown on paper cards. |
| `journal_ref`            | String(1000)    | Yes      | Full citation string. Used for "cite this paper" button. |
| `status`                 | String(50), indexed | No | One of: `uploaded`, `parsing`, `parsed`, `parsing_failed`, `unsupported_pdf`, `corrupted`. Indexed because the dashboard filters on it. |
| `error_message`          | Text            | Yes      | Human-readable failure reason when `status` is not `parsed`. |
| `raw_tei_xml`            | Text            | Yes      | Full GROBID XML output (~50–200 KB). Stored so we can re-parse without re-running GROBID. Never returned in API responses. |
| `retraction_status`      | String(50)      | No       | One of: `unchecked`, `none`, `retracted`, `corrected`, `expression_of_concern`, `unavailable`. RIGOR's critical red-flag signal. |
| `retraction_source_url`  | String(500)     | Yes      | URL of the retraction notice (Retraction Watch or journal). |
| `retraction_reason`      | Text            | Yes      | Description of why the paper was retracted. |
| `retraction_checked_at`  | DateTime        | Yes      | Last retraction check timestamp. Rechecked periodically because papers can be retracted years after publication. |
| `uploaded_at`            | DateTime        | No       | When the file was received. Never changes after creation. |
| `parsed_at`              | DateTime        | Yes      | When parsing finished. Null if parsing failed or is still running. |
| `updated_at`             | DateTime, auto-updated | No | Row's last modification. Used for cache invalidation. |

### How Paper helps the audit workflow

Every audit begins by loading the Paper row. From it, the audit engine navigates to `paper.sections` to get body text for the LLM, `paper.references` to run retraction cascade checks, and creates new `audits` and `findings` rows pointing back to `paper.id`. An audit cannot start unless `paper.status = "parsed"` — otherwise there is no data to audit against.

---

## 2. `sections` — paper body text, chunked

**Purpose:** Store the actual paragraph text of each section of the paper. This is the raw material the LLM reads during auditing. GROBID chops the paper into sections; each becomes one row.

**Populated at upload** (immediately after GROBID returns), inserted in a single batch. Not modified afterward — sections are immutable once parsed. If a paper is re-parsed, old sections are deleted and new ones inserted.

### Fields

| Field          | Type                  | Nullable | Purpose |
| -------------- | --------------------- | -------- | ------- |
| `id`           | UUID (PK)             | No       | Unique section identifier. Findings link back via `section_id`. |
| `paper_id`     | UUID (FK → papers), indexed, CASCADE | No | Which paper this section belongs to. |
| `heading`      | String(500)           | No       | Section title as printed (e.g. "3.2 Training Details"). Displayed in frontend paper viewer. |
| `body_text`    | Text                  | No       | The actual paragraphs — every word of the section, merged. This is what the LLM reads. |
| `section_type` | String(50), indexed   | Yes      | Classified type: `abstract`, `introduction`, `related_work`, `methods`, `results`, `discussion`, `conclusion`, `references`, `appendix`, `other`. Indexed because LLM queries filter on it. |
| `level`        | Integer               | No       | Header depth (1 = main section, 2 = subsection, 3 = sub-subsection). Enables outline rendering. |
| `order_index`  | Integer               | No       | Position of section in the paper (0-indexed). Used to sort sections into reading order. |
| `is_appendix`  | Boolean               | No       | True for appendix content. Important because appendices often hold critical reproducibility details the LLM should search first. |
| `page_start`   | Integer               | Yes      | First page of this section. Used to validate LLM location claims. |
| `page_end`     | Integer               | Yes      | Last page of this section. |
| `word_count`   | Integer               | No       | Word count of `body_text`. Used for LLM token-budget planning. |
| `char_count`   | Integer               | No       | Character count. Cheaper than word_count for size checks. |
| `created_at`   | DateTime              | No       | When the section was inserted. Audit trail. |

### How Section helps the audit workflow

When the audit engine needs to check something like "did the paper report the learning rate?", it queries the Section table filtered by `paper_id` and `section_type="methods"`, then sends that section's `body_text` to the LLM. The grounding verifier later searches all sections' body text to confirm evidence quotes actually appear in the paper. Findings then link back to the specific section via `section_id` so the frontend can highlight the relevant text.

Sections also power the frontend paper viewer — a table of contents ordered by `order_index` lets users jump to any part of the paper.

---

## 3. `references` — bibliography entries

**Purpose:** Store each work the paper cites. Populated by GROBID. Used later for retraction cascade checks, citation quality metrics, and LLM cross-referencing.

**Populated at upload** (one row per bibliography entry). Later updated by Week 4's retraction lookup, which fills `verified_via_crossref`, `is_retracted`, and `crossref_checked_at`.

**Important:** A Reference row is NOT the same as a Paper row. If the paper cites Bahdanau 2015, we have a Reference row containing what Attention's authors *wrote about* Bahdanau — not the Bahdanau PDF itself.

### Fields

| Field                    | Type                    | Nullable | Purpose |
| ------------------------ | ----------------------- | -------- | ------- |
| `id`                     | UUID (PK)               | No       | Unique reference identifier. |
| `paper_id`               | UUID (FK → papers), indexed, CASCADE | No | Which paper contains this bibliography entry. |
| `order_index`            | Integer                 | No       | Citation number in the paper ([1], [2], [3]...). Used to sort references in bibliography order. |
| `raw_text`               | Text                    | No       | The full reference string as GROBID sees it. Preserved for display and for cases where structured parsing fails. |
| `title`                  | Text                    | Yes      | Extracted title of the cited work. |
| `authors`                | JSONB                   | No       | List of `{full_name}` objects. Simpler than Paper.authors because cited-work affiliations are usually unknown. |
| `year`                   | Integer                 | Yes      | Publication year of the cited work. |
| `venue`                  | String(500)             | Yes      | Journal or conference of the cited work. |
| `doi`                    | String(255), indexed    | Yes      | DOI of the cited work. Indexed because Week 4's retraction cascade query filters on it. |
| `verified_via_crossref`  | Boolean                 | No       | True if we looked this reference up in Crossref and confirmed it exists. False may indicate a fabricated reference. |
| `is_retracted`           | Boolean                 | No       | True if the cited work itself has been retracted. **RIGOR's biggest red flag.** |
| `crossref_checked_at`    | DateTime                | Yes      | Last verification timestamp. Rechecked periodically. |
| `created_at`             | DateTime                | No       | When the reference was extracted. |

### How Reference helps the audit workflow

Two distinct roles:

**Role 1 — Retraction cascade check (Week 4):** The audit iterates every reference for the paper, calls the Retraction Watch API on each DOI, and updates `verified_via_crossref` and `is_retracted`. If any references are retracted, a Finding is created flagging it.

**Role 2 — Citation quality metrics (Week 5):** The audit computes statistics — "12% of citations are >20 years old", "3 references have no DOI (possibly fabricated)" — and creates Findings for each. Each metric becomes a checklist item verdict.

---

## 4. `audits` — audit runs

**Purpose:** Record that an audit happened. Stores metadata about the run (which LLM, which checklist version, when, overall score) — but not the individual verdicts. Those live in the Finding table.

**Populated when audit starts:** `id`, `paper_id`, `status="running"`, `checklist_version`, `llm_provider`, `llm_model`, `created_at`, `started_at`.

**Updated during audit:** `progress` (frontend polls this for progress bar).

**Updated when audit finishes:** `status="completed"` (or `"failed"`), `completed_at`, `overall_score`, and `error_message` if failed.

### Fields

| Field              | Type                    | Nullable | Purpose |
| ------------------ | ----------------------- | -------- | ------- |
| `id`               | UUID (PK)               | No       | Unique audit identifier. Findings link back via `audit_id`. |
| `paper_id`         | UUID (FK → papers), indexed, CASCADE | No | Which paper was audited. |
| `status`           | String(50), indexed     | No       | One of: `pending`, `running`, `completed`, `failed`. Indexed for dashboard filtering. |
| `progress`         | Float                   | No       | Value 0.0 to 1.0. Frontend polls to show a progress bar. |
| `error_message`    | Text                    | Yes      | Populated when `status = failed`. |
| `checklist_version`| String(20)              | No       | Checklist.yaml version this audit ran against. Critical for reproducibility — if the checklist evolves, findings remain interpretable. |
| `llm_provider`     | String(50)              | No       | `groq` or `openrouter`. |
| `llm_model`        | String(100)             | No       | Specific model name (e.g. `llama-3.3-70b-versatile`). Enables comparing findings across model versions. |
| `overall_score`    | Float                   | Yes      | Aggregate 0.0–1.0 score computed from findings. Denormalized (could be recomputed) but stored so dashboard sorting is fast. |
| `created_at`       | DateTime                | No       | When audit was requested. |
| `started_at`       | DateTime                | Yes      | When execution actually began. Differs from `created_at` when audits are queued (Week 3+). |
| `completed_at`     | DateTime                | Yes      | When audit finished. Null if still running or failed. |

### How Audit helps the audit workflow

The Audit row is the coordinator — created before any LLM work happens and tying together every Finding produced. Re-auditing a paper creates a new Audit row; old audits are preserved, giving RIGOR a full history of how findings changed over time or across LLM upgrades. The frontend dashboard uses `overall_score` (denormalized on this row) to sort papers instantly without re-aggregating findings on every request.

---

## 5. `findings` — checklist item verdicts

**Purpose:** Store one row per checklist item that was checked during an audit. This is where the LLM's actual answers live. Each row is one verdict: "for item X, the paper says Y with evidence Z at location W, verified: true/false".

**Populated during audit:** After each LLM call returns, one Finding row per item is inserted. A typical audit produces ~25 Findings.

**Updated during verification:** The grounding verifier sets `verified`, `verification_reason`, `fuzzy_match_score`, `verified_at`, and refines `page_number` + `section_id`.

### Fields

| Field                 | Type                    | Nullable | Purpose |
| --------------------- | ----------------------- | -------- | ------- |
| `id`                  | UUID (PK)               | No       | Unique finding identifier. |
| `audit_id`            | UUID (FK → audits), indexed, CASCADE | No | Which audit produced this finding. |
| `item_id`             | String(100), indexed    | No       | Checklist item identifier (e.g. `hyperparameter.learning_rate`, `data.dataset_name`). Indexed for cross-audit queries. |
| `category`            | String(50), indexed     | No       | Category name (e.g. `hyperparameter`, `data`, `code`). Derived from `item_id` but stored explicitly for fast filtering. |
| `present`             | String(20)              | No       | Core verdict: `true`, `false`, or `cannot_determine`. |
| `value`               | Text                    | Yes      | The actual extracted value (e.g. "3e-4" for learning rate, "Adam" for optimizer). Null when `present` is not `true`. |
| `confidence`          | Float                   | Yes      | LLM's self-reported confidence (0.0–1.0). Used to flag low-confidence findings for human review. |
| `notes`               | Text                    | Yes      | LLM's free-text explanation (e.g. "Found in Table 3 caption"). |
| `evidence_quote`      | Text                    | Yes      | Verbatim quote from the paper supporting the finding. What the grounding verifier checks against Section.body_text. |
| `page_number`         | Integer                 | Yes      | Page where the evidence appears. Populated by the verifier. |
| `section_id`          | UUID (FK → sections), SET NULL | Yes | Section containing the evidence. SET NULL on delete so findings survive section re-parsing. |
| `location_hint`       | String(500)             | Yes      | LLM's original raw location claim before the verifier resolved it. Kept for debugging. |
| `verified`            | Boolean, indexed        | No       | True if the grounding verifier confirmed the quote is in the paper. Indexed because "show me unverified findings" is a common quality-check query. |
| `verification_reason` | String(100)             | Yes      | How verified: `exact_match`, `fuzzy_match`, `quote_not_found_in_paper`, or `no_quote_provided`. |
| `fuzzy_match_score`   | Float                   | Yes      | If fuzzy-matched, the similarity score (0.0–1.0). Below 0.90 is suspicious. |
| `verified_at`         | DateTime                | Yes      | When verification ran. |
| `created_at`          | DateTime                | No       | When the finding was inserted. |

### How Finding helps the audit workflow

Findings are the output — the point of the whole system. Everything else exists to produce good Findings. The audit engine loops over checklist categories, calls the LLM for each, runs the grounding verifier on returned quotes, and inserts a Finding per item. When users view an audit result, they're looking at Findings grouped by category, sorted with unverified ones surfaced for scrutiny.

Every claim RIGOR makes about a paper — "the learning rate is reported", "the random seed is omitted", "3 retracted works are cited" — is a Finding row.

---

## Relationships & cascade behavior

Foreign keys wire the five tables together and control what happens when rows are deleted.

| From            | To         | On delete | Effect |
| --------------- | ---------- | --------- | ------ |
| `sections.paper_id`    | `papers.id` | CASCADE  | Deleting a paper deletes all its sections. |
| `references.paper_id`  | `papers.id` | CASCADE  | Deleting a paper deletes all its references. |
| `audits.paper_id`      | `papers.id` | CASCADE  | Deleting a paper deletes all its audits (which cascade to findings). |
| `findings.audit_id`    | `audits.id` | CASCADE  | Deleting an audit deletes all its findings. |
| `findings.section_id`  | `sections.id` | SET NULL | Deleting or re-parsing a section leaves the finding intact but unlinked. |

**Net effect:** Deleting a Paper deletes everything about it — sections, references, audits, and findings. No orphaned rows are left behind.

---

## Indexes

Databases without indexes on foreign keys and filter columns become unusably slow at moderate row counts. These 14 indexes are required:

| Table       | Column            | Reason |
| ----------- | ----------------- | ------ |
| `papers`    | `sha256_hash`     | Duplicate-upload detection (unique constraint) |
| `papers`    | `doi`             | Retraction lookup |
| `papers`    | `status`          | Dashboard status filtering |
| `papers`    | `uploaded_at`     | Default dashboard sort |
| `sections`  | `paper_id`        | Fetch all sections for a paper |
| `sections`  | `section_type`    | LLM section targeting (e.g. "give me methods") |
| `references`| `paper_id`        | Fetch all references for a paper |
| `references`| `doi`             | Retraction cascade check |
| `audits`    | `paper_id`        | Fetch all audits for a paper |
| `audits`    | `status`          | Dashboard status filtering |
| `findings`  | `audit_id`        | Fetch all findings for an audit |
| `findings`  | `item_id`         | Cross-audit item queries |
| `findings`  | `category`        | Category filtering in dashboard |
| `findings`  | `verified`        | Quality-control queries |

---

## What is deliberately not in v1.0

These entities were considered and consciously deferred. Each can be added later as a new table without disturbing the existing schema.

| Entity                       | Deferred to  | Reason                                                           |
| ---------------------------- | ------------ | ---------------------------------------------------------------- |
| `Claim`                      | Week 5       | Quantitative results extraction separate from checklist findings |
| `Table`, `Figure`            | Week 6       | Table understanding and figure extraction                        |
| `User`, `Auth`               | Out of scope | Multi-tenancy is not a Week 1 goal                               |
| Vector embeddings on Section | Week 7+      | Semantic search over sections                                    |
| Full-text search (tsvector)  | Week 6       | Faceted paper search                                             |

---

## Change log

| Version | Date        | Author       | Change |
| ------- | ----------- | ------------ | ------ |
| 1.0     | 2026-08-26  | Backend team | Initial schema for Week 1 |
