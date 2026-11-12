#!/usr/bin/env python3
"""Collect candidate AI news for one issue of AI 每日简报.

Fetches official blogs, aggregators, Hacker News and trending repos, keeps events whose
own publish time falls in the collection window, merges reports of the same event across
sources, and flags events that the last 7 days of issues already covered.

Writes, under work/:
  candidates-DATE.md     read this; grouped by 窗口内 / 待核实日期 / 窗口外
  candidates-DATE.json   same data for scripts
  run-DATE.json          run log: cutoff (UTC + Beijing), window, rules version, per-source status

Usage, from the repo root:
  python3 -I skill/ai-daily/scripts/collect.py [--date 2026-11-11] [--hours 36] [--now ISO]
Standard library only; Python 3.9+.

Time model. Every item carries up to three times, kept apart:
  event_time    when the thing happened: the primary page's datePublished, or the feed's own
                pubDate when the feed IS the primary source
  article_time  when the source article that mentioned it was published (aggregators)
  fetched_at    when we fetched it
An aggregator's pubDate is never used as the event time. Items without an event time go to
the 待核实 queue instead of being dropped or assumed current.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import email.utils
import gzip
import html
import json
import pathlib
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zlib

RULES_VERSION = "2026-11-12"  # bump when SOURCES, clustering or window rules change
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
UTC, BJ = dt.timezone.utc, dt.timezone(dt.timedelta(hours=8))
AI_WORDS = re.compile(r"\b(AI|LLMs?|GPT[\w.-]*|Claude|Gemini|OpenAI|Anthropic|DeepMind|agents?|"
                      r"agentic|DeepSeek|Qwen|Kimi|Mistral|Llama|Grok|Codex|Cursor|MCP|RAG|"
                      r"diffusion|transformers?|inference|embeddings?|fine-?tun\w*|"
                      r"copilot|chatbot|neural|machine learning|deep learning|"
                      r"text-to-\w+|generative)\b", re.I)
HOURS = 36
FUTURE_SLACK = dt.timedelta(minutes=10)   # clock skew tolerance; anything later is "future"
RETRIES = 2                               # extra attempts after the first (3 total)
NOW = None                                # set in main(); tests may inject
PRIMARY_DATE_BUDGET = 40                  # max primary pages fetched per run for dates

# Hosts whose pages count as official first-party sources. Matched on exact host or a
# subdomain of it (never substring), so "notopenai.com" or "openai.com.evil.net" fail.
OFFICIAL_HOSTS = [
    "openai.com", "anthropic.com", "claude.com", "deepmind.google", "blog.google", "google.com",
    "googleblog.com", "ai.google", "developer.chrome.com", "antigravity.google", "mistral.ai",
    "huggingface.co", "meta.com", "ai.meta.com", "microsoft.com", "x.ai", "nvidia.com",
    "developer.nvidia.com", "blogs.nvidia.com", "amazon.science", "aws.amazon.com", "apple.com",
    "machinelearning.apple.com", "deepseek.com", "api-docs.deepseek.com", "moonshot.cn", "kimi.com",
    "qwen.ai", "qwenlm.github.io", "qwencloud.com", "alibabacloud.com", "minimax.io", "minimaxi.com", "zhipuai.cn",
    "z.ai", "bytedance.com", "seed.bytedance.com", "ernie.baidu.com", "baidu.com", "runway.com", "runwayml.com",
    "cursor.com", "cognition.ai", "elevenlabs.io",
    "arxiv.org", "tailscale.com", "stripe.com", "vercel.com", "cloudflare.com", "figma.com",
    "adobe.com", "perplexity.ai", "together.ai", "fireworks.ai", "groq.com", "cohere.com",
    "sakana.ai", "ideogram.ai", "pika.art", "lumalabs.ai", "midjourney.com",
    "openrouter.ai", "github.blog", "githubnext.com",
]
# GitHub organisations whose repos count as official. Any other repo is community code.
OFFICIAL_GH_ORGS = {
    "openai", "anthropics", "google", "google-deepmind", "googlechrome", "google-gemini",
    "googleapis", "huggingface", "facebookresearch", "meta-llama", "meta", "microsoft", "nvidia",
    "nvidia-nemo", "deepseek-ai", "moonshotai", "qwenlm", "alibaba", "minimaxai", "zai-org",
    "thudm", "bytedance", "mistralai", "xai-org", "apple", "aws", "awslabs", "amazon-science",
    "vercel", "vercel-labs", "cloudflare", "stripe", "tailscale", "elevenlabs", "modelcontextprotocol",
    "anthropic", "cognition-ai", "cursor",
}


# ---------- fetching ----------
class FetchError(Exception):
    def __init__(self, msg, status=None, ctype=None, snippet=""):
        super().__init__(msg)
        self.status, self.ctype, self.snippet = status, ctype, snippet


def _decode(raw, headers):
    enc = (headers.get("Content-Encoding") or "").lower()
    if enc == "gzip" or raw[:2] == b"\x1f\x8b":          # some servers gzip and don't say so
        raw = gzip.decompress(raw)
    elif enc == "deflate":
        raw = zlib.decompress(raw, -zlib.MAX_WBITS) if raw[:1] != b"\x78" else zlib.decompress(raw)
    elif enc == "br":
        raise FetchError("brotli encoding not supported by stdlib", ctype=headers.get("Content-Type"))
    return raw.decode("utf-8", "replace")


def get(url, timeout=20, retries=RETRIES):
    """GET with transparent gzip/deflate handling and bounded retries on transient errors."""
    last = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return _decode(r.read(), r.headers)
        except urllib.error.HTTPError as e:
            body = e.read()[:200] if e.fp else b""
            last = FetchError(f"HTTP {e.code}", e.code, e.headers.get("Content-Type"),
                              body.decode("utf-8", "replace").replace("\n", " "))
            if e.code in (401, 403, 404, 410):   # not transient; do not hammer or try to bypass
                raise last
        except (urllib.error.URLError, TimeoutError, OSError, EOFError, zlib.error) as e:
            last = FetchError(f"{type(e).__name__}: {str(e)[:80]}")
        if attempt < retries:
            time.sleep(1.5 * (attempt + 1))
    raise last


def parse_xml(s, what="feed"):
    try:
        return ET.fromstring(s)
    except ET.ParseError as e:
        head = s[:60].replace("\n", " ")
        raise FetchError(f"XML parse error ({e}); response starts with {head!r}", snippet=head)


# ---------- text / time helpers ----------
def text(s, n=None):
    s = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()
    return s[:n].rstrip() + "…" if n and len(s) > n else s


def when(s):
    """Parse RFC 2822 / ISO 8601. Returns (datetime_utc, precision) or (None, None).
    precision: 'minute' when a time of day was given, 'day' when only a date was."""
    if not s:
        return None, None
    s = s.strip()
    precision = "day" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else "minute"
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError, IndexError):
        try:
            d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s)
            if not m:
                return None, None
            d, precision = dt.datetime(*map(int, m.groups())), "day"
    if d.tzinfo is None:
        d = d.replace(tzinfo=UTC)   # date-only: midnight UTC as a lower bound, precision says so
    d = d.astimezone(UTC)
    if precision == "minute" and d.hour == d.minute == d.second == 0:
        precision = "day"           # "2026-11-10T00:00:00Z" is how most CMSes write a date-only stamp
    return d, precision


def now_utc():
    return NOW or dt.datetime.now(UTC)


def host_of(url):
    try:
        return (urllib.parse.urlsplit(url).hostname or "").lower().removeprefix("www.")
    except ValueError:
        return ""


def is_official(url):
    """True only for exact official hosts / their subdomains, or repos under official GitHub orgs."""
    h = host_of(url)
    if not h:
        return False
    if h == "github.com":
        m = re.match(r"^/([^/]+)/", urllib.parse.urlsplit(url).path)
        return bool(m) and m.group(1).lower() in OFFICIAL_GH_ORGS
    return any(h == o or h.endswith("." + o) for o in OFFICIAL_HOSTS)


def item(src, title, url, event_time=None, summary="", aliases=(), note="", merge=True,
         article_time=None, precision=None):
    """One mention of an event by one source. merge=False keeps a sub-topic from joining
    clusters by URL (it shares its parent's URL)."""
    return {"source": src["name"], "tier": src["tier"], "title": text(title), "url": url,
            "event_time": event_time, "precision": precision, "article_time": article_time,
            "fetched_at": now_utc(), "summary": text(summary, 180), "aliases": list(aliases),
            "note": note, "merge": merge, "primary": src["tier"] == 1}


def local(tag):
    return tag.rsplit("}", 1)[-1]


# ---------- source parsers ----------
def feed(src):
    root, out = parse_xml(get(src["url"])), []
    primary = src["tier"] == 1
    for e in root.iter():
        if local(e.tag) not in ("item", "entry"):
            continue
        f = {}
        for c in e:
            f.setdefault(local(c.tag), c)
        link = f.get("link")
        url = ((link.get("href") or link.text or "") if link is not None else "").strip()
        d, prec = next(((w, p) for w, p in (when(f[k].text) for k in ("pubDate", "published", "updated", "date")
                                           if k in f and f[k].text) if w), (None, None))
        body = next((f[k].text for k in ("encoded", "description", "summary", "content")
                     if k in f and f[k].text), "")
        t = f["title"].text if "title" in f else ""
        if src.get("filter") and not AI_WORDS.search(f"{t} {text(body, 300)}"):
            continue
        # Official feed: its pubDate is the event time. Aggregator: it is only the article time.
        out.append(item(src, t, url, d if primary else None, body,
                        article_time=None if primary else d, precision=prec if primary else None))
        if src.get("topics") and "AINews" in (t or ""):
            # each AINews issue covers many events; its headings are separate signals
            for h in re.findall(r"<h[34][^>]*>(.*?)</h[34]>|<p><strong>([^<]{12,100})</strong>",
                                body or "", re.S):
                ht = re.sub(r"^\d+\.\s*", "", text(h[0] or h[1])).rstrip(":： ")
                if len(ht) > 10:
                    out.append(item(src, ht, url, None, note="AINews 小标题", merge=False, article_time=d))
    return out


def juya(src):
    """橘鸦 AI 早报: ~30 Chinese one-liners a day, each with links to its original sources.
    Detail blocks are <h3>…<code>#N</code></h3>; section names are <h2>/<h3> without '#N'.
    A detail heading may have no link (e.g. an IPO item), so '#N' decides, not the <a>."""
    root, out = parse_xml(get(src["url"])), []
    for e in root.iter("item"):
        art, _ = when(e.findtext("pubDate"))
        body = (e.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
                or e.findtext("description") or "")
        section = ""
        for m in re.finditer(r"<h([23])[^>]*>(.*?)</h\1>(.*?)(?=<h[23][\s>]|\Z)", body, re.S):
            head, rest = m.group(2), m.group(3)
            num = re.search(r"<code>#(\d+)</code>", head)
            if not num:
                section = text(head)
                continue
            a = re.search(r'<a href="(https?://[^"]+)"[^>]*>(.*?)</a>', head, re.S)
            title = text(a.group(2) if a else re.sub(r"<code>.*?</code>", "", head))
            links = [u for u in re.findall(r'href="(https?://[^"]+)"', rest) if "juya.uk" not in u]
            url = a.group(1) if a else (links[0] if links else "")
            if not url:
                continue   # nothing to verify against; the overview list repeats these anyway
            q = re.search(r"<blockquote>(.*?)</blockquote>", rest, re.S)
            out.append(item(src, title, url, None, q.group(1) if q else rest,
                            [u for u in links if u != url], f"{section} #{num.group(1)}".strip(),
                            article_time=art))
    return out


def sitemap(src):
    """Sites without a feed but with <lastmod> in their sitemap (anthropic.com). lastmod is
    the page's last modification, not publication: use it only to pick recent URLs, then
    read datePublished from each page."""
    root = parse_xml(get(src["url"]))
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    rows = []
    for u in root.findall("s:url", ns):
        loc, lm = u.findtext("s:loc", "", ns).strip(), u.findtext("s:lastmod", "", ns)
        if re.search(src["paths"], urllib.parse.urlsplit(loc).path):
            d, _ = when(lm)
            rows.append((d or dt.datetime.min.replace(tzinfo=UTC), loc))
    cutoff = now_utc() - dt.timedelta(hours=HOURS + 48)   # lastmod lags; look a bit wider
    recent = [loc for d, loc in sorted(rows, reverse=True) if d >= cutoff][:src.get("max", 20)]

    def one(url):
        meta = page_meta(url)
        if not meta.get("title"):
            return None
        return item(src, meta["title"], url, meta.get("published"), meta.get("description", ""),
                    precision=meta.get("precision"))

    with cf.ThreadPoolExecutor(6) as ex:
        return [x for x in ex.map(one, recent) if x]


def listing(src):
    """A plain HTML index page that links to articles (claude.com/resources/articles)."""
    page = get(src["url"])
    seen, urls = set(), []
    for m in re.finditer(src["pattern"], page):
        u = urllib.parse.urljoin(src["url"], m.group(1))
        if u not in seen:
            seen.add(u)
            urls.append(u)

    def one(url):
        meta = page_meta(url)
        if not meta.get("title"):
            return None
        return item(src, meta["title"], url, meta.get("published"), meta.get("description", ""),
                    precision=meta.get("precision"))

    with cf.ThreadPoolExecutor(6) as ex:
        return [x for x in ex.map(one, urls[:src.get("max", 16)]) if x]


def page_meta(url):
    """Title / description / published time from a page's meta tags or JSON-LD. Cached per run."""
    if url in _META:
        return _META[url]
    out = {}
    try:
        p = get(url, retries=1)
    except FetchError as e:
        _META[url] = {"error": str(e)}
        return _META[url]
    pat = r'<meta[^>]+(?:property|name)="%s"[^>]+content="([^"]*)"|<meta[^>]+content="([^"]*)"[^>]+(?:property|name)="%s"'
    def meta(k):
        m = re.search(pat % (re.escape(k), re.escape(k)), p, re.I)
        return html.unescape((m.group(1) if m.group(1) is not None else m.group(2)) or "") if m else ""
    out["title"] = meta("og:title") or text((re.search(r"<title[^>]*>(.*?)</title>", p, re.S) or [None, ""])[1])
    out["description"] = meta("og:description") or meta("description")
    raw = (meta("article:published_time") or
           (re.search(r'"datePublished"\s*:\s*"([^"]+)"', p) or [None, ""])[1] or
           (re.search(r'<time[^>]+datetime="(\d{4}-\d{2}-\d{2}[^"]*)"', p) or [None, ""])[1])
    d, prec = when(raw)
    if d:
        out["published"], out["precision"] = d, prec
    _META[url] = out
    return out


_META = {}


def hn(src):
    since = int(now_utc().timestamp()) - HOURS * 3600
    q = urllib.parse.urlencode({"tags": "story", "hitsPerPage": 100,
                                "numericFilters": f"points>{src['min_points']},created_at_i>{since}"})
    out = []
    for h in json.loads(get(src["url"] + "?" + q))["hits"]:
        if not AI_WORDS.search(h.get("title") or ""):
            continue
        disc = f"https://news.ycombinator.com/item?id={h['objectID']}"
        # HN's created_at is when it was posted to HN, i.e. an article time, not the event time
        x = item(src, h["title"], h.get("url") or disc, None,
                 note=f"HN {h['points']} 分 · {h.get('num_comments') or 0} 评论 · {disc}",
                 article_time=dt.datetime.fromtimestamp(h["created_at_i"], UTC))
        x["hn_points"] = h["points"]
        out.append(x)
    return out


NON_AI_REPO = re.compile(r"\b(stock|stocks|trading|crypto|bitcoin|blockchain|finance app|personal finance|"
                         r"all algorithms|algorithms implemented|interview|awesome-|tutorial|course|roadmap)\b", re.I)
AI_REPO = re.compile(r"\b(AI|LLMs?|agents?|agentic|coding agents?|copilot|claude|chatgpt|gpt|gemini|"
                     r"codex|cursor|mcp|rag|embedding|inference|model|models|transformer|diffusion|"
                     r"prompt|skills?)\b", re.I)


def repo_relevant(name, desc, topics=()):
    """AI-application relevance for Trending. Name, description and topics are judged together;
    a single 'model' in the description is not enough on its own; finance/algorithm-collection
    repos are out even if they mention LLMs."""
    blob = f"{name} {desc} {' '.join(topics)}"
    if NON_AI_REPO.search(blob):
        return False
    hits = set(h.lower() for h in AI_REPO.findall(blob))
    weak = {"model", "models", "prompt"}
    strong = hits - weak
    if strong:
        return True
    # only weak words: need two distinct ones, or a weak word in the repo name itself
    return len(hits) >= 2 or bool(AI_REPO.search(name) and hits)


def gh_trending(src):
    out = []
    for a in re.findall(r'<article class="Box-row">(.*?)</article>', get(src["url"]), re.S):
        name = re.search(r'<h2[^>]*>\s*<a[^>]*href="/([^/"]+/[^/"]+)"', a)
        if not name:
            continue
        desc = re.search(r'<p class="col-9[^"]*">(.*?)</p>', a, re.S)
        today = re.search(r"([\d,]+) stars today", a)
        total = re.search(r'href="/[^"]+/stargazers"[^>]*>(.*?)</a>', a, re.S)
        d = text(desc.group(1)) if desc else ""
        full = name.group(1)
        if not d and src.get("lookup", True):
            # empty description on the Trending page; the repo may still have one (or a homepage)
            try:
                r = json.loads(get(f"https://api.github.com/repos/{full}", retries=0))
                d = r.get("description") or ""
                topics = r.get("topics") or []
            except (FetchError, ValueError):
                topics = []
        else:
            topics = []
        if not repo_relevant(full, d, topics):
            continue
        out.append(item(src, full, "https://github.com/" + full, None, d,
                        note=f"今日 +{today.group(1) if today else '?'} star · 共 "
                             f"{text(total.group(1)) if total else '?'}"))
    return out


def hf_papers(src):
    out = []
    for p in json.loads(get(src["url"])):
        up = p["paper"].get("upvotes", 0)
        if up >= src["min_upvotes"]:
            d, prec = when(p["paper"].get("publishedAt") or p.get("publishedAt"))
            out.append(item(src, p["paper"]["title"], "https://huggingface.co/papers/" +
                            p["paper"]["id"], d, p["paper"].get("summary", ""),
                            note=f"HF 论文 {up} 赞", precision=prec))
    return out


# tier: 1 = 官方一手, 2 = 聚合 / 媒体（发现用，正文须回到一手来源）, 3 = 社区信号
SOURCES = [
    {"name": "OpenAI", "tier": 1, "kind": feed, "url": "https://openai.com/news/rss.xml"},
    {"name": "Anthropic", "tier": 1, "kind": sitemap, "url": "https://www.anthropic.com/sitemap.xml",
     "paths": r"^/(news|research|engineering)/[a-z0-9-]+/?$", "max": 24},
    {"name": "Claude", "tier": 1, "kind": listing, "url": "https://claude.com/resources/articles",
     "pattern": r'href="((?:https://claude\.com)?/resources/articles/[a-z0-9-]+)"', "max": 16},
    {"name": "Google DeepMind", "tier": 1, "kind": feed, "url": "https://deepmind.google/blog/rss.xml"},
    {"name": "Google AI", "tier": 1, "kind": feed, "url": "https://blog.google/technology/ai/rss/"},
    # the AI category feed misses some model posts (Gemini 4 Carbon, 2026-11-10); the全站 feed has them
    {"name": "Google 全站", "tier": 1, "kind": feed, "filter": True, "url": "https://blog.google/rss/"},
    {"name": "Hugging Face", "tier": 1, "kind": feed, "url": "https://huggingface.co/blog/feed.xml"},
    {"name": "Mistral", "tier": 1, "kind": feed, "url": "https://mistral.ai/news/rss"},
    {"name": "橘鸦 AI 早报", "tier": 2, "kind": juya, "url": "https://daily.juya.uk/rss.xml"},
    {"name": "Latent Space", "tier": 2, "kind": feed, "topics": True, "url": "https://www.latent.space/feed"},
    {"name": "The Rundown", "tier": 2, "kind": feed, "url": "https://www.therundown.ai/feed"},
    {"name": "Simon Willison", "tier": 2, "kind": feed, "filter": True,
     "url": "https://simonwillison.net/atom/everything/"},
    {"name": "TechCrunch AI", "tier": 2, "kind": feed,
     "url": "https://techcrunch.com/category/artificial-intelligence/feed/"},
    {"name": "The Verge AI", "tier": 2, "kind": feed,
     "url": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml"},
    {"name": "Hacker News", "tier": 3, "kind": hn, "min_points": 100,
     "url": "https://hn.algolia.com/api/v1/search_by_date"},
    {"name": "GitHub Trending", "tier": 3, "kind": gh_trending, "url": "https://github.com/trending"},
    {"name": "HF Daily Papers", "tier": 3, "kind": hf_papers, "min_upvotes": 20,
     "url": "https://huggingface.co/api/daily_papers?limit=50"},
]
# ---------- clustering ----------
STOP = set("""a an the and or of to in on for with by from at as is are be now new its it this that
how why what you your we our via vs into over up out after about than more can will just all
ai model models launch launches launched introducing introduces announces announced available
release released releases update updates open source opensource today first official
openai google anthropic deepmind meta microsoft amazon apple nvidia claude chatgpt
show hn ask""".split())
VERSION = re.compile(r"\b(?:v|version\s*)?(\d+(?:\.\d+)+)\b|\b(\d+(?:\.\d+)?)\s*(?:b|B|k|K|m|M)?\b")


CJK_STOP = set("正式 宣布 发布 推出 上线 开放 开源 升级 推进 可以 可用 已经 一个 这个 我们 他们 用户 模型 公司 "
               "服务 功能 支持 提供 进行 使用 通过 表示 认为 称其 以及 并且 或者 但是 因为 所以 对于 关于 "
               "最新 最强 全新 今日 本周 本月 今年 正在 即将 预计 据悉 消息 报道".split())


def latin_tokens(t):
    """Latin words / numbers only (product names, versions). Used for zh↔en pairs."""
    return {x for x in re.findall(r"[a-z][a-z0-9+-]*(?:\.[0-9]+)*|[0-9]+(?:\.[0-9]+)*", t.lower())
            if x not in STOP and (len(x) > 1 or x.isdigit())}


def key_tokens(t):
    """Informative tokens of a title: Latin words / numbers minus STOP, plus CJK character
    bigrams minus CJK_STOP. Without the bigrams a Chinese title such as
    「Tailscale OAuth apps 正式可用，Grok Bot 可访问内网 MCP 服务器」 reduces to a handful of
    Latin words, and any other title sharing two of them (「马斯克称 Grok Bot 服务成本…」)
    would clear the 2/3 overlap bar."""
    toks = latin_tokens(t)
    for run in re.findall(r"[一-鿿]{2,}", t):
        toks |= {run[i:i + 2] for i in range(len(run) - 1)} - CJK_STOP
    return toks


def has_cjk(t):
    return bool(re.search(r"[一-鿿]", t))


def similar_titles(a, b):
    """Token-overlap hint that two mentions are one event.
    Same script: full token sets (CJK bigrams included). Cross-script (zh vs en): only the
    Latin tokens can match, so compare those, and demand at least 3 on each side so that a
    pair like {grok, bot} alone cannot merge two different stories."""
    if has_cjk(a["title"]) != has_cjk(b["title"]):
        ka, kb, floor = a["_l"], b["_l"], 3
    else:
        ka, kb, floor = a["_k"], b["_k"], 2
    if len(ka) < floor or len(kb) < floor:
        return False
    inter = len(ka & kb)
    return inter >= 2 and inter / min(len(ka), len(kb)) >= 0.67


def versions(t):
    """Version-like numbers in a title (4.1, 5.5, 2.0). Different versions = different events."""
    return {m.group(1) for m in re.finditer(r"\b(?:v|version\s*)?(\d+\.\d+(?:\.\d+)?)\b", t.lower())}


def norm_url(u):
    """Canonical form for matching: host without www, path without trailing slash, no query/fragment,
    and a few known aliases (anthropic.com/claude-x == anthropic.com/news/claude-x is NOT assumed)."""
    try:
        p = urllib.parse.urlsplit((u or "").strip())
    except ValueError:
        return ""
    host = (p.hostname or "").lower().removeprefix("www.")
    path = re.sub(r"/+$", "", p.path or "")
    path = re.sub(r"\.html?$", "", path)
    if host == "github.com":                      # repo page, not deep links into it
        path = "/".join(path.split("/")[:3])
    return (host + path).lower()


def canonical_pairs(items):
    """Extra URL identities worth joining on: a GitHub repo and its homepage/blog post are the
    same project only when the page itself links to the repo, so we don't guess here. We do
    treat 'x.com/<org>/status/..' as non-identifying (never join on it)."""
    out = []
    for x in items:
        for u in [x["url"], *x["aliases"]]:
            n = norm_url(u)
            if not n or n.count("/") < 1:
                continue
            if re.match(r"^(x|twitter)\.com/", n) or re.match(r"^news\.ycombinator\.com/", n):
                continue
            out.append((n, x))
    return out


def cluster(items):
    """Union-find over (a) shared canonical URLs and (b) title-token overlap. Token overlap is
    only a hint: it needs 2 shared informative tokens and 2/3 of the smaller set, AND no
    conflicting version numbers, AND the pair must not both be the same official feed (two
    different posts from one feed are two events)."""
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i, j):
        parent[find(i)] = find(j)

    idx = {id(x): i for i, x in enumerate(items)}
    for x in items:
        x["_k"], x["_l"], x["_v"] = key_tokens(x["title"]), latin_tokens(x["title"]), versions(x["title"])
    by_url = {}
    for n, x in canonical_pairs(items):
        if not x["merge"]:
            continue
        i = idx[id(x)]
        if n in by_url:
            join(i, by_url[n])
        by_url.setdefault(n, i)
    for i, a in enumerate(items):
        for j in range(i):
            b = items[j]
            if len(a["_k"]) < 2 or len(b["_k"]) < 2:
                continue
            if a["_v"] and b["_v"] and a["_v"] != b["_v"]:
                continue                                   # Gemini 4.1 vs Gemini 4.2
            if a["primary"] and b["primary"] and a["source"] == b["source"] and norm_url(a["url"]) != norm_url(b["url"]):
                continue                                   # two posts from the same official feed
            if similar_titles(a, b):
                join(i, j)
    groups = {}
    for i, x in enumerate(items):
        groups.setdefault(find(i), []).append(x)
    return list(groups.values())


def covered(date, outputs, days=7):
    """URLs and title tokens from the issues of the previous `days` days."""
    urls, titles = set(), []
    for p in sorted(outputs.glob("AI-Daily-*.md")):
        m = re.search(r"\d{4}-\d{2}-\d{2}", p.name)
        d = dt.date.fromisoformat(m.group())
        if not (date - dt.timedelta(days=days) <= d < date):
            continue
        s = p.read_text(encoding="utf-8")
        urls |= {norm_url(u) for u in re.findall(r"\]\((https?://[^)\s]+)\)", s)}
        titles += [(d, key_tokens(t), t.strip()) for t in re.findall(r"^#{3,4} \d*\.?\s*(.+)$", s, re.M)]
    return urls, titles


def history(date, outputs, days=30):
    """Headlines from the last `days` issues, for placing today's events in their thread.
    Returns [(date, tokens, title, kind)] where kind is 要闻 / 快讯 / 开源."""
    rows = []
    for p in sorted(outputs.glob("AI-Daily-*.md")):
        m = re.search(r"\d{4}-\d{2}-\d{2}", p.name)
        d = dt.date.fromisoformat(m.group())
        if not (date - dt.timedelta(days=days) <= d < date):
            continue
        kind = ""
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                kind = "快讯" if "快讯" in line else "开源" if "开源" in line else "要闻"
                continue
            h = re.match(r"^### \d*\.?\s*(.+)$", line) if kind == "要闻" else \
                re.match(r"^\d+\.\s+\*\*(.+?)\*\*", line) if kind == "快讯" else \
                re.match(r"^\d+\.\s+项目名[：:]\s*(.+)$", line)
            if h:
                rows.append((d, key_tokens(h.group(1)), h.group(1).strip(), kind))
    return rows


COMMON_WORDS = {"gemini", "claude", "gpt", "openai", "google", "anthropic", "model", "models", "release",
                "api", "open", "source", "新模型", "发布", "推出", "上线", "agent", "agents", "agentic", "ai",
                "token", "tokens", "intelligence", "spaces", "space", "benchmark", "benchmarks", "preview",
                "launch", "introducing", "better", "faster", "fast", "with", "from", "your", "into",
                "multimodal", "language", "learning", "world", "real", "data", "code", "coding", "developers",
                "developer", "cloud", "pro", "flash", "max", "mini", "large", "small", "version", "update",
                "available", "general", "now", "new", "first", "next", "open-source", "opensource",
                "hugging", "face", "huggingface", "github", "microsoft", "meta", "amazon", "aws", "nvidia",
                "apple", "deepmind", "mistral", "alibaba", "阿里", "字节", "谷歌", "微软", "百度", "腾讯"}


def related(cand, hist, pool):
    """Earlier events in the same thread: past headlines (30 days) and out-of-window candidates
    from this run. A match needs two shared informative tokens, or one token that is specific
    enough (not a company name, not a generic AI word). This is a lead for the writer, not a verdict."""
    keys = set()
    for t in (cand["title"], cand["title_zh"], cand.get("summary", "")):
        keys |= {k for k in key_tokens(t) if len(k) >= 4 and not k.isdigit()}
    keys -= COMMON_WORDS
    if not keys:
        return []

    def strength(hit):
        return len(hit) if len(hit) >= 2 else (1 if any(len(k) >= 6 for k in hit) else 0)

    out = []
    for d, k, title, kind in hist:
        s = strength(keys & (k - COMMON_WORDS))
        if s:
            out.append((s, f"{d} 已写（{kind}）：{title}"))
    for p in pool:
        if p is cand or p["window"] not in ("stale", "unknown"):
            continue
        pk = (key_tokens(p["title"]) | key_tokens(p["title_zh"])) - COMMON_WORDS
        s = strength(keys & pk)
        if s:
            when_ = p["event_time_bj"] or p["article_time_bj"] or "日期未知"
            out.append((s, f"候选池窗口外 {when_}：{p['title'][:60]}"))
    out.sort(key=lambda x: -x[0])
    seen, res = set(), []
    for _, line in out:
        if line not in seen:
            seen.add(line)
            res.append(line)
    return res[:5]


# ---------- event time resolution ----------
def resolve_event_time(group, budget):
    """Best event time for a cluster. Order: an official feed/page time we already have; else
    datePublished of the first official-looking URL we are allowed to fetch (budget-limited);
    else None -> 待核实. Returns (time, precision, how)."""
    official = [x for x in group if x["event_time"] and (x["primary"] or is_official(x["url"]))]
    if official:
        x = min(official, key=lambda x: x["event_time"])
        return x["event_time"], x["precision"], f"官方来源时间（{x['source']}）"
    cands = []
    for x in group:
        for u in [x["url"], *x["aliases"]]:
            if is_official(u) and u not in cands and host_of(u) != "github.com":
                cands.append(u)
    for u in cands[:2]:
        if budget[0] <= 0:
            break
        budget[0] -= 1
        m = page_meta(u)
        if m.get("published"):
            return m["published"], m.get("precision"), f"原文 datePublished（{host_of(u)}）"
    others = [x for x in group if x["event_time"]]
    if others:
        x = min(others, key=lambda x: x["event_time"])
        return x["event_time"], x["precision"], f"非官方来源时间（{x['source']}）"
    return None, None, "未知"


def window_status(t, prec, since, until):
    """'in' | 'future' | 'stale' | 'unknown'. Day-precision dates are compared as whole days
    against the window's days, so a date-only post on the cutoff day stays in."""
    if t is None:
        return "unknown"
    if prec == "day":
        d = t.date()
        if d > until.date():
            return "future"
        return "in" if d >= since.date() else "stale"
    if t > until:
        return "future"
    return "in" if t >= since else "stale"


def summarize(group, seen_urls, seen_titles, since, until, budget):
    group.sort(key=lambda x: (x["tier"], x["event_time"] or x["article_time"] or dt.datetime.max.replace(tzinfo=UTC)))
    srcs = sorted({x["source"] for x in group})
    urls = []
    for x in group:
        for u in [x["url"], *x["aliases"]]:
            if u and u not in urls:
                urls.append(u)
    official_urls = [u for u in urls if is_official(u)]
    keys = set().union(*(x.get("_k") or key_tokens(x["title"]) for x in group))
    seen = next((f"{d} 已写过：{t}" for d, k, t in seen_titles
                 if len(k & keys) >= 2 and len(k & keys) / max(1, min(len(k), len(keys))) >= 0.67), "")
    if not seen and any(norm_url(u) in seen_urls for u in urls):
        seen = "链接在近 7 天的某期出现过"
    et, prec, how = None, None, "未知"
    arts = [x["article_time"] for x in group if x["article_time"]]
    # An article cannot report an event before it happens, so the earliest article that
    # mentions it is an upper bound on the event time. We only take the shortcut when EVERY
    # mention is older than the window: a cluster can be two developments of one product
    # (release, then weights), and a fresh mention may be the newer one.
    bound_stale = bool(arts) and not any(x["event_time"] for x in group) and max(arts) < since
    if bound_stale:
        how = f"所有来源文章 ≤ {max(arts).astimezone(BJ):%m-%d %H:%M}，早于窗口，事件不会更晚"
        status = "stale"
    else:
        et, prec, how = resolve_event_time(group, budget)
        status = window_status(et, prec, since, until)
    zh = next((x["title"] for x in group if re.search(r"[一-鿿]", x["title"])), "")
    fmt = lambda t: t.astimezone(BJ).strftime("%m-%d %H:%M") if t else ""
    return {"title": group[0]["title"], "title_zh": zh if zh != group[0]["title"] else "",
            "sources": srcs, "n_sources": len(srcs),
            # three separate facts, none implies another:
            "official_urls": official_urls[:4],            # links to first-party pages exist
            "from_official_feed": any(x["primary"] for x in group),   # we got it from an official channel
            "verified": False,                              # a human/bot read the primary page (set in triage)
            "hn_points": max([x.get("hn_points", 0) for x in group]),
            "event_time": et.isoformat() if et else "", "event_time_bj": fmt(et),
            "time_precision": prec or "", "time_source": how,
            "article_time_bj": fmt(max(arts)) if arts else "",
            "window": status,
            "urls": urls[:6], "summary": next((x["summary"] for x in group if x["summary"]), ""),
            "notes": sorted({x["note"] for x in group if x["note"]}),
            "kinds": sorted({x["source"] for x in group if x["tier"] == 3}), "seen": seen}


def score(c):
    """Pre-sort only: how widely the event was picked up. Editorial judgment is in SKILL.md."""
    return (c["n_sources"] + 1.5 * bool(c["official_urls"]) + 0.5 * c["from_official_feed"]
            + min(c["hn_points"], 600) / 200 - 3 * bool(c["seen"]))
# ---------- run / status / output ----------
def run_source(s, since, until):
    """Fetch + parse one source. Returns (items, status dict). Transport, parse and 'zero items'
    are reported apart: HTTP 200 with nothing in the window is not failure, and not coverage."""
    st = {"name": s["name"], "tier": s["tier"], "url": s["url"], "transport": "ok", "parse": "ok",
          "items": 0, "in_window": 0, "unknown_time": 0, "stale": 0, "future": 0, "error": ""}
    try:
        got = [x for x in s["kind"](s) if x["title"]]
    except FetchError as e:
        st.update(transport="failed" if e.status or "XML" not in str(e) else "ok",
                  parse="failed" if "XML" in str(e) else "n/a",
                  error=str(e)[:160], status=e.status, ctype=e.ctype, snippet=e.snippet[:120])
        return [], st
    except (ValueError, KeyError, ET.ParseError) as e:   # JSON / structure problems
        st.update(parse="failed", error=f"{type(e).__name__}: {str(e)[:120]}")
        return [], st
    st["items"] = len(got)
    kept = []
    for x in got:
        # per-item window on the item's OWN event time (official feeds); aggregators are 'unknown'
        # here and get resolved per cluster later
        w = window_status(x["event_time"], x["precision"], since, until) if x["primary"] else "unknown"
        st[{"in": "in_window", "stale": "stale", "future": "future", "unknown": "unknown_time"}[w]] += 1
        if x["primary"] and w == "stale":
            continue   # its own reliable time says it is old; official archives are thousands of posts
        kept.append(x)
    if not got:
        st["note"] = "传输与解析正常，但没有条目：不能视为该渠道无新闻"
    return kept, st


def render(date, cands, status, run):
    def block(title, rows, note="", cap=None):
        out = [f"## {title}", ""]
        if note:
            out += [note, ""]
        if cap and len(rows) > cap:
            out += [f"共 {len(rows)} 条，只列前 {cap} 条；完整列表在 candidates-{date}.json。", ""]
            rows = rows[:cap]
        if not rows:
            out += ["（无）", ""]
        for n, c in rows:
            flag = "【近 7 天已写】" if c["seen"] else ""
            off = ("官方链接 " + "、".join(host_of(u) for u in c["official_urls"][:2])) if c["official_urls"] else "无官方链接"
            chan = "，来自官方渠道" if c["from_official_feed"] else ""
            t = f"{c['event_time_bj']}（{'仅日期' if c['time_precision']=='day' else '精确到分'}，{c['time_source']}）" if c["event_time_bj"] else f"事件时间未知（来源文章 {c['article_time_bj'] or '?'}）"
            out.append(f"### {n}. {flag}{c['title']}")
            if c["title_zh"]:
                out.append(f"- 中文标题：{c['title_zh']}")
            out.append(f"- 来源（{c['n_sources']}）：{'、'.join(c['sources'])}；{off}{chan}")
            out.append(f"- 事件时间：{t}；核实状态：未读原文")
            if c["notes"]:
                out.append(f"- 信号：{'；'.join(c['notes'])}")
            if c["seen"]:
                out.append(f"- 去重：{c['seen']}")
            if c.get("related"):
                out.append("- 相关脉络：" + "；".join(c["related"]))
            if c["summary"]:
                out.append(f"- 摘要：{c['summary']}")
            out += [f"- 链接：{u}" for u in c["urls"]] + [""]
        return out

    lines = [f"# 候选池 {date}", "",
             f"采集截止 {run['cutoff_bj']} 北京时间（{run['cutoff_utc']} UTC）；窗口 {run['window_bj'][0]} → {run['window_bj'][1]} 北京时间，"
             f"共 {run['hours']} 小时；规则版本 {run['rules_version']}，代码 {run['commit']}。",
             "排序只反映被多少来源报道，不代表值得写。按 SKILL.md 的标准挑选。「官方链接」只表示链接指向官方域名，不表示已读过原文。", "",
             "## 信源状态", "",
             "| 信源 | 传输 | 解析 | 条目 | 窗口内 | 时间待定 | 窗口外 | 未来 | 备注 |", "|---|---|---|---|---|---|---|---|---|"]
    for s in status:
        note = s.get("error") or s.get("note", "")
        lines.append(f"| {s['name']} | {s['transport']} | {s['parse']} | {s['items']} | {s['in_window']} | {s['unknown_time']} | {s['stale']} | {s['future']} | {note} |")
    gaps = run["coverage_gaps"]
    lines += ["", f"失败 {run['failed']} / 配置 {run['configured']} 个信源。" + (" 覆盖缺口：" + "；".join(gaps) if gaps else " 没有已知覆盖缺口。"), ""]
    numbered = list(enumerate(cands, 1))
    lines += block("窗口内候选", [(n, c) for n, c in numbered if c["window"] == "in"])
    lines += block("待核实日期", [(n, c) for n, c in numbered if c["window"] == "unknown"],
                   "事件时间没有拿到。写之前先打开原文确认发布日期；确认在窗口内才算当日新闻，确认不了就不发。")
    lines += block("窗口外（仅供参考，不作为当日新闻）", [(n, c) for n, c in numbered if c["window"] in ("stale", "future")],
                   "stale = 早于窗口起点；future = 晚于采集截止（含 10 分钟时钟容差）。", cap=40)
    return "\n".join(lines)


def git_commit(repo):
    try:
        return subprocess.run(["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
                              capture_output=True, text=True, timeout=5).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def collect(date, hours, repo, now, sources=SOURCES):
    """Pure-ish entry used by main() and tests: returns (cands, status, run)."""
    global HOURS, NOW
    HOURS, NOW = hours, now
    _META.clear()
    until = now + FUTURE_SLACK
    since = now - dt.timedelta(hours=hours)
    items, status = [], []
    with cf.ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(run_source, s, since, until): s for s in sources}
        for f in cf.as_completed(futs):
            got, st = f.result()
            items += got
            status.append(st)
    order = [s["name"] for s in sources]
    status.sort(key=lambda s: order.index(s["name"]))
    seen_urls, seen_titles = covered(date, repo / "outputs")
    budget = [PRIMARY_DATE_BUDGET]
    groups = cluster(items)
    # spend the page-fetch budget on clusters that can still turn out to be today's news:
    # mentioned in-window by some article, and with an official URL to read the date from
    def prio(g):
        arts = [x["article_time"] for x in g if x["article_time"]]
        fresh = any(x["event_time"] for x in g) or (bool(arts) and min(arts) >= since)
        official = any(is_official(u) for x in g for u in [x["url"], *x["aliases"]])
        return (not fresh, not official)
    groups.sort(key=prio)
    cands = [summarize(g, seen_urls, seen_titles, since, until, budget) for g in groups]
    cands = [c for c in cands if c["n_sources"] > 1 or c["official_urls"] or c["from_official_feed"]
             or c["hn_points"] or c["kinds"] or "橘鸦 AI 早报" in c["sources"]]
    cands.sort(key=lambda c: ({"in": 0, "unknown": 1, "stale": 2, "future": 2}[c["window"]], -score(c)))
    hist = history(date, repo / "outputs")
    for c in cands:
        if c["window"] in ("in", "unknown"):
            c["related"] = related(c, hist, cands)
    configured = len({s["name"] for s in sources})
    failed = [s["name"] for s in status if s["transport"] != "ok" or s["parse"] != "ok"]
    gaps = [f"{s['name']} 失败（{s['error'][:60]}）" for s in status if s["name"] in failed]
    gaps += [f"{s['name']} 返回 0 条" for s in status if s["tier"] == 1 and s["transport"] == "ok" and s["items"] == 0]
    run = {"date": str(date), "hours": hours, "rules_version": RULES_VERSION, "commit": git_commit(repo),
           "cutoff_utc": now.strftime("%Y-%m-%d %H:%M"), "cutoff_bj": now.astimezone(BJ).strftime("%Y-%m-%d %H:%M"),
           "window_utc": [since.strftime("%Y-%m-%d %H:%M"), until.strftime("%Y-%m-%d %H:%M")],
           "window_bj": [since.astimezone(BJ).strftime("%m-%d %H:%M"), until.astimezone(BJ).strftime("%m-%d %H:%M")],
           "future_slack_minutes": int(FUTURE_SLACK.total_seconds() // 60),
           "configured": configured, "failed": len(failed), "failed_sources": failed,
           "coverage_gaps": gaps, "primary_pages_fetched_for_dates": PRIMARY_DATE_BUDGET - budget[0],
           "items": len(items), "candidates": len(cands),
           "by_window": {k: sum(c["window"] == k for c in cands) for k in ("in", "unknown", "stale", "future")}}
    return cands, status, run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="issue date, Beijing time (default: today)")
    ap.add_argument("--hours", type=int, default=HOURS)
    ap.add_argument("--now", default=None, help="override the collection cutoff, ISO 8601 (for reruns)")
    ap.add_argument("--repo", default=str(pathlib.Path(__file__).resolve().parents[3]))
    a = ap.parse_args()
    now = when(a.now)[0] if a.now else dt.datetime.now(UTC)
    date = dt.date.fromisoformat(a.date) if a.date else now.astimezone(BJ).date()
    repo = pathlib.Path(a.repo)
    cands, status, run = collect(date, a.hours, repo, now)
    work = repo / "work"
    work.mkdir(exist_ok=True)
    (work / f"candidates-{date}.md").write_text(render(date, cands, status, run), encoding="utf-8")
    (work / f"candidates-{date}.json").write_text(
        json.dumps({"run": run, "status": status, "candidates": cands}, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    (work / f"run-{date}.json").write_text(json.dumps(run, ensure_ascii=False, indent=1), encoding="utf-8")
    bw = run["by_window"]
    print(f"{run['items']} items -> {run['candidates']} candidates "
          f"(窗口内 {bw['in']} / 待核实 {bw['unknown']} / 窗口外 {bw['stale'] + bw['future']}) -> work/candidates-{date}.md")
    print(f"sources: {run['configured']} configured, {run['failed']} failed"
          + (f": {', '.join(run['failed_sources'])}" if run["failed_sources"] else ""))
    if run["coverage_gaps"]:
        print("coverage gaps: " + "; ".join(run["coverage_gaps"]))
    if run["failed"] > run["configured"] // 2:
        sys.exit("more than half of the sources failed; check the network before writing an issue")


if __name__ == "__main__":
    main()
