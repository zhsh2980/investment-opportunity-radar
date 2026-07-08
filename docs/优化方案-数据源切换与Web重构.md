# 投资机会雷达 · 优化方案（数据源切换 + Web 重构）

日期：2026-07-08
结论：数据源从自部署 WeRSS 切换到「今天看啥」VIP RSS；Web 端按"机会处理工作台"思路整体重做；每天 5 次批次 + 钉钉推送机制保留不动。

---

## 一、现状与问题

现有链路：WeRSS（自部署）→ Celery 定时批次（07/12/14/18/22 点）→ DeepSeek 分析打分 → 钉钉推送 + Web 展示（FastAPI + Jinja2）。

两个核心痛点：

1. **数据源不可靠**：WeRSS 依赖微信扫码登录，2~3 天过期一次，需人工维护，等于系统没有无人值守能力。
2. **Web 端可用性差**：首页信息效率低，看不到"今天该干什么"；机会没有操作闭环（执行/观望/跳过后无跟踪、无复盘）；整体信息架构需要推倒重做。

## 二、新数据源调研结论（jintiankansha.me）

已实际验证（2026-07-07）：

| 能力 | 免费 | VIP |
|---|---|---|
| 专栏列表页（标题+文章链接+相对时间） | ✅ 可匿名抓 | ✅ |
| 文章正文（/t_snapshot/xxx） | ❌ 跳登录页 | ✅ |
| 标准 RSS feed（任意阅读器可用） | 10 天体验期 | ✅ |
| 开放 API（拉 RSS 内容/专栏列表/文章链接列表） | ❌ | ✅（vip1+） |
| 更新时延 | — | 10 分钟~3 天；极速订阅可缩至 2 分钟~1 小时（积分另购） |

三个目标专栏（均已收录、正常更新）：

- 饕餮海投资：`https://www.jintiankansha.me/column/Cp600KKG7B`（可转债/套利/现金管理）
- `https://www.jintiankansha.me/column/ii4KrSebgM`
- `https://www.jintiankansha.me/column/y26zTGTqBb`

**选定方案：购买 VIP，走标准 RSS 接入。** 理由：RSS 是站方承诺的稳定交付形式，标准 XML 用 `feedparser` 十行代码解析；正文随 feed 返回（后台可设返回条数）；无登录态维护，彻底解决扫码过期问题。开放 API 作为备用通道（`/subscribe/rss/api_common?type=simple`）。

时延说明：普通订阅最坏 3 天延迟。现有系统 `window_days=3` 的拉取窗口 + `external_id` 去重天然兼容这种迟到数据，无需改批次逻辑。若后续发现套利类机会（如可转债申购）经常因延迟错过时间窗口，再加购"极速订阅"即可，代码不用动。

## 三、方案 A：数据源切换（WeRSS → 今天看啥 RSS）

### 3.1 准备工作（人工，一次性）

1. 注册今天看啥账号，购买 VIP（客服微信 knightliao；也支持平台自助购买）。
2. 登录后订阅上述 3 个专栏，在「RSS 订阅管理」后台拿到每个专栏的 RSS 链接（含个人 token）。
3. 后台把"RSS 返回条数"调到上限，确认 feed item 内含正文全文。

### 3.2 代码改造

新增 `src/app/clients/jtks.py`（替代 `werss.py`）：

```python
class JtksClient:
    """今天看啥 RSS 客户端：无登录态，纯拉 feed"""
    def fetch_feed(self, feed_url) -> list[dict]:
        # feedparser.parse()，返回统一结构：
        # {external_id, title, url, html, published_at, column_id, column_name}
        # external_id 取 /t/xxx 的 xxx（feed guid），与现 ContentItem.external_id 对齐
```

配套改动：

- `config.py`：删除 `werss_*` 三项，新增 `jtks_feeds`（JSON：`[{column_id, name, feed_url}]`）与 `jtks_fallback_cookie`（可选，见 3.3）。
- `services/analyzer.py::fetch_and_save_articles`：改为遍历 feeds 拉取入库。`ContentItem` 结构不变，仅 `source_type="jtks"`、`mp_id=column_id`、`mp_name=专栏名`。正文直接来自 feed item，`raw_html/raw_text/content_hash` 逻辑复用。
- `try_refresh_content`：改为重拉 feed 或走 fallback（3.3）。
- 数据库**无需迁移**——模型字段全部兼容（`werss_publish_time` 建议 alembic 改名为 `source_publish_time`，非必须）。
- 删除 `clients/werss.py`、docker-compose 中的 WeRSS 服务、`docs/WeRSS相关`。

### 3.3 兜底与告警

