# bilalbill: Python-only static blog

A small, Python-only static site generator for `bilalbill.com`. It writes HTML, images, RSS, robots.txt, and a sitemap to `public/`; there is no WordPress, JavaScript application runtime, paid hosting dependency, click bot, or fake traffic. Content drafts are **not published by default**.

Organic search growth is not guaranteed. Search engines decide whether and where to show pages. This project discovers topic ideas and publishes helpful pages; it never searches Google results and clicks them, creates fake visitors, or manipulates ads.

## What is included

- Python 3.11+, Jinja2, Markdown-it (raw HTML disabled), frontmatter, SQLite, Requests, Pillow, python-dotenv, Google Auth, and pytest.
- Google Autosuggest research with one-second request spacing, deduplication, and keyword scoring.
- Gemini article drafts with three attempts and checks for length, keyword, FAQ, headings, placeholders, repeated paragraphs, and similarity. Every draft carries three fact-check notes.
- A static, responsive, accessible site with clean URLs, categories/tags, pagination, internal links, table of contents, reading time, related posts, JSON-LD, canonical/Open Graph tags, XML sitemap, robots.txt, and RSS.
- GitHub Pages deployment, optional IndexNow and Search Console sitemap notifications, optional Telegram/Facebook/Pinterest sharing, and an optional weekly Search Console report.
- `AUTO_PUBLISH=False` by default. Review every claim, source, link, and generated image before publication.

## 1. Set up Python and the project

This project lives in `bilalbill-site/` inside the repository. Open a terminal in that folder:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env`. Set the correct niche, language, author, email, and seed phrases before research. The example uses `technology` and `en-PK`; change those if the site will cover another subject or primarily Urdu. Put credentials only in `.env` locally and GitHub Actions secrets in production. Never commit `.env`, API keys, or the Search Console private key.

For Gemini, create an API key in Google AI Studio and set `GEMINI_API_KEY`. Gemini free-tier access, model availability, and quotas can change; generation stops with a clear error if there is no key or available quota. The requested model is `gemini-2.0-flash`.

## 2. Research, generate, and review

```powershell
python main.py --research
python main.py --generate
python main.py --build
python main.py --all --dry-run
```

Research uses the public Autosuggest endpoint with a one-second pause between requests. A seed expands into alphabet and question/price variants, so one research run may take a few minutes. The keyword database is `data/bilalbill.sqlite3`.

`--generate` writes a Markdown article to `content/posts/` with `status: draft`, unless you explicitly change `AUTO_PUBLISH`. Generation requires available keywords and `GEMINI_API_KEY`. Verify each `verify_before_publish` note against reliable, current sources; edit the article and metadata yourself. Generated copy, factual accuracy, originality, and SEO results are not guaranteed.

Publish one reviewed draft by its filename slug:

```powershell
python main.py publish your-article-slug
```

For bulk publishing, first edit each reviewed draft's frontmatter to include `reviewed: true`, then run:

```powershell
python main.py publish --all-reviewed
python main.py --build
```

The explicit `publish <slug>` command is itself the editor's approval. `publish --all-reviewed` only selects drafts you have marked `reviewed: true`. `--build` includes **only** `status: published` articles. Unpublished titles are listed in `build/drafts-report.html`, which is not copied into the deployable site.

`--dry-run` prints intended actions without making network calls or changing files or the database. `--all` runs research, generation, and build; deployment, social sharing, indexing, and reporting are separate opt-in flags.

## 3. Preview the static site

```powershell
python main.py --build
python -m http.server 8000 --directory public
```

Open `http://127.0.0.1:8000`. The source templates and styling are in `templates/` and `static/`. Static pages live in `content/pages/`. Review the About, Contact, Privacy, and Disclaimer pages and replace the example contact email if needed.

## 4. Deploy free with GitHub Pages

The GitHub Actions workflow must be at the repository-level path `.github/workflows/daily.yml` (provided here), because GitHub does not run workflows stored inside a nested project directory.

1. Push the repository to GitHub and add the repository secret `GEMINI_API_KEY`. Add `INDEXNOW_KEY` and `GSC_SERVICE_ACCOUNT_JSON` as secrets if using those integrations.
2. A repository administrator must open **Settings → Pages** and choose **GitHub Actions** as the build/deploy source, then add the Actions repository variable `BILALBILL_PAGES_ENABLED=true`. This account currently has push access only. Until the administrator completes these steps, the scheduled workflow can research, generate drafts, and build, but it will not try to deploy.
3. By default the workflow serves this project at `https://israinsols.github.io/ai-website-automation/`. It sets `SITE_BASE_PATH=/ai-website-automation` so static assets and internal links work on that project URL. Configure optional repository **Variables** listed below. Keep `AUTO_PUBLISH` false; the workflow deliberately forces it off.
4. Open **Actions → bilalbill daily static site → Run workflow** once. The scheduled job runs daily, researches keywords, generates drafts when `GEMINI_API_KEY` is configured, builds, and deploys. Without that key it warns and deploys the current site without new drafts. It also runs a weekly report when explicitly enabled.
5. Generated drafts and keyword state are committed back to the repository. Review/approve a draft, push your content change, then manually run the workflow to publish the updated site. The daily job alone does not publish drafts.

