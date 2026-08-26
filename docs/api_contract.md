# RIGOR — API Contract

**Version:** 1.0
**Last updated:** August 26, 2026
**Owner:** Backend team
**Status:** Locked for Week 1 implementation
**Related doc:** `docs/database_schema.md`

---

## Overview

This document defines the JSON shape of every backend API endpoint in Week 1. It is the source of truth that both backend and frontend build against. If backend and frontend disagree on a field, this doc wins.

**Base URL (local dev):** `http://localhost:8000`

**Content type:** All requests and responses are `application/json`, except file uploads which are `multipart/form-data`.

**Character encoding:** UTF-8.

**Timestamps:** All datetimes are ISO 8601 with timezone (e.g. `2026-08-26T10:30:00Z`).

---

## Endpoints in Week 1

| Method | Path             | Purpose                          |
| ------ | ---------------- | -------------------------------- |
| POST   | `/papers`        | Upload a PDF and parse it        |
| GET    | `/papers/{id}`   | Fetch a single paper by ID       |
| GET    | `/papers`        | List all papers (dashboard view) |
| GET    | `/health`        | Service health check             |

Audit endpoints (`POST /papers/{id}/audits`, `GET /audits/{id}`) are defined in Week 3's contract.

---

## POST `/papers` — upload a paper

Upload a PDF file. Backend validates it, sends it to GROBID for parsing, stores everything in the database, and returns the fully parsed paper as JSON.

**Request:**

```
POST /papers HTTP/1.1
Content-Type: multipart/form-data; boundary=---xyz
```

**Form fields:**

| Field  | Type | Required | Description                       |
| ------ | ---- | -------- | --------------------------------- |
| `file` | File | Yes      | The PDF file to upload. Max 20 MB. |

**Success response — `201 Created`:**

```json
{
  "id": "d7f8a3e2-6b1c-4f9a-8e2d-1a4b5c6d7e8f",
  "filename": "attention_is_all_you_need.pdf",
  "file_size_bytes": 2145678,
  "sha256_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "page_count": 15,
  "title": "Attention Is All You Need",
  "authors": [
    {
      "full_name": "Ashish Vaswani",
      "affiliation": "Google Brain",
      "email": "avaswani@google.com",
      "orcid": null
    },
    {
      "full_name": "Noam Shazeer",
      "affiliation": "Google Brain",
      "email": null,
      "orcid": null
    }
  ],
  "abstract": "The dominant sequence transduction models are based on complex recurrent or convolutional neural networks...",
  "keywords": ["attention mechanism", "transformer", "sequence modeling"],
  "doi": "10.48550/arXiv.1706.03762",
  "publication_year": 2017,
  "venue": "NeurIPS",
  "journal_ref": "Advances in Neural Information Processing Systems 30, pp. 5998-6008",
  "status": "parsed",
  "error_message": null,
  "uploaded_at": "2026-08-26T10:30:00Z",
  "parsed_at": "2026-08-26T10:30:04Z"
}
```

### Response field reference

| Field                 | Type                  | Nullable | Purpose |
| --------------------- | --------------------- | -------- | ------- |
| `id`                  | UUID string           | No       | Primary key. Used in every subsequent request for this paper. |
| `filename`            | string                | No       | Original filename user uploaded. For frontend display only. |
| `file_size_bytes`     | integer               | No       | File size. Frontend formats as "2.1 MB". |
| `sha256_hash`         | string (64 hex chars) | No       | PDF fingerprint. Enables duplicate-upload detection. |
| `page_count`          | integer               | Yes      | Number of pages. Null if PDF was malformed. |
| `title`               | string                | Yes      | Paper title. Null when GROBID cannot extract it. |
| `authors`             | array of objects      | No       | Rich author list. Empty array if none extracted. See object schema below. |
| `abstract`            | string                | Yes      | Full abstract text. |
| `keywords`            | array of strings      | No       | Keywords from paper header. Empty array if none. |
| `doi`                 | string                | Yes      | Digital Object Identifier. |
| `publication_year`    | integer               | Yes      | Year of publication. |
| `venue`               | string                | Yes      | Conference or journal short name (e.g. "NeurIPS"). |
| `journal_ref`         | string                | Yes      | Full citation string. |
| `status`              | string enum           | No       | One of the six status values (see below). |
| `error_message`       | string                | Yes      | Human-readable reason when `status` is not `parsed`. |
| `uploaded_at`         | ISO 8601 datetime     | No       | When the file was received. |
| `parsed_at`           | ISO 8601 datetime     | Yes      | When parsing finished. Null if still parsing or failed. |

### Author object schema

Each element of the `authors` array:

| Field         | Type   | Nullable | Purpose |
| ------------- | ------ | -------- | ------- |
| `full_name`   | string | No       | Author's full name as printed in the paper. |
| `affiliation` | string | Yes      | Institution or organization. |
| `email`       | string | Yes      | Email address, usually only for the corresponding author. |
| `orcid`       | string | Yes      | ORCID identifier, disambiguates authors with common names. |

