#!/usr/bin/env python3
"""Quarterly review: compare 产品君's recent weekly roundups with what this daily published.

Implements selection.md §八. For each item in the last N weekly reports, decides whether the
daily (a) wrote it, (b) had it in a candidate pool but dropped it, or (c) never saw it. Writes
work/review-DATE.md with the three buckets, a category breakdown, and what to change.

Usage, from the repo root:
  python3 -I skill/ai-daily/scripts/review_quarter.py [--weeks 10] [--save work/cpj.json]
  python3 -I skill/ai-daily/scripts/review_quarter.py --from-json work/cpj.json   # offline rerun
Standard library only. Needs network (Bilibili public API, anonymous) unless --from-json.
"""
import argparse
import datetime as dt
import http.cookiejar
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from collect import key_tokens, latin_tokens, COMMON_WORDS, BJ  # noqa: E402

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
PRODUCT_JUN_MID = 1845434732          # B 站「产品君」
SERIES_RE = re.compile(r"盘点一周AI大事")
# Same buckets as selection.md §一, so the breakdown is comparable across quarters.
CATEGORIES = [
    ("科研/数学突破", r"猜想|难题|数学|千禧年|菲尔兹|诺奖|科学家|材料|物理|量子|果蝇|大脑|意识|生物|分子|天气|AI ?科学家|AI Scientist|AI研究员|Co-Scientist|AlphaEvolve|科研"),
    ("机器人/硬件/芯片", r"机器人|芯片|灵巧手|脑机|Neuralink|硬件|RTX|纳米|人形"),
    ("Agent/产品形态", r"龙虾|Claw|智能体|Agent|agent|Codex|Claude Code|Cowork|助理|技能|[Ss]kill|MCP|Harness|harness|浏览器|Computer|电脑操作|员工|公司|超级应用|dots|Copilot|桌面版|Duet|Managed|协议|Deep Research|深度研究|框架"),
    ("设计/办公工具", r"Figma|Stitch|Design|设计|PPT|NotebookLM|Office|画布|网页|矢量|Canvas|可视化|文件生成"),
    ("多媒体生成模型", r"视频|图像|生图|Image|音乐|语音|TTS|配音|声音|数字人|3D|Avatar|超分|打光|动作|嘴型|动画|试穿|分割|OCR|识别|同传|翻译|世界模型|Genie|Veo|Sora|Seedance|Banana|Music|Audio|Transcribe|口语|字体|MIDI|Omni"),
    ("大模型发布/竞赛", r"模型|GPT|Claude|Gemini|Kimi|DeepSeek|Qwen|千问|GLM|智谱|MiniMax|Grok|Muse|Mythos|Fable|Opus|Sonnet|Haiku|Gemma|Nemotron|混元|MiMo|Inkling|Astra|Sol"),
]


def session():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    hdr = {"User-Agent": UA, "Referer": "https://search.bilibili.com/"}
    op.open(urllib.request.Request("https://www.bilibili.com/", headers=hdr), timeout=20).read()
    return op, hdr


def get_json(op, hdr, url):
    with op.open(urllib.request.Request(url, headers=hdr), timeout=20) as r:
        return json.load(r)


def split_items(desc):
    """One weekly item per line of the video description; drops the series tagline."""
    return [l.strip() for l in re.split(r"\n|\s{2,}", desc or "")
            if 4 < len(l.strip()) < 100 and not l.strip().startswith("盘点一周")]


def load_weeklies_json(path, weeks):
    """Offline alternative: a JSON file {bvid: {date, title, view, desc}} saved earlier."""
    data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    rows = data.values() if isinstance(data, dict) else data
    out = [{"bvid": v.get("bvid", k), "date": dt.date.fromisoformat(v["date"]), "title": v["title"],
            "view": v.get("view", 0), "items": split_items(v.get("desc"))}
           for k, v in (data.items() if isinstance(data, dict) else enumerate(rows))]
    out.sort(key=lambda w: w["date"], reverse=True)
    return out[:weeks]


