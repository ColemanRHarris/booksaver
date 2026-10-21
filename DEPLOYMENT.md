# BookSaver Deployment Guide

## Environment Variables

Copy `.env.example` to `.env` and fill in real values. Required for core functionality:

```bash
GEMINI_API_KEY=...        # Google Gemini API key (book identification + recommendations)
SECRET_KEY=...            # Flask session secret
MAGIC_LINK_SECRET=...     # Signs passwordless login links (defaults to SECRET_KEY if unset)
```

### Email (passwordless magic-link login)

The app sends login links via **SendGrid** if `SENDGRID_API_KEY` is set, falling back to
**Mailgun** if `MAILGUN_API_KEY`/`MAILGUN_DOMAIN` are set instead (see `services/email_service.py`).
At least one provider must be configured for login to work.

```bash
# Primary
SENDGRID_API_KEY=your_sendgrid_api_key

# Fallback (used only if SENDGRID_API_KEY is unset)
MAILGUN_API_KEY=your_mailgun_api_key
MAILGUN_DOMAIN=your_mailgun_domain
```

### Stripe (billing)

Optional — only needed if you want pay-per-scan / Pro subscription billing enabled.

```bash
STRIPE_SECRET_KEY=...
STRIPE_PUBLISHABLE_KEY=...
STRIPE_WEBHOOK_SECRET=...
```

### Other

```bash
GOOGLE_BOOKS_KEY=...      # Optional, raises Google Books API rate limits
APP_URL=https://your-domain.com   # Used to build absolute links in emails
PORT=5000
```

## Render.com Deployment

This repo is set up to deploy on [Render](https://render.com) via `render.yaml`:

1. Create a new Web Service from this repo; Render will read `render.yaml` automatically.
2. In the service's **Environment** settings, fill in the `sync: false` variables listed in
   `render.yaml` (API keys, secrets) — these aren't stored in the repo.
3. Render runs `build.sh` on deploy, which installs Python dependencies and applies database
   migrations (`flask db upgrade head`), then starts the app with `gunicorn`.
4. The SQLite database lives on a persistent disk mounted at `instance/` (see the `disk:` block
   in `render.yaml`) so it survives redeploys.

## Local Development

1. Copy `.env.example` to `.env` and fill in at minimum `GEMINI_API_KEY`, `SECRET_KEY`, and an
   email provider key.
2. Install dependencies: `uv sync` (or `pip install -r requirements.txt`).
3. Run migrations: `flask db upgrade`.
4. Start the app: `python app.py`.

## Troubleshooting

**Login emails not sending**
- Confirm `SENDGRID_API_KEY` or both `MAILGUN_API_KEY`/`MAILGUN_DOMAIN` are set.
- Check logs for the exception raised by `services/email_service.py` — it names the missing
  config explicitly.

**Migrations fail on deploy**
- `build.sh` falls back to `db.create_all()` if `flask db upgrade head` fails, to avoid a broken
  deploy on a fresh database; check Render build logs for the actual migration error.

## Security

- Never commit `.env` or any file containing real credentials.
- Rotate API keys periodically, especially after any suspected exposure.
