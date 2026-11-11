#!/usr/bin/env python3
"""Collect candidate AI news for one issue of AI 每日简报.

Fetches official blogs, aggregators, Hacker News and trending repos, keeps the last
--hours, merges reports of the same event across sources, and flags events that the
last 7 days of issues already covered. Writes work/candidates-DATE.md (read this) and
work/candidates-DATE.json.

Usage, from the repo root:
  python3 -I skill/ai-daily/scripts/collect.py [--date 2026-11-11] [--hours 36]
Standard library only; Python 3.9+.
"""
import argparse
import concurrent.futures as cf
import datetime as dt
import email.utils
import html
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
UTC, BJ = dt.timezone.utc, dt.timezone(dt.timedelta(hours=8))
AI_WORDS = re.compile(r"\b(AI|LLMs?|GPT[\w.-]*|Claude|Gemini|OpenAI|Anthropic|DeepMind|agents?|"
                      r"agentic|DeepSeek|Qwen|Kimi|Mistral|Llama|Grok|Codex|Cursor|MCP|RAG|"
                      r"diffusion|transformers?|inference|embeddings?|fine-?tun\w*)\b", re.I)
HOURS = 36


def get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def text(s, n=None):
    s = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()
    return s[:n].rstrip() + "…" if n and len(s) > n else s


def when(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s.strip())
    except (TypeError, ValueError, IndexError):
        try:
            d = dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


def item(src, title, url, date=None, summary="", aliases=(), note="", merge=True):
    """merge=False: a sub-topic sharing its parent's URL, so the URL must not join clusters."""
    return {"source": src["name"], "tier": src["tier"], "title": text(title), "url": url,
            "date": date, "summary": text(summary, 180), "aliases": list(aliases),
            "note": note, "merge": merge}


def local(tag):
    return tag.rsplit("}", 1)[-1]


def feed(src):
    root, out = ET.fromstring(get(src["url"])), []
    for e in root.iter():
        if local(e.tag) not in ("item", "entry"):
            continue
        f = {}
        for c in e:
            f.setdefault(local(c.tag), c)
        link = f.get("link")
        url = ((link.get("href") or link.text or "") if link is not None else "").strip()
        d = next((when(f[k].text) for k in ("pubDate", "published", "updated", "date")
                  if k in f and f[k].text), None)
        body = next((f[k].text for k in ("encoded", "description", "summary", "content")
                     if k in f and f[k].text), "")
        t = f["title"].text if "title" in f else ""
        if src.get("filter") and not AI_WORDS.search(f"{t} {text(body, 300)}"):
            continue
        out.append(item(src, t, url, d, body))
        if src.get("topics") and "AINews" in (t or ""):
            # each AINews issue covers many events; its headings are separate signals
            for h in re.findall(r"<h[34][^>]*>(.*?)</h[34]>|<p><strong>([^<]{12,100})</strong>",
                                body or "", re.S):
                ht = re.sub(r"^\d+\.\s*", "", text(h[0] or h[1])).rstrip(":： ")
                if len(ht) > 10:
                    out.append(item(src, ht, url, d, note="AINews 小标题", merge=False))
    return out


def juya(src):
    """橘鸦 AI 早报: ~30 Chinese one-liners a day, each linking its original sources."""
    root, out = ET.fromstring(get(src["url"])), []
    for e in root.iter("item"):
        d = when(e.findtext("pubDate"))
        body = (e.findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
                or e.findtext("description") or "")
        section = ""
        for m in re.finditer(r'<h[23][^>]*>(?!\s*<a)(.*?)</h[23]>|<h3[^>]*>\s*<a href="([^"]+)"'
                             r'[^>]*>(.*?)</a>(.*?)</h3>(.*?)(?=<h[23][ >]|\Z)', body, re.S):
            if m.group(1) is not None:
                section = text(m.group(1))
                continue
            rest = m.group(5)
            q = re.search(r"<blockquote>(.*?)</blockquote>", rest, re.S)
            links = [u for u in re.findall(r'href="(https?://[^"]+)"', rest)
                     if "juya.uk" not in u]
            out.append(item(src, m.group(3), m.group(2), d, q.group(1) if q else rest,
                            links, section))
    return out


def anthropic(src):
    page, slugs = get(src["url"]), []
    for s in re.findall(r'href="/news/([a-z0-9-]+)"', page):
        if s not in slugs:
            slugs.append(s)

    def one(slug):
        url = "https://www.anthropic.com/news/" + slug
        p = get(url)
        meta = lambda k: (re.search(r'(?:property|name)="%s" content="([^"]*)"' % k, p) or [None, ""])[1]
        d = when(meta("article:published_time"))
        return item(src, meta("og:title"), url, d, meta("og:description")) if d else None

    with cf.ThreadPoolExecutor(8) as ex:
        return [x for x in ex.map(one, slugs[:16]) if x]
