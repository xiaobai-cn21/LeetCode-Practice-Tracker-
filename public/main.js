const form = document.getElementById('search-form');
const qInput = document.getElementById('query');
const limitSelect = document.getElementById('limit');
const resultsTbody = document.getElementById('results');
const prevBtn = document.getElementById('prev');
const nextBtn = document.getElementById('next');
const pageInfo = document.getElementById('page-info');
const todayBody = document.getElementById('today-body');
const mineBody = document.getElementById('mine-body');
const customForm = document.getElementById('custom-form');
const customTitle = document.getElementById('custom-title');
const customLink = document.getElementById('custom-link');
const tabs = document.querySelectorAll('.tab');
const panels = document.querySelectorAll('[data-panel]');
const pagination = document.querySelector('.pagination');

let currentPage = 1;

function problemUrl(titleSlug) { return `https://leetcode.cn/problems/${titleSlug}/`; }
function getItemUrl(item) {
  if (item.link && item.link.startsWith('http')) return item.link;
  if (item.title_slug) return problemUrl(item.title_slug);
  return '#';
}

async function search(page = 1) {
  const q = (qInput.value || '').trim();
  const limit = parseInt(limitSelect.value, 10);
  const params = new URLSearchParams({ q, page: String(page), limit: String(limit) });
  resultsTbody.innerHTML = '<tr><td class="meta" colspan="4">加载中...</td></tr>';
  try {
    const resp = await fetch(`/api/search?${params.toString()}`);
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || '请求失败');
    renderResults(data, q);
  } catch (e) {
    resultsTbody.innerHTML = `<tr><td class="meta" colspan="4">错误：${e.message}</td></tr>`;
  }
}

function renderResults(data, q) {
  currentPage = data.page;
  const totalPages = Math.max(1, Math.ceil((data.total || 0) / data.limit));
  pageInfo.textContent = `第 ${currentPage} / ${totalPages} 页（共 ${data.total} 题）`;
  prevBtn.disabled = currentPage <= 1;
  nextBtn.disabled = currentPage >= totalPages;

  const list = data.questions || [];
  if (list.length === 0) {
    resultsTbody.innerHTML = '<tr><td class="meta" colspan="4">没有找到结果</td></tr>';
    return;
  }

  resultsTbody.innerHTML = list.map(item => {
    const url = problemUrl(item.titleSlug);
    const diffClass = `difficulty ${item.difficulty}`;
    return `
      <tr>
        <td>#${item.frontendQuestionId}</td>
        <td><a href="${url}" target="_blank" rel="noreferrer">${item.title}</a></td>
        <td><span class="${diffClass}">${item.difficulty}</span></td>
        <td>${(item.acRate || 0).toFixed(2)}% <button data-add="${encodeURIComponent(item.titleSlug)}" data-title="${encodeURIComponent(item.title)}" data-id="${encodeURIComponent(item.frontendQuestionId)}" data-diff="${encodeURIComponent(item.difficulty)}">添加</button></td>
      </tr>
    `;
  }).join('');
}

resultsTbody.addEventListener('click', async (e) => {
  const btn = e.target.closest('button[data-add]');
  if (!btn) return;
  const titleSlug = decodeURIComponent(btn.getAttribute('data-add'));
  const title = decodeURIComponent(btn.getAttribute('data-title'));
  const frontendId = decodeURIComponent(btn.getAttribute('data-id'));
  const difficulty = decodeURIComponent(btn.getAttribute('data-diff'));
  btn.disabled = true; btn.textContent = '添加中...';
  try {
    const resp = await fetch('/api/my/add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ titleSlug, title, frontendQuestionId: frontendId, difficulty }) });
    const text = await resp.text();
    let data;
    try { data = JSON.parse(text); } catch (_) { throw new Error(`服务器返回异常：${text.slice(0,120)}`); }
    if (!resp.ok || !data.ok) throw new Error(data.error || '添加失败');
    btn.textContent = '已添加';
  } catch (err) {
    btn.textContent = '重试添加'; btn.disabled = false; alert(err.message);
  }
});

async function loadToday() {
  todayBody.innerHTML = '<tr><td class="meta" colspan="4">加载中...</td></tr>';
  try {
    const resp = await fetch('/api/my/today');
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || '加载失败');
    const list = data.items || [];
    if (list.length === 0) {
      todayBody.innerHTML = '<tr><td class="meta" colspan="4">今天没有需要复习的题</td></tr>';
      return;
    }
    todayBody.innerHTML = list.map(item => {
      const url = problemUrl(item.title_slug);
      const diffClass = `difficulty ${item.difficulty}`;
      return `
        <tr>
          <td>#${item.frontend_id || ''}</td>
          <td><a href="${url}" target="_blank" rel="noreferrer">${item.title}</a></td>
          <td><span class="${diffClass}">${item.difficulty}</span></td>
          <td>
            <button data-check="ok" data-slug="${item.title_slug}">完成</button>
            <button data-check="again" data-slug="${item.title_slug}">再练</button>
          </td>
        </tr>
      `;
    }).join('');
  } catch (e) {
    todayBody.innerHTML = `<tr><td class="meta" colspan="4">错误：${e.message}</td></tr>`;
  }
}

