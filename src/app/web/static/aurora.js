/* ============================================================
   Aurora — 投资机会雷达 前端交互（无框架，原生 JS）
   ============================================================ */

/* ---------- 主题切换 ---------- */
(function initTheme() {
  const saved = localStorage.getItem('radar-theme');
  if (saved === 'dark') document.documentElement.dataset.theme = 'dark';
})();

function toggleTheme() {
  const html = document.documentElement;
  const dark = html.dataset.theme === 'dark';
  if (dark) { delete html.dataset.theme; localStorage.setItem('radar-theme', 'light'); }
  else { html.dataset.theme = 'dark'; localStorage.setItem('radar-theme', 'dark'); }
}

/* ---------- Toast ---------- */
function toast(msg) {
  let wrap = document.getElementById('toast-wrap');
  if (!wrap) { wrap = document.createElement('div'); wrap.id = 'toast-wrap'; document.body.appendChild(wrap); }
  const el = document.createElement('div');
  el.className = 'toast';
  el.textContent = msg;
  wrap.appendChild(el);
  setTimeout(() => el.remove(), 2600);
}

/* ---------- fetch 帮助函数 ---------- */
async function apiPost(url, data) {
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data || {}),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || ('请求失败 ' + res.status));
  }
  return res.json();
}

/* ---------- 倒计时渲染 ---------- */
function renderCountdowns() {
  document.querySelectorAll('[data-deadline]').forEach(el => {
    const dl = el.dataset.deadline;
    if (!dl) return;
    const end = new Date(dl);
    const now = new Date();
    let ms = end - now;
    el.classList.remove('is-urgent', 'is-expired');
    if (isNaN(end.getTime())) { el.textContent = '无时限'; return; }
    if (ms <= 0) {
      el.classList.add('is-expired');
      el.textContent = '已过期';
      const card = el.closest('.opp-card');
      if (card) card.dataset.expired = '1';
      return;
    }
    const hours = ms / 3.6e6;
    const d = Math.floor(hours / 24);
    const h = Math.floor(hours % 24);
    const m = Math.floor((ms % 3.6e6) / 6e4);
    el.textContent = '还剩 ' + (d > 0 ? `${d} 天 ${h} 小时` : (h > 0 ? `${h} 小时 ${m} 分` : `${m} 分钟`));
    if (hours < (window.URGENT_HOURS || 48)) el.classList.add('is-urgent');
  });
}

/* ---------- 机会卡片：展开/收起 ---------- */
function toggleExpand(btn) {
  const card = btn.closest('.opp-card');
  card.classList.toggle('expanded');
  const label = btn.querySelector('.lbl');
  if (label) label.textContent = card.classList.contains('expanded') ? '收起完整分析' : '展开完整分析';
}

/* ---------- 机会卡片：执行/观望/跳过 ---------- */
const ACTION_LABEL = { executed: '已执行', watching: '已转观望', skipped: '已跳过' };

async function oppAction(btn, analysisId, action) {
  const card = btn.closest('.opp-card');
  card.querySelectorAll('.opp-actions .ds-btn').forEach(b => b.disabled = true);
  try {
    await apiPost(`/api/workbench/${analysisId}/action`, { action });
    toast(ACTION_LABEL[action] || '已更新');
    // 打状态标记并淡出移出列表
    const mark = document.createElement('span');
    mark.className = 'opp-status-mark';
    mark.style.color = action === 'executed' ? 'var(--success)' : 'var(--text-3)';
    mark.textContent = ACTION_LABEL[action];
    card.querySelector('.opp-actions').replaceChildren(mark);
    setTimeout(() => {
      card.classList.add('leaving');
      setTimeout(() => { card.remove(); updateWorkbenchStats(); applyFilters(); }, 320);
    }, 600);
  } catch (e) {
    toast(e.message);
    card.querySelectorAll('.opp-actions .ds-btn').forEach(b => b.disabled = false);
  }
}

