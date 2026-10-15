# AI Website Automation

Create SEO drafts with Groq, let client accounts submit articles for editorial review, and publish approved content to the built-in blog. The standalone CLI can also publish to WordPress and notify IndexNow. The keyword bank rotates without repeating a keyword until every current keyword has been used once.

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

Open `http://127.0.0.1:5000`. On first local use, create the one-time admin account in the browser; its password is stored as a hash in SQLite. Then use the workspace to manage keywords, submissions, drafts, and review dates. Clients can save private drafts or submit articles for editorial review; only an admin can publish them. Admin-managed content also requires review and approval before it appears on the built-in blog at `/blog`.

The signed-in workspace also includes **Site manager** for the site name, category, homepage headline, image URL, theme colors, navigation links, and newsletter signup section; **Pages** for SEO-described standalone draft or published pages; and **Newsletter** for reviewing/removing subscribers. These settings, pages, queued keywords, and subscriber lists are stored in the selected site's database.

Newsletter and client workflow emails can be sent through the Resend API by setting `RESEND_API_KEY`, `NEWSLETTER_FROM_EMAIL`, and `PUBLIC_SITE_URL` in each profile's environment. Verify the sender domain in Resend before using it. If `RESEND_API_KEY` is unset, the app can instead use SMTP settings: `NEWSLETTER_SMTP_HOST`, `NEWSLETTER_SMTP_PORT`, `NEWSLETTER_SMTP_SECURITY` (`starttls`, `ssl`, or `none`), and optional `NEWSLETTER_SMTP_USERNAME` / `NEWSLETTER_SMTP_PASSWORD`. Set `EDITORIAL_NOTIFICATION_EMAIL` (or `CONTACT_EMAIL` as a fallback) to receive client-submission alerts. Keep credentials private. `PUBLIC_SITE_URL` must be the site's public HTTPS origin so confirmation, unsubscribe, review, and publication links work outside the local machine. Clients receive a notification after an admin publishes their article. Visitors must confirm within 24 hours before they receive an email for each newly published article. Each article email includes an unsubscribe link. If neither Resend nor SMTP is configured, the public signup form is disabled. Delivery errors are logged and surfaced in the publishing workspace; failed recipient deliveries are not automatically retried.

Published blog posts display topic-specific Unsplash cover images by default. Open **Images** in the workspace to review covers that need descriptive alt text, or edit an article's **Article cover** to add alt text. Uploading a JPG, PNG, or WebP (up to 8 MB) resizes it to at most 1800 × 1800 pixels and stores an optimized WebP in that site's local static uploads; direct HTTPS image URLs remain supported. This works for both drafts and published posts. The public site visitor's browser loads external images directly from their host, so review the Privacy page and your chosen host before production.

The **Images** workspace can also run a report-only image and link check over published articles and standalone pages. It checks local routes and files plus public HTTP(S) URLs, reports redirects without following them, and does not contact private/local network addresses. Scans are capped at 120 image/link references to keep local checks bounded; no content is changed.

Use **Sites** in the admin workspace for an at-a-glance summary of the configured Home Decor and Tech profiles. Each profile keeps a separate database and workspace. The article review checklist checks SEO metadata, keyword placement, heading/paragraph structure, and saved research references. These automated checks do not fact-check claims or verify source reliability; review article claims and references yourself before publishing. Use **Autopilot** to switch between manual article review and automatic daily publishing. The public sitemap includes published standalone pages.

## Second Site: Tech

The same codebase now supports a separate Tech publication without mixing it with Home Decor. Copy `.env.tech.example` to `.env.tech`, replace its placeholder credentials and domain, then start it in another terminal:

```powershell
Copy-Item .env.tech.example .env.tech
$env:ENV_FILE = ".env.tech"
python app.py
```

The Tech profile uses `SITE_NICHE=tech`, its own branding, `data/tech.sqlite3`, `data/tech_used_keywords.json`, `data/tech_pending_wordpress_article.json`, and port `5001`. Keep the existing Home Decor process on port `5000`. For production, point the Tech profile at its own HTTPS domain and persistent storage; both sites can share the codebase and API keys but should use separate databases, domains, and admin credentials.

Because the management features use `DATABASE_PATH`, each running profile has its own site settings, custom pages, keyword queue, and newsletter subscribers.

