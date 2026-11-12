#!/usr/bin/env python3
"""Build the AI 每日简报 static site from outputs/AI-Daily-YYYY-MM-DD.md.

Usage: python3 site/build.py [OUT_DIR]   (default: site/dist)
Standard library only, so it runs anywhere the daily bot runs.
"""
import datetime
import html
import os
import pathlib
import re
import shutil
import sys

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE.parent / "outputs"
OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "dist"
REPO_URL = "https://github.com/yuzhang-ai/ai-daily"
WEEK = "一二三四五六日"
# Cover gradients (name, dark stop, light stop). Ordered so neighbours in the rotation differ in hue.
# An issue picks one with a `封面色：名称` line (or `封面色：#rrggbb[, #rrggbb]`); otherwise it rotates.
PALETTE = [("靛蓝", "#2b2fb8", "#5a63ff"), ("珊瑚", "#c2410c", "#ff7a59"),
           ("青绿", "#0b7a8a", "#22c1c3"), ("紫罗兰", "#5b2bd6", "#a06bff"),
           ("琥珀", "#b45309", "#f5a524"), ("墨绿", "#0f5b45", "#2bb673"),
           ("玫红", "#be185d", "#f472b6"), ("极光", "#0369a1", "#8b5cf6"),
           ("橄榄", "#3f4a0f", "#9aab2e"), ("日落", "#ea580c", "#db2777"),
           ("石墨", "#2a2f45", "#5b6280"), ("海蓝", "#075985", "#38bdf8")]
HEX = re.compile(r"#[0-9a-fA-F]{6}\b")
ASSETS = ("style.css", "fonts", "icons")
# Source sites: (host suffix, icon in site/icons, display name). First match wins, so list
# specific subdomains before their parent. Unknown hosts fall back to a link glyph + bare host.
SITES = [
    ("github.com", "github", "GitHub"), ("cdn.openai.com", "openai", "OpenAI"),
    ("developers.openai.com", "openai", "OpenAI 开发者"), ("openai.com", "openai", "OpenAI"),
    ("chatgpt.com", "chatgpt", "ChatGPT"), ("arxiv.org", "arxiv", "arXiv"),
    ("platform.claude.com", "claude", "Claude 文档"), ("claude.com", "claude", "Claude"),
    ("anthropic.com", "anthropic", "Anthropic"), ("latent.space", "latentspace", "Latent Space"),
    ("deepmind.google", "deepmind", "Google DeepMind"), ("antigravity.google", "antigravity", "Antigravity"),
    ("blog.google", "google", "Google 博客"), ("storage.googleapis.com", "google", "Google"),
    ("developers.googleblog.com", "googledev", "Google 开发者博客"),
    ("developer.chrome.com", "chrome", "Chrome 开发者"), ("cursor.com", "cursor", "Cursor"),
    ("cognition.com", "cognition", "Cognition"), ("cognition.ai", "cognition", "Cognition"),
    ("devin.ai", "devin", "Devin"), ("news.ycombinator.com", "hn", "Hacker News"),
    ("learn.microsoft.com", "microsoft", "Microsoft Learn"), ("langchain.com", "langchain", "LangChain"),
    ("dwarkesh.com", "dwarkesh", "Dwarkesh"), ("wiz.io", "wiz", "Wiz"),
    ("platform.kimi.ai", "kimi", "Kimi 开放平台"), ("kimi.com", "kimi", "Kimi"),
    ("minimax.io", "minimax", "MiniMax"), ("isomorphiclabs.com", "isomorphic", "Isomorphic Labs"),
    ("huggingface.co", "huggingface", "Hugging Face"), ("elevenlabs.io", "elevenlabs", "ElevenLabs"),
    ("amazon.science", "amazon", "Amazon Science"), ("agents-last-exam.org", "ale", "Agents' Last Exam"),
    ("0din.ai", "odin", "0DIN"), ("thevelocitywhitepapers.com", "velocity", "Velocity"),
]
GENERIC_LINK = {"来源", "原文", "链接", "source", "link"}
# English display names for the SITES entries that carry Chinese words
EN_SITES = {"OpenAI 开发者": "OpenAI Developers", "Claude 文档": "Claude Docs", "Google 博客": "Google Blog",
            "Google 开发者博客": "Google Developers Blog", "Chrome 开发者": "Chrome Developers",
            "Kimi 开放平台": "Kimi Platform"}
