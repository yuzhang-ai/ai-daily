#!/usr/bin/env python3
"""Offline tests for collect.py. No network: every fetch is served from tests/fixtures/.

Run from the repo root:  python3 -I skill/ai-daily/scripts/test_collect.py
Fixtures are trimmed real responses captured 2026-11-12 (see FIXTURES below).
"""
import datetime as dt
import pathlib
import sys
import unittest
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import collect as C  # noqa: E402

FX = HERE / "tests" / "fixtures"
NOW = dt.datetime(2026, 11, 11, 14, 56, tzinfo=C.UTC)        # 2026-11-11 22:56 Beijing, like the audit rerun
SINCE, UNTIL = NOW - dt.timedelta(hours=36), NOW + C.FUTURE_SLACK

FIXTURES = {   # url -> fixture file (bytes); what the server returned, trimmed
    "https://blog.google/rss/": "google_all_rss.xml",
    "https://blog.google/technology/ai/rss/": "google_ai_rss.xml",
    "https://openai.com/news/rss.xml": "openai_rss.xml",
    "https://mistral.ai/news/rss": "mistral_rss.xml",
    "https://daily.juya.uk/rss.xml": "juya_rss.xml",
    "https://deepmind.google/blog/rss.xml": "deepmind_rss.xml",
    "https://github.com/trending": "github_trending.html",
    "https://www.anthropic.com/sitemap.xml": "anthropic_sitemap.xml",
}
PAGES = {   # primary pages: minimal HTML with the date metadata the real pages expose
    "https://tailscale.com/blog/oauth-apps-ga":
        '<html><head><title>OAuth apps GA</title><script type="application/ld+json">{"datePublished":"2026-11-09T20:30:00.000Z"}</script></head></html>',
    "https://blog.google/innovation-and-ai/models-and-research/gemini-models/gemini-4-carbon-now-available/":
        '<html><head><meta property="og:title" content="Gemini 4 Carbon is now available"/><meta property="article:published_time" content="2026-11-10"/></head></html>',
    "https://claude.com/resources/articles/more-ways-to-work-with-claude-sheets-whiteboards-and-interactive-connectors":
        '<html><head><meta property="og:title" content="Working with Claude Sheets, Whiteboards, and Interactive Connectors"/><meta property="article:published_time" content="2026-11-10"/><meta property="og:description" content="New artifact types."/></head></html>',
    "https://claude.com/resources/articles/jpmorganchase-expands-claude-code":
        '<html><head><meta property="og:title" content="JPMorganChase expands Claude Code"/><meta property="article:published_time" content="2026-11-04"/></head></html>',
    "https://developer.chrome.com/blog/modern-web-guidance-v1":
        '<html><head><title>Modern Web Guidance 1.0</title></head><body>Published: November 10, 2026</body></html>',
    "https://www.anthropic.com/news/roadshow-launch":
        '<html><head><meta property="og:title" content="Anthropic launches roadshow for proposed initial public offering"/><meta property="article:published_time" content="2026-11-10T00:00:00.000Z"/></head></html>',
}
CLAUDE_LISTING = ('<html><body>'
                  '<a href="/resources/articles/more-ways-to-work-with-claude-sheets-whiteboards-and-interactive-connectors">x</a>'
                  '<a href="/resources/articles/jpmorganchase-expands-claude-code">y</a>'
                  '<a href="/resources/articles/more-ways-to-work-with-claude-sheets-whiteboards-and-interactive-connectors">dup</a>'
                  '</body></html>')


