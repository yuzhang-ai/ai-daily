#!/usr/bin/env python3
"""Mechanical fact check between two markdown issues. Exit 1 on any difference.

  check_pair.py polish ORIGINAL.md REVISED.md
      Same issue before and after a wording pass. Everything that is a fact must be
      unchanged: every URL, every number, every ★ rating, every heading, every image path.
      Only prose may differ. Use it after a polishing tool or editor touched the draft.

  check_pair.py en outputs/AI-Daily-DATE.md outputs/en/AI-Daily-DATE.md
      Chinese issue and its English edition. Prose differs by design, so only structure
      and the fields that carry facts are compared: story / brief / repo counts, the set
      of URLs, the ★ ratings in order, image paths, repo star counts, key-figure numbers.

Standard library only. Run with `python3 -I`.
"""
import pathlib
import re
import sys

URL = re.compile(r"\((https?://[^)\s]+)\)")
STARS = re.compile(r"★+☆*")
NUM = re.compile(r"\d[\d,.]*\d|\d")
HEAD = re.compile(r"^#{1,6} .+$", re.M)
IMG = re.compile(r"!\[[^\]]*\]\((images/[^)\s]+)\)")


def multiset_diff(name, a, b, out):
    ca, cb = {}, {}
    for x in a:
        ca[x] = ca.get(x, 0) + 1
    for x in b:
        cb[x] = cb.get(x, 0) + 1
    gone = [x for x in ca if ca[x] > cb.get(x, 0)]
    added = [x for x in cb if cb[x] > ca.get(x, 0)]
    if gone or added:
        out.append(f"{name}: {len(gone)} missing, {len(added)} added")
        for x in gone[:10]:
            out.append(f"    - {x}")
        for x in added[:10]:
            out.append(f"    + {x}")


def seq_diff(name, a, b, out):
    if a != b:
        out.append(f"{name}: order or count differs")
        out.append(f"    original: {a}")
        out.append(f"    revised : {b}")


def check_polish(a, b):
    out = []
    multiset_diff("URLs", URL.findall(a), URL.findall(b), out)
    multiset_diff("numbers", NUM.findall(a), NUM.findall(b), out)
    seq_diff("ratings", STARS.findall(a), STARS.findall(b), out)
    seq_diff("headings", HEAD.findall(a), HEAD.findall(b), out)
    seq_diff("images", IMG.findall(a), IMG.findall(b), out)
    return out


def norm_num(s):
    return re.sub(r"[,\s]", "", s)


def star_value(s):
    """'约 2.4 万' / 'about 24k' / '1,925 (2026-11-12)' -> 24000 / 24000 / 1925. None when no number."""
    s = re.sub(r"\(.*?\)|（.*?）", "", s or "")
    m = re.search(r"(\d[\d,]*(?:\.\d+)?)\s*(万|k|K)?", s)
    if not m:
        return None
    v = float(m.group(1).replace(",", ""))
    unit = m.group(2)
    if unit == "万":
        v *= 10000
    elif unit:
        v *= 1000
    return int(round(v))


def load_builder():
    """site/build.py has the one parser the website uses; compare what it sees, not raw text."""
    import importlib.util
    path = pathlib.Path(__file__).resolve().parents[3] / "site" / "build.py"
    argv, sys.argv = sys.argv, [str(path), "/tmp/check-pair-ignored"]
    try:
        spec = importlib.util.spec_from_file_location("ai_daily_build", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        sys.argv = argv
    return mod


def check_en(zh_path, en_path):
    b = load_builder()
    zh, en = b.parse_issue(zh_path), b.parse_issue(en_path)
    out = []
    for name in ("stories", "briefs", "repos"):
        if len(zh[name]) != len(en[name]):
            out.append(f"{name}: zh {len(zh[name])} vs en {len(en[name])}")
    if not zh["lede"] or not en["lede"]:
        out.append(f"one-liner: zh {'present' if zh['lede'] else 'missing'}, en {'present' if en['lede'] else 'missing'}")
    for k, (a, c) in enumerate(zip(zh["stories"], en["stories"]), 1):
        if a.get("stars") != c.get("stars"):
            out.append(f"story {k} rating: zh {a.get('stars')} vs en {c.get('stars')}")
        la = {l[1] if isinstance(l, (list, tuple)) else l for l in a.get("links", [])}
        lc = {l[1] if isinstance(l, (list, tuple)) else l for l in c.get("links", [])}
        la = {u for u in la if "/sources/" not in u}       # private local files may be dropped in en
        if la != lc:
            out.append(f"story {k} links: {sorted(la - lc)} only in zh; {sorted(lc - la)} only in en")
        ia, ic = (a.get("image") or {}).get("src"), (c.get("image") or {}).get("src")
        if ia != ic:
            out.append(f"story {k} image: zh {ia} vs en {ic}")
        sa, sc = a.get("stat") or ("", ""), c.get("stat") or ("", "")
        na, nc = norm_num("".join(NUM.findall(sa[0]))), norm_num("".join(NUM.findall(sc[0])))
        if na != nc:
            out.append(f"story {k} key figure: zh {sa[0]!r} vs en {sc[0]!r}")
        pa = a.get("points") or ""
        pc = c.get("points") or ""
        count = lambda p: len(re.findall(r"^\s*\d+\.", p, re.M)) if isinstance(p, str) else len(p)
        if count(pa) != count(pc):
            out.append(f"story {k} key points: zh {count(pa)} vs en {count(pc)}")
    for k, (a, c) in enumerate(zip(zh["repos"], en["repos"]), 1):
        if (a.get("href") or "").rstrip("/") != (c.get("href") or "").rstrip("/"):
            out.append(f"repo {k}: zh {a.get('href')} vs en {c.get('href')}")
        if star_value(a.get("star")) != star_value(c.get("star")):
            out.append(f"repo {k} stars: zh {a.get('star')!r} vs en {c.get('star')!r}")
    za = {u for x in zh["briefs"] for u in URL.findall(x)}
    ea = {u for x in en["briefs"] for u in URL.findall(x)}
    if za != ea:
        out.append(f"brief links: {sorted(za - ea)} only in zh; {sorted(ea - za)} only in en")
    return out


def main(argv):
    if len(argv) != 4 or argv[1] not in ("polish", "en"):
        sys.exit(__doc__)
    pa, pb = pathlib.Path(argv[2]), pathlib.Path(argv[3])
    if argv[1] == "polish":
        problems = check_polish(pa.read_text(encoding="utf-8"), pb.read_text(encoding="utf-8"))
    else:
        problems = check_en(pa, pb)
    if problems:
        print("\n".join(problems))
        print(f"\n{argv[1]}: FAIL — facts differ; fix the revised file or revert to the original")
        sys.exit(1)
    print(f"{argv[1]}: OK — facts match")


if __name__ == "__main__":
    main(sys.argv)
