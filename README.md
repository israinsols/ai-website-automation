# AI Website Automation

Create SEO drafts with Groq, accept client article submissions for review, and publish approved content to the built-in blog. The standalone CLI can also publish to WordPress and notify IndexNow. The keyword bank rotates without repeating a keyword until every current keyword has been used once.

## Setup

In PowerShell from this folder:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Put your credentials in `.env`. Never commit that file. `GROQ_API_KEY` is always required. `GROQ_MODEL` defaults to `openai/gpt-oss-120b`, which matches the model currently available on the Groq account used for this project. For publishing runs, also set `WP_SITE_URL`, `WP_AUTH_TOKEN` (a WordPress JWT bearer token), and `INDEXNOW_KEY`.

IndexNow requires a publicly reachable text file containing the same key. Host it at `https://your-site.example/<key>.txt`, or set `INDEXNOW_KEY_LOCATION` to the public URL where you host that file.

Edit `keywords.json` to suit the site's audience. Each successful generation is recorded in `data/used_keywords.json`, which is local and ignored by Git. Once all entries have been used, rotation starts a new cycle.

## Local Workspace

Start the web app from this folder:

```powershell
python app.py
```

Open `http://127.0.0.1:5000`. On first local use, create the one-time admin account in the browser; its password is stored as a hash in SQLite. Then use the workspace to manage keywords, submissions, drafts, and review dates. Client submissions stay pending until you review and approve them. Approved content appears on the built-in blog at `/blog`.

The signed-in workspace also includes **Site manager** for the site name, category, homepage headline, image URL, theme colors, navigation links, and newsletter signup section; **Pages** for SEO-described standalone draft or published pages; and **Newsletter** for reviewing/removing subscribers. These settings, pages, queued keywords, and subscriber lists are stored in the selected site's database. Newsletter signups are collected locally; this app does not send email campaigns. Header images are configured with an HTTPS image URL.

Published blog posts display topic-specific Unsplash cover images by default. Open an article in the workspace and use **Article cover** to provide your own direct HTTPS image URL; this works for both drafts and published posts. The public site visitor's browser loads the image directly from its host, so review the Privacy page and your chosen host before production.

Use **Autopilot** to switch between manual article review and automatic daily publishing. The public sitemap includes published standalone pages.

## Second Site: Tech

The same codebase now supports a separate Tech publication without mixing it with Home Decor. Copy `.env.tech.example` to `.env.tech`, replace its placeholder credentials and domain, then start it in another terminal:

```powershell
Copy-Item .env.tech.example .env.tech
$env:ENV_FILE = ".env.tech"
python app.py
```

The Tech profile uses `SITE_NICHE=tech`, its own branding, `data/tech.sqlite3`, `data/tech_used_keywords.json`, `data/tech_pending_wordpress_article.json`, and port `5001`. Keep the existing Home Decor process on port `5000`. For production, point the Tech profile at its own HTTPS domain and persistent storage; both sites can share the codebase and API keys but should use separate databases, domains, and admin credentials.

Because the management features use `DATABASE_PATH`, each running profile has its own site settings, custom pages, keyword queue, and newsletter subscribers.

The public blog, article pages, sitemap, and RSS feed show published articles matching that profile's configured category across both configured profile databases. This lets a Tech article published from a workspace currently pointed at the Home Decor database appear on the Tech site, without exposing it on the Home Decor site. Site settings, custom pages, keyword queues, and subscribers remain separate per database.

For the automatic feed-based writing flow, configure `GROQ_API_KEY` and set `RSS_FEED_URLS` in `.env`. The app can build a draft from recent feed items, ask Groq to write original copy, and store the feed source details with the draft. Review all facts and feed items before publication. The older manual-keyword generator does not rely on live search. Feed summaries are not proof of ranking or search volume.

## Daily Autopilot

Autopilot is off by default. In the admin workspace, open **Autopilot**, choose a daily time, check the acknowledgement that posts will publish without individual approval, and save. It requires both API keys above. Each run discovers a new long-tail topic from current web results, checks it against existing keywords/articles, assigns it to a topic cluster, researches sources, generates and validates an article, then publishes it to the built-in blog. A database lock prevents more than one successful autopilot post per local day. Keyword suggestions do not include measured search volume or competition.

On Windows, create a Task Scheduler task with a **Daily** trigger at the same local time selected in Autopilot. Set the action to:

- Program: `<project folder>\\.venv\\Scripts\\python.exe`
- Arguments: `automation.py`
- Start in: `<project folder>`