class Net:
    """Fake network. `script` lets a test make a URL fail N times then succeed."""
    def __init__(self):
        self.calls, self.script = [], {}

    def __call__(self, url, timeout=20, retries=C.RETRIES):
        self.calls.append(url)
        for attempt in range(retries + 1):
            fail = self.script.get(url)
            if fail:
                self.script[url] = fail - 1
                if attempt == retries:
                    raise C.FetchError("XML parse error (simulated)", snippet="")
                continue
            return self.body(url)
        raise C.FetchError("unreachable")

    def body(self, url):
        if url in FIXTURES:
            return (FX / FIXTURES[url]).read_bytes().decode("utf-8", "replace")
        if url in PAGES:
            return PAGES[url]
        if url == "https://claude.com/resources/articles":
            return CLAUDE_LISTING
        if url.startswith("https://api.github.com/repos/"):
            return '{"description":"","topics":[]}'
        raise C.FetchError(f"no fixture for {url}", status=404)


class Base(unittest.TestCase):
    def setUp(self):
        self.net = Net()
        C.get = self.net
        C.NOW, C.HOURS = NOW, 36
        C._META.clear()

    def src(self, name):
        return next(s for s in C.SOURCES if s["name"] == name)

    def run_src(self, name):
        return C.run_source(self.src(name), SINCE, UNTIL)


# ---------- P0: event time vs article time, window bounds ----------
class TestTime(Base):
    def test_aggregator_pubdate_is_not_event_time(self):
        items, _ = self.run_src("橘鸦 AI 早报")
        ts = next(x for x in items if "Tailscale" in x["title"])
        self.assertIsNone(ts["event_time"])
        self.assertEqual(ts["article_time"].date(), dt.date(2026, 11, 11))

    def test_stale_event_behind_fresh_aggregator_is_excluded(self):
        items, _ = self.run_src("橘鸦 AI 早报")
        ts = [x for x in items if "Tailscale" in x["title"]]
        c = C.summarize(ts, set(), [], SINCE, UNTIL, [10])
        self.assertEqual(c["window"], "stale")           # 11-09 20:30Z is 42h before cutoff
        self.assertIn("datePublished", c["time_source"])

    def test_future_feed_item_is_flagged_not_included(self):
        items, st = self.run_src("OpenAI")
        fut = [x for x in items if x["title"].startswith("Gilbert")]
        self.assertEqual(len(fut), 1)
        self.assertEqual(C.window_status(fut[0]["event_time"], fut[0]["precision"], SINCE, UNTIL), "future")
        self.assertEqual(st["future"], 1)

    def test_future_six_hours_not_in(self):
        t = NOW + dt.timedelta(hours=6)
        self.assertEqual(C.window_status(t, "minute", SINCE, UNTIL), "future")

    def test_clock_slack_is_bounded(self):
        self.assertEqual(C.window_status(NOW + dt.timedelta(minutes=9), "minute", SINCE, UNTIL), "in")
        self.assertEqual(C.window_status(NOW + dt.timedelta(minutes=11), "minute", SINCE, UNTIL), "future")

    def test_date_only_precision_kept_and_compared_by_day(self):
        d, p = C.when("2026-11-10")
        self.assertEqual(p, "day")
        # 11-10 00:00Z is 38h56m before NOW, outside a 36h window by the minute, but the
        # window starts on 11-10 (02:56Z) so by day it is still in
        self.assertEqual(C.window_status(d, p, SINCE, UNTIL), "in")
        self.assertEqual(C.window_status(C.when("2026-11-09")[0], "day", SINCE, UNTIL), "stale")
        self.assertEqual(C.window_status(C.when("2026-11-12")[0], "day", SINCE, UNTIL), "future")

    def test_timezone_boundary(self):
        # 08:00+08:00 == 00:00Z; make sure offsets are honoured, not stripped
        d, _ = C.when("2026-11-10T08:00:00+08:00")
        self.assertEqual(d, dt.datetime(2026, 11, 10, 0, 0, tzinfo=C.UTC))

    def test_unknown_time_goes_to_pending_not_dropped(self):
        x = C.item({"name": "HN", "tier": 3}, "Some model thing", "https://example.org/post")
        x["hn_points"] = 150
        cands, _, run = C.collect(dt.date(2026, 11, 11), 36, HERE.parent.parent.parent.parent, NOW, sources=[])
        c = C.summarize([x], set(), [], SINCE, UNTIL, [0])
        self.assertEqual(c["window"], "unknown")
        self.assertEqual(c["time_source"], "未知")

    def test_stale_official_items_are_counted_but_not_carried(self):
        items, st = self.run_src("Mistral")
        self.assertEqual((st["items"], st["stale"]), (3, 3))
        self.assertEqual(items, [])                   # nothing to cluster, status still shows them

    def test_article_time_upper_bound_marks_stale_without_fetch(self):
        old = C.item({"name": "橘鸦 AI 早报", "tier": 2}, "Kimi 正式推出托管智能体服务",
                     "https://platform.kimi.com/docs/hosted-agents/", article_time=NOW - dt.timedelta(days=5))
        n = len(self.net.calls)
        c = C.summarize([old], set(), [], SINCE, UNTIL, [10])
        self.assertEqual(c["window"], "stale")
        self.assertIn("早于窗口", c["time_source"])
        self.assertEqual(len(self.net.calls), n)      # no page fetch spent on it

    def test_old_plus_fresh_mention_is_not_shortcut_to_stale(self):
        # same product, two developments: an October article and a fresh one. The cluster must
        # not be declared stale on the old mention alone.
        s = {"name": "The Rundown", "tier": 2}
        old = C.item(s, "Kimi K3.1 Pro challenges the frontier", "https://rundown.example/k31", article_time=NOW - dt.timedelta(days=16))
        new = C.item({"name": "橘鸦 AI 早报", "tier": 2}, "月之暗面开放 Kimi K3.1 Pro 模型权重", "https://weixin.example/x",
                     article_time=NOW - dt.timedelta(hours=3))
        c = C.summarize([old, new], set(), [], SINCE, UNTIL, [10])
        self.assertEqual(c["window"], "unknown")

    def test_in_window_article_with_official_url_gets_page_date(self):
        x = C.item({"name": "橘鸦 AI 早报", "tier": 2}, "Tailscale OAuth apps 正式可用",
                   "https://tailscale.com/blog/oauth-apps-ga", article_time=NOW - dt.timedelta(hours=5))
        c = C.summarize([x], set(), [], SINCE, UNTIL, [10])
        self.assertEqual(c["window"], "stale")        # article fresh, event 42h old
        self.assertEqual(c["event_time_bj"], "11-10 04:30")

    def test_run_log_fields(self):
        _, _, run = C.collect(dt.date(2026, 11, 11), 36, HERE.parent.parent.parent.parent, NOW,
                              sources=[self.src("OpenAI")])
        for k in ("cutoff_utc", "cutoff_bj", "window_utc", "window_bj", "rules_version", "commit",
                  "configured", "failed", "coverage_gaps", "future_slack_minutes"):
            self.assertIn(k, run)
        self.assertEqual(run["cutoff_bj"], "2026-11-11 22:56")
        self.assertEqual(run["configured"], 1)