- **正文缺失兜底**：若某 item feed 内无全文（截断/异常），用登录 cookie 请求 `/t_snapshot/{id}` 抓快照页正文。cookie 一个月有效，仅作兜底，不作主链路。
- **数据源健康监控**：每个批次记录各 feed 的拉取成功率与最新文章时间；某专栏 >48h 无新文章或 feed 请求连续失败 3 次，钉钉发告警（复用 NotificationLog）。这是 WeRSS 时代缺失的能力，必须补上。
- **RSS 调用频控**：站方对调用额度有限制。每天 5 个批次 × 3 个 feed = 15 次/天，远低于限额，安全；但要在 client 里加最小间隔与 429 退避，防止误触发限制。

## 四、方案 B：Web 整体重构

定位从"分析结果展示页"改为**"机会处理工作台"**：打开即知今天该做什么，每个机会可操作、可跟踪、可复盘。

### 4.1 技术选型

保留 FastAPI + Jinja2 + 单库，前端引入 **HTMX + Tailwind CSS**（CDN 引入，无构建链）。不上 React/Vue——单人维护项目，前后端分离只会增加负担；HTMX 足以支撑卡片状态流转、筛选、无刷新更新。

### 4.2 页面结构（5 页 → 4 页）

**1. 今日工作台（首页，核心重做）**

- 顶部三数字：今日待处理机会数 / 临期机会数（时间窗口 <48h）/ 今日已分析文章数。
- 机会卡片流，默认排序 = `临期优先 → 分数降序`。卡片直接展示：分数、机会类型标签、**时间窗口倒计时**（"还剩 1 天 3 小时"，过期自动置灰）、how_to 前两步、一键操作按钮（执行 / 观望 / 跳过）。
- 筛选条：机会类型（可转债/套利/…）、分数区间、状态。
- 关键原则：不点进详情页就能完成 80% 的判断和操作。

**2. 跟踪台（新增）**

- 三列看板：观望中 / 已执行 / 待复盘。
- 已执行机会可记录：实际操作、金额、平仓结果、收益（新增 `OpportunityTrack` 表）。
- 复盘视图：按月汇总命中率、收益，反过来评估 AI 打分准确性（分数段 vs 实际有效率），为调 prompt/阈值提供数据。

**3. 历史与搜索（合并现 history + daily）**

- 文章 + 分析结果时间线，按专栏/日期/关键词过滤；日报作为时间线上的锚点卡片。

**4. 系统页（合并现 prompts + settings + health）**

- Prompt 版本管理、阈值设置、**数据源健康面板**（各 feed 最近拉取时间/成功率）、批次运行记录。

### 4.3 数据库增量

```sql
-- 新增：机会跟踪
CREATE TABLE opportunity_track (
  id BIGSERIAL PRIMARY KEY,
  opportunity_id BIGINT REFERENCES opportunity(id),
  action VARCHAR(32),          -- executed / watching / skipped
  note TEXT,                   -- 操作记录
  amount NUMERIC,              -- 投入金额（可空）
  pnl NUMERIC,                 -- 收益（可空）
  closed_at TIMESTAMPTZ,       -- 平仓/结束时间
  created_at / updated_at
);
```

`analysis_result.action_status` 已存在，作为卡片当前状态；`opportunity_track` 记流水与复盘数据。

## 五、实施计划

| 阶段 | 内容 | 工作量 |
|---|---|---|
| 0 | 购买 VIP、订阅 3 专栏、拿 RSS 链接、验证 feed 含全文 | 0.5 天（人工） |
| 1 | JtksClient + fetch 改造 + 配置切换 + 健康告警，跑通一个完整批次 | 1~2 天 |
| 2 | Web 重构：工作台 + 跟踪台 + opportunity_track 迁移 | 3~4 天 |
| 3 | 历史/系统页合并、WeRSS 代码与文档清理、部署 | 1 天 |

阶段 1 完成后系统即恢复无人值守运行（这是最痛的问题），Web 重构可以之后从容做。

## 六、风险

1. **第三方依赖风险**：今天看啥是个人性质服务，存在跑路/涨价/被微信封锁的可能。缓解：`ContentItem.source_type` 已抽象，client 层接口统一，未来换 RSSHub 或其他源只需新写一个 client；数据全量落库，历史不受影响。
2. **正文完整性**：feed 可能对超长文截断。阶段 0 验证时重点检查；兜底走快照页。
3. **时延 vs 机会窗口**：普通订阅最坏 3 天延迟，对"可转债申购日"类机会可能致命。上线后观察 2 周，统计"机会发现时间 vs 窗口截止时间"，若超 10% 机会因延迟失效则加购极速订阅。