function updateWorkbenchStats() {
  const cards = document.querySelectorAll('.opp-card');
  const pendingEl = document.getElementById('stat-pending');
  const urgentEl = document.getElementById('stat-urgent');
  if (pendingEl) pendingEl.textContent = cards.length;
  if (urgentEl) {
    let urgent = 0;
    cards.forEach(c => { if (c.querySelector('.countdown.is-urgent')) urgent++; });
    urgentEl.textContent = urgent;
  }
  const sub = document.getElementById('page-sub-dynamic');
  if (sub) sub.textContent = `待处理 ${cards.length} 个机会,其中 ${urgentEl ? urgentEl.textContent : 0} 个临期需在 ${window.URGENT_HOURS || 48} 小时内决策`;
}

/* ---------- 筛选 ---------- */
const filterState = { type: 'all', score: 'all', status: 'pending' };

function setTypeFilter(btn, type) {
  filterState.type = type;
  btn.closest('.filter-pills').querySelectorAll('.filter-pill').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  applyFilters();
}

function setScoreFilter(sel) { filterState.score = sel.value; applyFilters(); }
function setStatusFilter(sel) { filterState.status = sel.value; applyFilters(); }

function resetFilters() {
  filterState.type = 'all'; filterState.score = 'all';
  const pills = document.querySelector('.filter-pills');
  if (pills) {
    pills.querySelectorAll('.filter-pill').forEach(b => b.classList.remove('active'));
    const first = pills.querySelector('.filter-pill');
    if (first) first.classList.add('active');
  }
  const scoreSel = document.getElementById('score-filter');
  if (scoreSel) scoreSel.value = 'all';
  applyFilters();
}

function applyFilters() {
  const cards = document.querySelectorAll('.opp-card');
  let shown = 0;
  cards.forEach(card => {
    let ok = true;
    if (filterState.type !== 'all' && card.dataset.type !== filterState.type) ok = false;
    if (ok && filterState.score !== 'all') {
      const s = parseInt(card.dataset.score || '0', 10);
      if (filterState.score === '80' && s < 80) ok = false;
      if (filterState.score === '60' && (s < 60 || s >= 80)) ok = false;
      if (filterState.score === 'lt60' && s >= 60) ok = false;
    }
    card.style.display = ok ? '' : 'none';
    if (ok) shown++;
  });
  const cnt = document.getElementById('filter-count');
  if (cnt) cnt.textContent = `共 ${shown} 条机会`;
  const empty = document.getElementById('opp-empty');
  if (empty) empty.style.display = shown === 0 ? '' : 'none';
}

/* ---------- 跟踪台：复盘表单 ---------- */
function toggleTrackForm(btn) {
  btn.closest('.track-card').classList.toggle('editing');
}

async function saveTrack(btn, trackId) {
  const card = btn.closest('.track-card');
  const get = n => { const el = card.querySelector(`[name="${n}"]`); return el ? el.value : null; };
  try {
    await apiPost(`/api/workbench/track/${trackId}/review`, {
      amount: get('amount') || null,
      pnl: get('pnl') || null,
      note: get('note') || null,
      close: !!card.querySelector('[name="close"]')?.checked,
    });
    toast('已保存');
    location.reload();
  } catch (e) { toast(e.message); }
}

/* ---------- 系统页：设置保存 / prompt 激活 ---------- */
async function saveSettings(btn) {
  const form = btn.closest('form');
  const data = {};
  form.querySelectorAll('[data-key]').forEach(el => {
    let v = el.value;
    if (el.dataset.json === '1') { try { v = JSON.parse(v); } catch (e) { toast(el.dataset.key + ' 不是合法 JSON'); throw e; } }
    else if (el.type === 'number') v = Number(v);
    data[el.dataset.key] = v;
  });
  try { await apiPost('/api/settings', data); toast('设置已保存'); }
  catch (e) { toast(e.message); }
}

async function activatePrompt(id) {
  try { await apiPost(`/api/prompts/${id}/activate`); toast('已激活'); location.reload(); }
  catch (e) { toast(e.message); }
}

async function runSlotNow() {
  try { await apiPost('/api/run-now'); toast('已触发批次,请稍后刷新'); }
  catch (e) { toast(e.message); }
}

/* ---------- 初始化 ---------- */
document.addEventListener('DOMContentLoaded', () => {
  renderCountdowns();
  setInterval(renderCountdowns, 60 * 1000);
  updateWorkbenchStats();
  applyFilters();
});