## Railway deployment

The Flask application serves both the rendered pages and static assets, so a Railway service deploys the full website and backend together. For separate Home Decor and Tech sites, create two Railway services from this repository and configure each service with its own profile variables and Railway volume mounted at `/data`.

For each service, set `APP_ENV=production`, a unique random `FLASK_SECRET_KEY`, a unique `ADMIN_USERNAME` and `ADMIN_PASSWORD` (at least 16 characters), `DATABASE_PATH=/data/site.sqlite3`, `UPLOADS_PATH=/data/uploads`, `KEYWORD_STATE_PATH=/data/used_keywords.json`, and `PENDING_ARTICLE_PATH=/data/pending_wordpress_article.json`. Set the site's `SITE_NICHE`, branding, and `PUBLIC_SITE_URL` separately. Add `GROQ_API_KEY` to enable article generation. Configure each assigned domain as the profile's HTTPS `PUBLIC_SITE_URL`; configure SMTP and other optional integrations only when needed. Do not commit credentials or local databases.

The `Procfile` starts Gunicorn using Railway's assigned `PORT`. SQLite databases, uploaded article images, and keyword state must use the mounted volume; the app's `/uploads/...` route serves those persistent images. Keep one application instance per SQLite database.

The public blog, article pages, sitemap, and RSS feed show published articles matching that profile's configured category across both configured profile databases. This lets a Tech article published from a workspace currently pointed at the Home Decor database appear on the Tech site, without exposing it on the Home Decor site. Site settings, custom pages, keyword queues, and subscribers remain separate per database.

For the automatic feed-based writing flow, configure `GROQ_API_KEY` and set `RSS_FEED_URLS` in `.env`. The app can build a draft from recent feed items, ask Groq to write original copy, and store the feed source details with the draft. Review all facts and feed items before publication. The older manual-keyword generator does not rely on live search. Feed summaries are not proof of ranking or search volume.

## Daily Autopilot

Autopilot is off by default. In the admin workspace, open **Autopilot**, choose a daily time, check the acknowledgement that posts will publish without individual approval, and save. It requires both API keys above. Each run discovers a new long-tail topic from current web results, checks it against existing keywords/articles, assigns it to a topic cluster, researches sources, generates and validates an article, then publishes it to the built-in blog. A database lock prevents more than one successful autopilot post per local day. Keyword suggestions do not include measured search volume or competition.

On Windows, create a Task Scheduler task with a **Daily** trigger at the same local time selected in Autopilot. Set the action to:

- Program: `<project folder>\\.venv\\Scripts\\python.exe`
- Arguments: `automation.py`
- Start in: `<project folder>`

The computer must be awake and online at run time. For hosted deployment, use the host's persistent scheduler instead and point `DATABASE_PATH` at persistent storage. Autopilot publishes straight to the site's public blog; review it manually while testing, and only enable autonomous publishing when you accept that risk.

The editorial **Calendar** includes a month view with review reminders and approved publication times; select a day to see that day's items. It can schedule an individual draft or pending submission after you explicitly approve it. Choose its local publish date and time and tick the approval checkbox; it stays private until the scheduled time. To publish on time, create a separate Windows Task Scheduler task that repeats every 5 minutes indefinitely. For Home Decor, run `.venv\Scripts\python.exe` with arguments `automation.py --scheduled-publications` and the project folder as **Start in**. For Tech, run `cmd.exe` with arguments `/c "set ENV_FILE=.env.tech&& .venv\Scripts\python.exe automation.py --scheduled-publications"` and the project folder as **Start in**. This runner publishes only explicitly approved, due items and works with Autopilot disabled. The computer must be awake and online; without the runner, approved posts remain drafts. You can reschedule or cancel any item from Calendar. Editing a scheduled article cancels its approval and schedule so the updated version needs fresh approval.

The **Growth plan** groups the configured home-decor keywords into pillar/supporting topic clusters and tracks each as planned, in progress, or published. Public article pages link to other published articles in the same cluster when available. This creates a clearer content roadmap and useful internal navigation; it does not predict or guarantee search rankings.

