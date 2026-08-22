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
- `data/manual-check.json`：暫不納入排程、改由人工確認的公告頁清單
- `data/notified.json`：Discord 通知初始化基準與已成功發送的公告網址
- `scripts/check_announcements.py`：公告 crawler 與 NSS 全文檢索整合
- `.github/workflows/check-sources.yml`：巡查、更新資料與部署最新資料
- `.github/workflows/pages.yml`：一般網站部署

## 網站呈現

- **最新公告**：每間學校最多顯示兩筆，分別是最新的「登記／報名」與「抽籤結果」公告。
- **歷史資料**：預設收合，展開後可依學校、公告類型及關鍵字篩選全部已蒐集公告。
- **正在監測的學校**：保留每個來源的最近檢查時間與讀取狀態，不顯示候選公告數量。
- **人工檢查**：爬蟲無法讀取的公告頁保留校方連結，但不會納入排程掃描。

## 公告資料與分類

每筆公告至少包含：

- `school`：學校名稱
- `title`：公告標題
- `published_at`：公告日期
- `source_url`：原始公告網址
- `category`：公告分類

分類規則以**公告標題優先**、內容輔助判斷：

- `registration`：登記、報名、申請、出租、租用、租借、預約、抽籤辦法
- `result`：抽籤結果、中籤名單、登記結果、錄取結果
- `rule`：管理辦法、使用規則、使用管理、租借管理
- `other`：其他相關公告

標題優先可避免「登記公告提到日後抽籤」被誤判為抽籤結果。

## 公告蒐集流程

1. 讀取 `sources.csv` 中啟用的公開學校首頁。
2. 針對 NSS 網站自動發現公開公告 RSS 與全文檢索端點。
3. 以羽球、場地抽籤、場地登記與場地借用等關鍵字搜尋公告與歷史資料。
4. 篩選羽球場地相關內容、分類並寫入 `announcements.json`。
5. 首次執行時建立 Discord 通知基準；之後只對新出現的登記／報名或抽籤結果公告發送通知。
6. 更新監控狀態後，部署最新資料至 GitHub Pages。

## 新增學校來源

在 `data/sources.csv` 加上一列公開的體育室、總務處或場館公告首頁。格式如下：

```csv
school,source_url,enabled
範例國小,https://example.edu.tw/nss/p/index,true
```

`enabled` 設為 `true` 才會納入巡查。不同網站格式可能不同，新增來源後請先確認 Actions 執行結果。

若來源長期無法讀取，請從 `data/sources.csv` 移除，並加入 `data/manual-check.json`。該清單會顯示在網站的「人工檢查」區塊，保留連至校方公告頁的按鈕，但排程不會掃描它。

## GitHub 設定

推送到 GitHub 後，在 Repository 的 **Settings → Pages**，將 Source 設為 **GitHub Actions**。網站將在每次推送後自動部署。

巡查排程為台灣時間每日 **10:08** 與 **18:08**；新增或修改來源資料、crawler 程式時也會立即巡查。每次巡查完成後會部署最新資料至 GitHub Pages。

GitHub Actions 的整點排程可能延遲，因此刻意避開整點。公告資訊仍應以校方原始公告為準。

## Discord 通知設定

Crawler 可透過 Discord Webhook 通知新發現的羽球場地公告，不需要主機或資料庫。公告通知與來源異常通知使用不同的 Webhook，因此可以送到不同 Discord 頻道。

1. 在 Discord 伺服器的目標頻道開啟 **編輯頻道 → 整合 → Webhooks → 新增 Webhook**，複製 Webhook URL。
2. 開啟 GitHub Repository 的 **Settings → Secrets and variables → Actions → New repository secret**。
3. Name 輸入 `DISCORD_WEBHOOK_URL`，Value 貼上 Discord Webhook URL 後儲存。

公告頻道的 Webhook URL 只會在 GitHub Actions 執行時以 Secret 環境變數 `DISCORD_WEBHOOK_URL` 讀取，不會寫入程式碼或資料檔。

通知只涵蓋 `registration`（登記／報名）與 `result`（抽籤結果），且公告日期必須在 crawler 執行日的最近 31 天內。每則公告以 `source_url` 去重；Discord 成功接收後才會寫入 `data/notified.json`。若發送失敗或尚未設定 Secret，該公告不會被標示為已通知，下一次排程會重試。超過 31 天或沒有標準日期的首次發現資料會記為歷史基準，不發送通知也不重試，避免新增學校來源時補發舊公告。

初次啟用時，crawler 會將當前所有符合分類的歷史公告寫入 `data/notified.json` 作為基準，**不會補發歷史通知**；只有基準建立後新出現的公告才會通知。

### 公告來源異常通知

請在要接收異常通知的**另一個 Discord 頻道**建立 Webhook，並於 GitHub Repository 的 **Settings → Secrets and variables → Actions** 新增 Secret：`DISCORD_ERROR_WEBHOOK_URL`。它與 `DISCORD_WEBHOOK_URL` 完全分開；未設定時不會影響一般公告通知。

啟用中的學校公告頁若無法讀取，Discord 會收到一則「學校公告來源讀取異常」通知，內容含學校、錯誤訊息、檢查時間與校方公告頁連結。同一來源持續出現相同錯誤時不會重複通知；成功讀取後會解除異常狀態，之後若再次失敗才會重新通知。異常狀態同樣只在 Discord 成功接收後才寫入 `data/notified.json`，因此傳送失敗會在下次排程重試。人工檢查清單的學校不會由 crawler 掃描，也不會觸發此通知。

### 測試 Webhook

在 GitHub 的 **Actions → Check school announcement pages → Run workflow** 中，可以勾選以下任一項後執行：

- `send_test_discord_notification`：在一般公告頻道收到一則「BadmintonDraw 測試」通知。
- `send_test_discord_error_notification`：在異常通知頻道收到一則模擬的「學校公告來源讀取異常」通知。

兩種測試皆不會新增或修改 `data/notified.json`，也不會影響正式通知的去重紀錄。