The computer must be awake and online at run time. For hosted deployment, use the host's persistent scheduler instead and point `DATABASE_PATH` at persistent storage. Autopilot publishes straight to the site's public blog; review it manually while testing, and only enable autonomous publishing when you accept that risk.

The **Growth plan** groups the configured home-decor keywords into pillar/supporting topic clusters and tracks each as planned, in progress, or published. Public article pages link to other published articles in the same cluster when available. This creates a clearer content roadmap and useful internal navigation; it does not predict or guarantee search rankings.

The public home page and published articles include canonical URLs, social metadata, and structured data. The app serves `/robots.txt`, `/sitemap.xml`, and `/feed.xml`; only published articles are listed. After choosing a domain, set `PUBLIC_SITE_URL` to its HTTPS origin. To verify the domain with Google Search Console, add the HTML tag value Google provides to `GOOGLE_SITE_VERIFICATION`, deploy, verify the property, and submit `https://your-domain.example/sitemap.xml` in Search Console. These files make the site easier to crawl; they do not guarantee rankings or measure search traffic.

Public `/about`, `/contact`, `/privacy`, and `/editorial-policy` pages are included. Set `CONTACT_EMAIL` before launch; the Contact page intentionally does not invent an address. Review the Privacy page against the actual hosting, analytics, and data-retention setup before making the site public.

To accept client articles in production, set `ALLOW_PUBLIC_SUBMISSIONS=1`. The form requires a contact email and explicit reprint permission, validates CSRF, uses a honeypot and minimum completion time, and limits each email to three submissions per hour with a keyed hash. Add host/proxy rate limiting as another layer. Have the reprint terms reviewed for your jurisdiction before relying on them. Submissions remain private until approved. Contributors can provide the source URL and request an external canonical for an identical syndicated copy; approved copies with an external canonical are excluded from the sitemap and link to the original from the RSS feed.

The admin **Traffic report** shows approximate production page views by day and page, with simple bot filtering. It does not store IP addresses, referrers, user agents, or analytics cookies, and it does not report unique visitors or Google organic clicks. Search Console reporting still requires separate verification and integration.

Before publishing, the article review screen lets you edit the SEO title, meta description, and focus keyword. Its checklist checks character limits and keyword placement in the title/opening; it is not a search ranking score or a substitute for editorial review.

The article store is SQLite at `DATABASE_PATH` (default `data/site.sqlite3`). On first start, existing `data/dashboard_articles.json` records are copied once; the JSON file is kept unchanged as a backup. Signed-in admins can download a consistent SQLite backup from the workspace sidebar. Store downloaded backups separately from the app. When deploying, point `DATABASE_PATH` at persistent storage provided by the host.

The first local visit prompts you to create one admin account. Alternatively, set `ADMIN_USERNAME` and `ADMIN_PASSWORD` in `.env` for environment-managed credentials. For production, set `APP_ENV=production`, a random `FLASK_SECRET_KEY` (at least 32 characters), an admin username, and an admin password (at least 16 characters); production startup fails without these values. Public client submissions return 404 in production unless `ALLOW_PUBLIC_SUBMISSIONS=1`; enable them only after testing the form and configuring upstream rate limiting. Calendar dates are review reminders only. With Autopilot off, every article requires manual approval; with it on, daily articles publish automatically. Keep `.env` private.

The workspace has one admin account, not separate client accounts. Production still needs host-level backups, upstream rate limiting, and HTTPS. Search Console metrics require a verified public domain and separate integration.

## Run Once

Set `TEST_MODE=1` in `.env` and run:

```powershell
python main.py
```

The script prints the metadata and complete article JSON, records the successfully generated keyword, and skips WordPress and IndexNow. Set `TEST_MODE=0` to publish directly with status `publish`. The SEO meta title is sent as the WordPress post title and the meta description as the excerpt; the article HTML contains its own H1.

The generator validates article length (900-1300 words), title and description limits, keyword placement, and clean HTML. Invalid model responses are retried up to three times. A publish error is reported; an IndexNow error is reported separately because the post is already live.

If WordPress publishing fails after generation, the exact article is kept locally in `data/pending_wordpress_article.json` and retried on the next run without generating it again. The file is ignored by Git; keep the project data directory on persistent storage if you rely on this recovery behavior.

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
- `automation.py`: one-shot daily autopilot entry point for Windows Task Scheduler or a host scheduler.
- `keywords.json`: editable rotating keyword bank.
- `tests/test_autopilot.py`: offline tests for keyword discovery, explicit opt-in, source-backed publishing, and duplicate-run protection.
- `requirements.txt`: Python dependencies.
- `.env.example`: required and optional environment variable names without real credentials.
- `.gitignore`: excludes credentials, virtual environment, caches, and the local usage log.