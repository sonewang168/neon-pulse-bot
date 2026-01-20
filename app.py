"""
Neon Pulse Bot - 健康管理 LINE Bot
喝水提醒 + 久坐提醒 + 運動紀錄 + 儀表板
"""

import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, request, abort, render_template, jsonify
import gspread
from google.oauth2.service_account import Credentials
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    ReplyMessageRequest, TextMessage, FlexMessage, FlexContainer
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError

app = Flask(__name__)

# ===== 環境變數 =====
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')

# ===== LINE Bot 設定 =====
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ===== Google Sheets 設定 =====
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
TZ = ZoneInfo('Asia/Taipei')

def get_gspread_client():
    """取得 Google Sheets 客戶端"""
    creds_dict = json.loads(GOOGLE_CREDENTIALS_JSON)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(creds)

def get_sheet(sheet_name):
    """取得指定的工作表"""
    gc = get_gspread_client()
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)
    return spreadsheet.worksheet(sheet_name)

# ===== 運動類型與卡路里估算 =====
EXERCISE_TYPES = {
    '跑步': 10,      # 每分鐘卡路里
    '走路': 4,
    '游泳': 12,
    '騎車': 8,
    '重訓': 6,
    '瑜伽': 4,
    '跳繩': 12,
    '籃球': 8,
    '羽球': 7,
    '桌球': 5,
    '其他': 5
}

# ===== 資料記錄函數 =====
def log_water():
    """記錄喝水"""
    sheet = get_sheet('water_log')
    now = datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')
    sheet.append_row([now])
    return True

def log_stand():
    """記錄起身"""
    sheet = get_sheet('stand_log')
    now = datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')
    sheet.append_row([now])
    return True

def log_exercise(exercise_type, duration):
    """記錄運動"""
    sheet = get_sheet('exercise_log')
    now = datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')
    cal_per_min = EXERCISE_TYPES.get(exercise_type, 5)
    calories = duration * cal_per_min
    sheet.append_row([now, exercise_type, duration, calories])
    return calories

def get_settings():
    """取得設定"""
    sheet = get_sheet('settings')
    data = sheet.get_all_records()
    if data:
        return data[0]
    return {
        'water_interval': 60,
        'stand_interval': 45,
        'dnd_start': '22:00',
        'dnd_end': '08:00',
        'enabled': True
    }

def update_setting(key, value):
    """更新設定"""
    sheet = get_sheet('settings')
    headers = sheet.row_values(1)
    if key in headers:
        col = headers.index(key) + 1
        sheet.update_cell(2, col, value)
        return True
    return False

# ===== 統計函數 =====
def get_today_stats():
    """取得今日統計"""
    today = datetime.now(TZ).strftime('%Y-%m-%d')
    
    # 喝水次數
    water_sheet = get_sheet('water_log')
    water_data = water_sheet.get_all_values()[1:]  # 跳過標題
    water_count = sum(1 for row in water_data if row[0].startswith(today))
    
    # 起身次數
    stand_sheet = get_sheet('stand_log')
    stand_data = stand_sheet.get_all_values()[1:]
    stand_count = sum(1 for row in stand_data if row[0].startswith(today))
    
    # 運動統計
    exercise_sheet = get_sheet('exercise_log')
    exercise_data = exercise_sheet.get_all_values()[1:]
    today_exercises = [row for row in exercise_data if row[0].startswith(today)]
    exercise_minutes = sum(int(row[2]) for row in today_exercises) if today_exercises else 0
    exercise_calories = sum(int(row[3]) for row in today_exercises) if today_exercises else 0
    
    return {
        'date': today,
        'water_count': water_count,
        'stand_count': stand_count,
        'exercise_minutes': exercise_minutes,
        'exercise_calories': exercise_calories
    }

def get_week_stats():
    """取得本週統計"""
    today = datetime.now(TZ)
    week_start = today - timedelta(days=today.weekday())
    
    stats = []
    for i in range(7):
        day = week_start + timedelta(days=i)
        day_str = day.strftime('%Y-%m-%d')
        
        # 取得各工作表資料
        water_sheet = get_sheet('water_log')
        water_data = water_sheet.get_all_values()[1:]
        water_count = sum(1 for row in water_data if row[0].startswith(day_str))
        
        stand_sheet = get_sheet('stand_log')
        stand_data = stand_sheet.get_all_values()[1:]
        stand_count = sum(1 for row in stand_data if row[0].startswith(day_str))
        
        exercise_sheet = get_sheet('exercise_log')
        exercise_data = exercise_sheet.get_all_values()[1:]
        day_exercises = [row for row in exercise_data if row[0].startswith(day_str)]
        exercise_minutes = sum(int(row[2]) for row in day_exercises) if day_exercises else 0
        
        stats.append({
            'date': day_str,
            'weekday': ['一', '二', '三', '四', '五', '六', '日'][i],
            'water': water_count,
            'stand': stand_count,
            'exercise': exercise_minutes
        })
    
    return stats

