# AI 每日简报

给 AI 产品经理和 FDE 的每日情报：每天 3 条值得关注的内容、1 个最该记住的观点、几个值得研究的开源项目，以及第二天可以动手做的事。内容由 AI 整理、人工核验。

**在线阅读：** https://yuzhang-ai.github.io/ai-daily/

## 仓库结构

```
outputs/AI-Daily-YYYY-MM-DD.md   每期原稿（markdown，固定五段结构）
site/build.py                    静态站生成脚本，仅标准库
site/style.css                   样式与设计 tokens
site/fonts/                      得意黑 Smiley Sans（OFL）
site/DESIGN.md                   设计决策：定位、参照、tokens、动效、响应式
.github/workflows/pages.yml      推送到 main 后自动构建并发布到 GitHub Pages
```

## 本地预览

```bash
python3 -I site/build.py site/dist
```

```bash
python3 -m http.server 8765 --directory site/dist
```

然后打开 http://localhost:8765 。

## 公开版与完整版

每期 markdown 同时包含公开内容和作者自己的笔记。默认构建的是**公开版**，面向所有关注 AI 行业的读者：一句话观点、3 条要闻（一句话 / 为什么重要 / 核心观点 / 这意味着什么 / 风险与待验证 / 原文链接）、值得研究的开源项目。

作者私人的部分（可落地行动、开源项目怎么用到自己项目、明日行动建议、人工验证清单）不会出现在公开版里。需要完整版时：

```bash
AI_DAILY_PRIVATE=1 python3 -I site/build.py site/dist-private
```

## 每期 markdown 的结构

生成脚本按下面的标题和字段解析，新增一期时沿用即可：

```markdown
# AI Daily 2026-07-20

## 一、今日最值得关注的 3 条内容
### 1. 机构名: 标题
- 来源链接：[名称](https://…)；[名称](https://…)
- 类型：官方博客 / 论文 / 开源项目
- 推荐指数：★★★★★
- 一句话总结：…
**为什么重要：** …
**核心观点 3 条：** 1. … 2. … 3. …
**对 AI 产品经理 / FDE 的启发：** …
**可落地行动或作品集切入点：** …
**风险提醒：** … 是否值得精读：是。

## 二、今日最重要的一个观点
> 今天我最应该记住的是：…

## 三、值得深入学习的开源项目
1. 项目名：owner/repo
   GitHub 链接：[owner/repo](https://github.com/…)
   Star 数：约 1.2k
   解决什么问题：…
   为什么值得我学习：…
   如何用到我的项目 / 工作中：…

## 四、明日行动建议
1. …

## 人工验证清单
- [x] …
- [ ] …
```

推荐指数兼容 `★★★★☆`、`5`、`5/5`、`4 星` 等写法；来源行里的本地 PDF 链接会被忽略，只保留 http 链接。

## 关于原始 PDF

早期几期会把论文或报告 PDF 下载到 `outputs/sources/`。这些文件已经移出仓库（约 80 MB），日报里对应的本地链接旁边都保留了原文的外部链接。
