# ⚡ Neon Pulse Bot

賽博龐克風格的健康管理 LINE Bot - 喝水提醒、久坐提醒、運動紀錄

![Dashboard Preview](https://img.shields.io/badge/style-cyberpunk-ff0080?style=for-the-badge)
![Python](https://img.shields.io/badge/python-3.9+-00f5ff?style=for-the-badge&logo=python)
![LINE](https://img.shields.io/badge/LINE-Bot-39ff14?style=for-the-badge&logo=line)

## ✨ 功能

- 💧 **喝水提醒** - 定時提醒補充水分
- 🧍 **久坐提醒** - 避免久坐，定時起身活動
- 🏃 **運動紀錄** - 記錄運動類型、時長、卡路里
- 📊 **統計儀表板** - 賽博龐克風格視覺化數據
- ⚙️ **彈性設定** - 自訂提醒間隔、勿擾時段

## 🏗️ 架構

```
┌─────────────────────────────────────────────────┐
│                GAS 排程觸發器                    │
│     (每 5-10 分鐘檢查，發送 LINE 提醒)           │
└──────────────────────┬──────────────────────────┘
                       ↓ LINE Push API
┌─────────────────────────────────────────────────┐
│                   LINE Bot                       │
│   用戶回報：已喝水 / 已起身 / 運動紀錄            │
└──────────────────────┬──────────────────────────┘
                       ↓ 寫入 / 讀取
┌─────────────────────────────────────────────────┐
│               Google Sheets                      │
│   water_log │ stand_log │ exercise_log │ settings│
└──────────────────────┬──────────────────────────┘
                       ↓
┌─────────────────────────────────────────────────┐
│              Railway (Flask)                     │
│   • LINE Webhook 處理                            │
│   • Dashboard 儀表板                             │
│   • API 端點                                     │
└─────────────────────────────────────────────────┘
```

## 🚀 部署步驟

### 1️⃣ 建立 Google Sheet

建立新的 Google Sheet，新增以下工作表：

**settings** (設定)
| water_interval | stand_interval | dnd_start | dnd_end | enabled |
|----------------|----------------|-----------|---------|---------|
| 60 | 45 | 22:00 | 08:00 | TRUE |

**water_log** (喝水紀錄)
| timestamp |
|-----------|

**stand_log** (起身紀錄)
| timestamp |
|-----------|

**exercise_log** (運動紀錄)
| timestamp | type | duration | calories |
|-----------|------|----------|----------|

### 2️⃣ 建立 Google Cloud 服務帳戶

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 建立新專案或選擇現有專案
3. 啟用 **Google Sheets API**
4. 建立服務帳戶 (IAM 與管理 > 服務帳戶)
5. 建立金鑰 (JSON 格式) 並下載
6. 將服務帳戶 Email 加入 Google Sheet 共用 (編輯者)

Neon Pulse Bot 設定完成！
已建立以下工作表：

• settings - 設定
• water_log - 喝水紀錄
• stand_log - 起身紀錄
• exercise_log - 運動紀錄

📋 你的 Spreadsheet ID:
17UKgUxXmTqzBdgZVkfHu4EV7zl_aJQdeXu_wMKu36ug

Spreadsheet ID: 17UKgUxXmTqzBdgZVkfHu4EV7zl_aJQdeXu_wMKu36ug

Spreadsheet URL: https://docs.google.com/spreadsheets/d/17UKgUxXmTqzBdgZVkfHu4EV7zl_aJQdeXu_wMKu36ug/edit

### 3️⃣ 建立 LINE Bot

1. 前往 [LINE Developers](https://developers.line.biz/)
2. 建立 Provider 和 Messaging API Channel
3. 記下 **Channel Secret** 和 **Channel Access Token**
4. 取得你的 **User ID** (Basic Settings > Your user ID)

### 4️⃣ 部署到 Railway

1. Fork 此專案到你的 GitHub
2. 前往 [Railway](https://railway.app/)
3. New Project > Deploy from GitHub repo
4. 選擇 `neon-pulse-bot` 專案
5. 設定環境變數：

| 變數名稱 | 值 |
|---------|-----|
| `LINE_CHANNEL_ACCESS_TOKEN` | LINE Bot 的 Channel Access Token |
| `LINE_CHANNEL_SECRET` | LINE Bot 的 Channel Secret |
| `SPREADSHEET_ID` | Google Sheet 的 ID (網址中的一長串字元) |
| `GOOGLE_CREDENTIALS_JSON` | 服務帳戶 JSON 金鑰 (整個 JSON 內容) |

6. 部署完成後，記下網址 (例如 `https://neon-pulse-bot-xxx.railway.app`)

### 5️⃣ 設定 LINE Webhook

1. 回到 LINE Developers Console
2. 進入你的 Channel > Messaging API
3. 設定 Webhook URL: `https://你的網址.railway.app/callback`
4. 開啟 **Use webhook**
5. 關閉 **Auto-reply messages** (自動回應訊息)

### 6️⃣ 設定 GAS 排程

1. 前往 [Google Apps Script](https://script.google.com/)
2. 建立新專案
3. 貼上 `gas/reminder.gs` 的內容
4. 設定指令碼屬性 (檔案 > 專案設定 > 指令碼屬性)：
   - `LINE_CHANNEL_ACCESS_TOKEN`: LINE Bot Token
   - `LINE_USER_ID`: 你的 LINE User ID
   - `SPREADSHEET_ID`: Google Sheet ID
5. 新增觸發器：
   - 函式: `checkAndSendReminders`
   - 時間驅動 > 分鐘計時器 > 每 5 分鐘

### 7️⃣ 設定 Rich Menu (選用)

使用 LINE Official Account Manager 或 API 上傳 Rich Menu 圖片

## 📱 使用方式

### LINE 指令

| 指令 | 功能 |
|------|------|
| `已喝水` | 記錄喝水 |
| `已起身` | 記錄起身 |
| `記錄運動` | 顯示運動輸入提示 |
| `跑步 30` | 記錄跑步 30 分鐘 |
| `今日統計` | 查看今日數據 |
| `設定` | 查看目前設定 |
| `喝水間隔 30` | 設定喝水提醒間隔 |
| `久坐間隔 60` | 設定久坐提醒間隔 |
| `勿擾 23:00-07:00` | 設定勿擾時段 |
| `開啟提醒` | 開啟提醒功能 |
| `關閉提醒` | 關閉提醒功能 |

### 支援的運動類型

跑步、走路、游泳、騎車、重訓、瑜伽、跳繩、籃球、羽球、桌球、其他

### 儀表板

訪問 `https://你的網址.railway.app/dashboard` 查看統計數據

## 🛠️ API 端點

| 端點 | 說明 |
|------|------|
| `GET /` | 儀表板首頁 |
| `GET /dashboard` | 儀表板 |
| `GET /api/today` | 今日統計 JSON |
| `GET /api/week` | 本週統計 JSON |
| `GET /api/settings` | 設定 JSON |
| `POST /callback` | LINE Webhook |
| `GET /health` | 健康檢查 |

## 📝 License

MIT License

---

Made with 💜 and ☕