LINK_SVG = ('<svg class="src-ico" viewBox="0 0 16 16" aria-hidden="true"><path fill="none" stroke="currentColor" '
            'stroke-width="1.6" stroke-linecap="round" d="M6.5 9.5l3-3M7 4.5l1-1a2.8 2.8 0 014 4l-1 1M9 11.5l-1 1a2.8 2.8 0 01-4-4l1-1"/></svg>')
OUT_SVG = ('<svg class="src-out" viewBox="0 0 12 12" aria-hidden="true"><path fill="none" stroke="currentColor" '
           'stroke-width="1.4" stroke-linecap="round" d="M4.5 2.5h5v5M9.5 2.5l-7 7"/></svg>')
GH_SVG = ('<svg class="gh" viewBox="0 0 16 16" aria-hidden="true"><path fill="currentColor" d="M8 0C3.58 0 0 3.58 0 8c0 '
          '3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94'
          '-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2'
          '-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 '
          '1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95'
          '.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>')

STORY_KEYS = [("来源链接", "src"), ("类型", "type"), ("推荐指数", "stars"),
              ("配图", "img"), ("关键数字", "keynum"),
              ("一句话总结", "tldr"), ("为什么重要", "why"), ("核心观点", "points"),
              ("对 AI", "insight"), ("这意味着", "insight"), ("可落地", "action"), ("风险", "risk"),
              ("是否值得精读", "worth"),
              # English companion files (outputs/en/) use these labels
              ("Sources", "src"), ("Source", "src"), ("Type", "type"), ("Rating", "stars"),
              ("Image", "img"), ("Key figure", "keynum"), ("Key number", "keynum"),
              ("Summary", "tldr"), ("TL;DR", "tldr"), ("Why it matters", "why"), ("Key points", "points"),
              ("What it means", "insight"), ("Risks", "risk"), ("Worth reading", "worth")]
REPO_KEYS = [("项目名", "name"), ("GitHub 链接", "url"), ("Star 数", "star"),
             ("解决什么问题", "what"), ("为什么值得", "why"), ("如何用到", "how"),
             ("Project", "name"), ("GitHub", "url"), ("Stars", "star"),
             ("What it solves", "what"), ("Why it's worth", "why"), ("Why worth", "why"), ("How to use", "how")]
