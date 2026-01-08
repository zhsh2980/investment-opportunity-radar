# We-MP-RSS 部署工作流（Ubuntu 22.04 源码部署）

> 目标：本地（Mac）让 AI 读/改代码 → `git push` 到你的 fork → SSH 到服务器 `git pull/reset` 并重启服务。  
> 你的仓库（origin）：`zhsh2980/we-mp-rss-linux`（private）  
> 官方仓库（upstream）：`rachelos/we-mp-rss`

> [!NOTE]
> 约定：所有"你自己新增的流程/脚本/密钥/笔记"都放在 `bro_private/`；`bro_private/key/` 永远不提交。

---

## 🚀 首次部署快速指南

首次部署可以使用自动化脚本一键完成：

### 1. 配置本地环境变量

```bash
cp bro_private/.env.example bro_private/.env
```

编辑 `bro_private/.env`，配置以下内容：

```bash
PROD_SSH_HOST=ubuntu@你的服务器IP
PROD_SSH_KEY=/path/to/your/key.pem  # 如果使用密钥登录
ADMIN_USER=admin
ADMIN_PASS=你的密码
```

### 2. 运行首次部署脚本

```bash
./bro_private/scripts/init_server.sh
```

脚本会自动完成：
- 生成 GitHub Deploy Key（需要你手动添加到 GitHub）
- 安装系统依赖
- 克隆代码并安装 Python 依赖
- 安装 Playwright 浏览器
- 创建 systemd 服务并启动

### 3. 验证

访问 `http://你的服务器IP:8001`，使用配置的管理员账号登录。

---

## 1) 分支与远端约定

- `origin`：你的 fork（用于开发与部署）
- `upstream`：官方仓库（用于同步更新）
- 分支：
  - `main`：只做"跟官方保持一致"的基线（尽量只 fast-forward）
  - `dev`：你的二开开发分支
  - `deploy`：线上部署分支（从 dev 挑选/合并后发布）

## 2) 本地初始化（只做一次）

```bash
git remote add upstream https://github.com/rachelos/we-mp-rss.git
git fetch --all --prune

# 从 main 拉出 dev / deploy
git switch -c dev
git switch -c deploy main
git switch dev
```

### GitHub SSH 22 端口被拦时（可选）

如果你所在网络无法访问 `github.com:22`，用 443：

```bash
git remote set-url origin ssh://git@ssh.github.com:443/zhsh2980/we-mp-rss-linux.git
```

## 3) 跟官方同步（每次官方更新后）

推荐用 rebase，保证你的二开提交清晰：

```bash
git fetch upstream --prune

# 1) 更新 main（只快进）
git switch main
git merge --ff-only upstream/main

# 2) 把 dev 变基到最新 main
git switch dev
git rebase main

# 3) 更新 deploy（发布前再做）
git switch deploy
git merge --ff-only dev

# 4) 推送到你的 fork
git push origin main dev deploy
```

冲突处理要点：
- rebase 冲突：按提示解决后 `git rebase --continue`
- 不确定时：先 `git status` 看冲突文件，再用你的 AI 协助分析/解决

## 4) 服务器拉代码：GitHub Deploy Key

> [!IMPORTANT]
> 如果使用 `init_server.sh` 脚本，此步骤会自动完成，无需手动操作。

目的：让服务器能 `git clone/pull` 你的私有仓库，但权限最小（只读）。

### 在服务器上生成 deploy key

```bash
ssh -i bro_private/key/你的密钥.pem ubuntu@你的服务器IP

# 在服务器上执行：
mkdir -p ~/.ssh && chmod 700 ~/.ssh
ssh-keygen -t ed25519 -C "we-mp-rss-linux deploy@服务器IP" -f ~/.ssh/we_mp_rss_deploy -N ""
cat ~/.ssh/we_mp_rss_deploy.pub
```

### 添加到 GitHub

1. 复制上面输出的公钥
2. 访问你的仓库 → `Settings` → `Deploy keys` → `Add deploy key`
3. 粘贴公钥，**不要勾选** write access

### 配置 SSH（重要）

