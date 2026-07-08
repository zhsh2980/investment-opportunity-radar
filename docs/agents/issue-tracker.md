# Issue 跟踪器：本地 Markdown

本仓库的 issue 和 PRD 以 markdown 文件形式存于 `.scratch/`（已加入 `.gitignore`，仓库公开但 issue 留在本地）。

## 约定

- 一个功能一个目录：`.scratch/<feature-slug>/`
- PRD 是 `.scratch/<feature-slug>/PRD.md`
- 实施 issue 是 `.scratch/<feature-slug>/issues/<NN>-<slug>.md`，从 `01` 开始编号
- Triage 状态写在 issue 文件顶部的 `Status:` 行（角色字符串见 `triage-labels.md`）
- 评论和讨论历史追加到文件底部的 `## Comments` 标题下

## 当 skill 说「发布到 issue 跟踪器」

在 `.scratch/<feature-slug>/` 下新建文件（目录不存在则创建）。

## 当 skill 说「获取相关工单」

读取被引用路径的文件。用户通常会直接给出路径或 issue 编号。

## Wayfinding 操作

供 `/wayfinder` 使用。**map** 是一个文件，每个工单一个**子**文件。

- **Map**：`.scratch/<effort>/map.md` — Notes / Decisions-so-far / Fog 正文
- **子工单**：`.scratch/<effort>/issues/NN-<slug>.md`，从 `01` 编号，问题写在正文。`Type:` 行记录类型（`research`/`prototype`/`grilling`/`task`）；`Status:` 行记录 `claimed`/`resolved`
- **阻塞**：文件顶部的 `Blocked by: NN, NN` 行。所列文件全部 `resolved` 后解除阻塞
- **Frontier**：扫描 `.scratch/<effort>/issues/` 中开放、未阻塞、未认领的文件；编号最小者优先
- **认领**：动工前先写 `Status: claimed` 并保存
- **解决**：在 `## Answer` 标题下追加答案，置 `Status: resolved`，再把要点和链接追加到 `map.md` 的 Decisions-so-far