def hn(src):
    since = int(time.time()) - HOURS * 3600
    q = urllib.parse.urlencode({"tags": "story", "hitsPerPage": 100,
                                "numericFilters": f"points>{src['min_points']},created_at_i>{since}"})
    out = []
    for h in json.loads(get(src["url"] + "?" + q))["hits"]:
        if not AI_WORDS.search(h.get("title") or ""):
            continue
        disc = f"https://news.ycombinator.com/item?id={h['objectID']}"
        x = item(src, h["title"], h.get("url") or disc,
                 dt.datetime.fromtimestamp(h["created_at_i"], UTC),
                 note=f"HN {h['points']} 分 · {h.get('num_comments') or 0} 评论 · {disc}")
        x["hn_points"] = h["points"]
        out.append(x)
    return out


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
        if not AI_WORDS.search(f"{name.group(1)} {d}"):
            continue
        out.append(item(src, name.group(1), "https://github.com/" + name.group(1), None, d,
                        note=f"今日 +{today.group(1) if today else '?'} star · 共 "
                             f"{text(total.group(1)) if total else '?'}"))
    return out


def hf_papers(src):
    out = []
    for p in json.loads(get(src["url"])):
        up = p["paper"].get("upvotes", 0)
        if up >= src["min_upvotes"]:
            out.append(item(src, p["paper"]["title"], "https://huggingface.co/papers/" +
                            p["paper"]["id"], None, p["paper"].get("summary", ""),
                            note=f"HF 论文 {up} 赞"))
    return out