# ===== LINE 訊息建構 =====
def create_stats_flex(stats):
    """建立統計 Flex Message"""
    flex_content = {
        "type": "bubble",
        "styles": {
            "body": {"backgroundColor": "#0a0a12"}
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": f"📊 {stats['date']} 統計",
                    "weight": "bold",
                    "size": "xl",
                    "color": "#00f5ff"
                },
                {"type": "separator", "margin": "md", "color": "#333355"},
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "lg",
                    "spacing": "md",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "💧 喝水", "color": "#00f5ff", "flex": 2},
                                {"type": "text", "text": f"{stats['water_count']} 次", "color": "#ffffff", "align": "end", "flex": 1}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "🧍 起身", "color": "#39ff14", "flex": 2},
                                {"type": "text", "text": f"{stats['stand_count']} 次", "color": "#ffffff", "align": "end", "flex": 1}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "🏃 運動", "color": "#ff6b00", "flex": 2},
                                {"type": "text", "text": f"{stats['exercise_minutes']} 分鐘", "color": "#ffffff", "align": "end", "flex": 1}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "🔥 消耗", "color": "#ff0080", "flex": 2},
                                {"type": "text", "text": f"{stats['exercise_calories']} 卡", "color": "#ffffff", "align": "end", "flex": 1}
                            ]
                        }
                    ]
                }
            ]
        }
    }
    return flex_content

def create_settings_flex(settings):
    """建立設定 Flex Message"""
    status = "🟢 開啟" if settings.get('enabled', True) else "🔴 關閉"
    flex_content = {
        "type": "bubble",
        "styles": {
            "body": {"backgroundColor": "#0a0a12"}
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "⚙️ 目前設定",
                    "weight": "bold",
                    "size": "xl",
                    "color": "#8888ff"
                },
                {"type": "separator", "margin": "md", "color": "#333355"},
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "lg",
                    "spacing": "md",
                    "contents": [
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "提醒狀態", "color": "#aaaaaa", "flex": 2},
                                {"type": "text", "text": status, "color": "#ffffff", "align": "end", "flex": 1}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "💧 喝水間隔", "color": "#00f5ff", "flex": 2},
                                {"type": "text", "text": f"{settings.get('water_interval', 60)} 分鐘", "color": "#ffffff", "align": "end", "flex": 1}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "🧍 久坐間隔", "color": "#39ff14", "flex": 2},
                                {"type": "text", "text": f"{settings.get('stand_interval', 45)} 分鐘", "color": "#ffffff", "align": "end", "flex": 1}
                            ]
                        },
                        {
                            "type": "box",
                            "layout": "horizontal",
                            "contents": [
                                {"type": "text", "text": "🌙 勿擾時段", "color": "#ff0080", "flex": 2},
                                {"type": "text", "text": f"{settings.get('dnd_start', '22:00')}-{settings.get('dnd_end', '08:00')}", "color": "#ffffff", "align": "end", "flex": 1}
                            ]
                        }
                    ]
                },
                {"type": "separator", "margin": "lg", "color": "#333355"},
                {
                    "type": "text",
                    "text": "輸入指令修改：\n• 喝水間隔 30\n• 久坐間隔 60\n• 勿擾 23:00-07:00\n• 開啟提醒 / 關閉提醒",
                    "color": "#666688",
                    "size": "sm",
                    "margin": "md",
                    "wrap": True
                }
            ]
        }
    }
    return flex_content

def create_exercise_prompt_flex():
    """建立運動輸入提示"""
    flex_content = {
        "type": "bubble",
        "styles": {
            "body": {"backgroundColor": "#0a0a12"}
        },
        "body": {
            "type": "box",
            "layout": "vertical",
            "contents": [
                {
                    "type": "text",
                    "text": "🏃 記錄運動",
                    "weight": "bold",
                    "size": "xl",
                    "color": "#ff6b00"
                },
                {"type": "separator", "margin": "md", "color": "#333355"},
                {
                    "type": "text",
                    "text": "請輸入運動類型和時間，例如：",
                    "color": "#aaaaaa",
                    "margin": "lg",
                    "wrap": True
                },
                {
                    "type": "box",
                    "layout": "vertical",
                    "margin": "md",
                    "spacing": "sm",
                    "contents": [
                        {"type": "text", "text": "• 跑步 30", "color": "#ffffff"},
                        {"type": "text", "text": "• 游泳 45", "color": "#ffffff"},
                        {"type": "text", "text": "• 重訓 60", "color": "#ffffff"}
                    ]
                },
                {"type": "separator", "margin": "lg", "color": "#333355"},
                {
                    "type": "text",
                    "text": "支援類型：跑步、走路、游泳、騎車、重訓、瑜伽、跳繩、籃球、羽球、桌球、其他",
                    "color": "#666688",
                    "size": "xs",
                    "margin": "md",
                    "wrap": True
                }
            ]
        }
    }
    return flex_content