# ---------- P0: official channels ----------
class TestChannels(Base):
    def test_google_full_feed_has_carbon_and_filters_non_ai(self):
        items, _ = self.run_src("Google 全站")
        titles = [x["title"] for x in items]
        self.assertTrue(any("Gemini 4 Carbon is now available" == t for t in titles))
        self.assertFalse(any("domains" in t.lower() or "Fi’s new super network" in t for t in titles))
        self.assertFalse(any("Waze" in t for t in titles))

    def test_google_ai_category_feed_lacks_carbon(self):
        items, _ = self.run_src("Google AI")
        self.assertFalse(any("Carbon" in x["title"] for x in items))

    def test_claude_listing_dedups_and_dates(self):
        items, st = self.run_src("Claude")
        self.assertEqual(st["items"], 2)                 # duplicate link collapsed
        self.assertEqual(st["stale"], 1)                 # jpmorganchase, 2026-11-04
        self.assertEqual(len(items), 1)
        s = items[0]
        self.assertIn("Sheets", s["title"])
        self.assertEqual(s["event_time"].date(), dt.date(2026, 11, 10))
        self.assertEqual(s["precision"], "day")
        self.assertTrue(C.is_official(s["url"]))

    def test_midnight_utc_stamp_is_day_precision(self):
        d, p = C.when("2026-11-10T00:00:00.000Z")
        self.assertEqual(p, "day")
        d, p = C.when("Tue, 10 Nov 2026 16:00:00 GMT")
        self.assertEqual(p, "minute")

    def test_anthropic_sitemap_picks_news_and_research_only(self):
        items, st = self.run_src("Anthropic")
        self.assertEqual(st["transport"], "ok")
        self.assertTrue(all("/legal/" not in x["url"] for x in items))
        self.assertTrue(any(x["url"].endswith("/news/roadshow-launch") for x in items))

    def test_zero_items_is_not_failure_and_not_coverage(self):
        _, st = self.run_src("Mistral")
        self.assertEqual((st["transport"], st["parse"], st["items"]), ("ok", "ok", 3))
        self.assertEqual(st["in_window"], 0)
        # 3 items, all stale: the row says so instead of pretending the channel is covered
        self.assertEqual(st["stale"], 3)


