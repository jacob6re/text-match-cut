# text-match-cut

将同一个关键词在不同真实网页中的出现位置对齐，制作网页高亮快闪视频的 Codex Skill。

输入关键词 → 搜索网页 → 定位并高亮真实原文 → 截图 → 对齐位置和大小 → 添加鱼眼效果 → 快速切换 → 使用 HyperFrames 导出 MP4。

## 使用

将本仓库放到 Codex 的 skills 目录，目录名保持为 `text-match-cut`：

```sh
git clone https://github.com/jacob6re/text-match-cut.git ~/.codex/skills/text-match-cut
```

这是私有仓库，克隆需要有访问权限。重新打开 Codex 后，可以请求：

```text
$text-match-cut 生成关键词为“边做边学”的视频
```

也可以提供网页链接，或指定画幅、时长、高亮颜色和鱼眼强度。

## 默认效果

- 20 个不同网页的真实截图，关键词居中并以蓝色高亮。
- 1080×1920，30 fps；前 19 张各保持 3 帧，最后一张保持 9 帧，共 2.2 秒。
- 鱼眼强度 0.55，外围文字弯曲，中心关键词保持可读。
- 每次网页切换配原创合成的胶片更换声；20 张截图对应 19 次音效。
- 交付 MP4 与来源记录，保留可编辑的 HyperFrames 项目。

## 运行依赖

- Node.js 22+、Playwright 与 Chromium/Chrome，用于网页截图。
- Python 3.10+、Pillow 与 NumPy，用于对齐和鱼眼处理。
- HyperFrames CLI、本地 GSAP 文件、FFmpeg 与 ffprobe，用于检查、渲染和验证。

具体命令与环境变量见 [运行说明](references/workflow.md)。已使用本 Skill 生成并验证 `jake` 和 `边做边学` 两条 20 页视频。

## 文件

- [SKILL.md](SKILL.md)：Skill 入口与制作流程。
- [capture.mjs](scripts/capture.mjs)：真实网页定位、高亮、截图及出处记录。
- [build.py](scripts/build.py)：截图对齐、鱼眼处理、胶片声及 HyperFrames 项目生成。
- [workflow.md](references/workflow.md)：依赖、命令与验收标准。
- [openai.yaml](agents/openai.yaml)：Codex 显示信息。

截图中的关键词必须来自网页原文；不生成虚构网页、不重新排字替换关键词。抓取失败保留记录，不能用重复截图补足数量。
