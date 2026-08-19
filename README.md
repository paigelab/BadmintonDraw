# 羽球場地抽籤資訊站

蒐集各校公開的羽球場地抽籤、登記與場地使用公告，並統一整理在 GitHub Pages 網站。

## 專案結構

- `index.html`：公開網站首頁
- `data/sources.csv`：學校公告來源清單
- `data/announcements.json`：網站顯示的整理公告資料
- `scripts/check_announcements.py`：定期檢查來源頁面是否更新
- `.github/workflows/`：GitHub Pages 部署與每日巡查排程

## 新增學校來源

在 `data/sources.csv` 加上一列公開的體育室或場館公告網址。第一版先從 5 至 10 所學校開始，確認各網站格式後再擴大。

## GitHub 設定

推送到 GitHub 後，在 Repository 的 **Settings → Pages**，將 Source 設為 **GitHub Actions**。網站將在每次推送後自動部署。

巡查排程預設為台灣時間每天 10:08 與 18:08；新增或修改來源資料時也會立即巡查。系統會從公告連結標題中篩選羽球、抽籤或場地登記等候選資訊，並寫入網站資料檔。不同學校網站格式可能不同，請定期以原始公告確認內容。