### Status enum values

| Value              | Meaning |
| ------------------ | ------- |
| `uploaded`         | File received, parsing not yet started (async, Week 3+). |
| `parsing`          | GROBID is currently running (async, Week 3+). |
| `parsed`           | Successfully parsed. All metadata fields are populated. |
| `parsing_failed`   | GROBID ran but returned unusable output. Paper row still created. |
| `unsupported_pdf`  | Scanned or image-only PDF with no text layer. |
| `corrupted`        | Bytes received but not a valid PDF. |

**Important:** When status is not `parsed`, the metadata fields (`title`, `authors`, etc.) may be null. Frontend must handle this.

### Notes on the response

- The Paper row's `raw_tei_xml` field is **never** returned in API responses. It can be several MB and the frontend has no use for it.
- The response is returned **only after parsing completes** in Week 1 (synchronous). In Week 3 we may return early with `status="parsing"` and let the frontend poll `GET /papers/{id}`.

---

## GET `/papers/{id}` — fetch a single paper

Retrieve the full details of one paper by its UUID.

**Request:**

```
GET /papers/d7f8a3e2-6b1c-4f9a-8e2d-1a4b5c6d7e8f HTTP/1.1
```

**Path parameters:**

| Parameter | Type | Description                    |
| --------- | ---- | ------------------------------ |
| `id`      | UUID | The paper's primary key. |

**Success response — `200 OK`:**

Identical shape to the `POST /papers` success response. Uses the same 17-field structure.

**Error responses:** `404 Not Found` if the paper does not exist. See error section below.

---

## GET `/papers` — list all papers

Return a paginated list of all uploaded papers, newest first. Used by the frontend dashboard.

**Request:**

```
GET /papers?limit=20&offset=0 HTTP/1.1
```

**Query parameters:**

| Parameter | Type    | Default | Description |
| --------- | ------- | ------- | ----------- |
| `limit`   | integer | 20      | Number of results to return (max 100). |
| `offset`  | integer | 0       | Number of results to skip (for pagination). |
| `status`  | string  | (all)   | Optional filter by status (e.g. `parsed`). |

**Success response — `200 OK`:**

```json
{
  "total": 47,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "id": "d7f8a3e2-...",
      "filename": "attention_is_all_you_need.pdf",
      "title": "Attention Is All You Need",
      "authors_summary": "Vaswani et al.",
      "publication_year": 2017,
      "venue": "NeurIPS",
      "status": "parsed",
      "page_count": 15,
      "uploaded_at": "2026-08-26T10:30:00Z"
    },
    {
      "id": "b1c2d3e4-...",
      "filename": "bert.pdf",
      "title": "BERT: Pre-training of Deep Bidirectional Transformers",
      "authors_summary": "Devlin et al.",
      "publication_year": 2018,
      "venue": "NAACL",
      "status": "parsed",
      "page_count": 16,
      "uploaded_at": "2026-08-26T09:15:00Z"
    }
  ]
}
```

### List response field reference

| Field    | Type              | Description |
| -------- | ----------------- | ----------- |
| `total`  | integer           | Total papers matching the filter (across all pages). |
| `limit`  | integer           | The limit that was applied. |
| `offset` | integer           | The offset that was applied. |
| `items`  | array of objects  | The paper summaries for this page. |

Each item is a **compact summary** — not the full paper. This keeps the payload small for the dashboard. To get the full paper, call `GET /papers/{id}`.

### Item object schema

| Field              | Type              | Nullable | Purpose |
| ------------------ | ----------------- | -------- | ------- |
| `id`               | UUID string       | No       | For linking to full paper view. |
| `filename`         | string            | No       | Fallback when title is null. |
| `title`            | string            | Yes      | Displayed as card heading. |
| `authors_summary`  | string            | Yes      | Compact "First Author et al." string. Frontend does not have to compute this. |
| `publication_year` | integer           | Yes      | Displayed on card. |
| `venue`            | string            | Yes      | Displayed on card. |
| `status`           | string            | No       | Frontend badges failed papers differently. |
| `page_count`       | integer           | Yes      | Displayed on card. |
| `uploaded_at`      | ISO 8601 datetime | No       | For sorting and "uploaded 2 hours ago" display. |

---

## GET `/health` — health check

Simple endpoint used by Docker and monitoring to verify the service is alive.

**Request:**

```
GET /health HTTP/1.1
```

**Success response — `200 OK`:**

```json
{
  "status": "ok",
  "database": "connected",
  "grobid": "connected",
  "version": "0.1.0"
}
```

If any dependency is down, the field shows `"unavailable"` and the top-level `status` becomes `"degraded"`. Response is always `200 OK` — the field values, not the HTTP code, carry the diagnosis.