# PUBLIC (default) renders the parts that matter to any AI follower; the markdown keeps the
# author's own notes too (action items, repo how-tos, QA checklist), shown with AI_DAILY_PRIVATE=1.
PUBLIC = os.environ.get("AI_DAILY_PRIVATE") != "1"
# UI strings per language. Content comes from outputs/ (zh) and outputs/en/ (en, optional).
L = {
    "zh": {
        "brand": "AI 每日简报", "html_lang": "zh-CN", "archive": "往期",
        "tagline": "每天 3 条值得关注的 AI 动态，附观点、要点和风险提示" if PUBLIC else "AI PM / FDE 的每日情报与行动清单",
        "foot": "内容由 AI 整理、人工核验来源链接；判断可能有误，请以原文为准。" if PUBLIC
                else "给 AI 产品经理和 FDE 的每日情报。内容由 AI 整理、人工核验，转发前请点开原文确认。",
        "sections": ([("why", "为什么重要"), ("points", "核心观点"), ("insight", "这意味着什么"), ("risk", "风险与待验证")]
                     if PUBLIC else [("why", "为什么重要"), ("points", "核心观点"), ("insight", "对 AI PM / FDE 的启发"),
                                     ("action", "可以动手做的事"), ("risk", "风险提醒")]),
        "latest": "最新一期 · 第 {no} 期 · {date}", "issue": "第 {no} 期", "issue_date": "第 {no} 期 · {date}",
        "month": "{y} 年 {m} 月", "count": "{n} 期", "sources": "原文", "briefs": "快讯",
        "repos": "值得研究的开源项目", "actions": "明天可以做的事", "checks": "人工验证清单",
        "prev": "上一期", "next": "下一期", "rating": "推荐 {n} / 5", "week": "一二三四五六日", "weekfmt": "周{w}",
        "title": "第 {no} 期 · {date} · AI 每日简报",
        "untranslated": "",
    },
    "en": {
        "brand": "AI Daily Brief", "html_lang": "en", "archive": "Archive",
        "tagline": "Three AI developments a day, with context, key facts and caveats" if PUBLIC
                   else "Daily intelligence and action list for AI PMs / FDEs",
        "foot": "Compiled by AI, source links checked by a human; judgments may be wrong, the original sources are authoritative." if PUBLIC
                else "Daily intelligence for AI PMs and FDEs. Compiled by AI, checked by a human; open the originals before forwarding.",
        "sections": ([("why", "Why it matters"), ("points", "Key points"), ("insight", "What it means"), ("risk", "Risks and open questions")]
                     if PUBLIC else [("why", "Why it matters"), ("points", "Key points"), ("insight", "Takeaways for AI PMs / FDEs"),
                                     ("action", "Things to try"), ("risk", "Risks")]),
        "latest": "Latest · Issue {no} · {date}", "issue": "Issue {no}", "issue_date": "Issue {no} · {date}",
        "month": "{mname} {y}", "count": "{n} issues", "sources": "Sources", "briefs": "In brief",
        "repos": "Open source worth a look", "actions": "Things to try tomorrow", "checks": "Verification checklist",
        "prev": "Previous", "next": "Next", "rating": "Rating {n} / 5", "week": "MonTueWedThuFriSatSun", "weekfmt": "{w}",
        "title": "Issue {no} · {date} · AI Daily Brief",
        "untranslated": "No English edition for this issue yet; showing the Chinese original.",
    },
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
LANG, BASE = "zh", ""      # set per output language in main(); BASE is the relative path to assets


def t(key, **kw):
    return L[LANG][key].format(**kw)


def asset(p):
    """Prefix relative asset paths with BASE; leave absolute URLs alone."""
    return p if p.startswith(("http://", "https://", "/")) else BASE + p


def field_re(keys):
    labels = "|".join(re.escape(k) for k, _ in keys)
    return re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+)?(?:\*\*)?(" + labels +
                      r")[^：:\n]{0,20}[：:](?:\*\*)?\s*(.*)$")


STORY_RE, REPO_RE = field_re(STORY_KEYS), field_re(REPO_KEYS)
LOCAL_FILE = re.compile(r"\s*(?:[/；;，,]\s*)?本地[^：:\[\n]{0,6}[：:]\s*"
                        r"\[[^\]]*\]\((?:outputs/)?sources/[^)]*\)")
LOCAL_LINK = re.compile(r"\[([^\]]*)\]\((?:outputs/)?sources/[^)]*\)")


def collect(lines, regex, keys):
    """Split field lines into {key: text}; continuation lines join the open field."""
    mapping, fields, cur = dict(keys), {}, None
    for line in lines:
        m = regex.match(line)
        if m:
            cur = mapping[m.group(1)]
            fields[cur] = m.group(2).strip()
        elif cur and line.strip():
            fields[cur] = (fields[cur] + "\n" + line.rstrip()).strip()
    return fields


def parse_stars(s):
    s = s or ""
    if "★" in s:
        return s.count("★")
    m = re.search(r"\d+(?:\.\d+)?", s)
    return int(float(m.group())) if m else 0


