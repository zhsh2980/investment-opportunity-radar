# WeRSS SQL 数据库 API 文档

> 创建时间：2026-01-08
> 用途：为其他服务提供只读访问 WeRSS 爬取的公众号文章数据

---

## 📋 目录

- [概述](#概述)
- [认证与授权](#认证与授权)
- [数据库表结构](#数据库表结构)
- [HTTP API 接口](#http-api-接口)
- [调用示例](#调用示例)
- [SQLite 直连查询](#sqlite-直连查询)

---

## 概述

### 服务信息

| 项目 | 值 |
|------|-----|
| 服务地址 | http://154.8.205.159:8001 |
| 本地访问 | http://localhost:8001 |
| API 基础路径 | `/api` |
| 数据库文件 | `/srv/we-mp-rss/data/db.db` (SQLite) |
| API 文档 | http://154.8.205.159:8001/api/docs |

### 使用场景

- ✅ 查询订阅的公众号列表
- ✅ 查询指定公众号的文章（支持按日期筛选）
- ✅ 查询文章详情（含完整内容）
- ✅ 按标签分组查询
- ✅ 云服务器本地访问（无需暴露公网）

### 访问限制

- **只读**：仅提供数据查询接口，不可修改或删除数据
- **认证**：API 需要 Bearer Token 认证
- **本地访问优先**：建议在云服务器内部使用 localhost 访问

---

## 认证与授权

### 1. 获取访问 Token

所有 API 接口（除 RSS 订阅外）均需要 Bearer Token 认证。

#### 登录接口

```http
POST /api/auth/token
Content-Type: application/x-www-form-urlencoded

username=admin&password=admin@123
```

#### 响应示例

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 259200
}
```

#### 默认管理员账号

| 用户名 | 密码 |
|--------|------|
| `admin` | `admin@123` |

> ⚠️ **生产环境请立即修改默认密码！**

---

### 2. 使用 Token 调用 API

在请求头中添加 Authorization：

```http
GET /api/mps
Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
```

---

## 数据库表结构

### 核心表关系

```
feeds (公众号)
  ↓ (1:N)
articles (文章)

tags (标签/分组)
  ↓ (N:N)
feeds (通过 mps_id 关联)
```

---

### 1. `feeds` 表 - 公众号信息

存储订阅的微信公众号基本信息。

| 字段名 | 类型 | 说明 | 示例 |
|--------|------|------|------|
| `id` | STRING(255) | 主键，公众号唯一ID | `MP_WXS_MzI1MDY3MTkyMw==` |
| `mp_name` | STRING(255) | 公众号名称 | `Python之禅` |
| `mp_cover` | STRING(255) | 公众号头像URL | `/files/avatars/xxx.jpg` |
| `mp_intro` | STRING(255) | 公众号简介 | `分享Python技术文章` |
| `status` | INTEGER | 状态（1=启用，2=禁用） | `1` |
| `sync_time` | INTEGER | 上次同步时间戳 | `1704672000` |
| `update_time` | INTEGER | 更新时间戳 | `1704672000` |
| `created_at` | DATETIME | 创建时间 | `2026-01-08 10:00:00` |
| `updated_at` | DATETIME | 更新时间 | `2026-01-08 10:00:00` |
| `faker_id` | STRING(255) | 加密后的公众号ID（base64） | `MzI1MDY3MTkyMw==` |

---

### 2. `articles` 表 - 文章内容

存储从公众号爬取的文章详情。

| 字段名 | 类型 | 说明 | 示例 |
|--------|------|------|------|
| `id` | STRING(255) | 主键，文章唯一ID | `MP_WXS_xxx-2651087878` |
| `mp_id` | STRING(255) | 外键，关联 `feeds.id` | `MP_WXS_MzI1MDY3MTkyMw==` |
| `title` | STRING(1000) | 文章标题 | `Python 3.13 新特性详解` |
| `pic_url` | STRING(500) | 封面图片URL | `https://mmbiz.qpic.cn/...` |
| `url` | STRING(500) | 文章原文链接 | `https://mp.weixin.qq.com/s/...` |
| `description` | TEXT | 文章摘要 | `本文介绍 Python 3.13...` |
| `content` | TEXT | 文章完整HTML内容 | `<div>...</div>` |
| `status` | INTEGER | 状态（1=正常，1000=已删除） | `1` |
| `publish_time` | INTEGER | 发布时间戳（**可排序**） | `1704672000` |
| `created_at` | DATETIME | 入库时间 | `2026-01-08 10:00:00` |
| `updated_at` | DATETIME | 更新时间 | `2026-01-08 10:00:00` |
| `is_export` | INTEGER | 是否已导出 | `0` |
| `is_read` | INTEGER | 是否已读（0=未读，1=已读） | `0` |

---

### 3. `tags` 表 - 标签/分组

用于将多个公众号分组管理。

| 字段名 | 类型 | 说明 | 示例 |
|--------|------|------|------|
| `id` | STRING(255) | 主键，标签ID | `tag_001` |
| `name` | STRING(255) | 标签名称 | `技术类` |
| `cover` | STRING(255) | 标签封面 | `/static/tag_cover.jpg` |
| `intro` | STRING(255) | 标签简介 | `收集技术类公众号` |
| `status` | INTEGER | 状态 | `1` |
| `mps_id` | TEXT | 关联的公众号ID列表（JSON） | `[{"id":"MP_WXS_xxx"}]` |
| `sync_time` | INTEGER | 同步时间戳 | `1704672000` |
| `update_time` | INTEGER | 更新时间戳 | `1704672000` |
| `created_at` | DATETIME | 创建时间 | `2026-01-08 10:00:00` |
| `updated_at` | DATETIME | 更新时间 | `2026-01-08 10:00:00` |

---

### 4. `users` 表 - 用户信息

管理系统用户账号（仅做参考，不建议直接访问）。

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `id` | STRING(255) | 用户ID |
| `username` | STRING(50) | 用户名 |
| `password_hash` | STRING(255) | 密码哈希（bcrypt） |
| `role` | STRING(20) | 角色（admin/editor/user） |
| `is_active` | BOOLEAN | 是否激活 |

---

## HTTP API 接口

### 基础信息

- **Base URL**: `http://154.8.205.159:8001/api`
- **认证方式**: Bearer Token
- **响应格式**: JSON

---

### 统一响应格式

#### 成功响应

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    // 实际数据
  }
}
```

#### 错误响应

```json
{
  "code": 40101,
  "message": "用户名或密码错误",
  "data": null
}
```

---

### 1. 认证接口

#### 1.1 登录获取 Token

```http
POST /api/auth/token
Content-Type: application/x-www-form-urlencoded
```

**请求参数**：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `username` | string | ✅ | 用户名 |
| `password` | string | ✅ | 密码 |

**响应示例**：

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 259200
}
```

---

#### 1.2 验证 Token 有效性

```http
GET /api/auth/verify
Authorization: Bearer {token}
```

**响应示例**：

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "is_valid": true,
    "username": "admin",
    "expires_at": 1704931200
  }
}
```

---

### 2. 公众号接口

#### 2.1 获取公众号列表

```http
GET /api/mps?limit=10&offset=0&kw=Python
Authorization: Bearer {token}
```

**查询参数**：

| 参数名 | 类型 | 必填 | 说明 | 默认值 |
|--------|------|------|------|--------|
| `limit` | integer | ❌ | 每页数量 | `10` |
| `offset` | integer | ❌ | 偏移量 | `0` |
| `kw` | string | ❌ | 搜索关键词（模糊搜索名称） | `""` |

**响应示例**：

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "list": [
      {
        "id": "MP_WXS_MzI1MDY3MTkyMw==",
        "mp_name": "Python之禅",
        "mp_cover": "/files/avatars/xxx.jpg",
        "mp_intro": "分享Python技术文章",
        "status": 1,
        "created_at": "2026-01-08T10:00:00"
      }
    ],
    "page": {
      "limit": 10,
      "offset": 0,
      "total": 25
    },
    "total": 25
  }
}
```

---

#### 2.2 获取公众号详情

```http
GET /api/mps/{mp_id}
Authorization: Bearer {token}
```

**路径参数**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| `mp_id` | string | 公众号ID |

**响应示例**：

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "id": "MP_WXS_MzI1MDY3MTkyMw==",
    "mp_name": "Python之禅",
    "mp_cover": "/files/avatars/xxx.jpg",
    "mp_intro": "分享Python技术文章",
    "status": 1,
    "created_at": "2026-01-08T10:00:00",
    "faker_id": "MzI1MDY3MTkyMw=="
  }
}
```

---

### 3. 文章接口

#### 3.1 获取文章列表（支持按日期筛选）

```http
GET /api/articles?mp_id={mp_id}&limit=10&offset=0&has_content=true
Authorization: Bearer {token}
```

**查询参数**：

| 参数名 | 类型 | 必填 | 说明 | 默认值 |
|--------|------|------|------|--------|
| `mp_id` | string | ❌ | 公众号ID（筛选指定公众号） | - |
| `limit` | integer | ❌ | 每页数量（1-100） | `5` |
| `offset` | integer | ❌ | 偏移量 | `0` |
| `status` | string | ❌ | 状态筛选 | - |
| `search` | string | ❌ | 搜索关键词（标题/内容） | - |
| `has_content` | boolean | ❌ | 是否返回完整内容 | `false` |

**响应示例**：

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "list": [
      {
        "id": "MP_WXS_xxx-2651087878",
        "mp_id": "MP_WXS_MzI1MDY3MTkyMw==",
        "mp_name": "Python之禅",
        "title": "Python 3.13 新特性详解",
        "pic_url": "https://mmbiz.qpic.cn/...",
        "url": "https://mp.weixin.qq.com/s/...",
        "description": "本文介绍 Python 3.13...",
        "content": "<div>...</div>",
        "status": 1,
        "publish_time": 1704672000,
        "is_read": 0,
        "created_at": "2026-01-08T10:00:00",
        "updated_at": "2026-01-08T10:00:00"
      }
    ],
    "total": 128
  }
}
```