# ---------- P1: official flag, verified flag, clustering ----------
class TestOfficialAndCluster(Base):
    def test_official_host_boundaries(self):
        self.assertTrue(C.is_official("https://blog.google/x"))
        self.assertTrue(C.is_official("https://www.anthropic.com/news/x"))
        self.assertTrue(C.is_official("https://developer.chrome.com/blog/x"))
        self.assertFalse(C.is_official("https://notopenai.com/x"))
        self.assertFalse(C.is_official("https://openai.com.evil.net/x"))
        self.assertFalse(C.is_official("https://blog.google.fake.site/x"))
        self.assertTrue(C.is_official("https://github.com/GoogleChrome/modern-web-guidance"))
        self.assertFalse(C.is_official("https://github.com/random-user/openai-clone"))
        self.assertFalse(C.is_official("https://x.com/OpenAI/status/1"))

    def test_carbon_cluster_has_official_links_and_is_in_window(self):
        a, _ = self.run_src("橘鸦 AI 早报")
        g, _ = self.run_src("Google 全站")
        groups = C.cluster(a + g)
        carbon = next(gr for gr in groups if any("Gemini 4 Carbon is now available" == x["title"] for x in gr))
        self.assertTrue(any("Carbon" in x["title"] and x["source"] == "橘鸦 AI 早报" for x in carbon))
        c = C.summarize(carbon, set(), [], SINCE, UNTIL, [10])
        self.assertTrue(c["official_urls"])
        self.assertTrue(c["from_official_feed"])
        self.assertFalse(c["verified"])
        self.assertEqual(c["window"], "in")

    def test_cross_language_merge_via_canonical_url(self):
        zh = C.item({"name": "橘鸦", "tier": 2}, "Chrome 联合 Firefox、Edge 和 MDN 发布 Modern Web Guidance 1.0",
                    "https://developer.chrome.com/blog/modern-web-guidance-v1")
        hn = C.item({"name": "HN", "tier": 3}, "Show HN: Get your coding agent off ~2019 JavaScript",
                    "https://github.com/GoogleChrome/modern-web-guidance",
                    aliases=["https://developer.chrome.com/blog/modern-web-guidance-v1/"])
        self.assertEqual(len(C.cluster([zh, hn])), 1)

    def test_hn_pointing_at_official_blog_is_official_link_not_verified(self):
        hn = C.item({"name": "HN", "tier": 3}, "Gemini 4 Carbon is now available",
                    "https://deepmind.google/blog/gemini-4-carbon-is-now-available/")
        c = C.summarize([hn], set(), [], SINCE, UNTIL, [0])
        self.assertTrue(c["official_urls"])
        self.assertFalse(c["from_official_feed"])
        self.assertFalse(c["verified"])

    def test_different_versions_do_not_merge(self):
        a = C.item({"name": "A", "tier": 2}, "Gemini Omni 1.2 Flash released", "https://a.example/1")
        b = C.item({"name": "B", "tier": 2}, "Gemini Omni 1.1 Flash released", "https://b.example/2")
        self.assertEqual(len(C.cluster([a, b])), 2)

    def test_same_feed_two_posts_do_not_merge_on_words_alone(self):
        s = {"name": "Google 全站", "tier": 1}
        a = C.item(s, "Gemini 4 Carbon is now available", "https://blog.google/a")
        b = C.item(s, "Gemini 4 Carbon is now available for developers.", "https://blog.google/b")
        # same official feed, different URLs: keep apart (editor merges if it is one launch)
        self.assertEqual(len(C.cluster([a, b])), 2)

    def test_two_shared_product_words_do_not_merge_chinese_titles(self):
        # Found in the 2026-11-12 live run: these were one cluster because both titles yield
        # only {grok, bot} in Latin tokens.
        s = {"name": "橘鸦 AI 早报", "tier": 2}
        a = C.item(s, "Tailscale OAuth apps 正式可用，Grok Bot 可访问内网 MCP 服务器", "https://tailscale.com/blog/oauth-apps-ga")
        b = C.item(s, "马斯克称 Grok Bot 服务成本相对收入高得不可持续", "https://x.com/elonmusk/status/1")
        c = C.item(s, "Grok Bot 宣布为所有用户重置每周限额", "https://x.com/bot/status/2")
        self.assertEqual(len(C.cluster([a, b, c])), 3)

    def test_same_event_zh_en_still_merge_on_tokens(self):
        a = C.item({"name": "橘鸦 AI 早报", "tier": 2}, "谷歌正式开放模型 Gemini 4 Carbon", "https://juya.example/1")
        b = C.item({"name": "The Verge AI", "tier": 2}, "Google rolls out Gemini 4 Carbon to the public", "https://theverge.example/2")
        self.assertEqual(len(C.cluster([a, b])), 1)

    def test_zh_en_with_only_two_shared_latin_words_do_not_merge(self):
        a = C.item({"name": "橘鸦 AI 早报", "tier": 2}, "马斯克称 Grok Bot 服务成本相对收入高得不可持续", "https://x.com/elonmusk/status/1")
        b = C.item({"name": "The Verge AI", "tier": 2}, "Grok Bot resets weekly limits for all users", "https://theverge.example/3")
        self.assertEqual(len(C.cluster([a, b])), 2)

    def test_fake_domain_url_does_not_grant_official(self):
        x = C.item({"name": "HN", "tier": 3}, "OpenAI thing", "https://openai.com.evil.net/post")
        c = C.summarize([x], set(), [], SINCE, UNTIL, [0])
        self.assertFalse(c["official_urls"])