---

## Error response format

Every error response — from any endpoint — uses the same envelope. Frontend switches on `error.code`, falls back to `error.message` for display.

```json
{
  "error": {
    "code": "file_too_large",
    "message": "File exceeds 20 MB limit.",
    "details": {
      "max_size_bytes": 20971520,
      "actual_size_bytes": 45678901
    }
  }
}
```

### Envelope fields

| Field             | Type   | Required | Purpose |
| ----------------- | ------ | -------- | ------- |
| `error.code`      | string | Yes      | Machine-readable error identifier. Frontend switches on this. |
| `error.message`   | string | Yes      | Human-readable error message. Frontend can display as fallback. |
| `error.details`   | object | No       | Additional structured context. Shape depends on `code`. |

### Error codes

| HTTP status | `code`                       | When | Details fields |
| ----------- | ---------------------------- | ---- | -------------- |
| 400         | `not_a_pdf`                  | File does not start with `%PDF` bytes | none |
| 400         | `empty_file`                 | Zero bytes uploaded | none |
| 400         | `missing_file`               | Multipart form missing the `file` field | none |
| 400         | `invalid_uuid`               | URL path UUID is malformed | `provided_id` |
| 404         | `not_found`                  | Paper does not exist for the given ID | `paper_id` |
| 413         | `file_too_large`             | File exceeds 20 MB | `max_size_bytes`, `actual_size_bytes` |
| 415         | `unsupported_content_type`   | Content-Type is not `application/pdf` or `application/octet-stream` | `provided_content_type` |
| 422         | `parsing_failed`             | Valid PDF but GROBID could not parse it. **Paper row is still created** with `status="parsing_failed"` — this error only fires if we can't even create the row. | none |
| 500         | `internal_error`             | Server crash, database down, GROBID unreachable | `request_id` for log correlation |

**Important behavior:** When GROBID fails on an otherwise valid PDF, the API returns `201 Created` with the paper's `status="parsing_failed"` — NOT a 422. This is intentional: the paper row exists, the frontend can display it, and the user sees "we tried but failed" instead of "your upload vanished".

---

## HTTP conventions

- **Successful GET → `200 OK`**
- **Successful POST creating a resource → `201 Created`**
- **Successful action with no body → `204 No Content`**
- **Malformed request → `400 Bad Request`**
- **Not found → `404 Not Found`**
- **Payload too big → `413 Payload Too Large`**
- **Wrong content type → `415 Unsupported Media Type`**
- **Validation failed after receipt → `422 Unprocessable Entity`**
- **Server-side crash → `500 Internal Server Error`**

CORS headers are enabled for all origins during Week 1 (development). Locked down in later weeks.

---

## Frontend TypeScript types

The frontend must generate these types from this doc — they cannot drift. Save as `frontend/src/types/paper.ts`.

```typescript
export type PaperStatus =
  | "uploaded"
  | "parsing"
  | "parsed"
  | "parsing_failed"
  | "unsupported_pdf"
  | "corrupted";

export type Author = {
  full_name: string;
  affiliation: string | null;
  email: string | null;
  orcid: string | null;
};

export type Paper = {
  id: string;
  filename: string;
  file_size_bytes: number;
  sha256_hash: string;
  page_count: number | null;
  title: string | null;
  authors: Author[];
  abstract: string | null;
  keywords: string[];
  doi: string | null;
  publication_year: number | null;
  venue: string | null;
  journal_ref: string | null;
  status: PaperStatus;
  error_message: string | null;
  uploaded_at: string;      // ISO 8601
  parsed_at: string | null; // ISO 8601 or null
};

export type PaperSummary = {
  id: string;
  filename: string;
  title: string | null;
  authors_summary: string | null;
  publication_year: number | null;
  venue: string | null;
  status: PaperStatus;
  page_count: number | null;
  uploaded_at: string;
};

export type PaperListResponse = {
  total: number;
  limit: number;
  offset: number;
  items: PaperSummary[];
};

export type ApiError = {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
  };
};
```

---

## What is deliberately not in v1.0

| Feature                       | Deferred to | Reason |
| ----------------------------- | ----------- | ------ |
| Audit endpoints               | Week 3      | Audit engine not yet built |
| Section-detail endpoint       | Week 2      | Sections table populated but no UI needs it yet |
| Reference-detail endpoint     | Week 4      | Retraction cascade check drives when this is needed |
| Pagination cursors            | Week 5      | `offset` pagination is enough for < 10k papers |
| Auth headers (JWT / API keys) | Out of scope | Single-user dev only |
| Rate limiting                 | Week 6      | Not a blocker for dev |
| Webhook callbacks             | Out of scope | Frontend polls instead |

---

## Change log

| Version | Date       | Author       | Change |
| ------- | ---------- | ------------ | ------ |
| 1.0     | 2026-08-26 | Backend team | Initial contract for Week 1 |