> 💡 **按日期查询提示**：
> - `publish_time` 是 Unix 时间戳（秒），可以在应用层筛选日期范围
> - 文章列表默认按 `publish_time` 降序排列（最新的在前）

---

#### 3.2 获取文章详情

```http
GET /api/articles/{article_id}
Authorization: Bearer {token}
```

**路径参数**：

| 参数名 | 类型 | 说明 |
|--------|------|------|
| `article_id` | string | 文章ID |

**响应示例**：

```json
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "id": "MP_WXS_xxx-2651087878",
    "mp_id": "MP_WXS_MzI1MDY3MTkyMw==",
    "title": "Python 3.13 新特性详解",
    "pic_url": "https://mmbiz.qpic.cn/...",
    "url": "https://mp.weixin.qq.com/s/...",
    "description": "本文介绍 Python 3.13...",
    "content": "<div>完整的HTML内容...</div>",
    "status": 1,
    "publish_time": 1704672000,
    "is_read": 0,
    "created_at": "2026-01-08T10:00:00",
    "updated_at": "2026-01-08T10:00:00"
  }
}
```

---

### 4. RSS 订阅接口（无需认证）

#### 4.1 获取公众号 RSS Feed

```http
GET /rss/{feed_id}?limit=50
```

**说明**：
- ✅ **无需认证**，可直接访问
- 返回 XML 格式的 RSS Feed
- 适合 RSS 阅读器订阅