# ---------- P1: parsing, retries, observability ----------
class TestParsingAndRetries(Base):
    def test_juya_sections_do_not_bleed(self):
        items, _ = self.run_src("橘鸦 AI 早报")
        by = {x["title"]: x for x in items}
        self.assertIn("NVIDIA 将开源运行时 OpenShell 贡献给 CNCF Sandbox", by)
        self.assertTrue(by["NVIDIA 将开源运行时 OpenShell 贡献给 CNCF Sandbox"]["note"].startswith("行业动态 #27"))
        self.assertFalse(any("IPO" in x["note"] for x in items))
        self.assertTrue(any("Modern Web Guidance" in x["title"] and x["note"].startswith("开发生态 #12") for x in items))
        self.assertTrue(by["Tailscale OAuth apps 正式可用，Grok Bot 可访问内网 MCP 服务器"]["url"].startswith("https://tailscale.com/"))
        # overview bullets (no #N) must not produce items
        self.assertEqual(len([x for x in items if "Carbon" in x["title"]]), 1)

    def test_linkless_heading_is_skipped_not_misattributed(self):
        items, _ = self.run_src("橘鸦 AI 早报")
        self.assertFalse(any("IPO" in x["title"] for x in items))

    def test_gzip_body_without_header_is_decoded(self):
        raw = (FX / "deepmind_rss.xml.gz").read_bytes()
        s = C._decode(raw, {})
        self.assertTrue(s.startswith("<?xml"))
        self.assertIn("Gemini 4 Carbon", s)

    def test_transient_parse_failure_recovers_within_retries(self):
        self.net.script["https://deepmind.google/blog/rss.xml"] = 1
        items, st = self.run_src("Google DeepMind")
        self.assertEqual(st["transport"], "ok")
        self.assertTrue(len(items) >= 1)

    def test_persistent_failure_keeps_diagnostics(self):
        self.net.script["https://deepmind.google/blog/rss.xml"] = 99
        items, st = self.run_src("Google DeepMind")
        self.assertEqual(items, [])
        self.assertEqual(st["parse"], "failed")
        self.assertIn("XML", st["error"])

    def test_failed_ratio_uses_configured_sources(self):
        srcs = [self.src("OpenAI"), self.src("Mistral"), self.src("Google DeepMind")]
        self.net.script["https://deepmind.google/blog/rss.xml"] = 99
        _, status, run = C.collect(dt.date(2026, 11, 11), 36, HERE.parent.parent.parent.parent, NOW, sources=srcs)
        self.assertEqual((run["configured"], run["failed"]), (3, 1))
        self.assertEqual(len(status), 3)
        self.assertTrue(any("Google DeepMind" in g for g in run["coverage_gaps"]))

    def test_404_is_not_retried(self):
        n = len(self.net.calls)
        with self.assertRaises(C.FetchError):
            C.get("https://nowhere.example/missing")
        # our fake raises 404 on the first attempt; a real 404 must not be retried either
        self.assertEqual(len(self.net.calls) - n, 1)


