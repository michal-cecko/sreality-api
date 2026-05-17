# Sreality Apartment Monitor

Python daemon that polls [Sreality.cz](https://www.sreality.cz) for newly-listed apartments matching a saved search and emails alerts on changes.

> Personal tool — runs as a single container, persists state to a host volume, sends notifications via SMTP.

## What it does

- Polls Sreality.cz at a configurable interval (default: 5 minutes)
- Diffs current results against the last fetch (`results.json` ↔ `previous_results.json`)
- For each new listing → sends an HTML email with title, price, location, link
- Graceful shutdown on `SIGTERM` (saves state before exit)

## Stack

- **Python 3.13**
- **requests** for HTTP
- Stdlib **smtplib** + **email.mime** for notifications
- **Docker** for deployment (`docker compose up -d --build`)

## Run

```bash
cp .env.example .env             # fill in SMTP credentials + recipient
docker compose up -d --build
docker logs -f sreality-api      # watch for "[CHECK]" and "[EMAIL SENT]" lines
```

## Env vars

| Var | Default | Purpose |
|---|---|---|
| `MAIL_HOST` | — | SMTP server hostname |
| `MAIL_PORT` | — | SMTP port (587 for STARTTLS, 465 for SSL) |
| `MAIL_USERNAME` | — | SMTP auth username |
| `MAIL_PASSWORD` | — | SMTP auth password |
| `MAIL_ENCRYPTION` | — | `tls` or `ssl` |
| `MAIL_FROM_ADDRESS` | — | "From:" address |
| `MAIL_FROM_NAME` | — | "From:" display name |
| `RECIPIENT_EMAIL` | — | Where alerts go |
| `DATA_DIR` | `/app/data` | Persistent state directory |
| `CHECK_INTERVAL` | `300` | Polling interval (seconds) |
| `EMAIL_TIMEOUT` | `30` | SMTP send timeout (seconds) |

## License

[MIT](LICENSE) © Michal Čečko
