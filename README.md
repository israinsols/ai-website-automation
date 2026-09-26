# AI Website Automation

Generate SEO articles with Groq, publish them to WordPress, and notify IndexNow. The keyword bank rotates without repeating a keyword until every current keyword has been used once.

## Setup

In PowerShell from this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Put your credentials in `.env`. Never commit that file. `GROQ_API_KEY` is always required. `GROQ_MODEL` defaults to `llama-3.3-70b-versatile`, which matches the Groq setup in this project. For publishing runs, also set `WP_SITE_URL`, `WP_AUTH_TOKEN` (a WordPress JWT bearer token), and `INDEXNOW_KEY`.

IndexNow requires a publicly reachable text file containing the same key. Host it at `https://your-site.example/<key>.txt`, or set `INDEXNOW_KEY_LOCATION` to the public URL where you host that file.

Edit `keywords.json` to suit the site's audience. Each successful generation is recorded in `data/used_keywords.json`, which is local and ignored by Git. Once all entries have been used, rotation starts a new cycle.

## Run Once

Set `TEST_MODE=1` in `.env` and run:

```powershell
python main.py
```

The script prints the metadata and complete article JSON, records the successfully generated keyword, and skips WordPress and IndexNow. Set `TEST_MODE=0` to publish directly with status `publish`. The SEO meta title is sent as the WordPress post title and the meta description as the excerpt; the article HTML contains its own H1.

The generator validates article length (900-1300 words), title and description limits, keyword placement, and clean HTML. Invalid model responses are retried up to three times. A publish error is reported; an IndexNow error is reported separately because the post is already live.

## Daily Schedule

Set `TEST_MODE=0` and `PUBLISH_TIME=09:00` (24-hour local time), then start the long-running daily scheduler:

```powershell
python main.py --schedule
```

The process must stay running. For unattended Windows startup, create a Task Scheduler task with an **At log on** trigger and these action fields:

- Program: `<project folder>\.venv\Scripts\python.exe`
- Arguments: `main.py --schedule`
- Start in: `<project folder>`

The scheduler loads `.env` from the project folder, catches and reports each day's errors, and continues waiting for the next scheduled run.

## Files

- `main.py`: keyword rotation, Groq generation and validation, WordPress publishing, IndexNow ping, and daily scheduler.
- `keywords.json`: editable rotating keyword bank.
- `requirements.txt`: Python dependencies.
- `.env.example`: required and optional environment variable names without real credentials.
- `.gitignore`: excludes credentials, virtual environment, caches, and the local usage log.