# tier: 1 = 官方一手, 2 = 聚合 / 媒体（发现用，正文须回到一手来源）, 3 = 社区信号
SOURCES = [
    {"name": "OpenAI", "tier": 1, "kind": feed, "url": "https://openai.com/news/rss.xml"},
    {"name": "Anthropic", "tier": 1, "kind": anthropic, "url": "https://www.anthropic.com/news"},
    {"name": "Google DeepMind", "tier": 1, "kind": feed, "url": "https://deepmind.google/blog/rss.xml"},
    {"name": "Google AI", "tier": 1, "kind": feed, "url": "https://blog.google/technology/ai/rss/"},
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
STOP = set("""a an the and or of to in on for with by from at as is are be now new its it this that
how why what you your we our via vs into over up out after about than more can will just all
ai model models launch launches launched introducing introduces announces announced available
release released releases update updates open source opensource today first official
openai google anthropic deepmind meta microsoft amazon apple nvidia claude chatgpt
show hn ask""".split())


def key_tokens(t):
    toks = re.findall(r"[a-z][a-z0-9+-]*(?:\.[0-9]+)*|[0-9]+(?:\.[0-9]+)*", t.lower())
    return {x for x in toks if x not in STOP and (len(x) > 1 or x.isdigit())}


def norm_url(u):
    p = urllib.parse.urlsplit((u or "").strip())
    return (p.netloc.lower().removeprefix("www.") + p.path.rstrip("/")).lower()


def cluster(items):
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(i, j):
        parent[find(i)] = find(j)

    by_url = {}
    for i, x in enumerate(items):
        x["_k"] = key_tokens(x["title"])
        if not x["merge"]:
            continue
        for u in [x["url"], *x["aliases"]]:
            n = norm_url(u)
            if n and n.count("/") >= 1 and not re.search(r"(x|twitter)\.com/\w+$", n):
                if n in by_url:
                    join(i, by_url[n])
                by_url.setdefault(n, i)
    for i, a in enumerate(items):
        for j in range(i):
            b, ka = items[j], a["_k"]
            kb = b["_k"]
            if len(ka) >= 2 and len(kb) >= 2:
                inter = len(ka & kb)
                if inter >= 2 and inter / min(len(ka), len(kb)) >= 0.67:
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


def summarize(group, seen_urls, seen_titles):
    group.sort(key=lambda x: (x["tier"], x["date"] or dt.datetime.max.replace(tzinfo=UTC)))
    srcs = sorted({x["source"] for x in group})
    tiers = sorted({x["tier"] for x in group})
    urls = []
    for x in group:
        for u in [x["url"], *x["aliases"]]:
            if u and u not in urls:
                urls.append(u)
    keys = set().union(*(x["_k"] for x in group))
    seen = next((f"{d} 已写过：{t}" for d, k, t in seen_titles
                 if len(k & keys) >= 2 and len(k & keys) / max(1, min(len(k), len(keys))) >= 0.67), "")
    if not seen and any(norm_url(u) in seen_urls for u in urls):
        seen = "链接在近 7 天的某期出现过"
    dates = [x["date"] for x in group if x["date"]]
    zh = next((x["title"] for x in group if re.search(r"[一-鿿]", x["title"])), "")
    return {"title": group[0]["title"], "title_zh": zh if zh != group[0]["title"] else "",
            "sources": srcs, "has_official": 1 in tiers, "n_sources": len(srcs),
            "hn_points": max([x.get("hn_points", 0) for x in group]),
            "date": max(dates).astimezone(BJ).strftime("%m-%d %H:%M") if dates else "",
            "urls": urls[:6], "summary": next((x["summary"] for x in group if x["summary"]), ""),
            "notes": sorted({x["note"] for x in group if x["note"]}),
            "kinds": sorted({x["source"] for x in group if x["tier"] == 3}), "seen": seen}


def score(c):
    """Pre-sort only: how widely the event was picked up. Editorial judgment is in SKILL.md."""
    return (c["n_sources"] + 1.5 * c["has_official"] + min(c["hn_points"], 600) / 200
            - 3 * bool(c["seen"]))
def render(date, cands, status):
    lines = [f"# 候选池 {date}", "",
             f"抓取时间 {dt.datetime.now(BJ):%Y-%m-%d %H:%M} 北京时间，窗口 {HOURS} 小时。"
             "排序只反映被多少来源报道，不代表值得写。按 SKILL.md 的标准挑选。", "",
             "## 信源状态", ""]
    lines += [f"- {n}：{s}" for n, s in status]
    lines += ["", "## 候选事件", ""]
    for n, c in enumerate(cands, 1):
        flag = "【近 7 天已写】" if c["seen"] else ""
        off = "有官方一手" if c["has_official"] else "无官方一手"
        lines.append(f"### {n}. {flag}{c['title']}")
        if c["title_zh"]:
            lines.append(f"- 中文标题：{c['title_zh']}")
        lines.append(f"- 来源（{c['n_sources']}）：{'、'.join(c['sources'])}；{off}；{c['date']}")
        if c["notes"]:
            lines.append(f"- 信号：{'；'.join(c['notes'])}")
        if c["seen"]:
            lines.append(f"- 去重：{c['seen']}")
        if c["summary"]:
            lines.append(f"- 摘要：{c['summary']}")
        lines += [f"- 链接：{u}" for u in c["urls"]] + [""]
    return "\n".join(lines)


def main():
    global HOURS
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=dt.datetime.now(BJ).date().isoformat())
    ap.add_argument("--hours", type=int, default=HOURS)
    ap.add_argument("--repo", default=str(pathlib.Path(__file__).resolve().parents[3]))
    a = ap.parse_args()
    HOURS = a.hours
    date, repo = dt.date.fromisoformat(a.date), pathlib.Path(a.repo)
    since = dt.datetime.now(UTC) - dt.timedelta(hours=HOURS)
    items, status = [], []
    with cf.ThreadPoolExecutor(8) as ex:
        futs = {ex.submit(s["kind"], s): s for s in SOURCES}
        for f in cf.as_completed(futs):
            s = futs[f]
            try:
                got = [x for x in f.result() if x["title"] and (x["date"] is None or x["date"] >= since)]
                items += got
                status.append((s["name"], f"{len(got)} 条"))
            except Exception as e:  # one broken source must not stop the issue
                status.append((s["name"], f"失败（{type(e).__name__}: {str(e)[:80]}）"))
    status.sort(key=lambda x: [s["name"] for s in SOURCES].index(x[0]))
    seen_urls, seen_titles = covered(date, repo / "outputs")
    cands = [summarize(g, seen_urls, seen_titles) for g in cluster(items)]
    cands = [c for c in cands if c["n_sources"] > 1 or c["has_official"] or c["hn_points"]
             or c["kinds"] or "橘鸦 AI 早报" in c["sources"]]
    cands.sort(key=score, reverse=True)
    work = repo / "work"
    work.mkdir(exist_ok=True)
    (work / f"candidates-{date}.md").write_text(render(date, cands, status), encoding="utf-8")
    (work / f"candidates-{date}.json").write_text(
        json.dumps({"date": str(date), "status": status, "candidates": cands},
                   ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    failed = sum("失败" in s for _, s in status)
    print(f"{len(items)} items -> {len(cands)} candidates -> work/candidates-{date}.md"
          f" ({failed} source(s) failed)")
    if failed > len(SOURCES) // 2:
        sys.exit("more than half of the sources failed; check the network before writing an issue")


if __name__ == "__main__":
    main()
