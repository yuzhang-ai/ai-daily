#!/usr/bin/env python3
"""Renderer checks for the weekly article. Daily issues stay a separate sequence.

Run: python3 -I site/test_weekly.py
"""
import hashlib
import html
import importlib.util
import pathlib
import re
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
WEEKLY_ZH = ROOT / "outputs" / "weekly" / "2026-11-23.zh.md"
WEEKLY_EN = ROOT / "outputs" / "weekly" / "2026-11-23.en.md"
# Approved drafts copied verbatim. A mismatch means the source was edited.
ZH_SHA = "4cea6ea39e72d242631418a1153df580a430833a7a2e6abe623be005aafc0079"
EN_SHA = "62493bfd00dc8d4fbb9d9cae6a1a2a4e8d922780d5212496ffbb15586221a0db"
REPO = "https://github.com/yuzhang-ai/ai-daily"
URL = re.compile(r"\((https?://[^)\s]+)\)")
HREF = re.compile(r'href="(https?://[^"]+)"')
NUM = re.compile(r"\d[\d,.]*\d|\d")
LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def load_build(out):
    sys.argv = ["build.py", str(out)]
    path = ROOT / "site" / "build.py"
    spec = importlib.util.spec_from_file_location("ai_daily_site_build_weekly", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def markdown_plain(text):
    s = text.replace("\r\n", "\n")
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"\1", s)
    s = re.sub(r"^#{1,3}\s+", "", s, flags=re.M)
    s = re.sub(r"^---+\s*$", "", s, flags=re.M)
    s = re.sub(r"^[-*]\s+", "", s, flags=re.M)
    s = s.replace("**", "").replace("`", "").replace("*", "")
    return re.sub(r"\s+", " ", s).strip()


