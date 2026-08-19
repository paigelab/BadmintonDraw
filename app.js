const list = document.querySelector('#announcement-list');
const search = document.querySelector('#search');
const schoolFilter = document.querySelector('#school-filter');
const resultCount = document.querySelector('#result-count');

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

async function init() {
  try {
    const response = await fetch('data/announcements.json');
    const data = await response.json();
    announcements = data.announcements || [];
    document.querySelector('#last-updated').textContent = data.last_updated || '尚未更新';
    [...new Set(announcements.map((item) => item.school))].sort().forEach((school) => {
      schoolFilter.add(new Option(school, school));
    });
  } catch { list.innerHTML = '<p class="empty">公告資料暫時無法讀取。</p>'; }
  render();
}
search.addEventListener('input', render);
schoolFilter.addEventListener('change', render);
init();
