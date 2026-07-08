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