# ---------- P1: Trending relevance ----------
class TestTrending(Base):
    def test_relevance_rules(self):
        self.assertTrue(C.repo_relevant("shadcn/improve", "Use your most capable model to audit your codebase and write plans for cheaper models to execute."))
        self.assertTrue(C.repo_relevant("GoogleChrome/modern-web-guidance", "Keep your coding agent up to date with the latest web best practices"))
        self.assertFalse(C.repo_relevant("TheAlgorithms/Java", "All Algorithms implemented in Java"))
        self.assertFalse(C.repo_relevant("we-promise/sure", "The personal finance app for everyone (by everyone)"))
        self.assertFalse(C.repo_relevant("ZhuLinsen/daily_stock_analysis", "LLM 驱动的多市场股票智能分析系统 LLM-powered multi-market stock analysis"))
        self.assertFalse(C.repo_relevant("foo/3d-viewer", "A model viewer for glTF files"))   # one weak 'model'
        self.assertTrue(C.repo_relevant("vercel-labs/agent-browser", "Browser automation CLI for AI agents"))

    def test_trending_page_filtering(self):
        items, _ = self.run_src("GitHub Trending")
        names = {x["title"] for x in items}
        self.assertIn("shadcn/improve", names)
        self.assertIn("meta/astryx", names)
        self.assertNotIn("TheAlgorithms/Java", names)
        self.assertNotIn("we-promise/sure", names)
        self.assertNotIn("ZhuLinsen/daily_stock_analysis", names)


