# 羽球場地抽籤資訊站

蒐集各校公開的羽球場地登記、抽籤與使用公告，並統一整理在 GitHub Pages 網站。

網站部署於 GitHub Pages，不需自行架設主機；GitHub Actions 會定期更新資料。

## 專案結構

- `index.html`：首頁與可收合的歷史資料區
- `app.js`：公告排序、分類標籤、歷史篩選及監控資訊顯示
- `styles.css`：網站樣式
- `data/sources.csv`：學校公開公告來源清單
- `data/announcements.json`：crawler 整理後、供網站顯示的公告資料
- `data/source-status.json`：各來源最近檢查時間與讀取狀態
- `scripts/check_announcements.py`：公告 crawler 與 NSS 全文檢索整合
- `.github/workflows/check-sources.yml`：巡查、更新資料與部署最新資料
- `.github/workflows/pages.yml`：一般網站部署

## 網站呈現

- **最新公告**：每間學校最多顯示兩筆，分別是最新的「登記／報名」與「抽籤結果」公告。
- **歷史資料**：預設收合，展開後可依學校、公告類型及關鍵字篩選全部已蒐集公告。
- **正在監測的學校**：保留每個來源的最近檢查時間與讀取狀態，不顯示候選公告數量。

## 公告資料與分類

每筆公告至少包含：

- `school`：學校名稱
- `title`：公告標題
- `published_at`：公告日期
- `source_url`：原始公告網址
- `category`：公告分類

分類規則以**公告標題優先**、內容輔助判斷：

- `registration`：登記、報名、申請、出租、租用、預約
- `result`：抽籤結果、中籤名單、登記結果、錄取結果
- `rule`：管理辦法、使用規則、使用管理、租借管理
- `other`：其他相關公告

標題優先可避免「登記公告提到日後抽籤」被誤判為抽籤結果。

## 公告蒐集流程

1. 讀取 `sources.csv` 中啟用的公開學校首頁。
2. 針對 NSS 網站自動發現公開公告 RSS 與全文檢索端點。
3. 以羽球、場地抽籤、場地登記與場地借用等關鍵字搜尋公告與歷史資料。
4. 篩選羽球場地相關內容、分類並寫入 `announcements.json`。
5. 更新監控狀態後，部署最新資料至 GitHub Pages。

## 新增學校來源

在 `data/sources.csv` 加上一列公開的體育室、總務處或場館公告首頁。格式如下：

```csv
school,unit,source_url,enabled,notes
範例國小,總務處,https://example.edu.tw/nss/p/index,true,一般公告
```

`enabled` 設為 `true` 才會納入巡查。不同網站格式可能不同，新增來源後請先確認 Actions 執行結果。

## GitHub 設定

推送到 GitHub 後，在 Repository 的 **Settings → Pages**，將 Source 設為 **GitHub Actions**。網站將在每次推送後自動部署。

巡查排程為台灣時間每日 **10:08** 與 **18:08**；新增或修改來源資料、crawler 程式時也會立即巡查。每次巡查完成後會部署最新資料至 GitHub Pages。

GitHub Actions 的整點排程可能延遲，因此刻意避開整點。公告資訊仍應以校方原始公告為準。
