const list = document.querySelector('#announcement-list');
const search = document.querySelector('#search');
const schoolFilter = document.querySelector('#school-filter');
const resultCount = document.querySelector('#result-count');
const sourceList = document.querySelector('#source-list');

let announcements = [];

function render() {
  const term = search.value.trim().toLowerCase();
  const school = schoolFilter.value;
  const shown = announcements.filter((item) => {
    const searchable = [item.school, item.title, item.summary, item.type].join(' ').toLowerCase();
    return (!term || searchable.includes(term)) && (!school || item.school === school);
  });
  resultCount.textContent = `共 ${shown.length} 筆`;
  list.innerHTML = shown.length ? shown.map((item) => `
    <article class="card">
      <div class="card-top"><span class="tag">${item.school}</span><time>${item.published_at || '日期待確認'}</time></div>
      <h3>${item.title}</h3>
      <p>${item.summary || '詳細資訊請見校方原始公告。'}</p>
      <a href="${item.source_url}" target="_blank" rel="noopener noreferrer">查看原始公告 →</a>
    </article>`).join('') : '<p class="empty">尚無符合條件的公告。</p>';
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

async function init() {
  try {
    const [response, statusResponse] = await Promise.all([fetch('data/announcements.json'), fetch('data/source-status.json')]);
    const [data, statusData] = await Promise.all([response.json(), statusResponse.json()]);
    announcements = data.announcements || [];
    document.querySelector('#last-updated').textContent = data.last_updated || '尚未更新';
    [...new Set(announcements.map((item) => item.school))].sort().forEach((school) => {
      schoolFilter.add(new Option(school, school));
    });
    renderSources(statusData.sources);
  } catch { list.innerHTML = '<p class="empty">公告資料暫時無法讀取。</p>'; }
  render();
}
search.addEventListener('input', render);
schoolFilter.addEventListener('change', render);
init();