def parse_story(block):
    lines = block.splitlines()
    head = re.sub(r"^\d+\.\s*", "", lines[0]).strip()
    m = re.match(r"^([^:：]{1,24})[:：]\s*(.+)$", head)
    org, title = (m.group(1).strip(), m.group(2).strip()) if m else ("", head)
    lines = [l for l in lines if not re.match(r"^\s*[-*]\s*本地", l)]
    f = collect(lines[1:], STORY_RE, STORY_KEYS)
    risk = f.get("risk", "")
    w = re.search(r"是否值得精读[：:]\s*(\S+?)[。.]?\s*$", risk)
    if w:
        f["risk"] = risk[:w.start()].strip()
        f.setdefault("worth", w.group(1))
    f["src"] = LOCAL_LINK.sub("", LOCAL_FILE.sub("", f.get("src", "")))
    links = re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", f["src"])
    return {"org": org, "title": title, "stars": parse_stars(f.get("stars")),
            "links": links, "image": parse_image(f.pop("img", "")),
            "stat": parse_stat(f.pop("keynum", "")),
            **{k: v for k, v in f.items() if k != "stars"}}


IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)\s*(?:[（(]([^）)]*)[）)])?")


def parse_image(s):
    """`![alt](images/DATE/x.jpg)（图源：Google）` -> {src, alt, credit}; local paths are relative to outputs/."""
    m = IMG_RE.search(s or "")
    if not m:
        return None
    src = m.group(2)
    if not src.startswith("https://"):
        src = src.removeprefix("outputs/")
        if ".." in src or not (SRC / src).is_file():
            print(f"warning: image not found, skipped: {m.group(2)}", file=sys.stderr)
            return None
    return {"src": src, "alt": m.group(1).strip(), "credit": (m.group(3) or "").strip()}


def parse_stat(s):
    """`2 美元 | 每百万输入 token 首发价` -> (value, label)."""
    if not (s or "").strip():
        return None
    parts = re.split(r"\s*[|｜]\s*", s.strip(), maxsplit=1)
    return parts[0], parts[1] if len(parts) > 1 else ""


def cover_colors(raw, no):
    """Resolve an issue's `封面色` line (palette name or 1–2 hex values); fall back to rotation."""
    raw = (raw or "").strip().rstrip("。.")
    hexes = HEX.findall(raw)
    if hexes:
        return hexes[0], hexes[1] if len(hexes) > 1 else f"color-mix(in oklab,{hexes[0]},#fff 40%)"
    for name, a, b in PALETTE:
        if raw == name:
            return a, b
    if raw:
        names = "、".join(n for n, _, _ in PALETTE)
        print(f"warning: unknown 封面色 {raw!r}, using rotation. Known: {names}", file=sys.stderr)
    _, a, b = PALETTE[(no - 1) % len(PALETTE)]
    return a, b