def html_plain(page):
    h1 = re.search(r"<h1[^>]*>(.*?)</h1>", page, re.S).group(1)
    article = re.search(r'<article class="weekly-body">(.*?)</article>', page, re.S).group(1)
    text = h1 + "\n" + article
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"</(?:p|h[1-3]|li|ul|ol|article)>", "\n", text)
    text = re.sub(r"<hr\s*/?>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


class WeeklyPublish(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = pathlib.Path(cls.tmp.name)
        cls.build = load_build(cls.out)
        cls.build.main()
        cls.zh_src = WEEKLY_ZH.read_text(encoding="utf-8")
        cls.en_src = WEEKLY_EN.read_text(encoding="utf-8")
        cls.zh_page = (cls.out / "weekly-2026-11-23.html").read_text(encoding="utf-8")
        cls.en_page = (cls.out / "en" / "weekly-2026-11-23.html").read_text(encoding="utf-8")
        cls.zh_index = (cls.out / "index.html").read_text(encoding="utf-8")
        cls.en_index = (cls.out / "en" / "index.html").read_text(encoding="utf-8")
        cls.dates = sorted(p.name[9:-3] for p in (ROOT / "outputs").glob("AI-Daily-*.md"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_sources_are_the_approved_drafts(self):
        self.assertEqual(hashlib.sha256(WEEKLY_ZH.read_bytes()).hexdigest(), ZH_SHA)
        self.assertEqual(hashlib.sha256(WEEKLY_EN.read_bytes()).hexdigest(), EN_SHA)

    def test_daily_count_stays_37_each_language(self):
        self.assertEqual(len(self.dates), 37)
        zh_pages = sorted(p.name for p in self.out.glob("20*.html"))
        en_pages = sorted(p.name for p in (self.out / "en").glob("20*.html"))
        self.assertEqual(zh_pages, [f"{d}.html" for d in self.dates])
        self.assertEqual(en_pages, [f"{d}.html" for d in self.dates])
        self.assertEqual(list(self.out.glob("weekly-*.html")), [self.out / "weekly-2026-11-23.html"])
        self.assertEqual(list((self.out / "en").glob("weekly-*.html")),
                         [self.out / "en" / "weekly-2026-11-23.html"])
        for page in list(self.out.glob("*.html")) + list((self.out / "en").glob("*.html")):
            text = page.read_text(encoding="utf-8")
            self.assertNotIn("第 38 期", text, page.name)
            self.assertNotIn("Issue 38", text, page.name)

    def test_archive_counts_dailies_separately_from_the_weekly(self):
        zh_counts = [int(n) for n in re.findall(r"<span>(\d+) 期</span>", self.zh_index)]
        en_counts = [int(n) for n in re.findall(r"<span>(\d+) issues</span>", self.en_index)]
        self.assertEqual(sum(zh_counts) + 1, 37)  # hero is the latest daily, not in a month span
        self.assertEqual(sum(en_counts) + 1, 37)
        self.assertIn(">周报<span>1 篇</span>", self.zh_index)
        self.assertIn(">Weekly<span>1 weekly</span>", self.en_index)
        self.assertIn('href="#weekly"', self.zh_index)
        self.assertIn('href="#weekly"', self.en_index)
        self.assertIn('href="weekly-2026-11-23.html"', self.zh_index)
        self.assertIn('href="weekly-2026-11-23.html"', self.en_index)
        self.assertIn("一周 AI 大事（2026-11-16–11-22，北京时间）", self.zh_index)
        self.assertIn("Weekly AI Brief: 16–22 November 2026 (Beijing time)", self.en_index)
        self.assertIn("第 37 期", self.zh_index)
        self.assertIn("Issue 37", self.en_index)

    def test_nav_and_language_switch(self):
        daily = (self.out / "2026-11-23.html").read_text(encoding="utf-8")
        en_daily = (self.out / "en" / "2026-11-23.html").read_text(encoding="utf-8")
        self.assertIn('href="index.html#weekly"', daily)
        self.assertIn('href="index.html#weekly"', en_daily)
        self.assertIn(">周报</a>", daily)
        self.assertIn(">Weekly</a>", en_daily)
        self.assertIn('href="en/weekly-2026-11-23.html"', self.zh_page)
        self.assertIn('hreflang="en"', self.zh_page)
        self.assertIn('href="../weekly-2026-11-23.html"', self.en_page)
        self.assertIn('hreflang="zh-CN"', self.en_page)
        self.assertIn('href="index.html#weekly"', self.zh_page)
        self.assertIn('href="index.html#weekly"', self.en_page)
        self.assertIn(">返回周报</a>", self.zh_page)
        self.assertIn(">Back to weeklies</a>", self.en_page)
        self.assertNotIn("第 37 期", self.zh_page)
        self.assertNotIn("Issue 37", self.en_page)

    def test_nov23_daily_is_unchanged_in_shape(self):
        page = (self.out / "2026-11-23.html").read_text(encoding="utf-8")
        en = (self.out / "en" / "2026-11-23.html").read_text(encoding="utf-8")
        self.assertEqual(page.count('<article class="story"'), 2)
        self.assertEqual(en.count('<article class="story"'), 2)
        self.assertIn("机器可检验的数学证明与公开的预训练尺子，今天都被拿出来核对。", page)
        self.assertIn("Machine-checkable mathematical proofs and a public pre-training ruler were both brought out for verification today.", en)
        for doc in (page, en):
            self.assertIn("https://openrouter.ai/blog/announcements/data-processing-incidents-on-inference-providers/", doc)
            self.assertIn("OpenRouter", doc)
            self.assertIn('class="briefs"', doc)
        self.assertNotIn("一周 AI 大事", page)
        self.assertIn("第 37 期", page)
        self.assertIn("Issue 37", en)
        for date in self.dates:
            for doc in ((self.out / f"{date}.html").read_text(encoding="utf-8"),
                        (self.out / "en" / f"{date}.html").read_text(encoding="utf-8")):
                self.assertIn('id="s1"', doc)

    def test_weekly_prose_urls_and_numbers_match_the_source(self):
        for src, page in ((self.zh_src, self.zh_page), (self.en_src, self.en_page)):
            self.assertEqual(markdown_plain(src), html_plain(page))
            self.assertEqual(
                sorted(URL.findall(src)),
                sorted(u for u in HREF.findall(page) if u != REPO),
            )
            # Visible numbers follow the prose. Identifiers that exist only inside URLs are
            # covered by the URL list above; the kicker date is chrome, not article text.
            self.assertEqual(NUM.findall(markdown_plain(src)), NUM.findall(html_plain(page)))
            for text, url in LINK.findall(src):
                self.assertIn(f'href="{url}"', page)
                self.assertIn(text, page)


if __name__ == "__main__":
    unittest.main(verbosity=1)