**示例**：

```bash
# 订阅指定公众号
curl http://154.8.205.159:8001/rss/MP_WXS_MzI1MDY3MTkyMw==

# 获取所有订阅
curl http://154.8.205.159:8001/rss/
```

---

## 调用示例

### 1. curl 命令行示例

#### 步骤 1：登录获取 Token

```bash
# 登录
TOKEN=$(curl -X POST "http://154.8.205.159:8001/api/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin@123" | jq -r '.access_token')

echo "Token: $TOKEN"
```

#### 步骤 2：查询公众号列表

```bash
# 获取公众号列表
curl -X GET "http://154.8.205.159:8001/api/mps?limit=10" \
  -H "Authorization: Bearer $TOKEN" | jq
```

#### 步骤 3：查询指定公众号的文章

```bash
# 替换为实际的 mp_id
MP_ID="MP_WXS_MzI1MDY3MTkyMw=="

# 获取该公众号的文章（按日期降序）
curl -X GET "http://154.8.205.159:8001/api/articles?mp_id=$MP_ID&limit=20&has_content=true" \
  -H "Authorization: Bearer $TOKEN" | jq
```

#### 步骤 4：按日期筛选文章（示例：最近 7 天）

```bash
# 在应用层筛选最近 7 天的文章
SEVEN_DAYS_AGO=$(date -d '7 days ago' +%s)

curl -X GET "http://154.8.205.159:8001/api/articles?mp_id=$MP_ID&limit=100&has_content=false" \
  -H "Authorization: Bearer $TOKEN" | \
  jq --argjson since "$SEVEN_DAYS_AGO" '.data.list[] | select(.publish_time >= $since)'
```