todayBody.addEventListener('click', async (e) => {
  const btn = e.target.closest('button[data-check]');
  if (!btn) return;
  const success = btn.getAttribute('data-check') === 'ok';
  const slug = btn.getAttribute('data-slug');
  btn.disabled = true;
  try {
    const resp = await fetch('/api/my/check', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ titleSlug: slug, success }) });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || '失败');
    await loadToday();
  } catch (err) {
    alert(err.message);
    btn.disabled = false;
  }
});

async function loadMine() {
  mineBody.innerHTML = '<tr><td class="meta" colspan="4">加载中...</td></tr>';
  try {
    const resp = await fetch('/api/my/list');
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || '加载失败');
    const list = data.items || [];
    if (list.length === 0) {
      mineBody.innerHTML = '<tr><td class="meta" colspan="5">还没有添加题目</td></tr>';
      return;
    }
    function tsToText(ts){
      if (!ts) return '-';
      const d = new Date(ts * 1000);
      // show only date part
      return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
    }
    mineBody.innerHTML = list.map(item => {
      const url = getItemUrl(item);
      const diffClass = `difficulty ${item.difficulty}`;
      return `
        <tr>
          <td>${item.frontend_id ? '#' + item.frontend_id : ''}</td>
          <td><a href="${url}" target="_blank" rel="noreferrer">${item.title}</a></td>
          <td><span class="${diffClass}">${item.difficulty || '-'}</span></td>
          <td>${tsToText(item.next_due_ts)}</td>
          <td><button data-del="${item.title_slug}">删除</button></td>
        </tr>
      `;
    }).join('');
customForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const title = customTitle.value.trim();
  const link = customLink.value.trim();
  if (!title || !link) { alert('题目名和链接必填'); return; }
  customForm.querySelector('button[type="submit"]').disabled = true;
  try {
    const resp = await fetch('/api/custom_add', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, link }) });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || '添加失败');
    customTitle.value = '';
    customLink.value = '';
    customForm.querySelector('button[type="submit"]').textContent = '已添加';
    setTimeout(() => {
      customForm.querySelector('button[type="submit"]').textContent = '添加自定义题目';
      customForm.querySelector('button[type="submit"]').disabled = false;
    }, 1200);
    loadMine();
  } catch (err) {
    customForm.querySelector('button[type="submit"]').disabled = false;
    alert(err.message);
  }
});
  } catch (e) {
    mineBody.innerHTML = `<tr><td class="meta" colspan="5">错误：${e.message}</td></tr>`;
  }
}

mineBody.addEventListener('click', async (e) => {
  const btn = e.target.closest('button[data-del]');
  if (!btn) return;
  const slug = btn.getAttribute('data-del');
  if (!confirm('确定删除该题目吗？')) return;
  btn.disabled = true;
  try {
    const resp = await fetch('/api/my/delete', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ titleSlug: slug }) });
    const data = await resp.json();
    if (!data.ok) throw new Error(data.error || '删除失败');
    await loadMine();
  } catch (err) {
    alert(err.message);
    btn.disabled = false;
  }
});

tabs.forEach(tab => {
  tab.addEventListener('click', () => {
    tabs.forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    const target = tab.getAttribute('data-tab');
    panels.forEach(p => {
      p.style.display = (p.getAttribute('data-panel') === target) ? '' : 'none';
    });
    // toggle pagination only for search panel
    if (pagination) {
      pagination.style.display = (target === 'search') ? '' : 'none';
    }
    if (target !== 'search') {
      // clear page label when leaving search to avoid confusing numbers
      pageInfo.textContent = '';
    }
    if (target === 'today') loadToday();
    if (target === 'mine') loadMine();
  });
});

form.addEventListener('submit', e => {
  e.preventDefault();
  currentPage = 1;
  search(1);
});

prevBtn.addEventListener('click', () => {
  if (currentPage > 1) search(currentPage - 1);
});
nextBtn.addEventListener('click', () => {
  search(currentPage + 1);
});

// Initial
search(1);


