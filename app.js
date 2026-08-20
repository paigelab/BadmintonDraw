const latestList = document.querySelector('#announcement-list');
const historyList = document.querySelector('#history-list');
const search = document.querySelector('#search');
const schoolFilter = document.querySelector('#school-filter');
const categoryFilter = document.querySelector('#category-filter');
const latestCount = document.querySelector('#result-count');
const historyCount = document.querySelector('#history-count');
const historyDetails = document.querySelector('#history-details');
const sourceList = document.querySelector('#source-list');

const LATEST_LIMIT = 6;
const CATEGORIES = {
  registration: '登記／報名',
  result: '抽籤結果',
  rule: '管理辦法',
  other: '其他',
};

let announcements = [];

function categoryOf(item) {
  if (item.category) return item.category;
  const text = `${item.title || ''} ${item.summary || ''}`.replace(/\s/g, '');
  if (/中籤|抽籤結果|抽籤名單|登記結果|錄取結果/.test(text)) return 'result';
  if (/登記|報名|申請|出租|租用|預約/.test(text)) return 'registration';
  if (/管理辦法|使用規則|使用管理|租借管理/.test(text)) return 'rule';
  return 'other';
}

function card(item) {
  const category = categoryOf(item);
  return `<article class="card">
    <div class="card-top"><span><span class="tag">${item.school}</span><span class="category">${CATEGORIES[category]}</span></span><time>${item.published_at || '日期待確認'}</time></div>
    <h3>${item.title}</h3>
    <a href="${item.source_url}" target="_blank" rel="noopener noreferrer">查看原始公告 →</a>
  </article>`;
}

function renderLatest() {
  const latest = announcements.slice(0, LATEST_LIMIT);
  latestCount.textContent = latest.length ? `近期 ${latest.length} 筆` : '';
  latestList.innerHTML = latest.length ? latest.map(card).join('') : '<p class="empty">尚無公告資料。</p>';
}

function renderHistory() {
  const term = search.value.trim().toLowerCase();
  const school = schoolFilter.value;
  const category = categoryFilter.value;
  const shown = announcements.filter((item) => {
    const searchable = [item.school, item.title, item.summary, CATEGORIES[categoryOf(item)]].join(' ').toLowerCase();
    return (!term || searchable.includes(term)) && (!school || item.school === school) && (!category || categoryOf(item) === category);
  });
  historyCount.textContent = `共 ${shown.length} 筆公告`;
  historyList.innerHTML = shown.length ? shown.map(card).join('') : '<p class="empty">尚無符合條件的公告。</p>';
}

function renderSources(sources) {
  const entries = Object.entries(sources || {});
  sourceList.innerHTML = entries.length ? entries.map(([url, item]) => {
    const checked = (item.checked_at || '尚未檢查').replace('T', ' ').replace(/:\d{2}\+08:00$/, '');
    const scanned = item.nss_fulltext_candidate_count !== undefined
      ? `已完成全文檢索，找到 ${item.nss_fulltext_candidate_count} 筆相關候選公告`
      : item.nss_announcement_count ? `已讀取 ${item.nss_announcement_count} 則一般公告` : '已檢查公告頁';
    const status = item.error ? '暫時無法讀取' : item.candidate_count ? `找到 ${item.candidate_count} 筆候選公告` : `${scanned}，尚無候選公告`;
    return `<article class="source-card">
      <span class="status">${status}</span>
      <h3>${item.school}</h3>
      <p>最近檢查：${checked}</p>
      <a href="${url}" target="_blank" rel="noopener noreferrer">開啟校方公告頁 →</a>
    </article>`;
  }).join('') : '<p class="empty">尚未加入學校公告來源。</p>';
}

function openHistoryFromHash() {
  if (location.hash === '#history') historyDetails.open = true;
}

async function init() {
  try {
    const [response, statusResponse] = await Promise.all([fetch('data/announcements.json'), fetch('data/source-status.json')]);
    const [data, statusData] = await Promise.all([response.json(), statusResponse.json()]);
    announcements = [...(data.announcements || [])].sort((a, b) => String(b.published_at || '').localeCompare(String(a.published_at || '')));
    document.querySelector('#last-updated').textContent = data.last_updated || '尚未更新';
    [...new Set(announcements.map((item) => item.school))].sort().forEach((school) => schoolFilter.add(new Option(school, school)));
    Object.entries(CATEGORIES).forEach(([value, label]) => categoryFilter.add(new Option(label, value)));
    renderLatest();
    renderHistory();
    renderSources(statusData.sources);
    openHistoryFromHash();
  } catch {
    latestList.innerHTML = '<p class="empty">公告資料暫時無法讀取。</p>';
  }
}

search.addEventListener('input', renderHistory);
schoolFilter.addEventListener('change', renderHistory);
categoryFilter.addEventListener('change', renderHistory);
window.addEventListener('hashchange', openHistoryFromHash);
init();
