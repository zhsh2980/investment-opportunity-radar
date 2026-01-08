# WeRSS 项目云服务器部署总结

> 部署时间：2026-01-08

## 部署概要

| 项目 | 状态 |
|------|------|
| 服务器 | `154.8.205.159` (Ubuntu 22.04) |
| 服务地址 | http://154.8.205.159:8001 |
| 管理员账号 | `admin` / `123654zz` |
| 服务状态 | ✅ 运行中 |

---

## 完成的配置

### 服务器端
- **GitHub Deploy Key**：已配置（只读权限），服务器可拉取私有仓库
- **代码目录**：`/srv/we-mp-rss/app`（deploy 分支）
- **数据目录**：`/srv/we-mp-rss/data`（持久化）
- **配置文件**：`/srv/we-mp-rss/config.yaml`（持久化）
- **Python 虚拟环境**：`/srv/we-mp-rss/venv`
- **Playwright Chromium**：已安装浏览器及系统依赖
- **systemd 服务**：`we-mp-rss`（开机自启 + 崩溃自动重启）

### 本地端
- 已创建 `bro_private/.env` 配置文件
- 后续可使用 `./bro_private/scripts/deploy_prod.sh` 快速部署

---

## 验证结果

```
✅ 服务监听端口 8001
✅ 本地 HTTP 请求返回 200
✅ 外部 HTTP 请求返回 200
✅ systemd 服务状态：active (running)
```

---

## 常用操作命令

### 登录 Web 界面
访问 http://154.8.205.159:8001，使用以下凭据登录：
- 用户名：`admin`
- 密码：`123654zz`

### 快速部署更新
```bash
# 确保在 deploy 分支，并且工作区干净
git switch deploy
git merge --ff-only dev
./bro_private/scripts/deploy_prod.sh
```

### 查看服务日志
```bash
ssh -i bro_private/key/ubuntu_beijing.pem ubuntu@154.8.205.159 "sudo journalctl -u we-mp-rss -f"
```

### 重启服务
```bash
ssh -i bro_private/key/ubuntu_beijing.pem ubuntu@154.8.205.159 "sudo systemctl restart we-mp-rss"
```

### 停止服务
```bash
ssh -i bro_private/key/ubuntu_beijing.pem ubuntu@154.8.205.159 "sudo systemctl stop we-mp-rss"
```

### 查看服务状态
```bash
ssh -i bro_private/key/ubuntu_beijing.pem ubuntu@154.8.205.159 "sudo systemctl status we-mp-rss"
```

---

## 目录结构

```
/srv/we-mp-rss/
├── app/              # 代码目录（git 仓库）
│   ├── config.yaml   # -> /srv/we-mp-rss/config.yaml（符号链接）
│   ├── data/         # -> /srv/we-mp-rss/data（符号链接）
│   └── ...
├── data/             # 数据目录（SQLite 数据库等）
├── config.yaml       # 配置文件
└── venv/             # Python 虚拟环境
```

---

## 注意事项

1. **安全组**：确保云服务器安全组已放行 TCP 8001 端口
2. **密码修改**：建议首次登录后修改管理员密码
3. **数据备份**：定期备份 `/srv/we-mp-rss/data` 目录
4. **配置修改**：修改 `/srv/we-mp-rss/config.yaml` 后需重启服务生效
