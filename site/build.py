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
PALETTE = 6  # number of cover hues in style.css (.c0 ... .c5)
ASSETS = ("style.css", "fonts")

STORY_KEYS = [("来源链接", "src"), ("类型", "type"), ("推荐指数", "stars"),
              ("一句话总结", "tldr"), ("为什么重要", "why"), ("核心观点", "points"),
              ("对 AI", "insight"), ("这意味着", "insight"), ("可落地", "action"), ("风险", "risk"),
              ("是否值得精读", "worth")]
REPO_KEYS = [("项目名", "name"), ("GitHub 链接", "url"), ("Star 数", "star"),
             ("解决什么问题", "what"), ("为什么值得", "why"), ("如何用到", "how")]
# PUBLIC (default) renders the parts that matter to any AI follower; the markdown keeps the
# author's own notes too (action items, repo how-tos, QA checklist), shown with AI_DAILY_PRIVATE=1.
PUBLIC = os.environ.get("AI_DAILY_PRIVATE") != "1"
SECTION_TITLES = ([("why", "为什么重要"), ("points", "核心观点"),
                   ("insight", "这意味着什么"), ("risk", "风险与待验证")] if PUBLIC else
                  [("why", "为什么重要"), ("points", "核心观点"),
                   ("insight", "对 AI PM / FDE 的启发"), ("action", "可以动手做的事"),
                   ("risk", "风险提醒")])
TAGLINE = ("每天 3 条值得关注的 AI 动态，附观点、要点和风险提示" if PUBLIC
           else "AI PM / FDE 的每日情报与行动清单")
FOOT = ("内容由 AI 整理、人工核验来源链接；判断可能有误，请以原文为准。" if PUBLIC
        else "给 AI 产品经理和 FDE 的每日情报。内容由 AI 整理、人工核验，转发前请点开原文确认。")


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
            "links": links, **{k: v for k, v in f.items() if k != "stars"}}


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
    for sec in re.split(r"^## ", text, flags=re.M)[1:]:
        name, _, body = sec.partition("\n")
        if "快讯" in name:
            issue["briefs"] = [m.group(1) for m in re.finditer(r"^\d+\.\s+(.+)$", body, flags=re.M)]
        elif "条内容" in name or "最值得关注" in name or "要闻" in name:
            issue["stories"] = [parse_story(b) for b in re.split(r"^### ", body, flags=re.M)[1:]]
        elif "观点" in name or "一句话" in name:
            q = " ".join(l.lstrip("> ").strip() for l in body.splitlines() if l.startswith(">"))
            issue["lede"] = re.sub(r"^今天我最应该记住的是[：:]\s*", "", q)
        elif "开源项目" in name:
            issue["repos"] = parse_repos(body)
        elif "行动" in name:
            issue["actions"] = [m.group(1) for m in re.finditer(r"^\d+\.\s+(.+)$", body, flags=re.M)]
        elif "验证" in name:
            issue["checks"] = [(m.group(1) != " ", m.group(2)) for m in
                               re.finditer(r"^- \[([ xX])\]\s+(.+)$", body, flags=re.M)]
    return issue
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


def plain(s):
    return re.sub(r"[`*]", "", s or "")


def stars(n):
    if not n:
        return ""
    return f'<span class="stars" title="推荐 {n} / 5">{"★" * n}<i>{"★" * (5 - n)}</i></span>'


def ymd(i):
    return i["date"].isoformat()


def dot_date(i):
    return f'{i["date"]:%Y.%m.%d} 周{WEEK[i["date"].weekday()]}'


def cover(i, big=False):
    """A generated issue cover: brand strip, lead headline, two more headlines, issue badge."""
    s = i["stories"]
    more = "".join(f"<li>{esc(plain(x['title']))}</li>" for x in s[1:3])
    return f'''<div class="cover c{i["no"] % PALETTE}{' big' if big else ''}" style="view-transition-name:cv-{ymd(i)}" aria-hidden="true">
  <div class="cv-panel">
    <div class="cv-head"><span class="cv-brand">AI 每日简报</span><span class="cv-date">{i["date"]:%Y.%m.%d}</span></div>
    <p class="cv-lead">{esc(plain(s[0]["title"])) if s else ""}</p>
    <ul class="cv-more">{more}</ul>
  </div>
  <span class="cv-no">#{i["no"]:02d}</span>
</div>'''


def heads(i, prefix=""):
    """Numbered headline list used in both hero and issue head; --i drives the stagger."""
    return "".join(f'''<li style="--i:{n}"><a href="{prefix}#s{n}">
  <span class="h-title">{esc(plain(s["title"]))}</span>{stars(s["stars"])}
  <span class="h-tldr">{inline(s.get("tldr"))}</span></a></li>''' for n, s in enumerate(i["stories"], 1))


def page(title, band, body, desc=""):
    return f'''<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta name="theme-color" content="#0b0f2a">
<link rel="preload" href="fonts/SmileySans-Oblique.ttf.woff2" as="font" type="font/woff2" crossorigin>
<link rel="stylesheet" href="style.css">
</head>
<body>
<div class="band">
<header class="bar"><div class="wrap bar-in">
  <a class="logo" href="index.html">AI 每日简报</a>
  <nav><a href="index.html#archive">往期</a><a href="{REPO_URL}">GitHub</a></nav>
</div></header>
{band}
</div>
{body}
<footer class="site-foot"><div class="wrap">{FOOT}</div></footer>
</body>
</html>'''