---

### 2. Python 示例

#### 完整示例代码

```python
import requests
from datetime import datetime, timedelta
import json

class WeRSSClient:
    """WeRSS API 客户端"""

    def __init__(self, base_url="http://154.8.205.159:8001", username="admin", password="admin@123"):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.token = None

    def login(self):
        """登录获取 Token"""
        url = f"{self.base_url}/api/auth/token"
        data = {
            "username": self.username,
            "password": self.password
        }
        response = requests.post(url, data=data)
        response.raise_for_status()
        self.token = response.json()["access_token"]
        return self.token

    def _headers(self):
        """获取请求头"""
        if not self.token:
            self.login()
        return {"Authorization": f"Bearer {self.token}"}

    def get_feeds(self, limit=10, offset=0, keyword=""):
        """获取公众号列表"""
        url = f"{self.base_url}/api/mps"
        params = {"limit": limit, "offset": offset, "kw": keyword}
        response = requests.get(url, headers=self._headers(), params=params)
        response.raise_for_status()
        return response.json()["data"]

    def get_articles(self, mp_id=None, limit=10, offset=0, has_content=False):
        """获取文章列表"""
        url = f"{self.base_url}/api/articles"
        params = {
            "limit": limit,
            "offset": offset,
            "has_content": has_content
        }
        if mp_id:
            params["mp_id"] = mp_id

        response = requests.get(url, headers=self._headers(), params=params)
        response.raise_for_status()
        return response.json()["data"]

    def get_article_detail(self, article_id):
        """获取文章详情"""
        url = f"{self.base_url}/api/articles/{article_id}"
        response = requests.get(url, headers=self._headers())
        response.raise_for_status()
        return response.json()["data"]

    def get_articles_by_date_range(self, mp_id, days=7, limit=100):
        """获取指定天数内的文章"""
        since_timestamp = int((datetime.now() - timedelta(days=days)).timestamp())

        # 获取文章列表
        result = self.get_articles(mp_id=mp_id, limit=limit, has_content=False)

        # 筛选日期范围
        filtered_articles = [
            article for article in result["list"]
            if article["publish_time"] >= since_timestamp
        ]

        return filtered_articles


# 使用示例
if __name__ == "__main__":
    # 初始化客户端
    client = WeRSSClient()

    # 1. 登录
    print("正在登录...")
    client.login()
    print("✅ 登录成功")

    # 2. 获取公众号列表
    print("\n获取公众号列表...")
    feeds_data = client.get_feeds(limit=5)
    print(f"共订阅了 {feeds_data['total']} 个公众号")

    for feed in feeds_data["list"]:
        print(f"  - {feed['mp_name']} (ID: {feed['id']})")

    # 3. 查询第一个公众号的文章
    if feeds_data["list"]:
        first_feed = feeds_data["list"][0]
        mp_id = first_feed["id"]
        mp_name = first_feed["mp_name"]

        print(f"\n查询「{mp_name}」的文章...")
        articles_data = client.get_articles(mp_id=mp_id, limit=5)
        print(f"该公众号共有 {articles_data['total']} 篇文章")

        for article in articles_data["list"]:
            publish_date = datetime.fromtimestamp(article["publish_time"])
            print(f"  - [{publish_date.strftime('%Y-%m-%d')}] {article['title']}")

    # 4. 查询最近 7 天的文章
    if feeds_data["list"]:
        print(f"\n查询「{mp_name}」最近 7 天的文章...")
        recent_articles = client.get_articles_by_date_range(mp_id=mp_id, days=7)
        print(f"最近 7 天共有 {len(recent_articles)} 篇文章")

        for article in recent_articles:
            publish_date = datetime.fromtimestamp(article["publish_time"])
            print(f"  - [{publish_date.strftime('%Y-%m-%d')}] {article['title']}")
```