# ===== LINE Webhook 處理 =====
@app.route('/callback', methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        
        reply_messages = []
        
        # 已喝水
        if text == '已喝水':
            log_water()
            stats = get_today_stats()
            reply_messages.append(TextMessage(text=f"💧 已記錄！今日第 {stats['water_count']} 杯"))
        
        # 已起身
        elif text == '已起身':
            log_stand()
            stats = get_today_stats()
            reply_messages.append(TextMessage(text=f"🧍 已記錄！今日第 {stats['stand_count']} 次"))
        
        # 記錄運動（顯示提示）
        elif text == '記錄運動':
            flex = create_exercise_prompt_flex()
            reply_messages.append(FlexMessage(
                alt_text='記錄運動',
                contents=FlexContainer.from_dict(flex)
            ))
        
        # 運動輸入 (格式：運動類型 分鐘數)
        elif any(text.startswith(ex) for ex in EXERCISE_TYPES.keys()):
            parts = text.split()
            if len(parts) >= 2 and parts[1].isdigit():
                exercise_type = parts[0]
                duration = int(parts[1])
                calories = log_exercise(exercise_type, duration)
                reply_messages.append(TextMessage(
                    text=f"🏃 已記錄 {exercise_type} {duration} 分鐘\n🔥 消耗約 {calories} 卡路里"
                ))
            else:
                reply_messages.append(TextMessage(text="格式錯誤，請輸入：運動類型 分鐘數\n例如：跑步 30"))
        
        # 今日統計
        elif text == '今日統計':
            stats = get_today_stats()
            flex = create_stats_flex(stats)
            reply_messages.append(FlexMessage(
                alt_text='今日統計',
                contents=FlexContainer.from_dict(flex)
            ))
        
        # 設定
        elif text == '設定':
            settings = get_settings()
            flex = create_settings_flex(settings)
            reply_messages.append(FlexMessage(
                alt_text='設定',
                contents=FlexContainer.from_dict(flex)
            ))
        
        # 修改喝水間隔
        elif text.startswith('喝水間隔'):
            parts = text.split()
            if len(parts) >= 2 and parts[1].isdigit():
                interval = int(parts[1])
                update_setting('water_interval', interval)
                reply_messages.append(TextMessage(text=f"✅ 喝水提醒間隔已設為 {interval} 分鐘"))
            else:
                reply_messages.append(TextMessage(text="格式錯誤，請輸入：喝水間隔 數字"))
        
        # 修改久坐間隔
        elif text.startswith('久坐間隔'):
            parts = text.split()
            if len(parts) >= 2 and parts[1].isdigit():
                interval = int(parts[1])
                update_setting('stand_interval', interval)
                reply_messages.append(TextMessage(text=f"✅ 久坐提醒間隔已設為 {interval} 分鐘"))
            else:
                reply_messages.append(TextMessage(text="格式錯誤，請輸入：久坐間隔 數字"))
        
        # 修改勿擾時段
        elif text.startswith('勿擾'):
            parts = text.replace('勿擾', '').strip().split('-')
            if len(parts) == 2:
                update_setting('dnd_start', parts[0].strip())
                update_setting('dnd_end', parts[1].strip())
                reply_messages.append(TextMessage(text=f"✅ 勿擾時段已設為 {parts[0].strip()} - {parts[1].strip()}"))
            else:
                reply_messages.append(TextMessage(text="格式錯誤，請輸入：勿擾 22:00-08:00"))
        
        # 開啟/關閉提醒
        elif text == '開啟提醒':
            update_setting('enabled', 'TRUE')
            reply_messages.append(TextMessage(text="✅ 提醒功能已開啟"))
        elif text == '關閉提醒':
            update_setting('enabled', 'FALSE')
            reply_messages.append(TextMessage(text="✅ 提醒功能已關閉"))
        
        # 未知指令
        else:
            reply_messages.append(TextMessage(
                text="🤖 指令列表：\n• 已喝水\n• 已起身\n• 記錄運動\n• 今日統計\n• 設定\n\n或使用下方選單操作"
            ))
        
        # 發送回覆
        if reply_messages:
            line_bot_api.reply_message(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=reply_messages
                )
            )

# ===== Dashboard API =====
@app.route('/api/today')
def api_today():
    """今日統計 API"""
    stats = get_today_stats()
    return jsonify(stats)

@app.route('/api/week')
def api_week():
    """本週統計 API"""
    stats = get_week_stats()
    return jsonify(stats)

@app.route('/api/settings')
def api_settings():
    """設定 API"""
    settings = get_settings()
    return jsonify(settings)

# ===== Dashboard 頁面 =====
@app.route('/dashboard')
def dashboard():
    """儀表板頁面"""
    return render_template('dashboard.html')

@app.route('/')
def index():
    """首頁導向儀表板"""
    return render_template('dashboard.html')

# ===== 健康檢查 =====
@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'neon-pulse-bot'})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