def render_index(issues):
    latest = issues[-1]
    hero = f'''<section class="hero wrap">
  <a class="hero-cover" href="{ymd(latest)}.html">{cover(latest, big=True)}</a>
  <div class="hero-text">
    <p class="kicker" style="--i:0">{TAGLINE}</p>
    <p class="kicker sub" style="--i:0">最新一期 · 第 {latest["no"]} 期 · {dot_date(latest)}</p>
    <h1 class="hero-lede" style="--i:1"><a href="{ymd(latest)}.html">{esc(plain(latest["lede"]))}</a></h1>
    <ol class="hero-heads" style="--i:2">{heads(latest, ymd(latest) + ".html")}</ol>
  </div>
</section>'''
    months = {}
    for i in reversed(issues[:-1]):
        months.setdefault(f'{i["date"].year} 年 {i["date"].month} 月', []).append(i)
    grid = []
    for m, items in months.items():
        cards = "".join(f'''<a class="card" href="{ymd(i)}.html">{cover(i)}
  <span class="card-date">第 {i["no"]} 期 · {dot_date(i)}</span>
  <span class="card-lede">{esc(plain(i["lede"]))}</span></a>''' for i in items)
        grid.append(f'<h2 class="month">{m}<span>{len(items)} 期</span></h2><div class="grid">{cards}</div>')
    body = f'<main class="archive wrap" id="archive">{"".join(grid)}</main>'
    return page("AI 每日简报", hero, body, plain(latest["lede"]))


def render_issue(i, prev, nxt):
    stories = []
    for n, s in enumerate(i["stories"], 1):
        src = "".join(f'<a href="{esc(u)}">{esc(t)}</a>' for t, u in s["links"])
        parts = "".join(f'<section class="part"><h3>{label}</h3>{blocks(s[k])}</section>'
                        for k, label in SECTION_TITLES if s.get(k))
        org = f'<span class="org">{esc(s["org"])}</span>' if s["org"] else ""
        stories.append(f'''<article class="story" id="s{n}">
  <header class="story-head">
    <span class="story-no">{n}</span>
    <div><p class="story-meta">{org}{esc(plain(s.get("type", "")))}{stars(s["stars"])}</p>
    <h2>{esc(plain(s["title"]))}</h2></div>
  </header>
  <p class="tldr">{inline(s.get("tldr"))}</p>
  {parts}
  <p class="sources">原文{src}</p>
</article>''')
    repos = "".join(f'''<a class="repo" href="{esc(r["href"])}">
  <span class="repo-name">{esc(r["name"])}</span><span class="repo-star">{esc(r.get("star", ""))}</span>
  <span class="repo-what">{inline(r.get("what"))}</span>
  {f'<span class="repo-how">{inline(r.get("why" if PUBLIC else "how"))}</span>' if r.get("why" if PUBLIC else "how") else ""}</a>''' for r in i["repos"])
    acts = "".join(f"<li>{inline(a)}</li>" for a in i["actions"])
    briefs = "".join(f"<li>{inline(b)}</li>" for b in i["briefs"])
    checks = "".join(f'<li class="{"ok" if ok else "todo"}">{inline(t)}</li>' for ok, t in i["checks"])
    nav = (f'<a class="prev" href="{ymd(prev)}.html">上一期<b>{dot_date(prev)}</b></a>' if prev else "<span></span>") + \
          (f'<a class="next" href="{ymd(nxt)}.html">下一期<b>{dot_date(nxt)}</b></a>' if nxt else "<span></span>")
    band = f'''<header class="issue-head wrap">
    {cover(i, big=True)}
    <div class="issue-intro">
      <p class="kicker" style="--i:0">第 {i["no"]} 期 · {dot_date(i)}</p>
      <h1 style="--i:1">{esc(plain(i["lede"]))}</h1>
      <ol class="hero-heads" style="--i:2">{heads(i)}</ol>
    </div>
  </header>'''
    body = f'''<main class="issue wrap">
  {"".join(stories)}
  {f'<section class="block"><h2>快讯</h2><ol class="actions briefs">{briefs}</ol></section>' if briefs else ""}
  {f'<section class="block"><h2>值得研究的开源项目</h2><div class="repos">{repos}</div></section>' if repos else ""}
  {f'<section class="block"><h2>明天可以做的事</h2><ol class="actions">{acts}</ol></section>' if acts and not PUBLIC else ""}
  {f'<details class="checks"><summary>人工验证清单</summary><ul>{checks}</ul></details>' if checks and not PUBLIC else ""}
  <nav class="pager">{nav}</nav>
</main>'''
    return page(f'第 {i["no"]} 期 · {dot_date(i)} · AI 每日简报', band, body, plain(i["lede"]))


def main():
    issues = sorted((parse_issue(p) for p in SRC.glob("AI-Daily-*.md")), key=lambda i: i["date"])
    if not issues:
        sys.exit(f"no issues found in {SRC}")
    for n, i in enumerate(issues, 1):
        i["no"] = n
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for a in ASSETS:
        src = HERE / a
        (shutil.copytree if src.is_dir() else shutil.copy2)(src, OUT / a)
    (OUT / "index.html").write_text(render_index(issues), encoding="utf-8")
    for n, i in enumerate(issues):
        prev = issues[n - 1] if n else None
        nxt = issues[n + 1] if n + 1 < len(issues) else None
        (OUT / f"{ymd(i)}.html").write_text(render_issue(i, prev, nxt), encoding="utf-8")
    print(f"built {len(issues)} issues -> {OUT}")


if __name__ == "__main__":
    main()