The public home page and published articles include canonical URLs, social metadata, and structured data. The app serves `/robots.txt`, `/sitemap.xml`, and `/feed.xml`; only published articles are listed. After choosing a domain, set `PUBLIC_SITE_URL` to its HTTPS origin. To verify the domain with Google Search Console, add the HTML tag value Google provides to `GOOGLE_SITE_VERIFICATION`, deploy, verify the property, and submit `https://your-domain.example/sitemap.xml` in Search Console. These files make the site easier to crawl; they do not guarantee rankings or measure search traffic.

The admin **Search Console** report can sync real Google organic clicks, impressions, CTR, and average position for the latest complete 28-day period. Verify the site in Search Console, enable the Search Console API in Google Cloud, create a service account, and grant its email access to the property. Store its downloaded JSON key outside the repository, set `GOOGLE_SEARCH_CONSOLE_PROPERTY` to the exact verified URL-prefix (for example `https://your-domain.example/`) or domain property (`sc-domain:your-domain.example`), and set `GOOGLE_SEARCH_CONSOLE_CREDENTIALS_FILE` to the private JSON file path. The property hostname must match `PUBLIC_SITE_URL`. Use **Search Console** in the workspace to sync on demand; the normal daily `automation.py` task also syncs metrics before its content run. Data is cached in that site's database, is capped at 100,000 query/page rows per sync, and is not shared between profiles. The report suggests high-impression queries that may benefit from content updates or more compelling snippets; it does not change published articles or guarantee traffic. Search Console data is delayed by Google, and API/authentication errors are reported by the sync.

Public `/about`, `/contact`, `/privacy`, and `/editorial-policy` pages are included. Set `CONTACT_EMAIL` before launch; the Contact page intentionally does not invent an address. Review the Privacy page against the actual hosting, analytics, and data-retention setup before making the site public.

Clients can create an account at `/client/signup`, sign in at `/client/login`, and generate an article from a topic without writing the article themselves. Generated articles are automatically submitted for editorial review; manually written articles can be saved privately or submitted after the client confirms publication rights. Only an admin can publish submissions. The editorial team is emailed when a client submits an article, and the client is emailed after publication. Generated articles use the configured Groq API; each client can generate up to three articles per local calendar day. Successful generations use the site owner's configured Groq account/quota. Clients can add their website URL; after editorial approval, the published article displays a link to it, marked `rel="sponsored nofollow"` for search-engine compliance. This can send interested readers to the client's site but does not guarantee clicks or rankings. Accounts are stored per selected site database and passwords are hashed. Account signup does not currently verify email or process payments; add an email verification and payment provider flow before selling access in production.

The public `/submit` link routes visitors to client signup, or signed-in clients to the client article editor. Anonymous guest submissions are disabled; clients must use their own account to create or AI-generate drafts and submit them for review.

The admin **Traffic report** shows approximate production page views by day and page, with simple bot filtering. It does not store IP addresses, referrers, user agents, or analytics cookies, and it does not report unique visitors or Google organic clicks. Use the separate **Search Console** report for Google organic clicks, impressions, CTR, average position, and query/page optimization opportunities.

Before publishing, the article review screen lets you edit the SEO title, meta description, and focus keyword. Its checklist checks character limits and keyword placement in the title/opening; it is not a search ranking score or a substitute for editorial review.

The article store is SQLite at `DATABASE_PATH` (default `data/site.sqlite3`). On first start, existing `data/dashboard_articles.json` records are copied once; the JSON file is kept unchanged as a backup. Signed-in admins can download a consistent SQLite backup from the workspace sidebar. Store downloaded backups separately from the app. When deploying, point `DATABASE_PATH` at persistent storage provided by the host.

The first local visit prompts you to create one admin account. Alternatively, set `ADMIN_USERNAME` and `ADMIN_PASSWORD` in `.env` for environment-managed credentials. For production, set `APP_ENV=production`, a random `FLASK_SECRET_KEY` (at least 32 characters), an admin username, and an admin password (at least 16 characters); production startup fails without these values. Calendar review dates are reminders only; scheduled publication is a separate, explicit per-article approval. With Autopilot off, unscheduled articles still require manual publication; with it on, daily autopilot articles publish automatically. Keep `.env` private.

The admin editorial workspace still has one admin account. Client accounts are separate and can only manage their own drafts and submissions. Their articles remain private until an admin approves and publishes them. Production still needs host-level backups, upstream rate limiting, HTTPS, and an email/payment provider before client billing.

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