def parse_repos(text):
    repos, cur = [], None
    for line in text.splitlines():
        h = re.match(r"^###\s+(.+)$", line)
        m = REPO_RE.match(line)
        if h or (m and m.group(1) == "项目名"):
            cur = {"name": (h.group(1) if h else m.group(2)).strip(), "_lines": []}
            repos.append(cur)
        elif cur is not None:
            cur["_lines"].append(line)
    for r in repos:
        r.update(collect(r.pop("_lines"), REPO_RE, REPO_KEYS))
        r["name"] = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", r["name"]).strip("`* ")
        u = re.search(r"\((https?://[^)\s]+)\)", r.get("url", "")) or \
            re.search(r"https?://\S+", r.get("url", ""))
        r["href"] = u.group(1) if u and u.groups() else (u.group() if u else "")
        r["star"] = re.sub(r"[（(].*$", "", r.get("star", "")).strip()
    return repos


def parse_issue(path):
    text = path.read_text(encoding="utf-8")
    date = datetime.date.fromisoformat(re.search(r"\d{4}-\d{2}-\d{2}", path.name).group())
    issue = {"date": date, "stories": [], "repos": [], "lede": "", "actions": [], "checks": [],
             "briefs": []}
    c = re.search(r"^(?:封面色|Cover color)[：:]\s*(.+)$", text, flags=re.M)
    issue["color_raw"] = c.group(1) if c else ""
    for sec in re.split(r"^## ", text, flags=re.M)[1:]:
        name, _, body = sec.partition("\n")
        low = name.lower()
        if "快讯" in name or "in brief" in low or low.startswith("brief"):
            issue["briefs"] = [m.group(1) for m in re.finditer(r"^\d+\.\s+(.+)$", body, flags=re.M)]
        elif "条内容" in name or "最值得关注" in name or "要闻" in name or "stories" in low or "headlines" in low:
            issue["stories"] = [parse_story(b) for b in re.split(r"^### ", body, flags=re.M)[1:]]
        elif "观点" in name or "一句话" in name or "one-liner" in low or "one liner" in low or "takeaway" in low:
            q = " ".join(l.lstrip("> ").strip() for l in body.splitlines() if l.startswith(">"))
            issue["lede"] = re.sub(r"^今天我最应该记住的是[：:]\s*", "", q)
        elif "开源项目" in name or "open source" in low or "open-source" in low:
            issue["repos"] = parse_repos(body)
        elif "行动" in name or "tomorrow" in low or "things to try" in low:
            issue["actions"] = [m.group(1) for m in re.finditer(r"^\d+\.\s+(.+)$", body, flags=re.M)]
        elif "验证" in name or "checklist" in low:
            issue["checks"] = [(m.group(1) != " ", m.group(2)) for m in
                               re.finditer(r"^- \[([ xX])\]\s+(.+)$", body, flags=re.M)]
    return issue


def content(i):
    """The language edition to render: the English companion when building en and one exists."""
    if LANG == "en" and i.get("en"):
        return i["en"]
    return i
# ---------- rendering ----------
esc = html.escape


def inline(s):
    """Escape, then render `code`, **bold** and [text](url)."""
    s = esc(s or "", quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", s)
    return re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
                  lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', s)


def blocks(text):
    """Turn a field's text into <p>, <ol> or <ul> blocks."""
    out, items, kind = [], [], None

    def flush():
        nonlocal items, kind
        if items:
            out.append(f"<{kind}>" + "".join(f"<li>{inline(i)}</li>" for i in items) + f"</{kind}>")
        items, kind = [], None

    for line in (text or "").splitlines():
        line = line.strip()
        m = re.match(r"^(\d+\.|[-*])\s+(.+)$", line)
        if m:
            k = "ol" if m.group(1)[0].isdigit() else "ul"
            if kind and kind != k:
                flush()
            kind = k
            items.append(m.group(2))
        elif line:
            flush()
            out.append(f"<p>{inline(line)}</p>")
    flush()
    return "".join(out)


def site_of(url):
    host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/")[0].lower())
    for suf, icon, name in SITES:
        if host == suf or host.endswith("." + suf):
            return icon, name
    return None, host


def src_chip(text, url):
    """A source link that reads as one: site icon + a name (the link text, or the site name if generic)."""
    icon, name = site_of(url)
    if LANG == "en":
        name = EN_SITES.get(name, name)
    label = name if text.strip().lower() in GENERIC_LINK else text
    ico = (f'<img class="src-ico" src="{BASE}icons/{icon}.png" alt="" width="16" height="16" loading="lazy">'
           if icon else LINK_SVG)
    return f'<a class="src" href="{esc(url)}" title="{esc(name)}">{ico}<span>{esc(label)}</span>{OUT_SVG}</a>'


LINK_RE = r"\[([^\]]+)\]\((https?://[^)\s]+)\)"


def brief(b):
    """'**Org · Title**：text [来源](url)' -> text with the trailing links pulled out as source chips."""
    m = re.search(rf"(?:\s*{LINK_RE}[。；;，,\s]*)+$", b)
    text, tail = (b[:m.start()], b[m.start():]) if m else (b, "")
    chips = "".join(src_chip(t, u) for t, u in re.findall(LINK_RE, tail))
    return f'<li><p>{inline(text.rstrip())}</p>{f"<p class=srcs>{chips}</p>" if chips else ""}</li>'


def plain(s):
    return re.sub(r"[`*]", "", s or "")


