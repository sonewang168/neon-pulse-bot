/**
 * Neon Pulse Bot - Google Apps Script 提醒排程
 * 
 * 設定方式：
 * 1. 建立新的 Google Apps Script 專案
 * 2. 貼上此程式碼
 * 3. 設定 Script Properties (檔案 > 專案設定 > 指令碼屬性):
 *    - LINE_CHANNEL_ACCESS_TOKEN: LINE Bot 的 Channel Access Token
 *    - LINE_USER_ID: 你的 LINE User ID
 *    - SPREADSHEET_ID: Google Sheet 的 ID
 * 4. 設定觸發器 (觸發條件 > 新增觸發器):
 *    - 選擇函式: checkAndSendReminders
 *    - 選擇活動來源: 時間驅動
 *    - 選擇時間型觸發器類型: 分鐘計時器
 *    - 選擇間隔: 每 5 分鐘 或 每 10 分鐘
 */

// ===== 設定 =====
function getConfig() {
  const props = PropertiesService.getScriptProperties();
  return {
    LINE_TOKEN: props.getProperty('LINE_CHANNEL_ACCESS_TOKEN'),
    USER_ID: props.getProperty('LINE_USER_ID'),
    SPREADSHEET_ID: props.getProperty('SPREADSHEET_ID')
  };
}

// ===== 主函式：檢查並發送提醒 =====
function checkAndSendReminders() {
  const config = getConfig();
  const settings = getSettings(config.SPREADSHEET_ID);
  
  // 檢查是否啟用
  if (!settings.enabled || settings.enabled === 'FALSE') {
    console.log('提醒功能已關閉');
    return;
  }
  
  // 檢查勿擾時段
  if (isInDndTime(settings.dnd_start, settings.dnd_end)) {
    console.log('目前在勿擾時段');
    return;
  }
  
  const now = new Date();
  const lastWater = getLastLogTime(config.SPREADSHEET_ID, 'water_log');
  const lastStand = getLastLogTime(config.SPREADSHEET_ID, 'stand_log');
  
  // 檢查喝水提醒
  const waterInterval = (settings.water_interval || 60) * 60 * 1000; // 轉毫秒
  if (!lastWater || (now - lastWater) >= waterInterval) {
    sendWaterReminder(config.LINE_TOKEN, config.USER_ID);
    console.log('已發送喝水提醒');
  }
  
  // 檢查久坐提醒
  const standInterval = (settings.stand_interval || 45) * 60 * 1000;
  if (!lastStand || (now - lastStand) >= standInterval) {
    sendStandReminder(config.LINE_TOKEN, config.USER_ID);
    console.log('已發送久坐提醒');
  }
}

// ===== 取得設定 =====
function getSettings(spreadsheetId) {
  try {
    const ss = SpreadsheetApp.openById(spreadsheetId);
    const sheet = ss.getSheetByName('settings');
    const data = sheet.getDataRange().getValues();
    
    if (data.length < 2) {
      return {
        water_interval: 60,
        stand_interval: 45,
        dnd_start: '22:00',
        dnd_end: '08:00',
        enabled: true
      };
    }
    
    const headers = data[0];
    const values = data[1];
    const settings = {};
    
    headers.forEach((header, index) => {
      settings[header] = values[index];
    });
    
    return settings;
  } catch (e) {
    console.error('取得設定失敗:', e);
    return {
      water_interval: 60,
      stand_interval: 45,
      dnd_start: '22:00',
      dnd_end: '08:00',
      enabled: true
    };
  }
}

// ===== 取得最後記錄時間 =====
function getLastLogTime(spreadsheetId, sheetName) {
  try {
    const ss = SpreadsheetApp.openById(spreadsheetId);
    const sheet = ss.getSheetByName(sheetName);
    const lastRow = sheet.getLastRow();
    
    if (lastRow <= 1) return null; // 只有標題行
    
    const lastTime = sheet.getRange(lastRow, 1).getValue();
    return new Date(lastTime);
  } catch (e) {
    console.error('取得記錄時間失敗:', e);
    return null;
  }
}