def fetch_weeklies(weeks, mid, save=None):
    """Recent 盘点一周AI大事 videos by `mid`, via the public search endpoint (no login needed)."""
    op, hdr = session()
    seen = {}
    for kw in ("产品君 盘点一周AI大事", "产品君", "盘点一周AI大事"):
        for page in (1, 2, 3):
            q = urllib.parse.urlencode({"search_type": "video", "keyword": kw, "order": "pubdate", "page": page})
            try:
                d = get_json(op, hdr, "https://api.bilibili.com/x/web-interface/search/type?" + q)
            except Exception as e:  # noqa: BLE001
                print(f"search failed ({kw} p{page}): {e}", file=sys.stderr)
                continue
            if d.get("code") != 0:
                print(f"search code {d.get('code')}: {d.get('message')}", file=sys.stderr)
                break
            for r in d["data"].get("result") or []:
                title = re.sub(r"<[^>]+>", "", r.get("title") or "")   # search wraps hits in <em class="keyword">
                if r.get("mid") == mid and SERIES_RE.search(title):
                    seen[r["bvid"]] = dt.date.fromtimestamp(r["pubdate"])
            time.sleep(1)
        if len(seen) >= weeks:
            break
    out, raw = [], {}
    for bvid, date in sorted(seen.items(), key=lambda x: x[1], reverse=True)[:weeks]:
        v = get_json(op, hdr, f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")["data"]
        raw[bvid] = {"date": date.isoformat(), "title": v["title"], "view": v["stat"]["view"], "desc": v.get("desc") or ""}
        out.append({"bvid": bvid, "date": date, "title": v["title"], "view": v["stat"]["view"],
                    "items": split_items(v.get("desc"))})
        time.sleep(0.6)
    if save:
        pathlib.Path(save).write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def load_daily(outputs, since):
    """Headlines (要闻 + 快讯 + 开源) from each daily issue since `since`."""
    issues = {}
    for p in sorted(outputs.glob("AI-Daily-*.md")):
        d = dt.date.fromisoformat(re.search(r"\d{4}-\d{2}-\d{2}", p.name).group())
        if d < since:
            continue
        heads = []
        for line in p.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^### \d*\.?\s*(.+)$", line) or re.match(r"^\d+\.\s+\*\*(.+?)\*\*", line) \
                or re.match(r"^\d+\.\s+项目名[：:]\s*(.+)$", line) or re.match(r"^### ([\w.-]+/[\w.-]+)\s*$", line)
            if m:
                heads.append(m.group(1).strip())
        issues[d] = heads
    return issues


def load_candidates(work, since):
    """Candidate titles per date from work/candidates-*.json, when present."""
    cands = {}
    for p in sorted(work.glob("candidates-*.json")):
        d = dt.date.fromisoformat(re.search(r"\d{4}-\d{2}-\d{2}", p.name).group())
        if d < since:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        cands[d] = [c["title"] + " " + c.get("title_zh", "") for c in data.get("candidates", [])]
    return cands


def toks(s):
    return key_tokens(s) | latin_tokens(s)


def matches(item, pool):
    """True when a weekly item plausibly refers to the same event as some headline in `pool`.
    Shared tokens are split into generic ones (COMMON_WORDS: vendor names, "model", ...) and
    specific ones. Match on two specific tokens, or one specific plus two generic
    (「Gemini 3.5 Flash」 vs "computer use in Gemini 3.5 Flash" shares gemini/flash/3.5),
    or one specific token of ≥6 chars (a product name such as gpt-5.6)."""
    ki = toks(item)
    if not ki:
        return False
    for h in pool:
        hit = ki & toks(h)
        specific = hit - COMMON_WORDS
        if len(specific) >= 2 or (specific and len(hit) >= 3) or any(len(k) >= 6 for k in specific):
            return True
    return False


def category(item):
    return next((n for n, p in CATEGORIES if re.search(p, item)), "其他/现象")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=10)
    ap.add_argument("--mid", type=int, default=PRODUCT_JUN_MID)
    ap.add_argument("--repo", default=str(HERE.parents[2]))
    ap.add_argument("--from-json", help="skip the network; read weeklies from a JSON saved with --save")
    ap.add_argument("--save", help="also write the fetched weeklies to this JSON (for --from-json later)")
    a = ap.parse_args()
    repo = pathlib.Path(a.repo)
    weeklies = load_weeklies_json(a.from_json, a.weeks) if a.from_json else fetch_weeklies(a.weeks, a.mid, a.save)
    if not weeklies:
        sys.exit("no weekly reports fetched; Bilibili search may be rate-limiting, retry later")
    since = min(w["date"] for w in weeklies) - dt.timedelta(days=7)
    daily = load_daily(repo / "outputs", since)
    cands = load_candidates(repo / "work", since)

    rows, by_cat = [], {}
    for w in weeklies:
        week_days = [w["date"] - dt.timedelta(days=k) for k in range(0, 8)]   # the 7 days before the Saturday video
        written = [h for d in week_days for h in daily.get(d, [])]
        pooled = [c for d in week_days for c in cands.get(d, [])]
        had_pool = any(d in cands for d in week_days)
        for it in w["items"]:
            if matches(it, written):
                verdict = "已写"
            elif had_pool and matches(it, pooled):
                verdict = "候选池有，被淘汰"
            elif had_pool:
                verdict = "候选池没有"
            else:
                verdict = "无候选池记录"
            cat = category(it)
            by_cat.setdefault(cat, 0)
            by_cat[cat] += 1
            rows.append((w["date"], it, cat, verdict))

    n = len(rows)
    counts = {k: sum(1 for r in rows if r[3] == k) for k in ("已写", "候选池有，被淘汰", "候选池没有", "无候选池记录")}
    known = n - counts["无候选池记录"]
    lines = [f"# 季度复核 {dt.datetime.now(BJ):%Y-%m-%d}", "",
             f"对照产品君最近 {len(weeklies)} 期「盘点一周AI大事」（{weeklies[-1]['date']} → {weeklies[0]['date']}），共 {n} 条。"
             f"本日报同期有 {len(daily)} 期，候选池记录 {len(cands)} 天。", "",
             "| 结果 | 条数 | 占比 |", "|---|---|---|"]
    for k, v in counts.items():
        lines.append(f"| {k} | {v} | {v / n:.0%} |")
    lines += ["", "## 判断", ""]
    if known:
        miss = counts["候选池没有"] / known
        lines.append(f"- 在有候选池记录的 {known} 条里，{miss:.0%} 根本没进候选池。" +
                     ("超过 30%：信源有缺口，去 `collect.py` 的 `SOURCES` 补。" if miss > 0.3 else "低于 30%，信源覆盖够用。"))
        lines.append(f"- 候选池有但被淘汰的 {counts['候选池有，被淘汰']} 条，逐条看下面的清单：如果有本该写的大事，回头看是哪一项打分偏低。")
    else:
        lines.append("- 这段时间没有候选池记录（`work/` 不进仓库，或者日报当时还没用采集脚本），只能看「已写 / 未写」。")
    lines += ["", "## 产品君的类别分布（对照 selection.md 第一节）", "", "| 类别 | 条数 | 占比 |", "|---|---|---|"]
    for c, v in sorted(by_cat.items(), key=lambda x: -x[1]):
        lines.append(f"| {c} | {v} | {v / n:.0%} |")
    lines += ["", "selection.md 第一节的基线：旗舰模型 26%，研究员开源 20%，多媒体模型 17%，Agent 工具 9%。某一类变化超过 10 个百分点就更新那张表。", ""]
    for verdict in ("候选池没有", "候选池有，被淘汰", "已写", "无候选池记录"):
        sub = [r for r in rows if r[3] == verdict]
        if not sub:
            continue
        lines += [f"## {verdict}（{len(sub)}）", ""]
        for d, it, cat, _ in sub:
            lines.append(f"- {d} · {cat} · {it}")
        lines.append("")
    lines += ["## 期次", ""] + [f"- {w['date']} {w['title']}（{w['view']} 播放，{len(w['items'])} 条）" for w in weeklies]
    out = repo / "work" / f"review-{dt.datetime.now(BJ):%Y-%m-%d}.md"
    out.parent.mkdir(exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{n} items from {len(weeklies)} weeklies -> {out.relative_to(repo)}")
    print("  " + "  ".join(f"{k} {v}" for k, v in counts.items()))


if __name__ == "__main__":
    main()