#### 输出示例

```
正在登录...
✅ 登录成功

获取公众号列表...
共订阅了 25 个公众号
  - Python之禅 (ID: MP_WXS_MzI1MDY3MTkyMw==)
  - 机器之心 (ID: MP_WXS_MzA3MjU2NDE5Mg==)
  - 前端之巅 (ID: MP_WXS_MzUxMjQ5NzY1OA==)

查询「Python之禅」的文章...
该公众号共有 128 篇文章
  - [2026-01-08] Python 3.13 新特性详解
  - [2026-01-07] 如何优雅地处理异常
  - [2026-01-06] 深入理解 Python 装饰器

查询「Python之禅」最近 7 天的文章...
最近 7 天共有 5 篇文章
  - [2026-01-08] Python 3.13 新特性详解
  - [2026-01-07] 如何优雅地处理异常
  - [2026-01-06] 深入理解 Python 装饰器
  - [2026-01-05] asyncio 并发编程实战
  - [2026-01-03] FastAPI 性能优化技巧
```

---

### 3. Node.js / JavaScript 示例

```javascript
const axios = require('axios');

class WeRSSClient {
  constructor(baseURL = 'http://154.8.205.159:8001', username = 'admin', password = 'admin@123') {
    this.baseURL = baseURL;
    this.username = username;
    this.password = password;
    this.token = null;
  }

  async login() {
    const url = `${this.baseURL}/api/auth/token`;
    const params = new URLSearchParams();
    params.append('username', this.username);
    params.append('password', this.password);

    const response = await axios.post(url, params);
    this.token = response.data.access_token;
    return this.token;
  }

  _headers() {
    if (!this.token) {
      throw new Error('请先调用 login() 方法');
    }
    return { Authorization: `Bearer ${this.token}` };
  }

  async getFeeds(limit = 10, offset = 0, keyword = '') {
    const url = `${this.baseURL}/api/mps`;
    const response = await axios.get(url, {
      headers: this._headers(),
      params: { limit, offset, kw: keyword }
    });
    return response.data.data;
  }

  async getArticles(mpId = null, limit = 10, offset = 0, hasContent = false) {
    const url = `${this.baseURL}/api/articles`;
    const params = { limit, offset, has_content: hasContent };
    if (mpId) params.mp_id = mpId;

    const response = await axios.get(url, {
      headers: this._headers(),
      params
    });
    return response.data.data;
  }

  async getArticlesByDateRange(mpId, days = 7, limit = 100) {
    const sinceTimestamp = Math.floor(Date.now() / 1000) - (days * 24 * 60 * 60);
    const result = await this.getArticles(mpId, limit, 0, false);

    return result.list.filter(article => article.publish_time >= sinceTimestamp);
  }
}

// 使用示例
(async () => {
  const client = new WeRSSClient();

  // 登录
  await client.login();
  console.log('✅ 登录成功');

  // 获取公众号列表
  const feedsData = await client.getFeeds(5);
  console.log(`共订阅了 ${feedsData.total} 个公众号`);

  // 查询最近 7 天的文章
  if (feedsData.list.length > 0) {
    const mpId = feedsData.list[0].id;
    const recentArticles = await client.getArticlesByDateRange(mpId, 7);
    console.log(`最近 7 天共有 ${recentArticles.length} 篇文章`);
  }
})();
```

