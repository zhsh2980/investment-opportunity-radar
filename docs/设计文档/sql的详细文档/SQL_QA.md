# WeRSS SQL API 常见问题解答

> 创建时间：2026-01-08
> 用途：解答使用 WeRSS API 访问数据时的常见问题

---

## 📋 目录

- [关于缓存机制](#关于缓存机制)
- [关于微信授权](#关于微信授权)
- [关于 TOKEN 认证](#关于-token-认证)
- [实用代码示例](#实用代码示例)

---

## 关于缓存机制

### Q1: "WeRSS 的定时任务会定期抓取公众号的最新文章，RSS Feed 会自动缓存，缓存时间默认为 1 小时" 这句话怎么理解？

#### A1.1 定时任务抓取文章

**定时任务做什么？**

WeRSS 通过定时任务定期抓取公众号的最新文章：

```yaml
# config.yaml
interval: 10  # 每篇文章的抓取间隔（秒）
```

定时任务的工作流程：

```
1. 根据 cron 表达式（如 "0 0 * * *" 每天午夜）触发
2. 遍历所有订阅的公众号
3. 调用微信接口获取最新文章
4. 保存到数据库（SQLite: /srv/we-mp-rss/data/db.db）
   - 新文章 → 插入数据库
   - 已存在的文章 → 跳过（避免重复）
   - 历史文章 → 永久保留 ✅
```

**重点**：定时任务只负责"增加"新文章，不会删除历史文章。

---

#### A1.2 RSS Feed 缓存机制

**缓存的是什么？**

RSS Feed 缓存的是 **XML 文件**，不是数据库中的文章数据。

**缓存位置和类型：**

| 缓存类型 | 路径 | 内容 | 过期策略 |
|---------|------|------|---------|
| **RSS Feed 缓存** | `data/cache/rss/` | RSS XML 文件 | 1 小时（默认） |
| **文章内容缓存** | `data/cache/content/` | 文章完整内容（JSON） | 永久存储 |
| **视图页面缓存** | `data/cache/views/` | Web 页面缓存 | 30 分钟（默认） |
| **数据库** | `data/db.db` | 所有文章数据 | **永久存储** ✅ |

**缓存工作流程示例：**

```bash
# 第 1 次访问 RSS（10:00）
访问：http://154.8.205.159:8001/feed/MP_WXS_xxx.xml
动作：
  1. 检查缓存文件：data/cache/rss/MP_WXS_xxx_50_0.xml
  2. 缓存不存在 → 从数据库查询文章
  3. 生成 RSS XML 文件并缓存
  4. 返回给用户

# 第 2 次访问 RSS（10:30，缓存未过期）
访问：http://154.8.205.159:8001/feed/MP_WXS_xxx.xml
动作：
  1. 检查缓存文件存在，且未过期（<1小时）
  2. 直接返回缓存的 XML 文件 ✅ 快速！

# 第 3 次访问 RSS（11:30，缓存已过期）
访问：http://154.8.205.159:8001/feed/MP_WXS_xxx.xml
动作：
  1. 检查缓存文件存在，但已过期（>1小时）
  2. 删除旧的缓存文件
  3. 从数据库重新查询文章（历史文章都在！）✅
  4. 生成新的 RSS XML 并缓存
  5. 返回给用户
```

---

#### A1.3 缓存时间过了会清掉历史文章吗？

**答案：不会！！！**

这是最重要的澄清：

```
┌─────────────────────────────────────────────────────┐
│                WeRSS 数据存储架构                      │
├─────────────────────────────────────────────────────┤
│                                                     │
│  1. 数据库（永久存储）                                 │
│     ├── /srv/we-mp-rss/data/db.db (SQLite)         │
│     ├── 存储所有抓取的文章                             │
│     └── 永不自动删除 ✅                               │
│                                                     │
│  2. RSS Feed 缓存（临时文件，定期刷新）                 │
│     ├── data/cache/rss/*.xml                       │
│     ├── 过期时间：1 小时（默认）                        │
│     ├── 过期后：删除缓存文件，重新从数据库生成            │
│     └── 不影响数据库中的历史文章 ✅                      │
│                                                     │
│  3. 文章内容缓存（JSON 文件）                          │
│     ├── data/cache/content/*.json                  │
│     ├── 用于 /rss/content/{id} 接口                 │
│     └── 不会自动删除 ✅                               │
│                                                     │
└─────────────────────────────────────────────────────┘
```

**验证：查看数据库中的历史文章**

```bash
# SSH 登录云服务器
ssh -i bro_private/key/ubuntu_beijing.pem ubuntu@154.8.205.159

# 查询数据库中的文章总数
sqlite3 /srv/we-mp-rss/data/db.db "SELECT COUNT(*) FROM articles;"
# 输出：假设有 1280 篇

# 查询最早的文章
sqlite3 /srv/we-mp-rss/data/db.db "
SELECT title, datetime(publish_time, 'unixepoch', 'localtime') as date
FROM articles
ORDER BY publish_time ASC
LIMIT 5;
"
# 输出：可能是几个月前的文章，依然存在！✅
```

---

### Q2: 缓存到哪里了？

#### A2: 缓存文件的具体位置

在云服务器上，缓存文件存储在以下位置：

```bash
# RSS Feed 缓存（XML 文件）
/srv/we-mp-rss/data/cache/rss/
├── all_10_0.rss              # 所有公众号的聚合 RSS
├── MP_WXS_xxx_50_0.xml       # 单个公众号的 RSS
└── tag_tech_news_30_0.xml    # 标签分组的 RSS

# 文章内容缓存（JSON 文件）
/srv/we-mp-rss/data/cache/content/
├── MP_WXS_xxx-2651087878.json  # 文章完整内容
└── MP_WXS_xxx-2651087879.json

# 视图页面缓存
/srv/we-mp-rss/data/cache/views/
├── home_page_xxxxx.cache
└── articles_list_xxxxx.cache
```

**查看缓存文件：**

```bash
# SSH 登录服务器
ssh -i bro_private/key/ubuntu_beijing.pem ubuntu@154.8.205.159

# 查看 RSS 缓存
ls -lh /srv/we-mp-rss/data/cache/rss/

# 查看文章内容缓存
ls -lh /srv/we-mp-rss/data/cache/content/
```

---

## 关于微信授权

### Q3: 抓取公众号需要扫码授权吗？

#### A3: 是的，必须扫码授权

这是 WeRSS 的核心机制，授权流程如下：

```
┌──────────────────────────────────────────────────┐
│            WeRSS 微信授权流程                       │
└──────────────────────────────────────────────────┘

1. 首次使用
   ↓
2. 打开 Web 界面 (http://154.8.205.159:8001)
   ↓
3. 登录管理后台
   ↓
4. 点击"微信授权"按钮
   ↓
5. 显示二维码
   ↓
6. 用微信扫码授权 ✅
   ↓
7. 获取微信 Cookie
   ↓
8. 开始抓取公众号文章
   ↓
9. 定期自动抓取（无需重复扫码）
   ↓
10. Cookie 过期？
    ├─ 否 → 继续自动抓取
    └─ 是 → 重新扫码授权（回到步骤 4）
```

#### 授权详细说明

**1. 首次授权**

访问 Web 界面 → 登录 → 点击"微信授权" → 扫码

**2. Cookie 有效期**

- 授权后会获得微信的 Cookie
- Cookie 通常有效期为 **几天到几周**（微信会随机调整）
- 有效期内可以自动抓取文章，无需重复扫码

**3. 过期后重新授权**

- Cookie 过期后，系统会提示需要重新授权
- 有定时任务检查授权状态
- 可以配置授权过期提醒（钉钉、飞书、企业微信等）

**4. 授权检查定时任务**

```python
# driver/auth.py
# 调试模式：每 5 分钟检查一次
auth_task.add_cron_job(auth, "*/5 * * * *", tag="授权定时更新")

# 生产模式：每天检查一次
auth_task.add_cron_job(auth, "0 0 */1 * *", tag="授权定时更新")
```

---

## 关于 TOKEN 认证

### Q4: 如果程序在同一台服务器上，想通过 API 获取数据库内容，需要 TOKEN 吗？

#### A4: 是的，仍然需要 TOKEN

**无论从哪里访问（公网、内网、本地 localhost），WeRSS 的 API 接口都需要提供有效的 TOKEN。**

#### TOKEN 认证机制

WeRSS 使用 **Bearer Token** 认证：

```python
# core/auth.py
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{API_BASE}/auth/token")
```

#### 例外情况：RSS 订阅接口

只有 **RSS 订阅接口** 不需要 TOKEN：

| 接口类型 | 路径 | 是否需要 TOKEN | 说明 |
|---------|------|---------------|------|
| **RSS 订阅** | `/rss/*`, `/feed/*` | ❌ 不需要 | 公开访问 |
| **API 接口** | `/api/*` | ✅ 需要 | Bearer Token 认证 |
| **Web 管理界面** | `/` | ✅ 需要 | 浏览器自动处理 |

#### 本地访问示例

即使在同一台服务器上，仍然需要 TOKEN：

```bash
# 在云服务器上运行（本地访问）
curl -X GET "http://localhost:8001/api/mps?limit=5" \
  -H "Authorization: Bearer {TOKEN}"
```

---

### Q5: TOKEN 会过期吗？

#### A5: 是的，TOKEN 会过期

#### 过期时间配置

```yaml
# config.yaml
token_expire_minutes: ${TOKEN_EXPIRE_MINUTES:-4320}
```

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `token_expire_minutes` | `4320` 分钟 | = 72 小时 = **3 天** |

#### 为什么会过期？

WeRSS 使用 **JWT (JSON Web Token)** 标准：

```python
# core/auth.py
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta  # 设置过期时间
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})  # JWT 标准的过期字段
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
```

**JWT 本身包含过期时间（`exp` 字段），服务器会自动验证。**

#### TOKEN 过期的表现

当 TOKEN 过期后，API 请求会返回：

```json
{
  "detail": "Could not validate credentials"
}
```

HTTP 状态码：`401 Unauthorized`

---

### Q6: TOKEN 过期后需要怎么处理？

#### A6: 三种处理方案

---

#### 方案 A：重新登录获取新 TOKEN（适合临时脚本）

```bash
# 重新登录
curl -X POST "http://localhost:8001/api/auth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin@123"

# 响应
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 259200  # 秒（3天）
}
```

---

#### 方案 B：使用刷新接口（适合长期运行的程序）

```bash
# 使用旧 TOKEN 刷新获取新 TOKEN
curl -X POST "http://localhost:8001/api/auth/refresh" \
  -H "Authorization: Bearer {旧TOKEN}"

# 响应（新的 TOKEN）
{
  "code": 0,
  "message": "操作成功",
  "data": {
    "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",  # 新 TOKEN
    "token_type": "bearer",
    "expires_in": 259200
  }
}
```

**优点**：
- 无需重新输入用户名密码
- 更安全（旧 TOKEN 验证通过才能刷新）

---

#### 方案 C：自动处理过期（最佳实践）

对于长期运行的程序，建议编写自动刷新逻辑：

```python
import requests
from datetime import datetime, timedelta
import time

class WeRSSClient:
    def __init__(self, base_url="http://localhost:8001", username="admin", password="admin@123"):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.token = None
        self.token_expires_at = None

    def login(self):
        """登录获取 TOKEN"""
        url = f"{self.base_url}/api/auth/token"
        data = {"username": self.username, "password": self.password}
        response = requests.post(url, data=data)
        response.raise_for_status()

        result = response.json()
        self.token = result["access_token"]
        # 计算过期时间（提前 5 分钟刷新，避免边界情况）
        expires_in = result["expires_in"]  # 秒
        self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)

        print(f"✅ 登录成功，TOKEN 将于 {self.token_expires_at.strftime('%Y-%m-%d %H:%M:%S')} 过期")
        return self.token

    def refresh_token(self):
        """刷新 TOKEN"""
        if not self.token:
            return self.login()

        url = f"{self.base_url}/api/auth/refresh"
        headers = {"Authorization": f"Bearer {self.token}"}

        try:
            response = requests.post(url, headers=headers)
            response.raise_for_status()

            result = response.json()
            self.token = result["data"]["access_token"]
            expires_in = result["data"]["expires_in"]
            self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)

            print(f"✅ TOKEN 已刷新，将于 {self.token_expires_at.strftime('%Y-%m-%d %H:%M:%S')} 过期")
            return self.token
        except Exception as e:
            print(f"⚠️  刷新失败，重新登录: {e}")
            return self.login()

    def _ensure_token_valid(self):
        """确保 TOKEN 有效（自动刷新）"""
        if not self.token or not self.token_expires_at:
            self.login()
        elif datetime.now() >= self.token_expires_at:
            print("⏰ TOKEN 即将过期，自动刷新...")
            self.refresh_token()

    def _headers(self):
        """获取请求头（自动处理 TOKEN 过期）"""
        self._ensure_token_valid()
        return {"Authorization": f"Bearer {self.token}"}

    def get_articles(self, mp_id=None, limit=10):
        """获取文章列表（自动处理 TOKEN）"""
        url = f"{self.base_url}/api/articles"
        params = {"limit": limit}
        if mp_id:
            params["mp_id"] = mp_id

        response = requests.get(url, headers=self._headers(), params=params)
        response.raise_for_status()
        return response.json()["data"]

    def get_feeds(self, limit=10):
        """获取公众号列表"""
        url = f"{self.base_url}/api/mps"
        params = {"limit": limit}
        response = requests.get(url, headers=self._headers(), params=params)
        response.raise_for_status()
        return response.json()["data"]


# 使用示例
if __name__ == "__main__":
    # 初始化客户端
    client = WeRSSClient()

    # 第一次调用会自动登录
    articles = client.get_articles(limit=5)
    print(f"获取到 {articles['total']} 篇文章")

    # 模拟长期运行
    # 再次调用时，如果 TOKEN 即将过期，会自动刷新
    time.sleep(10)
    feeds = client.get_feeds(limit=5)
    print(f"获取到 {feeds['total']} 个公众号")
```

---

## 实用代码示例

### 示例 1：Bash 脚本自动获取 TOKEN

```bash
#!/bin/bash
# werss_api.sh - WeRSS API 调用脚本

BASE_URL="http://localhost:8001"
USERNAME="admin"
PASSWORD="admin@123"
TOKEN_FILE="/tmp/werss_token.txt"
TOKEN_EXPIRE_FILE="/tmp/werss_token_expire.txt"

# 获取新 TOKEN
get_token() {
    echo "正在登录获取 TOKEN..."
    RESPONSE=$(curl -s -X POST "$BASE_URL/api/auth/token" \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "username=$USERNAME&password=$PASSWORD")

    TOKEN=$(echo "$RESPONSE" | jq -r '.access_token')
    EXPIRES_IN=$(echo "$RESPONSE" | jq -r '.expires_in')

    if [ "$TOKEN" != "null" ]; then
        echo "$TOKEN" > "$TOKEN_FILE"
        # 计算过期时间（当前时间 + expires_in - 300 秒）
        EXPIRE_TIME=$(($(date +%s) + EXPIRES_IN - 300))
        echo "$EXPIRE_TIME" > "$TOKEN_EXPIRE_FILE"
        echo "✅ TOKEN 获取成功"
        echo "$TOKEN"
    else
        echo "❌ 登录失败"
        exit 1
    fi
}

# 检查 TOKEN 是否有效
check_token() {
    if [ ! -f "$TOKEN_FILE" ] || [ ! -f "$TOKEN_EXPIRE_FILE" ]; then
        get_token
        return
    fi

    TOKEN=$(cat "$TOKEN_FILE")
    EXPIRE_TIME=$(cat "$TOKEN_EXPIRE_FILE")
    CURRENT_TIME=$(date +%s)

    if [ "$CURRENT_TIME" -ge "$EXPIRE_TIME" ]; then
        echo "⏰ TOKEN 已过期，重新获取..."
        get_token
    else
        echo "✅ TOKEN 有效"
        echo "$TOKEN"
    fi
}

# 调用 API
call_api() {
    local endpoint=$1
    shift  # 移除第一个参数
    local params="$@"

    TOKEN=$(check_token)

    curl -X GET "$BASE_URL$endpoint?$params" \
        -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json"
}

# 使用示例
case "$1" in
    feeds)
        call_api "/api/mps" "limit=10"
        ;;
    articles)
        call_api "/api/articles" "limit=20&has_content=false"
        ;;
    *)
        echo "Usage: $0 {feeds|articles}"
        exit 1
        ;;
esac
```

**使用方法：**

```bash
chmod +x werss_api.sh

# 获取公众号列表
./werss_api.sh feeds | jq

# 获取文章列表
./werss_api.sh articles | jq
```

---

### 示例 2：验证 TOKEN 是否有效

```bash
# 验证 TOKEN
TOKEN="your_token_here"

curl -X GET "http://localhost:8001/api/auth/verify" \
  -H "Authorization: Bearer $TOKEN" | jq

# 响应（如果有效）：
# {
#   "code": 0,
#   "message": "操作成功",
#   "data": {
#     "is_valid": true,
#     "username": "admin",
#     "expires_at": 1704931200  # Unix 时间戳
#   }
# }

# 响应（如果无效）：
# {
#   "detail": "Could not validate credentials"
# }
```

---

### 示例 3：Python 定时任务（每天同步数据）

```python
import requests
import schedule
import time
from datetime import datetime

class WeRSSSync:
    def __init__(self):
        self.base_url = "http://localhost:8001"
        self.username = "admin"
        self.password = "admin@123"
        self.token = None
        self.token_expires_at = None

    def login(self):
        """登录获取 TOKEN"""
        url = f"{self.base_url}/api/auth/token"
        data = {"username": self.username, "password": self.password}
        response = requests.post(url, data=data)
        response.raise_for_status()

        result = response.json()
        self.token = result["access_token"]
        expires_in = result["expires_in"]
        from datetime import timedelta
        self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)

        print(f"✅ {datetime.now()} - 登录成功")
        return self.token

    def _ensure_token_valid(self):
        """确保 TOKEN 有效"""
        if not self.token or not self.token_expires_at:
            self.login()
        elif datetime.now() >= self.token_expires_at:
            print(f"⏰ {datetime.now()} - TOKEN 即将过期，刷新中...")
            self.login()

    def _headers(self):
        """获取请求头"""
        self._ensure_token_valid()
        return {"Authorization": f"Bearer {self.token}"}

    def sync_articles(self):
        """同步文章数据"""
        print(f"\n{'='*50}")
        print(f"🔄 {datetime.now()} - 开始同步文章数据...")

        try:
            # 获取所有公众号
            feeds_url = f"{self.base_url}/api/mps"
            feeds_response = requests.get(feeds_url, headers=self._headers(), params={"limit": 100})
            feeds_response.raise_for_status()
            feeds = feeds_response.json()["data"]["list"]

            print(f"📚 找到 {len(feeds)} 个订阅的公众号")

            total_articles = 0
            for feed in feeds:
                # 获取每个公众号的文章
                articles_url = f"{self.base_url}/api/articles"
                params = {"mp_id": feed["id"], "limit": 50, "has_content": False}
                articles_response = requests.get(articles_url, headers=self._headers(), params=params)
                articles_response.raise_for_status()
                articles = articles_response.json()["data"]

                print(f"  📖 {feed['mp_name']}: {articles['total']} 篇文章")
                total_articles += articles["total"]

            print(f"✅ {datetime.now()} - 同步完成！共 {total_articles} 篇文章")
            print(f"{'='*50}\n")

        except Exception as e:
            print(f"❌ {datetime.now()} - 同步失败: {e}")


# 使用示例
if __name__ == "__main__":
    sync = WeRSSSync()

    # 立即执行一次
    sync.sync_articles()

    # 每天凌晨 2 点执行
    schedule.every().day.at("02:00").do(sync.sync_articles)

    print("⏰ 定时任务已启动，每天 02:00 同步数据...")
    print("按 Ctrl+C 停止")

    while True:
        schedule.run_pending()
        time.sleep(60)
```

---

## 配置 TOKEN 过期时间

如果你觉得默认的 3 天太短，可以修改配置：

```yaml
# /srv/we-mp-rss/config.yaml

# 修改为 30 天（43200 分钟）
token_expire_minutes: 43200

# 或者修改为 1 年（525600 分钟）
token_expire_minutes: 525600

# 或者设置更短的时间（出于安全考虑）
token_expire_minutes: 1440  # 1 天
```

修改后重启服务：

```bash
sudo systemctl restart we-mp-rss
```

---

## 最佳实践建议

### 对于同服务器上的程序：

1. **使用 localhost 访问**：
   ```python
   base_url = "http://localhost:8001"  # 而不是 http://154.8.205.159:8001
   ```

2. **存储 TOKEN 到文件**：
   ```python
   import json

   # 保存 TOKEN
   with open('/tmp/werss_token.json', 'w') as f:
       json.dump({
           'token': token,
           'expires_at': expires_at.isoformat()
       }, f)

   # 读取 TOKEN
   with open('/tmp/werss_token.json', 'r') as f:
       data = json.load(f)
       token = data['token']
   ```

3. **实现自动刷新逻辑**（见上面的 `WeRSSClient` 示例）

4. **长期运行的服务建议延长 TOKEN 过期时间**：
   ```yaml
   token_expire_minutes: 43200  # 30 天
   ```

5. **使用环境变量存储敏感信息**：
   ```bash
   # .env
   WERSS_USERNAME=admin
   WERSS_PASSWORD=admin@123
   WERSS_BASE_URL=http://localhost:8001
   ```

   ```python
   import os
   from dotenv import load_dotenv

   load_dotenv()

   username = os.getenv('WERSS_USERNAME')
   password = os.getenv('WERSS_PASSWORD')
   base_url = os.getenv('WERSS_BASE_URL')
   ```

---

## 总结对比表

| 问题 | 答案 | 详细说明 |
|------|------|---------|
| **抓取公众号需要扫码吗？** | ✅ 需要 | 首次使用和 Cookie 过期后需要扫码 |
| **缓存在哪里？** | 3 个位置 | RSS 文件、文章内容、视图页面 |
| **缓存过期会删除历史文章吗？** | ❌ 不会 | 只删除缓存文件，数据库中的文章永久保留 |
| **同服务器访问需要 TOKEN 吗？** | ✅ 需要 | 无论本地还是远程，API 接口都需要 TOKEN |
| **RSS 订阅需要 TOKEN 吗？** | ❌ 不需要 | `/rss/*` 和 `/feed/*` 路径无需认证 |
| **TOKEN 会过期吗？** | ✅ 会 | 默认 3 天（4320 分钟） |
| **如何知道 TOKEN 过期了？** | 返回 401 错误 | `"Could not validate credentials"` |
| **过期后怎么办？** | 3 种方案 | 1. 重新登录 <br> 2. 刷新 TOKEN <br> 3. 自动处理（推荐） |
| **可以修改过期时间吗？** | ✅ 可以 | 修改 `config.yaml` 中的 `token_expire_minutes` |

---

## 相关文档

- **SQL_API.md**：完整的 HTTP API 接口文档
- **RSS_SUBSCRIBE.md**：RSS 订阅使用指南
- **RUNBOOK.zh-CN.md**：部署和运维文档

---

**文档版本**: 1.0
**最后更新**: 2026-01-08
