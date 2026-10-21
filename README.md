# BookSaver

![tests](https://github.com/colemanrharris/booksaver/actions/workflows/tests.yml/badge.svg)

Photograph a stack of books — spines, covers, whatever's in frame — and get back matched
titles with purchase/reader-app links. Pro users also get AI-curated "read next" picks
generated from their own collection.

## Why this project is interesting

This isn't a thin wrapper around an LLM API call. The interesting engineering is in how the
model's output is constrained, verified, and recovered from when it's wrong.

**Vision extraction with a deterministic parsing contract.** `services/image_processor.py`
sends a photo to Gemini (`gemini-2.5-flash-preview-09-2025`) with a prompt that pins the output
to a strict Python-literal format (`["TITLE by AUTHOR", ...]`) instead of relying on JSON mode
or function calling. The response is parsed with `ast.literal_eval`, and a malformed or empty
response degrades to an empty result rather than raising — tested in
`tests/test_image_processor.py`.

**LLM output is never trusted blind.** Gemini's reading of a book spine is noisy, so the
extracted strings are never shown to the user directly. Each one is run through
`core/filters.py`'s `FuzzyBookSearcher`, which queries the Google Books API and re-ranks
candidates with a weighted blend of `fuzz.partial_ratio`, `token_sort_ratio`, and
`token_set_ratio` plus an exact-word-overlap bonus. The LLM proposes; classical string matching
disposes.

**A hallucination guard with a code-side check, not just a prompt.**
`services/recommendations_service.py` asks Gemini to rank the user's "want to read" shelf and
return the top 5 — but the prompt's instruction to "only use real titles" is backed by a
runtime check: every returned title is matched against the user's actual `BookCollection` rows
before anything is persisted, and non-matches are silently dropped
(`tests/test_recommendations_service.py::test_hallucinated_title_is_filtered_out`). Each saved
recommendation stores the model's own reasoning (`recommendation_reason`) for auditability, and
results are cached for 7 days to avoid redundant API calls.

**Production-hardened around a third-party AI API.** The Gemini vision call involves an async
upload, a polling loop with a timeout, and explicit handling of rate limits (429),
auth failures (401/403), and server errors (500) — translated into user-facing messages
distinct from the logged technical ones (`ImageProcessor._get_user_friendly_error`).

**A build-vs-buy story backed by the git history.** The project originally shipped a
self-hosted OCR and video-scraping pipeline — EasyOCR/PaddleOCR/Tesseract for text extraction,
YOLO (Ultralytics) for book detection, yt-dlp + ffmpeg for pulling frames out of TikTok videos.
Commit [`6529b5a`](https://github.com/colemanrharris/booksaver/commit/6529b5a) ("transition to
gemini api, remove recommendations, update caching") replaced all of it with a single Gemini
multimodal call — a real example of
cutting a bespoke ML pipeline in favor of a foundation model once one became good enough for
the job.

**Operational maturity, not just a demo.** `scripts/generate_recommendations.py` is a weekly
batch job that regenerates recommendations for every active Pro subscriber, with per-user rate
limiting and `--force`/single-user flags for manual reruns.

## Architecture

```
Photo upload → services/image_processor.py (Gemini vision extraction)
            → core/filters.py (fuzzy-match re-ranking against Google Books API)
            → core/filters.py (quality / language / trending filters)
            → routes/images.py (purchase + reader-app links, scan history)

Pro recommendations: services/recommendations_service.py (Gemini text generation,
            anti-hallucination check against models/book_collection.py)
            → scripts/generate_recommendations.py (weekly batch job)
```

- **`routes/`** — Flask blueprints (auth, billing, collections, dashboard, goals, images)
- **`services/`** — business logic: Gemini integration, Google Books client, Stripe, email
- **`models/`** — SQLAlchemy models
- **`core/`** — fuzzy matching, quality/trending/language filtering, shared utilities

## Tech stack

| Layer | Choice |
|---|---|
| Backend | Flask 3, SQLAlchemy, Flask-Migrate (Alembic) |
| Database | SQLite |
| Vision + recommendations | Google Gemini (`google-genai`) |
| Book metadata | Google Books API |
| Fuzzy matching | `fuzzywuzzy` / `python-Levenshtein` |
| Billing | Stripe |
| Email (magic-link login) | SendGrid (primary), Mailgun (fallback) |
| Deployment | Render.com, gunicorn |
| Package management | `uv` |

## Getting started

```bash
git clone https://github.com/colemanrharris/booksaver.git
cd booksaver
uv sync                              # or: pip install -r requirements.txt
cp .env.example .env                 # fill in GEMINI_API_KEY, SECRET_KEY, an email provider key
flask db upgrade
python app.py
```

See [`DEPLOYMENT.md`](DEPLOYMENT.md) for the full environment variable reference and Render
deployment notes.

## Testing

```bash
uv run pytest
```

CI runs the full suite on every push via [`.github/workflows/tests.yml`](.github/workflows/tests.yml).

## License

[MIT](LICENSE)

## Known limitations

- **Stripe customer lookup/creation logic is duplicated** across three route handlers in
  `routes/billing.py` — a good candidate for extraction into a shared `StripeService` method.
- **No dedicated eval harness for LLM output quality** beyond the unit tests covering parsing
  and the anti-hallucination guard — a real production version of this would want to track
  extraction accuracy against a labeled set of book-cover photos over time.
- **SQLite + a single persistent disk** is fine at this scale but doesn't support horizontal
  scaling; a Postgres migration would be the natural next step.