class TestRelated(Base):
    def test_related_finds_category_thread_not_company(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            out = pathlib.Path(td)
            (out / "AI-Daily-2026-11-05.md").write_text(
                "# AI Daily 2026-11-05\n\n## 今日要闻\n\n### 1. OpenAI: Decisions API 正式可用\n- 类型：产品更新\n\n"
                "## 快讯\n\n1. **Parallel · Decisions API 上线**：x。[来源](https://parallel.ai/blog/decisions-api)\n", encoding="utf-8")
            (out / "AI-Daily-2026-11-06.md").write_text(
                "# AI Daily 2026-11-06\n\n## 今日要闻\n\n### 1. Google: Gemini Omni 1.2 Flash 发布\n", encoding="utf-8")
            hist = C.history(dt.date(2026, 11, 12), out)
            self.assertEqual(len(hist), 3)
            cand = {"title": "Gemini Decisions API: Fast, calibrated multimodal decisions", "title_zh": "",
                    "summary": "", "window": "in", "event_time_bj": "", "article_time_bj": ""}
            stale = {"title": "OpenRouter 上架 Parallel Decisions，免费试用 7 天", "title_zh": "", "window": "stale",
                     "event_time_bj": "", "article_time_bj": "11-07 09:23"}
            rel = C.related(cand, hist, [cand, stale])
            joined = " ".join(rel)
            self.assertIn("OpenAI: Decisions API", joined)
            self.assertIn("Parallel", joined)
            self.assertNotIn("Omni", joined)          # sharing only 'Gemini' is not a thread

    def test_related_ignores_generic_words(self):
        cand = {"title": "Try Tabletop: Customizable, collaborative spaces for groups", "title_zh": "",
                "summary": "", "window": "in", "event_time_bj": "", "article_time_bj": ""}
        noise = [{"title": "Amp 推出 Spaces：一个主 Agent 协调多个线程", "title_zh": "", "window": "stale",
                  "event_time_bj": "", "article_time_bj": "11-07"},
                 {"title": "阿里云 Token Plan 个人版额度上调", "title_zh": "", "window": "stale",
                  "event_time_bj": "", "article_time_bj": "11-10"}]
        self.assertEqual(C.related(cand, [], [cand, *noise]), [])


class TestRealGet(unittest.TestCase):
    """Exercise the real get(): gzip decoding, bounded retries, no retry on 404. urlopen is patched."""
    def setUp(self):
        import importlib
        self.C = importlib.reload(C)      # restore the real get() (other tests replace it)
        self.calls = 0

    def tearDown(self):
        import time as _t
        self.C.time.sleep = _t.sleep

    def _serve(self, responses):
        import io, urllib.error, email.message
        C_ = self.C
        C_.time.sleep = lambda s: None
        seq = iter(responses)

        def urlopen(req, timeout=20):
            self.calls += 1
            r = next(seq)
            if isinstance(r, Exception):
                raise r
            body, headers = r
            h = email.message.Message()
            for k, v in headers.items():
                h[k] = v

            class Resp(io.BytesIO):
                def __enter__(s): return s
                def __exit__(s, *a): return False
            resp = Resp(body); resp.headers = h
            return resp
        C_.urllib.request.urlopen = urlopen

    def test_gzip_with_header(self):
        import gzip
        self._serve([(gzip.compress(b"<?xml version='1.0'?><rss/>"), {"Content-Encoding": "gzip"})])
        self.assertTrue(self.C.get("https://x.example/f").startswith("<?xml"))
        self.assertEqual(self.calls, 1)

    def test_transient_error_then_success(self):
        import urllib.error
        self._serve([urllib.error.URLError("reset"), (b"ok", {})])
        self.assertEqual(self.C.get("https://x.example/f"), "ok")
        self.assertEqual(self.calls, 2)

    def test_gives_up_after_bounded_retries(self):
        import urllib.error
        self._serve([urllib.error.URLError("down")] * 10)
        with self.assertRaises(self.C.FetchError):
            self.C.get("https://x.example/f")
        self.assertEqual(self.calls, self.C.RETRIES + 1)

    def test_404_not_retried_and_keeps_diagnostics(self):
        import urllib.error, io
        err = urllib.error.HTTPError("https://x.example/f", 404, "Not Found",
                                     {"Content-Type": "text/html"}, io.BytesIO(b"<html>gone</html>"))
        self._serve([err] * 3)
        with self.assertRaises(self.C.FetchError) as cm:
            self.C.get("https://x.example/f")
        self.assertEqual(self.calls, 1)
        self.assertEqual(cm.exception.status, 404)
        self.assertEqual(cm.exception.ctype, "text/html")
        self.assertIn("gone", cm.exception.snippet)


if __name__ == "__main__":
    unittest.main(verbosity=1)
