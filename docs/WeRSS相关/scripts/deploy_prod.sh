#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# WeRSS 生产环境部署脚本
# 用于更新部署（首次部署请使用 init_server.sh）
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
PROD_APP_DIR="${PROD_APP_DIR:-/srv/we-mp-rss/app}"
PROD_SERVICE="${PROD_SERVICE:-we-mp-rss}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-deploy}"
VENV_PY="${VENV_PY:-/srv/we-mp-rss/venv/bin/python}"
RUN_PIP_INSTALL="${RUN_PIP_INSTALL:-1}"
DRY_RUN="${DRY_RUN:-0}"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}==>${NC} $1"; }
log_warn() { echo -e "${YELLOW}WARN:${NC} $1" >&2; }
log_error() { echo -e "${RED}ERROR:${NC} $1" >&2; }

# 解析命令行参数
while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run|-n)
      DRY_RUN=1
      shift
      ;;
    --skip-pip)
      RUN_PIP_INSTALL=0
      shift
      ;;
    --help|-h)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --dry-run, -n    只显示将要执行的命令，不实际执行"
      echo "  --skip-pip       跳过 pip install 步骤"
      echo "  --help, -h       显示帮助信息"
      exit 0
      ;;
    *)
      log_error "未知参数: $1"
      exit 1
      ;;
  esac
done

cd "${repo_root}"

# 检查工作区是否干净
if ! git diff --quiet || ! git diff --cached --quiet; then
  log_error "工作区不干净，请先 commit 或 stash 后再部署"
  exit 1
fi

# 检查当前分支
current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ "${current_branch}" != "${DEPLOY_BRANCH}" ]]; then
  log_error "当前分支是 '${current_branch}'，期望 '${DEPLOY_BRANCH}'"
  echo "提示: git switch ${DEPLOY_BRANCH} && git merge --ff-only dev" >&2
  exit 1
fi

# 构建 SSH 参数
ssh_args=()
if [[ -n "${PROD_SSH_PORT}" ]]; then
  ssh_args+=(-p "${PROD_SSH_PORT}")
fi
if [[ -n "${PROD_SSH_KEY}" && -f "${PROD_SSH_KEY}" ]]; then
  ssh_args+=(-i "${PROD_SSH_KEY}")
fi

# 构建远程命令
remote_script=$(cat <<EOF
set -euo pipefail

cd "${PROD_APP_DIR}"

echo "==> 更新代码 ..."
git fetch origin --prune
git reset --hard "origin/${DEPLOY_BRANCH}"

if [[ "${RUN_PIP_INSTALL}" == "1" ]]; then
  if [[ -x "${VENV_PY}" ]]; then
    echo "==> 安装 Python 依赖 ..."
    "${VENV_PY}" -m pip install -q -r requirements.txt
  else
    echo "WARN: ${VENV_PY} 不存在，跳过 pip install" >&2
  fi
fi

echo "==> 重启服务 (${PROD_SERVICE}) ..."
sudo systemctl restart "${PROD_SERVICE}"

echo "==> 健康检查 ..."
sleep 2
if curl -s -o /dev/null -w '' --connect-timeout 5 http://localhost:8001/; then
  echo "✅ 服务健康检查通过 (HTTP 200)"
else
  echo "⚠️  健康检查未返回 200，请检查日志"
fi

sudo systemctl status "${PROD_SERVICE}" --no-pager
EOF
)

if [[ "${DRY_RUN}" == "1" ]]; then
  log_info "[DRY-RUN] 将执行以下操作："
  echo ""
  echo "1. git push origin ${DEPLOY_BRANCH}"
  echo ""
  echo "2. ssh ${ssh_args[*]} ${PROD_SSH_HOST} 执行："
  echo "---"
  echo "${remote_script}"
  echo "---"
  exit 0
fi

log_info "推送 origin/${DEPLOY_BRANCH} ..."
git push origin "${DEPLOY_BRANCH}"

log_info "部署到 ${PROD_SSH_HOST} ..."
ssh "${ssh_args[@]}" "${PROD_SSH_HOST}" bash -s <<< "${remote_script}"

log_info "部署完成 ✅"