---

## SQLite 直连查询

如果你需要直接访问数据库（适合临时查询、数据分析），可以使用以下方式。

### 1. 在云服务器上使用 SQLite 命令行

```bash
# SSH 登录云服务器
ssh -i bro_private/key/ubuntu_beijing.pem ubuntu@154.8.205.159

# 进入数据库文件目录
cd /srv/we-mp-rss/data

# 启动 SQLite 命令行
sqlite3 db.db
```

### 2. 常用 SQL 查询示例

#### 查询所有订阅的公众号

```sql
SELECT id, mp_name, mp_intro, mp_cover
FROM feeds
WHERE status = 1
ORDER BY created_at DESC;
```

#### 查询指定公众号的文章（按日期降序）

```sql
SELECT id, title, publish_time, url
FROM articles
WHERE mp_id = 'MP_WXS_MzI1MDY3MTkyMw=='
  AND status != 1000  -- 排除已删除的文章
ORDER BY publish_time DESC
LIMIT 20;
```

#### 查询最近 7 天的文章

```sql
SELECT a.id, a.title, f.mp_name, a.publish_time
FROM articles a
JOIN feeds f ON a.mp_id = f.id
WHERE a.publish_time >= strftime('%s', 'now', '-7 days')
  AND a.status != 1000
ORDER BY a.publish_time DESC;
```

#### 按日期范围查询（指定起止日期）

```sql
-- 查询 2026-01-01 到 2026-01-08 的文章
SELECT a.id, a.title, f.mp_name,
       datetime(a.publish_time, 'unixepoch', 'localtime') as publish_date
FROM articles a
JOIN feeds f ON a.mp_id = f.id
WHERE a.publish_time >= strftime('%s', '2026-01-01')
  AND a.publish_time < strftime('%s', '2026-01-08')
  AND a.status != 1000
ORDER BY a.publish_time DESC;
```

#### 统计每个公众号的文章数量

```sql
SELECT f.mp_name, COUNT(a.id) as article_count
FROM feeds f
LEFT JOIN articles a ON f.id = a.mp_id
WHERE a.status != 1000
GROUP BY f.id, f.mp_name
ORDER BY article_count DESC;
```

#### 查询未读文章

```sql
SELECT a.id, a.title, f.mp_name, a.publish_time
FROM articles a
JOIN feeds f ON a.mp_id = f.id
WHERE a.is_read = 0
  AND a.status != 1000
ORDER BY a.publish_time DESC
LIMIT 50;
```

#### 搜索包含关键词的文章

```sql
SELECT id, title, publish_time
FROM articles
WHERE (title LIKE '%Python%' OR description LIKE '%Python%')
  AND status != 1000
ORDER BY publish_time DESC
LIMIT 20;
```

---

### 3. Python 直连 SQLite

```python
import sqlite3
from datetime import datetime, timedelta

# 连接数据库（只读模式）
conn = sqlite3.connect('/srv/we-mp-rss/data/db.db', uri=True, check_same_thread=False)
conn.row_factory = sqlite3.Row  # 返回字典格式

# 查询最近 7 天的文章
seven_days_ago = int((datetime.now() - timedelta(days=7)).timestamp())

cursor = conn.cursor()
cursor.execute("""
    SELECT a.id, a.title, f.mp_name, a.publish_time
    FROM articles a
    JOIN feeds f ON a.mp_id = f.id
    WHERE a.publish_time >= ?
      AND a.status != 1000
    ORDER BY a.publish_time DESC
""", (seven_days_ago,))

articles = cursor.fetchall()

for article in articles:
    publish_date = datetime.fromtimestamp(article['publish_time'])
    print(f"[{publish_date.strftime('%Y-%m-%d')}] {article['title']} - {article['mp_name']}")

conn.close()
```

