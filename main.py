import argparse
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
from datetime import date, datetime
from urllib.parse import urlparse

from dotenv import load_dotenv
from groq import Groq
import requests


ROOT = Path(__file__).resolve().parent
KEYWORDS_PATH = ROOT / "keywords.json"
STATE_PATH = ROOT / "data" / "used_keywords.json"
INDEXNOW_URL = "https://api.indexnow.org/indexnow"
DEFAULT_MODEL = "openai/gpt-oss-120b"
ALLOWED_TAGS = {"h1", "h2", "h3", "p", "ul", "li", "strong", "em"}
BLOCKED_TAGS = {"script", "style", "iframe", "object"}


class ArticleHTMLParser(HTMLParser):
    """Keep article markup to a small, safe set of semantic HTML tags."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.open_tags = []
        self.blocked_tags = []

    def handle_starttag(self, tag, attrs):
        if self.blocked_tags:
            if tag in BLOCKED_TAGS:
                self.blocked_tags.append(tag)
            return
        if tag in BLOCKED_TAGS:
            self.blocked_tags.append(tag)
        elif tag in ALLOWED_TAGS:
            self.parts.append(f"<{tag}>")
            self.open_tags.append(tag)

    def handle_endtag(self, tag):
        if self.blocked_tags:
            if tag == self.blocked_tags[-1]:
                self.blocked_tags.pop()
            return
        if tag not in ALLOWED_TAGS or tag not in self.open_tags:
            return
        while self.open_tags:
            open_tag = self.open_tags.pop()
            self.parts.append(f"</{open_tag}>")
            if open_tag == tag:
                break

    def handle_data(self, data):
        if not self.blocked_tags:
            self.parts.append(html.escape(data, quote=False))

    def result(self):
        while self.open_tags:
            self.parts.append(f"</{self.open_tags.pop()}>")
        return "".join(self.parts).strip()


class PlainTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def article_text(article_html):
    parser = PlainTextParser()
    parser.feed(article_html)
    return " ".join(" ".join(parser.parts).split())


def required_env(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def load_keywords():
    try:
        data = json.loads(KEYWORDS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read {KEYWORDS_PATH.name}: {exc}") from exc

    keywords = data.get("keywords") if isinstance(data, dict) else data
    if not isinstance(keywords, list) or not keywords:
        raise RuntimeError("keywords.json must contain a non-empty JSON array of strings.")
    if any(not isinstance(item, str) or not item.strip() for item in keywords):
        raise RuntimeError("Every keyword in keywords.json must be a non-empty string.")

    normalized = [item.strip() for item in keywords]
    if len({item.casefold() for item in normalized}) != len(normalized):
        raise RuntimeError("keywords.json contains duplicate keywords (ignoring case).")
    return normalized


def load_state(keywords):
    try:
        state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        state = {"cycle": 1, "used_keywords": []}
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read keyword usage log: {exc}") from exc

    used = state.get("used_keywords", [])
    if not isinstance(used, list):
        raise RuntimeError("The used-keyword log is malformed; expected a used_keywords array.")
    available = {keyword.casefold() for keyword in keywords}
    state["cycle"] = int(state.get("cycle", 1))
    state["used_keywords"] = [item for item in used if isinstance(item, str) and item.casefold() in available]
    return state


def choose_keyword(keywords, state):
    used = {keyword.casefold() for keyword in state["used_keywords"]}
    for keyword in keywords:
        if keyword.casefold() not in used:
            return keyword
    return keywords[0]


def record_keyword(keywords, state, keyword):
    used = {item.casefold() for item in state["used_keywords"]}
    if all(item.casefold() in used for item in keywords):
        state["cycle"] += 1
        state["used_keywords"] = []
    state["used_keywords"].append(keyword)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = STATE_PATH.with_suffix(".tmp")
    temporary_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(STATE_PATH)


def response_schema():
    return {
        "article_title": "string: headline used for the article h1",
        "meta_title": "string: SEO title, maximum 60 characters",
        "meta_description": "string: SEO description, maximum 155 characters",
        "article_html": "string: complete article HTML, including one h1",
    }


def generate_article(client, keyword):
    model_id = os.getenv("GROQ_MODEL", DEFAULT_MODEL).strip() or DEFAULT_MODEL
    sections = [
        "Write the introduction followed by exactly two h2 sections. Include the keyword exactly once in the introduction, within its first 100 words. Return article_title, meta_title, meta_description, and article_html. The article_title must contain the keyword; metadata limits are 60 and 155 characters.",
        "Continue the same article with exactly three new h2 sections and no h1. Do not repeat the keyword in this segment. Return a JSON object with only article_html.",
        "Continue with exactly two new h2 sections and a useful conclusion, no h1. Include the keyword exactly once naturally. Return a JSON object with only article_html.",
    ]
    html_segments = []
    article = None

    for segment_index, section_instruction in enumerate(sections):
        prior_context = "\n".join(html_segments)[-3500:]
        prompt = f"""Write segment {segment_index + 1} of 3 for an original, useful SEO article about the exact keyword {keyword!r}.