```bash
# 添加 GitHub host key（防止 Host key verification failed）
ssh-keyscan -p 443 ssh.github.com >> ~/.ssh/known_hosts

# 配置 host alias（避免影响其它仓库）
cat >> ~/.ssh/config <<'EOF'
Host github.com-we-mp-rss-linux
  HostName ssh.github.com
  Port 443
  User git
  IdentityFile ~/.ssh/we_mp_rss_deploy
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config

# 测试连接
ssh -T github.com-we-mp-rss-linux
```

## 5) 服务器目录结构

```
/srv/we-mp-rss/
├── app/              # 代码目录（git 仓库）
│   ├── config.yaml   # -> /srv/we-mp-rss/config.yaml（符号链接）
│   ├── data/         # -> /srv/we-mp-rss/data（符号链接）
│   └── ...
├── data/             # 数据目录（SQLite 数据库等，持久化）
├── config.yaml       # 配置文件（持久化）
└── venv/             # Python 虚拟环境
```

- 只开 `8001` 端口（安全组放行 TCP 8001）
- 使用 SQLite（默认 `data/db.db`），需持久化 `data/`

## 6) systemd 服务配置

生产推荐使用 `systemd`：开机自启、崩溃自动拉起、统一日志。

服务文件模板位于：`bro_private/scripts/we-mp-rss.service`

```ini
[Unit]
Description=WeRSS - WeChat MP to RSS Service
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/srv/we-mp-rss/app
Environment="PATH=/srv/we-mp-rss/venv/bin:/usr/local/bin:/usr/bin:/bin"
ExecStart=/srv/we-mp-rss/venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

安装命令：

```bash
sudo cp bro_private/scripts/we-mp-rss.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable we-mp-rss
sudo systemctl start we-mp-rss
```

## 7) 更新部署

使用脚本快速部署更新：

```bash
# 确保在 deploy 分支
git switch deploy
git merge --ff-only dev

# 执行部署
./bro_private/scripts/deploy_prod.sh
```

### 部署脚本选项

```bash
./bro_private/scripts/deploy_prod.sh --help

Options:
  --dry-run, -n    只显示将要执行的命令，不实际执行
  --skip-pip       跳过 pip install 步骤
  --help, -h       显示帮助信息
```

## 8) 回滚

如果部署出现问题，可以快速回滚到上一个版本：

### 方法一：回滚到指定 commit

```bash
# 查看最近的提交
git log --oneline -10

# 回滚到指定 commit
ssh -i bro_private/key/你的密钥.pem ubuntu@服务器IP "cd /srv/we-mp-rss/app && git reset --hard <commit-hash> && sudo systemctl restart we-mp-rss"
```

### 方法二：回滚到上一个版本

```bash
ssh -i bro_private/key/你的密钥.pem ubuntu@服务器IP "cd /srv/we-mp-rss/app && git reset --hard HEAD~1 && sudo systemctl restart we-mp-rss"
```

## 9) 常用运维命令

```bash
# 查看服务状态
ssh -i key.pem ubuntu@服务器 "sudo systemctl status we-mp-rss"

# 查看实时日志
ssh -i key.pem ubuntu@服务器 "sudo journalctl -u we-mp-rss -f"

# 重启服务
ssh -i key.pem ubuntu@服务器 "sudo systemctl restart we-mp-rss"

# 停止服务
ssh -i key.pem ubuntu@服务器 "sudo systemctl stop we-mp-rss"
```

## 10) 国内镜像配置（可选）

源码部署会从外网下载依赖，如果下载很慢/失败，可以配置国内镜像：

### pip 镜像（清华）

```bash
mkdir -p ~/.pip
cat > ~/.pip/pip.conf <<EOF
[global]
index-url = https://pypi.tuna.tsinghua.edu.cn/simple
trusted-host = pypi.tuna.tsinghua.edu.cn
EOF
```

### npm/yarn 镜像

```bash
npm config set registry https://registry.npmmirror.com
```

---

## 脚本文件清单

| 文件 | 用途 |
|------|------|
| `scripts/init_server.sh` | 首次部署（全自动） |
| `scripts/deploy_prod.sh` | 更新部署 |
| `scripts/we-mp-rss.service` | systemd 服务模板 |
| `.env.example` | 环境变量配置模板 |