// ===== 檢查是否在勿擾時段 =====
function isInDndTime(startStr, endStr) {
  if (!startStr || !endStr) return false;
  
  const now = new Date();
  const currentMinutes = now.getHours() * 60 + now.getMinutes();
  
  const [startH, startM] = startStr.split(':').map(Number);
  const [endH, endM] = endStr.split(':').map(Number);
  
  const startMinutes = startH * 60 + startM;
  const endMinutes = endH * 60 + endM;
  
  // 處理跨午夜的情況 (例如 22:00 - 08:00)
  if (startMinutes > endMinutes) {
    // 跨午夜：在開始時間之後 或 在結束時間之前
    return currentMinutes >= startMinutes || currentMinutes < endMinutes;
  } else {
    // 同一天：在開始和結束之間
    return currentMinutes >= startMinutes && currentMinutes < endMinutes;
  }
}

// ===== 發送喝水提醒 =====
function sendWaterReminder(token, userId) {
  const message = {
    type: 'flex',
    altText: '💧 喝水提醒',
    contents: {
      type: 'bubble',
      styles: {
        body: { backgroundColor: '#0a0a12' }
      },
      body: {
        type: 'box',
        layout: 'vertical',
        contents: [
          {
            type: 'text',
            text: '💧 喝水時間到！',
            weight: 'bold',
            size: 'xl',
            color: '#00f5ff'
          },
          {
            type: 'text',
            text: '記得補充水分，保持身體健康',
            color: '#888888',
            margin: 'md',
            wrap: true
          },
          {
            type: 'button',
            action: {
              type: 'message',
              label: '✅ 已喝水',
              text: '已喝水'
            },
            style: 'primary',
            color: '#00f5ff',
            margin: 'lg'
          }
        ]
      }
    }
  };
  
  sendLineMessage(token, userId, message);
}

// ===== 發送久坐提醒 =====
function sendStandReminder(token, userId) {
  const message = {
    type: 'flex',
    altText: '🧍 起身提醒',
    contents: {
      type: 'bubble',
      styles: {
        body: { backgroundColor: '#0a0a12' }
      },
      body: {
        type: 'box',
        layout: 'vertical',
        contents: [
          {
            type: 'text',
            text: '🧍 該起身動一動了！',
            weight: 'bold',
            size: 'xl',
            color: '#39ff14'
          },
          {
            type: 'text',
            text: '久坐傷身，站起來伸展一下吧',
            color: '#888888',
            margin: 'md',
            wrap: true
          },
          {
            type: 'button',
            action: {
              type: 'message',
              label: '✅ 已起身',
              text: '已起身'
            },
            style: 'primary',
            color: '#39ff14',
            margin: 'lg'
          }
        ]
      }
    }
  };
  
  sendLineMessage(token, userId, message);
}

// ===== 發送 LINE 訊息 =====
function sendLineMessage(token, userId, message) {
  const url = 'https://api.line.me/v2/bot/message/push';
  
  const payload = {
    to: userId,
    messages: [message]
  };
  
  const options = {
    method: 'post',
    contentType: 'application/json',
    headers: {
      'Authorization': 'Bearer ' + token
    },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  };
  
  try {
    const response = UrlFetchApp.fetch(url, options);
    const code = response.getResponseCode();
    
    if (code !== 200) {
      console.error('LINE API 錯誤:', code, response.getContentText());
    }
  } catch (e) {
    console.error('發送訊息失敗:', e);
  }
}

// ===== 測試函式 =====
function testWaterReminder() {
  const config = getConfig();
  sendWaterReminder(config.LINE_TOKEN, config.USER_ID);
  console.log('測試喝水提醒已發送');
}

function testStandReminder() {
  const config = getConfig();
  sendStandReminder(config.LINE_TOKEN, config.USER_ID);
  console.log('測試久坐提醒已發送');
}

function testGetSettings() {
  const config = getConfig();
  const settings = getSettings(config.SPREADSHEET_ID);
  console.log('目前設定:', JSON.stringify(settings, null, 2));
}