def stars(n):
    if not n:
        return ""
    return f'<span class="stars" title="{t("rating", n=n)}">{"★" * n}<i>{"★" * (5 - n)}</i></span>'


def ymd(i):
    return i["date"].isoformat()


def dot_date(i):
    w = L[LANG]["week"]
    wd = w[i["date"].weekday()] if LANG == "zh" else w[i["date"].weekday() * 3:i["date"].weekday() * 3 + 3]
    return f'{i["date"]:%Y.%m.%d} {t("weekfmt", w=wd)}'


def cover(i, big=False):
    """A generated issue cover: brand strip, lead headline, two more headlines, issue badge."""
    s = content(i)["stories"]
    more = "".join(f"<li>{esc(plain(x['title']))}</li>" for x in s[1:3])
    a, b = i["colors"]
    return f'''<div class="cover{' big' if big else ''}" style="--cv-a:{a};--cv-b:{b};view-transition-name:cv-{ymd(i)}" aria-hidden="true">
  <div class="cv-panel">
    <div class="cv-head"><span class="cv-brand">{t("brand")}</span><span class="cv-date">{i["date"]:%Y.%m.%d}</span></div>
    <p class="cv-lead">{esc(plain(s[0]["title"])) if s else ""}</p>
    <ul class="cv-more">{more}</ul>
  </div>
  <span class="cv-no">#{i["no"]:02d}</span>
</div>'''


def heads(i, prefix=""):
    """Numbered headline list used in both hero and issue head; --i drives the stagger."""
    return "".join(f'''<li style="--i:{n}"><a href="{prefix}#s{n}">
  <span class="h-title">{esc(plain(s["title"]))}</span>{stars(s["stars"])}
  <span class="h-tldr">{inline(s.get("tldr"))}</span></a></li>''' for n, s in enumerate(content(i)["stories"], 1))


def page(title, band, body, desc="", slug="index", notice=""):
    other = f"en/{slug}.html" if LANG == "zh" else f"../{slug}.html"
    alt_zh = f"{BASE}{slug}.html"
    alt_en = f"{BASE}en/{slug}.html"
    # language switch: two text segments like the rest of the nav; the current one is lit, the
    # other is a link. Reads as "中 | EN", not as a button.
    zh_seg = '<span class="on" lang="zh-CN">中</span>' if LANG == "zh" else f'<a href="{other}" hreflang="zh-CN" data-lang="zh" lang="zh-CN">中</a>'
    en_seg = '<span class="on" lang="en">EN</span>' if LANG == "en" else f'<a href="{other}" hreflang="en" data-lang="en" lang="en">EN</a>'
    switch = f'<span class="lang" role="group" aria-label="Language">{zh_seg}<i aria-hidden="true"></i>{en_seg}</span>'
    return f'''<!doctype html>
<html lang="{L[LANG]["html_lang"]}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="theme-color" content="#0b0f2a">
<link rel="alternate" hreflang="zh-CN" href="{alt_zh}">
<link rel="alternate" hreflang="en" href="{alt_en}">
<link rel="preload" href="{BASE}fonts/SmileySans-Oblique.ttf.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="{BASE}style.css">
</head>
<body>
<div class="band">
<header class="bar"><div class="wrap bar-in">
  <a class="logo" href="index.html">{t("brand")}</a>
  <nav><a href="index.html#archive">{t("archive")}</a><a href="{REPO_URL}">GitHub</a>{switch}</nav>
</div></header>
{band}
</div>
<div class="band-fade" aria-hidden="true"></div>
{f'<p class="notice wrap">{esc(notice)}</p>' if notice else ""}
{body}
<footer class="site-foot"><div class="wrap">{t("foot")}</div></footer>
<script>
(function(){{var k="ai-daily-lang",here="{LANG}",a=document.querySelector(".lang a");if(!a)return;
try{{var s=localStorage.getItem(k);
if(s&&s!==here&&location.pathname.replace(/.*\\//,"")in{{"index.html":1,"":1}}&&!sessionStorage.getItem("ai-daily-switched")){{sessionStorage.setItem("ai-daily-switched","1");location.replace(a.href);return;}}
a.addEventListener("click",function(){{localStorage.setItem(k,a.dataset.lang);sessionStorage.setItem("ai-daily-switched","1");}});}}catch(e){{}}}})();
</script>
</body>
</html>'''