{section_instruction}

This segment must contain 320-450 words of article text; aim for about 370 words. Use clean HTML tags only: h1, h2, h3, p, ul, li, strong, em. Write specific, practical detail. Do not use markdown, code fences, CSS, or scripts. Avoid fabricated statistics or citations.
Previously generated article context, for continuity only:
{prior_context or "No earlier sections."}

Return valid JSON only. Use JSON-escaped strings. The article_html value must contain this segment's HTML."""

        last_error = None
        segment = None
        for attempt in range(3):
            try:
                completion = client.chat.completions.create(
                    model=model_id,
                    messages=[
                        {"role": "system", "content": "You are an experienced SEO editor. Return only the requested JSON object."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.65,
                    max_completion_tokens=3000,
                    reasoning_effort="low",
                    response_format={"type": "json_object"},
                )
                segment = json.loads(completion.choices[0].message.content)
                html_value = sanitize_article_html(segment["article_html"])
                word_count = len(re.findall(r"\b[\w’'-]+\b", article_text(html_value), flags=re.UNICODE))
                if not 320 <= word_count <= 450:
                    raise RuntimeError(f"Segment has {word_count} words; expected 320-450.")
                segment["article_html"] = html_value
                break
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    prompt += f"\nThe previous response failed: {exc}. Return the requested valid JSON with 320-450 words of HTML text."
        else:
            raise RuntimeError(f"Groq could not generate article segment {segment_index + 1}: {last_error}") from last_error

        if segment_index == 0:
            article = {key: segment.get(key, "") for key in ("article_title", "meta_title", "meta_description")}
        html_segments.append(segment["article_html"])

    article["article_html"] = "\n".join(html_segments)
    validate_article(article, keyword)
    return article


def sanitize_article_html(value):
    if not isinstance(value, str):
        raise RuntimeError("Groq response article_html must be a string.")
    value = re.sub(r"^\s*```(?:html)?\s*|\s*```\s*$", "", value, flags=re.IGNORECASE)
    parser = ArticleHTMLParser()
    parser.feed(value)
    parser.close()
    cleaned = parser.result()
    if not cleaned:
        raise RuntimeError("Groq response did not contain usable article HTML.")
    return cleaned


def keyword_occurrences(text, keyword):
    return len(list(re.finditer(re.escape(keyword), text, flags=re.IGNORECASE)))


def validate_article(article, keyword):
    required = {"article_title", "meta_title", "meta_description", "article_html"}
    if not isinstance(article, dict) or not required.issubset(article):
        raise RuntimeError("Groq response is missing one or more required article fields.")
    for key in required:
        if not isinstance(article[key], str) or not article[key].strip():
            raise RuntimeError(f"Groq response field {key} must be a non-empty string.")

    title = article["article_title"].strip()
    meta_title = article["meta_title"].strip()
    meta_description = article["meta_description"].strip()
    headings = re.findall(r"<h1>(.*?)</h1>", article["article_html"], flags=re.IGNORECASE | re.DOTALL)
    if len(headings) != 1 or article_text(headings[0]).casefold() != title.casefold():
        raise RuntimeError("Article HTML must contain exactly one h1 matching article_title.")
    body_html = re.sub(r"<h1>.*?</h1>", "", article["article_html"], count=1, flags=re.IGNORECASE | re.DOTALL)
    text = article_text(body_html)
    words = re.findall(r"\b[\w’'-]+\b", text, flags=re.UNICODE)
    if not 900 <= len(words) <= 1300:
        raise RuntimeError(f"Article has {len(words)} words; expected 900-1300.")
    if len(meta_title) > 60:
        raise RuntimeError(f"Meta title has {len(meta_title)} characters; maximum is 60.")
    if len(meta_description) > 155:
        raise RuntimeError(f"Meta description has {len(meta_description)} characters; maximum is 155.")
    if any(keyword.casefold() not in value.casefold() for value in (title, meta_title, meta_description)):
        raise RuntimeError("The keyword must appear in the article title, meta title, and meta description.")
    first_100_words = " ".join(words[:100])
    if keyword.casefold() not in first_100_words.casefold():
        raise RuntimeError("The keyword must appear in the first 100 body words.")
    occurrences = keyword_occurrences(text, keyword)
    if not 3 <= occurrences <= 4:
        raise RuntimeError(f"The keyword appears {occurrences} times in the body; expected 3-4.")


def publish_article(site_url, token, article):
    endpoint = f"{site_url.rstrip('/')}/wp-json/wp/v2/posts"
    payload = {
        "title": article["meta_title"],
        "content": article["article_html"],
        "excerpt": article["meta_description"],
        "status": "publish",
    }
    try:
        response = requests.post(
            endpoint,
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        post_url = data.get("link")
        if not post_url:
            raise RuntimeError("WordPress reported success but did not return the new post URL.")
        return post_url
    except requests.RequestException as exc:
        detail = getattr(exc.response, "text", "") if getattr(exc, "response", None) is not None else str(exc)
        raise RuntimeError(f"WordPress publishing failed: {detail[:1000]}") from exc
    except (ValueError, KeyError) as exc:
        raise RuntimeError(f"Could not parse the WordPress publish response: {exc}") from exc


def ping_indexnow(post_url, key):
    parsed_url = urlparse(post_url)
    payload = {"host": parsed_url.netloc, "key": key, "url": post_url}
    key_location = os.getenv("INDEXNOW_KEY_LOCATION", "").strip()
    if key_location:
        payload["keyLocation"] = key_location
    try:
        response = requests.post(INDEXNOW_URL, json=payload, timeout=20)
        response.raise_for_status()
    except requests.RequestException as exc:
        detail = getattr(exc.response, "text", "") if getattr(exc, "response", None) is not None else str(exc)
        raise RuntimeError(f"IndexNow ping failed for the published URL: {detail[:1000]}") from exc


def run_once():
    load_dotenv(ROOT / ".env")
    groq_key = required_env("GROQ_API_KEY")
    test_mode = os.getenv("TEST_MODE", "0").strip() == "1"
    if not test_mode:
        site_url = required_env("WP_SITE_URL")
        wp_token = required_env("WP_AUTH_TOKEN")
        indexnow_key = required_env("INDEXNOW_KEY")
    else:
        site_url = wp_token = indexnow_key = None

    keywords = load_keywords()
    state = load_state(keywords)
    keyword = choose_keyword(keywords, state)
    print(f"Generating article for keyword: {keyword}")

    try:
        client = Groq(api_key=groq_key, timeout=90, max_retries=2)
        article = generate_article(client, keyword)
    except Exception as exc:
        raise RuntimeError(f"Article generation failed: {exc}") from exc

    record_keyword(keywords, state, keyword)
    word_count = len(re.findall(r"\b[\w’'-]+\b", article_text(article["article_html"])))
    print(f"Generated {word_count} words.")

    if test_mode:
        print("\nTEST_MODE=1: article generated; WordPress publishing and IndexNow were skipped.\n")
        print(json.dumps(article, ensure_ascii=False, indent=2))
        return

    post_url = publish_article(site_url, wp_token, article)
    print(f"Published: {post_url}")
    try:
        ping_indexnow(post_url, indexnow_key)
        print("IndexNow accepted the URL.")
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)


def scheduled_loop(publish_time):
    try:
        datetime.strptime(publish_time, "%H:%M")
    except ValueError as exc:
        raise RuntimeError("PUBLISH_TIME must use 24-hour HH:MM format, for example 09:00.") from exc
    print(f"Daily scheduler active. Next publish time: {publish_time} local time.")
    last_run = None
    while True:
        now = datetime.now()
        if now.strftime("%H:%M") == publish_time and last_run != date.today():
            last_run = date.today()
            try:
                run_once()
            except Exception as exc:
                print(f"Scheduled run failed: {exc}", file=sys.stderr)
        time.sleep(20)


def main():
    parser = argparse.ArgumentParser(description="Generate and publish an SEO article with Groq and WordPress.")
    parser.add_argument("--schedule", action="store_true", help="Run daily at PUBLISH_TIME (default 09:00).")
    args = parser.parse_args()
    load_dotenv(ROOT / ".env")
    if args.schedule:
        scheduled_loop(os.getenv("PUBLISH_TIME", "09:00").strip())
    else:
        run_once()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)