---

### 4. 安全注意事项

⚠️ **直连数据库的注意事项**：

1. **只读访问**：
   ```bash
   # 以只读模式打开数据库
   sqlite3 -readonly db.db
   ```

2. **避免并发写入**：
   - SQLite 不适合高并发写入
   - 如果 WeRSS 服务正在运行，建议只进行查询操作

3. **备份数据**：
   ```bash
   # 定期备份数据库
   cp /srv/we-mp-rss/data/db.db /srv/we-mp-rss/data/backup_$(date +%Y%m%d).db
   ```

4. **使用视图（可选）**：
   ```sql
   -- 创建只读视图，简化查询
   CREATE VIEW recent_articles AS
   SELECT a.id, a.title, a.publish_time, f.mp_name
   FROM articles a
   JOIN feeds f ON a.mp_id = f.id
   WHERE a.status != 1000
   ORDER BY a.publish_time DESC;

   -- 使用视图查询
   SELECT * FROM recent_articles LIMIT 10;
   ```

---

## 常见问题

### Q1: Token 过期了怎么办？

Token 默认有效期为 3 天（259200 秒）。过期后需要重新调用 `/api/auth/token` 获取新 Token。

你也可以调用 `/api/auth/refresh` 刷新 Token：

```bash
curl -X POST "http://154.8.205.159:8001/api/auth/refresh" \
  -H "Authorization: Bearer $OLD_TOKEN"
```

---

### Q2: 如何按日期范围查询文章？

`publish_time` 是 Unix 时间戳（秒）。你可以：

1. **在应用层筛选**（推荐）：
   ```python
   since_timestamp = int((datetime.now() - timedelta(days=7)).timestamp())
   articles = [a for a in all_articles if a["publish_time"] >= since_timestamp]
   ```

2. **使用 SQLite 查询**（见上文 SQL 示例）

---

### Q3: 如何获取文章的完整内容？

在调用文章列表 API 时，添加 `has_content=true` 参数：

```bash
curl -X GET "http://154.8.205.159:8001/api/articles?mp_id=xxx&has_content=true" \
  -H "Authorization: Bearer $TOKEN"
```

或者使用 `/api/articles/{article_id}` 获取单篇文章详情。

---

### Q4: RSS 订阅接口和 API 接口有什么区别？

| 特性 | RSS 接口 | API 接口 |
|------|---------|----------|
| 认证 | ❌ 无需认证 | ✅ 需要 Bearer Token |
| 格式 | XML | JSON |
| 适用场景 | RSS 阅读器订阅 | 程序化数据访问 |
| 灵活性 | 较低 | 高（支持复杂筛选） |

---

### Q5: 如何修改管理员密码？

登录 Web 界面（http://154.8.205.159:8001），在用户设置中修改密码。

或者使用 API：

```python
# 需要先登录获取 token
import requests

url = "http://154.8.205.159:8001/api/user/password"
headers = {"Authorization": f"Bearer {token}"}
data = {
    "old_password": "admin@123",
    "new_password": "your_new_password"
}
response = requests.put(url, headers=headers, json=data)
```

---

## 总结

### 推荐方案

1. **其他服务访问**：使用 HTTP API（方案 A）
   - 标准化、易于维护
   - 支持复杂查询（按日期、公众号、关键词）
   - 安全（基于 Token 认证）

2. **临时查询/数据分析**：使用 SQLite 直连
   - 灵活的 SQL 查询
   - 适合一次性数据导出

3. **RSS 阅读器**：使用 RSS Feed 接口
   - 无需认证，直接订阅

### 联系方式

如有问题，请通过以下方式联系：
- GitHub Issues: https://github.com/rachelos/we-mp-rss/issues
- 项目文档: https://deepwiki.com/rachelos/we-mp-rss

---

**文档版本**: 1.0
**最后更新**: 2026-01-08