def render_index(issues):
    latest = issues[-1]
    lc = content(latest)
    hero = f'''<section class="hero wrap">
  <a class="hero-cover" href="{ymd(latest)}.html">{cover(latest, big=True)}</a>
  <div class="hero-text">
    <p class="kicker" style="--i:0">{t("tagline")}</p>
    <p class="kicker sub" style="--i:0">{t("latest", no=latest["no"], date=dot_date(latest))}</p>
    <h1 class="hero-lede" style="--i:1"><a href="{ymd(latest)}.html">{esc(plain(lc["lede"]))}</a></h1>
    <ol class="hero-heads" style="--i:2">{heads(latest, ymd(latest) + ".html")}</ol>
  </div>
</section>'''
    months = {}
    for i in reversed(issues[:-1]):
        key = t("month", y=i["date"].year, m=i["date"].month, mname=MONTHS[i["date"].month - 1])
        months.setdefault(key, []).append(i)
    grid = []
    for m, items in months.items():
        cards = "".join(f'''<a class="card" href="{ymd(i)}.html">{cover(i)}
  <span class="card-date">{t("issue_date", no=i["no"], date=dot_date(i))}</span>
  <span class="card-lede">{esc(plain(content(i)["lede"]))}</span></a>''' for i in items)
        grid.append(f'<h2 class="month">{m}<span>{t("count", n=len(items))}</span></h2><div class="grid">{cards}</div>')
    body = f'<main class="archive wrap" id="archive">{"".join(grid)}</main>'
    return page(t("brand"), hero, body, plain(lc["lede"]))