Optional repository variables: `BILALBILL_PAGES_ENABLED` (`true` only after a repository admin enables Pages), `BILALBILL_HOSTING` (`cloudflare` to skip GitHub Pages deployment), `BILALBILL_BASE_PATH` (default `/ai-website-automation`; set to `/` only when using a root/custom domain), `BILALBILL_SITE_NAME`, `BILALBILL_SITE_DOMAIN`, `BILALBILL_SITE_NICHE`, `BILALBILL_SITE_LANGUAGE`, `BILALBILL_SITE_AUTHOR`, `BILALBILL_CONTACT_EMAIL`, `BILALBILL_POSTS_PER_DAY` (1-5), `BILALBILL_KEYWORD_SEEDS`, `GSC_SITE_URL`, `ENABLE_GSC_REPORT` (`true` to enable the weekly report), `SOCIAL_TELEGRAM`, `SOCIAL_FACEBOOK`, `SOCIAL_PINTEREST`, and `FACEBOOK_GRAPH_API_VERSION`.

The scheduled job uses free GitHub Actions minutes subject to GitHub's current account limits. Google AI Studio quotas and API policies are separate and may change. The workflow never purchases a plan or creates simulated search traffic.

When `bilalbill.com` DNS is ready, add `bilalbill.com` under **Settings → Pages → Custom domain**, configure the domain DNS records in the next section, and set the repository variable `BILALBILL_BASE_PATH=/`. Keep `BILALBILL_SITE_DOMAIN=bilalbill.com`. Then run the workflow again. The build will switch root-relative links back to `/` and include the `CNAME` file. Do not set `/` before the custom domain is connected.

### Cloudflare Pages alternative

GitHub Pages is the default target in the included workflow. To use Cloudflare Pages instead, keep the same GitHub Actions research/content workflow and set the repository variable `BILALBILL_HOSTING=cloudflare`; this skips the GitHub Pages deploy and post-deploy notification jobs. Then connect the repository under **Cloudflare → Workers & Pages → Create → Pages → Connect to Git**, and set:

- Build command: `cd bilalbill-site && python -m pip install -r requirements.txt && python main.py --build`
- Build output directory: `bilalbill-site/public`
- Environment variable: `SITE_DOMAIN=bilalbill.com` (plus any site name/niche settings you changed)
- Optional environment variable: `INDEXNOW_KEY` if you want the public key file included in the Cloudflare build.

The GitHub workflow commits newly generated drafts/content state; Cloudflare's Git integration rebuilds the published static output from that commit. Add `bilalbill.com` under the Pages project's **Custom domains** and follow Cloudflare's DNS prompts; do not point the same hostname at GitHub Pages and Cloudflare Pages at the same time. Cloudflare deployment is independent of the GitHub Pages artifact deployment. Since the included post-deploy notification job is GitHub-Pages-only, run `python main.py --index` and `python main.py --share` locally after Cloudflare confirms a deployment, if those features are enabled. Cloudflare's free-plan limits and included capabilities can change; no paid integration is required by this code.

## 5. Connect `bilalbill.com`

You must own/control the domain. In GitHub Pages, add `bilalbill.com` as the custom domain and enable HTTPS after DNS has propagated. At your DNS provider, create:

- Apex `A` records for `@`: `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, and `185.199.111.153`.
- Optional IPv6 `AAAA` records for `@`: `2606:50c0:8000::153`, `2606:50c0:8001::153`, `2606:50c0:8002::153`, and `2606:50c0:8003::153`.
- `CNAME` for `www` pointing to `<your-github-username>.github.io` (use your actual GitHub username).

DNS changes can take time. Do not remove unrelated DNS records without checking what they serve. The build writes a `CNAME` file from `SITE_DOMAIN`. Verify the custom domain and HTTPS in GitHub Pages before sharing it publicly.

## 6. Search Console and IndexNow

1. Add `bilalbill.com` as a **Domain property** in Google Search Console and verify it by adding Google's TXT record at your DNS provider.
2. After deployment, open `https://bilalbill.com/sitemap.xml` and submit that URL under **Sitemaps** in Search Console. Check the URL Inspection tool for the homepage and first published post.
3. For automatic sitemap submission and reports, create a Google Cloud service account, enable the Search Console API, and grant the account access to the verified Search Console property. Store the complete service-account JSON in the `GSC_SERVICE_ACCOUNT_JSON` GitHub secret (or local `.env`) and set `GSC_SITE_URL=sc-domain:bilalbill.com`.
4. Optionally create a random IndexNow key (for example, `python -c "import secrets; print(secrets.token_hex(16))"`), save it as `INDEXNOW_KEY` in GitHub secrets and `.env`, and run a deploy. The site publishes `<key>.txt` and after deployment submits its sitemap URLs to IndexNow. IndexNow is a notification, not a promise of indexing or ranking.
5. To run Search Console reporting weekly, set `ENABLE_GSC_REPORT=true` as a repository variable and configure `GSC_SERVICE_ACCOUNT_JSON`. The report creates `reports/search-console-weekly.csv` and prioritizes queries averaging positions 8-20 in the keyword database. The report is local/CI output and is not committed.

Google's old unauthenticated sitemap-ping URL is deprecated; this project uses the Search Console API when configured and otherwise tells you to submit the sitemap in Search Console.

## 7. Optional social distribution

Sharing is disabled by default, uses official APIs, and only shares published articles once per platform. Configure credentials as GitHub Actions secrets and set the matching `SOCIAL_*` repository variable to `true`. Caption generation uses the Gemini key.

- **Telegram:** create a bot with BotFather, add it as an administrator to your channel, then set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHANNEL_ID`.
- **Facebook Page:** create a Meta app with the Page publishing permission, obtain a valid Page access token, and set `FACEBOOK_PAGE_ID` and `FACEBOOK_PAGE_ACCESS_TOKEN`. Review Meta's current permission/app-review rules and token expiry.
- **Pinterest:** create an app with permission to publish Pins, then set `PINTEREST_ACCESS_TOKEN` and the destination `PINTEREST_BOARD_ID`.

Never put personal account passwords or API tokens in source files. Disable any platform flag until its credential and permission setup is complete. Sharing is not paid promotion and does not guarantee referral visits.

## 8. Local scheduling and maintenance

GitHub Actions is the included scheduler; it runs the research/generation/build workflow daily. For local scheduling, use Windows Task Scheduler to run `python main.py --all` from this project folder, with the virtual environment's Python executable and required environment variables. Do not create unattended publishing unless an editor intentionally accepts that risk.

Useful commands:

```powershell
python main.py --research
python main.py --generate
python main.py --build
python main.py --share
python main.py --report
python main.py --index
python main.py --deploy
pytest -q
```

`--deploy` dispatches the GitHub workflow with the GitHub CLI (`gh auth login` first); the Actions tab is also available.

## Day 1 launch checklist

- [ ] Confirm the homepage title contains **bilalbill** and update the niche/language if necessary.
- [ ] Review the About, Contact, Privacy, and Disclaimer pages and contact email.
- [ ] Add the domain to GitHub Pages, configure DNS, and confirm HTTPS.
- [ ] Verify the domain property in Search Console.
- [ ] Deploy and submit `https://bilalbill.com/sitemap.xml`.
- [ ] Add an IndexNow key, deploy, and confirm `https://bilalbill.com/<key>.txt` is reachable.
- [ ] Research keywords and create five draft posts across separate `--generate` runs.
- [ ] Verify facts, sources, originality, links, titles, and descriptions; publish the first five posts only after human review.
- [ ] Check the homepage, mobile layout, canonical URLs, RSS, robots.txt, and Search Console coverage after deployment.

## Test and example output

From this directory, run `pytest -q`. A dry-run example:

```text
DRY RUN — no network calls or files/database changes.
- Would research 3 seed(s) with polite Autosuggest requests.
- Would generate up to 1 Gemini draft(s) (AUTO_PUBLISH=False).
- Would build static pages from published content only.
- Published markdown files available: 0.
```

Example build output:

```text
public/
  index.html
  404.html
  about/index.html
  contact/index.html
  privacy/index.html
  disclaimer/index.html
  robots.txt
  sitemap.xml
  rss.xml
  CNAME
  static/site.css
  static/favicon.svg
  static/og-default.png
  images/<published-slug>.png
  images/<published-slug>-thumb.webp
  <published-slug>/index.html
  category/<category>/index.html
  tag/<tag>/index.html
build/drafts-report.html  # local only; never deployed
```
