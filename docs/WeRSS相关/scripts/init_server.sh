#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# WeRSS 服务器首次部署脚本
# 用于在全新服务器上完成 WeRSS 的首次部署
# =============================================================================

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "${script_dir}/../.." && pwd)"

# 加载环境变量
env_file="${repo_root}/bro_private/.env"
if [[ -f "${env_file}" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "${env_file}"
  set +a
fi

# 默认配置
PROD_SSH_HOST="${PROD_SSH_HOST:-ubuntu@154.8.205.159}"
PROD_SSH_PORT="${PROD_SSH_PORT:-22}"
PROD_SSH_KEY="${PROD_SSH_KEY:-}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-deploy}"
ADMIN_USER="${ADMIN_USER:-admin}"
ADMIN_PASS="${ADMIN_PASS:-123654zz}"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() { echo -e "${GREEN}==>${NC} $1"; }
log_step() { echo -e "${CYAN}[STEP]${NC} $1"; }
log_warn() { echo -e "${YELLOW}WARN:${NC} $1" >&2; }
log_error() { echo -e "${RED}ERROR:${NC} $1" >&2; }

# 构建 SSH 参数
ssh_args=()
if [[ -n "${PROD_SSH_PORT}" ]]; then
  ssh_args+=(-p "${PROD_SSH_PORT}")
fi
if [[ -n "${PROD_SSH_KEY}" && -f "${PROD_SSH_KEY}" ]]; then
  ssh_args+=(-i "${PROD_SSH_KEY}")
fi

ssh_cmd() {
  ssh "${ssh_args[@]}" "${PROD_SSH_HOST}" "$@"
}

# =============================================================================
# Step 1: 检测服务器基本环境
# =============================================================================
log_step "1/7 检测服务器环境"
ssh_cmd "cat /etc/os-release | grep -E '^(NAME|VERSION_ID)' && which git python3"

# =============================================================================
# Step 2: 生成 GitHub Deploy Key（如果不存在）
# =============================================================================
log_step "2/7 配置 GitHub Deploy Key"
DEPLOY_KEY=$(ssh_cmd bash -s <<'EOF'
set -euo pipefail
mkdir -p ~/.ssh && chmod 700 ~/.ssh

if [[ ! -f ~/.ssh/we_mp_rss_deploy ]]; then
  ssh-keygen -t ed25519 -C "we-mp-rss-linux deploy" -f ~/.ssh/we_mp_rss_deploy -N ""
  echo "NEW_KEY"
else
  echo "KEY_EXISTS"
fi
EOF
)

if [[ "${DEPLOY_KEY}" == *"NEW_KEY"* ]]; then
  log_warn "已生成新的 Deploy Key，请将以下公钥添加到 GitHub 仓库："
  echo ""
  ssh_cmd "cat ~/.ssh/we_mp_rss_deploy.pub"
  echo ""
  echo "添加步骤："
  echo "1. 访问 https://github.com/zhsh2980/we-mp-rss-linux/settings/keys"
  echo "2. 点击 Add deploy key"
  echo "3. 粘贴上面的公钥，不要勾选 write access"
  echo ""
  read -p "添加完成后按 Enter 继续..."
fi

# 配置 SSH config 和 known_hosts
log_info "配置 SSH 连接 GitHub..."
ssh_cmd bash -s <<'EOF'
set -euo pipefail

# 添加 GitHub host key
ssh-keyscan -p 443 ssh.github.com >> ~/.ssh/known_hosts 2>/dev/null || true

# 配置 SSH config（如果不存在）
if ! grep -q "github.com-we-mp-rss-linux" ~/.ssh/config 2>/dev/null; then
  cat >> ~/.ssh/config <<'SSHCONFIG'
Host github.com-we-mp-rss-linux
  HostName ssh.github.com
  Port 443
  User git
  IdentityFile ~/.ssh/we_mp_rss_deploy
  IdentitiesOnly yes
SSHCONFIG
  chmod 600 ~/.ssh/config
fi

# 测试连接
ssh -T github.com-we-mp-rss-linux 2>&1 || true
EOF

# =============================================================================
# Step 3: 安装系统依赖
# =============================================================================
log_step "3/7 安装系统依赖"
ssh_cmd bash -s <<'EOF'
set -euo pipefail
sudo apt update
sudo apt install -y python3.10-venv python3-pip
EOF

# =============================================================================
# Step 4: 创建目录结构并克隆代码
# =============================================================================
log_step "4/7 克隆代码"
ssh_cmd bash -s <<EOF
set -euo pipefail
sudo mkdir -p /srv/we-mp-rss/{app,data}
sudo chown -R \$(whoami):\$(whoami) /srv/we-mp-rss

if [[ ! -d /srv/we-mp-rss/app/.git ]]; then
  rm -rf /srv/we-mp-rss/app
  cd /srv/we-mp-rss
  git clone git@github.com-we-mp-rss-linux:zhsh2980/we-mp-rss-linux.git app
fi

cd /srv/we-mp-rss/app
git fetch origin --prune
git checkout ${DEPLOY_BRANCH}
git reset --hard origin/${DEPLOY_BRANCH}
EOF

# =============================================================================
# Step 5: 创建虚拟环境并安装依赖
# =============================================================================
log_step "5/7 安装 Python 依赖"
ssh_cmd bash -s <<'EOF'
set -euo pipefail
python3 -m venv /srv/we-mp-rss/venv
source /srv/we-mp-rss/venv/bin/activate
pip install --upgrade pip
pip install -r /srv/we-mp-rss/app/requirements.txt
EOF

log_info "安装 Playwright..."
ssh_cmd bash -s <<'EOF'
set -euo pipefail
source /srv/we-mp-rss/venv/bin/activate
playwright install chromium
sudo /srv/we-mp-rss/venv/bin/playwright install-deps chromium
EOF

# =============================================================================
# Step 6: 配置应用
# =============================================================================
log_step "6/7 配置应用"
ssh_cmd bash -s <<EOF
set -euo pipefail

# 创建配置文件
if [[ ! -f /srv/we-mp-rss/config.yaml ]]; then
  cp /srv/we-mp-rss/app/config.example.yaml /srv/we-mp-rss/config.yaml
fi

# 创建符号链接
ln -sf /srv/we-mp-rss/config.yaml /srv/we-mp-rss/app/config.yaml
ln -sf /srv/we-mp-rss/data /srv/we-mp-rss/app/data

# 初始化管理员
cd /srv/we-mp-rss/app
USERNAME=${ADMIN_USER} PASSWORD=${ADMIN_PASS} /srv/we-mp-rss/venv/bin/python init_sys.py
EOF

# =============================================================================
# Step 7: 创建并启动 systemd 服务
# =============================================================================
log_step "7/7 配置 systemd 服务"
ssh_cmd bash -s <<'EOF'
set -euo pipefail

sudo tee /etc/systemd/system/we-mp-rss.service > /dev/null <<'SERVICE'
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
SERVICE

sudo systemctl daemon-reload
sudo systemctl enable we-mp-rss
sudo systemctl start we-mp-rss
sleep 3
sudo systemctl status we-mp-rss --no-pager
EOF

# =============================================================================
# 完成
# =============================================================================
log_info "🎉 首次部署完成！"
echo ""
echo "访问地址: http://${PROD_SSH_HOST#*@}:8001"
echo "管理员账号: ${ADMIN_USER}"
echo "管理员密码: ${ADMIN_PASS}"
echo ""
echo "后续更新请使用: ./bro_private/scripts/deploy_prod.sh"
