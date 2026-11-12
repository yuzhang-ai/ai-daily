# 核实与找脉络的工具箱

SKILL.md 说的是每一步要做到什么；这份文件说的是具体怎么查。全部是 2026-11-12 重写那期时实际用过的方法，命令可以直接跑。没有 shell 的 bot 用浏览器或搜索做同样的查询，要查的东西不变。

## 一、拿到事件的真实发布时间

采集脚本会自动读页面的 `article:published_time`、JSON-LD `datePublished`、`<time datetime>`。拿不到的，按来源类型手动查：

| 来源类型 | 怎么拿 |
|---|---|
| 微信公众号文章 | 页面源码里有 `var ct = "<unix 时间戳>"`，就是发布时间。`curl -sL <url> \| grep -o 'var ct = "[0-9]*"'` |
| X 帖子 | `https://cdn.syndication.twimg.com/tweet-result?id=<推文ID>&token=a` 返回 JSON，含 `created_at`、正文 `text`、图片 `mediaDetails[].media_url_https`，不用登录 |
| GitHub 发布 | `https://api.github.com/repos/OWNER/REPO/releases` 的 `published_at`；仓库的 `created_at` 和 `pushed_at` 能区分「新仓库」和「老仓库刚公开」（AWS Emulator 9 月建仓、11 月发布） |
| OpenAI | 博客页对 curl 返回 403，用 `https://developers.openai.com/api/docs/changelog`，公测、GA 都有日期 |
| Anthropic | `https://www.anthropic.com/sitemap.xml` 的 `lastmod` 定位近期页面，再读页面 `datePublished` |
| 没有任何时间戳 | 看最早提到它的文章时间，事件不会晚于那个时间；再去 HN Algolia 查首次出现（见第二节） |

## 二、找先行者和同类（脉络）

按这个顺序，找到两条以上就够写：

1. 候选池里这条的「相关脉络」行（脚本从近 30 天已发布的标题和本次窗口外候选里匹配出来的）。
2. `grep -il '<品类词>' outputs/AI-Daily-*.md`，看自己写过什么。
3. HN Algolia 按品类词搜，结果自带日期和分数，直接能排出时间线：
   ```bash
   curl -sG 'https://hn.algolia.com/api/v1/search' --data-urlencode 'query=decision model' --data-urlencode 'tags=story' --data-urlencode 'hitsPerPage=10'
   ```
   11-12 那期用它查到 Jev 9 月、OpenAI Decisions 10 月、Ollaya / Jeeves 等兼容工具。
4. 先行者的 GitHub 仓库：`https://api.github.com/repos/OWNER/REPO` 看 `created_at` 和 `stargazers_count`（LocalStack 2016 年、6.5 万 star）。
5. 竞品定价只从对方定价页取：`typesafe.ai/pricing`、`localstack.cloud/pricing`。二手转述的价格不用。
6. Simon Willison 的标签页是现成的品类编年史：`https://simonwillison.net/tags/<词>/`，例如 `jev`、`decision-models`。
7. 厂商自己之前的发布页。百度 ERNIE 5.5 Flash Base 在 Preview 页里就被提到，顺着链接找。

写进 triage 表的「脉络」列，格式：`先行者 + 日期 / 同类 + 日期 / 今天新在哪`。例如：`Jev 09-15 首创 / OpenAI 10-06 公测、10-22 GA / Parallel 10-25 加网页检索 / 今天 Google 补音视频 PDF`。

## 三、判断热度和争议点

HN 帖子的评论区是最快的「社区在拿它和谁比」：

```bash
curl -s 'https://hn.algolia.com/api/v1/items/<帖子ID>'
```

返回 `points` 和整棵评论树。把评论正文拼起来，数一下提到竞品名的条数。AWS Emulator 那帖 190 条评论里 24 条提 LocalStack，这个数字直接进了「风险与待验证」。帖子 ID 从候选池「信号」行的 HN 链接里取。

## 四、核实厂商声明

- 读发布页正文，不读 RSS 摘要。把要引用的那句话原文 grep 出来，看它的限定条件：Google 的 "no-cost tier" 前面是 "in Google AI Studio for prototyping"，是 AI Studio 一贯的免费额度，不是新东西。
- 同一天同一模型有两篇官方文章时两篇都读：Carbon 发布稿说三个榜第一，同日 MKA 基准博客说质量第二、成本六分之一。
- 基准数字要带榜单名和条件写，「Google 称在 X、Y、Z 三个榜单上第一」，不写「全面领先」。
- 「全部由 agent 编写」这类自述，原样标注为厂商自述。

## 五、找配图

1. 先列发布页正文里的 `<img>`：`curl -sL <url> \| grep -oE '<img[^>]+src="[^"]+"'`。挑架构图、基准图、界面截图。
2. og:image 最后考虑。纯色或渐变底上一行产品名的不要。
3. X 帖子的配图从第一节那个 syndication JSON 的 `mediaDetails` 里拿。
4. 竖图（海报类）不用，横版槽位会裁掉。
5. 示意图和截图存 PNG，网站对 PNG 整图等比缩放；照片存 JPG，按 1.9:1 裁切填满。
6. 下载后用 `sips -g pixelWidth -g pixelHeight <file>` 看尺寸，宽小于 800 的不用。

## 六、开源项目

- 只从两个地方选：候选池里来源为「GitHub Trending」的条目；当天要闻、快讯里第一次出现的新仓库。
- 每个仓库查一次 API 拿 star、许可证、`created_at`、`pushed_at`，写进正文的 star 数带查询日期。
- 读 README 前 30 行，「为什么值得看」写它具体怎么用或者设计上有什么可借鉴，不写「很火」「很多人用」。

## 七、一期的实际节奏（11-12 重写时的顺序）

1. 跑 `collect.py`，读候选池「窗口内」和「待核实」两组，约 10 分钟。
2. 对「待核实」组里有官方链接的逐个核日期，Qwen4 就是在这一步捞回来的。
3. 按打分表给 6 分以上的事件打分，写 triage 表，定 3 条要闻、快讯、开源项目。
4. 对每条要闻做第二节的脉络查询，至少查到两个先行者或同类，记进 triage 表。
5. 读每条要闻的一手来源全文，把要引用的数字和原句 grep 出来；查 HN 评论区的争议点。
6. 找配图，查开源项目的 API 数据。
7. 写稿。「这意味着什么」第一句先定位，再判断。
8. 跑第 5 节自检，构建网站，在浏览器里看一遍配图和星级。

范例：`outputs/AI-Daily-2026-11-12.md`。它的「为什么重要」和「这意味着什么」就是按上面第二、四节查出来的东西写的；bot 原稿在 `references/examples/2026-11-12-bot-draft.md`，逐项问题在 `references/examples/2026-11-12-audit.md`，两版对照能看出差别在哪。