def render_issue(i, prev, nxt):
    c = content(i)
    stories = []
    for n, s in enumerate(c["stories"], 1):
        src = "".join(src_chip(tx, u) for tx, u in s["links"])
        parts = "".join(f'<section class="part"><h3>{label}</h3>{blocks(s[k])}</section>'
                        for k, label in L[LANG]["sections"] if s.get(k))
        org = f'<span class="org">{esc(s["org"])}</span>' if s["org"] else ""
        img = s.get("image")
        fig = (f'''<figure class="story-img"><img src="{esc(asset(img["src"]))}" alt="{esc(img["alt"])}" loading="lazy" decoding="async">
  {f'<figcaption>{esc(img["credit"])}</figcaption>' if img["credit"] else ""}</figure>''' if img else "")
        stat = s.get("stat")
        stat_html = (f'<p class="stat"><b>{esc(stat[0])}</b><span>{esc(stat[1])}</span></p>' if stat else "")
        stories.append(f'''<article class="story{' has-img' if img else ''}" id="s{n}">
  {fig}
  <header class="story-head">
    <span class="story-no">{n}</span>
    <div><p class="story-meta">{org}{esc(plain(s.get("type", "")))}{stars(s["stars"])}</p>
    <h2>{esc(plain(s["title"]))}</h2></div>
  </header>
  <div class="lead-row">{stat_html}<p class="tldr">{inline(s.get("tldr"))}</p></div>
  {parts}
  <p class="sources"><span class="src-label">{t("sources")}</span>{src}</p>
</article>''')
    repos = "".join(f'''<a class="repo" href="{esc(r["href"])}">
  <span class="repo-name">{GH_SVG}<span>{esc(r["name"]).replace("/", "/<wbr>")}</span></span><span class="repo-star">{esc(r.get("star", ""))}</span>
  <span class="repo-what">{inline(r.get("what"))}</span>
  {f'<span class="repo-how">{inline(r.get("why" if PUBLIC else "how"))}</span>' if r.get("why" if PUBLIC else "how") else ""}</a>''' for r in c["repos"])
    acts = "".join(f"<li>{inline(a)}</li>" for a in c["actions"])
    briefs = "".join(brief(b) for b in c["briefs"])
    checks = "".join(f'<li class="{"ok" if ok else "todo"}">{inline(tx)}</li>' for ok, tx in c["checks"])
    def pg(x, cls, label):
        if not x:
            return "<span></span>"
        return f'''<a class="pg {cls}" href="{ymd(x)}.html"><span class="pg-label">{label}</span>{cover(x)}
  <span class="card-date">{t("issue_date", no=x["no"], date=dot_date(x))}</span>
  <span class="card-lede">{esc(plain(content(x)["lede"]))}</span></a>'''
    nav = pg(prev, "prev", t("prev")) + pg(nxt, "next", t("next"))
    band = f'''<header class="issue-head wrap">
    {cover(i, big=True)}
    <div class="issue-intro">
      <p class="kicker" style="--i:0">{t("issue_date", no=i["no"], date=dot_date(i))}</p>
      <h1 style="--i:1">{esc(plain(c["lede"]))}</h1>
      <ol class="hero-heads" style="--i:2">{heads(i)}</ol>
    </div>
  </header>'''
    body = f'''<main class="issue wrap">
  {"".join(stories)}
  {f'<section class="block"><h2>{t("briefs")}</h2><ol class="briefs">{briefs}</ol></section>' if briefs else ""}
  {f'<section class="block"><h2>{t("repos")}<span class="h-tag">{GH_SVG}GitHub</span></h2><div class="repos">{repos}</div></section>' if repos else ""}
  {f'<section class="block"><h2>{t("actions")}</h2><ol class="actions">{acts}</ol></section>' if acts and not PUBLIC else ""}
  {f'<details class="checks"><summary>{t("checks")}</summary><ul>{checks}</ul></details>' if checks and not PUBLIC else ""}
  <nav class="pager">{nav}</nav>
</main>'''
    notice = t("untranslated") if LANG == "en" and not i.get("en") else ""
    return page(t("title", no=i["no"], date=dot_date(i)), band, body, plain(c["lede"]), slug=ymd(i), notice=notice)


def main():
    global LANG, BASE
    issues = sorted((parse_issue(p) for p in SRC.glob("AI-Daily-*.md")), key=lambda i: i["date"])
    if not issues:
        sys.exit(f"no issues found in {SRC}")
    for n, i in enumerate(issues, 1):
        i["no"] = n
        i["colors"] = cover_colors(i["color_raw"], n)
        en = SRC / "en" / f"AI-Daily-{ymd(i)}.md"
        if en.is_file():
            i["en"] = parse_issue(en)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for a in ASSETS:
        src = HERE / a
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, OUT / a)
    if (SRC / "images").is_dir():
        shutil.copytree(SRC / "images", OUT / "images")
    for LANG, BASE, out in (("zh", "", OUT), ("en", "../", OUT / "en")):
        out.mkdir(exist_ok=True)
        (out / "index.html").write_text(render_index(issues), encoding="utf-8")
        for n, i in enumerate(issues):
            prev = issues[n - 1] if n else None
            nxt = issues[n + 1] if n + 1 < len(issues) else None
            (out / f"{ymd(i)}.html").write_text(render_issue(i, prev, nxt), encoding="utf-8")
    n_en = sum(1 for i in issues if i.get("en"))
    print(f"built {len(issues)} issues (zh + en, {n_en} with English editions) -> {OUT}")


if __name__ == "__main__":
    main()
