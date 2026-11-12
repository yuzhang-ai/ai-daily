# 每期模板

文件名 `outputs/AI-Daily-YYYY-MM-DD.md`。`site/build.py` 按下面的二级标题和字段名解析，标题和字段名不要改。

```markdown
# AI Daily 2026-11-11

封面色：日落

## 今日一句话

> 一句话说清今天最重要的变化，30–60 字，能单独转发。

## 今日要闻

### 1. 机构: 标题（中文，说清发生了什么）
- 来源链接：[官方博客](https://…)；[文档](https://…)
- 类型：模型发布 / 产品更新 / 开源项目 / 研究 / 行业
- 推荐指数：★★★★★
- 一句话总结：谁、做了什么、对谁可用，一句话。
- 配图：![图片说明](images/2026-11-11/1-slug.jpg)（图源：Google）
- 关键数字：2 美元 | 每百万输入 token 首发价

**为什么重要：** 之前怎样，现在怎样，变化在哪。2–4 句。

**核心观点：**
1. 一个具体事实：数字、名称或机制。
2. …
3. …

**这意味着什么：** 先定位，再判断。第一句说清这件事在哪条线上：谁先做的、之后谁跟进、今天这家补上了什么（例如「决策模型这条线由 TypeSafe 的 Jev 在 9 月开创，OpenAI 10 月跟进，Google 是第三家大厂，补上的是音视频和 PDF 输入」）。然后给判断：这个模式说明什么、谁受影响、接下来大概率发生什么。判断要能从上面的事实推出来，不能只复述发布稿的卖点。

**风险与待验证：** 厂商自测未经独立验证、仅预览、限地区或套餐、价格会变等。

### 2. …

### 3. …

## 快讯

1. **机构 · 标题**：一句话说清是什么、有什么数字。[来源](https://…)
2. …

## 值得研究的开源项目

1. 项目名：owner/repo
   GitHub 链接：[owner/repo](https://github.com/owner/repo)
   Star 数：约 1.2 万（2026-11-11）
   解决什么问题：一句话。
   为什么值得看：它的做法有什么可借鉴的，一两句。
```

## 字段说明

- **推荐指数**：按 `selection.md` 的总分换算，9–10 分 ★★★★★，7–8 分 ★★★★☆，6 分 ★★★☆☆。
- **来源链接**：一手来源在前；最多 4 个链接；不放 X / 微博截图链接，除非那就是官方唯一的发布渠道。
- **快讯**：3–6 条，每条 60 字以内，必须带一个可点击的一手来源。
- **开源项目**：2–3 个；Star 数写查询当天的数字和日期。
- 要闻少于 3 条达标时，只写达标的条数，不凑数。
- **封面色**（可选）：写调色板里的名字（靛蓝、珊瑚、青绿、紫罗兰、琥珀、墨绿、玫红、极光、橄榄、日落、石墨、海蓝），或 1–2 个色值，如 `封面色：#0f766e, #34d399`。不写就按期号轮换。
- **配图**（可选）：优先用官方发布页的主图或 og:image，下载到 `outputs/images/YYYY-MM-DD/`，用相对路径引用，括号里写图源。AI 生成的图要写成 `（图源：AI 生成）`，并且不能画出产品界面、logo 或数据来冒充真实截图。找不到合适的图就不写这一行。
- **关键数字**（可选）：竖线左边是数字（10 字以内），右边是说明（25 字以内）。数字必须能在来源链接里找到。

## 英文版（可选）

网站同时输出中文和英文两套页面，右上角可以切换。英文页面的界面文字由脚本翻译；正文需要一份英文稿 `outputs/en/AI-Daily-YYYY-MM-DD.md`。没有英文稿的那期，英文页面会显示中文原文并提示「暂无英文版」。

英文稿结构与中文稿一致，用下面的标题和字段名（脚本按这些名字解析）：

```markdown
# AI Daily 2026-11-11

## One-liner

> …

## Top stories

### 1. Org: Title
- Sources: [Official blog](https://…); [Docs](https://…)
- Type: Model release / Product update / Open source / Research / Industry
- Rating: ★★★★★
- Summary: …
- Image: ![Caption](images/2026-11-11/1-slug.jpg) (Image: Google)
- Key figure: $2 | per million input tokens at launch

**Why it matters:** …

**Key points:**
1. …

**What it means:** …

**Risks and open questions:** …

## In brief

1. **Org · Title**: … [Source](https://…)

## Open source worth a look

1. Project: owner/repo
   GitHub: [owner/repo](https://github.com/owner/repo)
   Stars: about 12k (2026-11-11)
   What it solves: …
   Why it's worth a look: …
```

英文稿是翻译，不是重写：事实、数字、链接、配图和推荐指数必须和中文稿一致。封面色跟随中文稿，英文稿里不用写。
