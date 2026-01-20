"""
⚡ Neon Pulse Bot v8
新增：週報統計、連續達標、體重記錄
"""

import os
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import time
import threading
from flask import Flask, request, abort, render_template, jsonify
import gspread
from google.oauth2.service_account import Credentials
from linebot.v3 import WebhookHandler
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, PushMessageRequest,
    ReplyMessageRequest, TextMessage, FlexMessage, FlexContainer,
    QuickReply, QuickReplyItem, MessageAction
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from linebot.v3.exceptions import InvalidSignatureError
import requests

app = Flask(__name__)

# ===== 環境變數 =====
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET')
GOOGLE_CREDENTIALS_JSON = os.environ.get('GOOGLE_CREDENTIALS_JSON')
SPREADSHEET_ID = os.environ.get('SPREADSHEET_ID')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
OPENAI_API_KEY = os.environ.get('OPENAI_API_KEY')
LINE_USER_ID = os.environ.get('LINE_USER_ID')

# ===== LINE Bot =====
configuration = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ===== Google Sheets =====
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
TZ = ZoneInfo('Asia/Taipei')

_gspread_client = None
_client_time = 0
CACHE_TTL = 300

COLORS = {
    'bg': '#0a0a12', 'bg_light': '#1a1a2e', 'cyan': '#00f5ff',
    'green': '#39ff14', 'orange': '#ff6b00', 'pink': '#ff0080',
    'purple': '#8888ff', 'yellow': '#ffff00', 'gray': '#888888',
    'white': '#ffffff', 'gemini_bg': '#1a0a2e', 'gemini_accent': '#a855f7',
    'openai_bg': '#0a1a1a', 'openai_accent': '#10b981', 'gold': '#ffd700',
    'red': '#ff4444', 'blue': '#4a90d9'
}

EXERCISE_TYPES = {'跑步': 10, '走路': 4, '游泳': 12, '騎車': 8, '重訓': 6, '瑜伽': 4, '跳繩': 12, '籃球': 8, '羽球': 7, '桌球': 5, '其他': 5}

# 達標標準
GOALS = {'water': 8, 'stand': 6, 'exercise': 30}

def get_gspread_client():
    global _gspread_client, _client_time
    now = time.time()
    if _gspread_client and (now - _client_time) < CACHE_TTL:
        return _gspread_client
    creds = Credentials.from_service_account_info(json.loads(GOOGLE_CREDENTIALS_JSON), scopes=SCOPES)
    _gspread_client = gspread.authorize(creds)
    _client_time = now
    return _gspread_client

def get_sheet(name):
    return get_gspread_client().open_by_key(SPREADSHEET_ID).worksheet(name)

def get_today():
    return datetime.now(TZ).strftime('%Y-%m-%d')

def get_now():
    return datetime.now(TZ).strftime('%Y-%m-%d %H:%M:%S')

# ===== 讀取函式 =====
def read_today_count(log_type):
    today = get_today()
    data = get_sheet(f'{log_type}_log').get_all_values()[1:]
    return sum(1 for row in data if row and len(row) > 0 and row[0].startswith(today))

def read_today_stats():
    today = get_today()
    client = get_gspread_client()
    ss = client.open_by_key(SPREADSHEET_ID)
    
    water_data = ss.worksheet('water_log').get_all_values()[1:]
    stand_data = ss.worksheet('stand_log').get_all_values()[1:]
    exercise_data = ss.worksheet('exercise_log').get_all_values()[1:]
    
    water_count = sum(1 for r in water_data if r and len(r) > 0 and r[0].startswith(today))
    stand_count = sum(1 for r in stand_data if r and len(r) > 0 and r[0].startswith(today))
    
    today_exercises = [r for r in exercise_data if r and len(r) > 0 and r[0].startswith(today)]
    ex_minutes, ex_calories, ex_details = 0, 0, []
    
    for row in today_exercises:
        if len(row) >= 4:
            ex_type = row[1] if row[1] else '運動'
            minutes = int(row[2]) if row[2].isdigit() else 0
            calories = int(row[3]) if row[3].isdigit() else 0
            ex_minutes += minutes
            ex_calories += calories
            ex_details.append(f"{ex_type} {minutes}分鐘")
    
    return {
        'date': today, 'water_count': water_count, 'stand_count': stand_count,
        'exercise_minutes': ex_minutes, 'exercise_calories': ex_calories,
        'exercise_details': ex_details, 'exercise_count': len(today_exercises)
    }

def read_day_stats(date_str):
    """讀取特定日期的統計"""
    client = get_gspread_client()
    ss = client.open_by_key(SPREADSHEET_ID)
    
    water_data = ss.worksheet('water_log').get_all_values()[1:]
    stand_data = ss.worksheet('stand_log').get_all_values()[1:]
    exercise_data = ss.worksheet('exercise_log').get_all_values()[1:]
    
    water = sum(1 for r in water_data if r and len(r) > 0 and r[0].startswith(date_str))
    stand = sum(1 for r in stand_data if r and len(r) > 0 and r[0].startswith(date_str))
    ex_min = sum(int(r[2]) for r in exercise_data if r and len(r) > 2 and r[0].startswith(date_str) and r[2].isdigit())
    ex_cal = sum(int(r[3]) for r in exercise_data if r and len(r) > 3 and r[0].startswith(date_str) and r[3].isdigit())
    
    return {'water': water, 'stand': stand, 'exercise_minutes': ex_min, 'exercise_calories': ex_cal}

def read_week_stats():
    """讀取本週每日統計"""
    today = datetime.now(TZ)
    start = today - timedelta(days=today.weekday())
    client = get_gspread_client()
    ss = client.open_by_key(SPREADSHEET_ID)
    
    water = ss.worksheet('water_log').get_all_values()[1:]
    stand = ss.worksheet('stand_log').get_all_values()[1:]
    exercise = ss.worksheet('exercise_log').get_all_values()[1:]
    
    stats = []
    for i in range(7):
        d = (start + timedelta(days=i)).strftime('%Y-%m-%d')
        w = sum(1 for r in water if r and len(r) > 0 and r[0].startswith(d))
        s = sum(1 for r in stand if r and len(r) > 0 and r[0].startswith(d))
        e = sum(int(r[2]) for r in exercise if r and len(r) > 0 and r[0].startswith(d) and len(r) > 2 and r[2].isdigit())
        stats.append({'date': d, 'weekday': ['一','二','三','四','五','六','日'][i], 'water': w, 'stand': s, 'exercise': e})
    return stats

def read_week_summary():
    """讀取本週總結"""
    week_stats = read_week_stats()
    today = datetime.now(TZ)
    week_start = (today - timedelta(days=today.weekday())).strftime('%Y-%m-%d')
    week_end = (today - timedelta(days=today.weekday()) + timedelta(days=6)).strftime('%Y-%m-%d')
    
    total_water = sum(d['water'] for d in week_stats)
    total_stand = sum(d['stand'] for d in week_stats)
    total_exercise = sum(d['exercise'] for d in week_stats)
    
    # 計算達標天數
    days_water_ok = sum(1 for d in week_stats if d['water'] >= GOALS['water'])
    days_stand_ok = sum(1 for d in week_stats if d['stand'] >= GOALS['stand'])
    days_exercise_ok = sum(1 for d in week_stats if d['exercise'] >= GOALS['exercise'])
    days_all_ok = sum(1 for d in week_stats if d['water'] >= GOALS['water'] and d['stand'] >= GOALS['stand'] and d['exercise'] >= GOALS['exercise'])
    
    # 計算總熱量
    client = get_gspread_client()
    exercise_data = client.open_by_key(SPREADSHEET_ID).worksheet('exercise_log').get_all_values()[1:]
    total_calories = 0
    for row in exercise_data:
        if row and len(row) > 3 and row[0] >= week_start and row[0] <= week_end + " 23:59:59":
            if row[3].isdigit():
                total_calories += int(row[3])
    
    return {
        'week_start': week_start,
        'week_end': week_end,
        'total_water': total_water,
        'total_stand': total_stand,
        'total_exercise': total_exercise,
        'total_calories': total_calories,
        'days_water_ok': days_water_ok,
        'days_stand_ok': days_stand_ok,
        'days_exercise_ok': days_exercise_ok,
        'days_all_ok': days_all_ok,
        'daily_stats': week_stats
    }

def calculate_streak():
    """計算連續達標天數（只檢查最近 30 天加速）"""
    today = datetime.now(TZ)
    client = get_gspread_client()
    ss = client.open_by_key(SPREADSHEET_ID)
    
    # 只讀取最近 35 天的資料
    cutoff = (today - timedelta(days=35)).strftime('%Y-%m-%d')
    
    water_data = ss.worksheet('water_log').get_all_values()[1:]
    stand_data = ss.worksheet('stand_log').get_all_values()[1:]
    exercise_data = ss.worksheet('exercise_log').get_all_values()[1:]
    
    # 過濾只保留近期資料
    water_data = [r for r in water_data if r and len(r) > 0 and r[0] >= cutoff]
    stand_data = [r for r in stand_data if r and len(r) > 0 and r[0] >= cutoff]
    exercise_data = [r for r in exercise_data if r and len(r) > 0 and r[0] >= cutoff]
    
    streak = 0
    check_date = today
    
    # 最多檢查 30 天
    for _ in range(30):
        d = check_date.strftime('%Y-%m-%d')
        
        water = sum(1 for r in water_data if r[0].startswith(d))
        stand = sum(1 for r in stand_data if r[0].startswith(d))
        exercise = sum(int(r[2]) for r in exercise_data if r[0].startswith(d) and len(r) > 2 and r[2].isdigit())
        
        # 檢查是否達標
        if water >= GOALS['water'] and stand >= GOALS['stand'] and exercise >= GOALS['exercise']:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            # 如果是今天還沒達標，不算中斷
            if check_date.date() == today.date():
                check_date -= timedelta(days=1)
                continue
            break
    
    return streak

def read_settings():
    data = get_sheet('settings').get_all_records()
    return data[0] if data else {'water_interval': 60, 'stand_interval': 45, 'dnd_start': '22:00', 'dnd_end': '08:00', 'enabled': True}

# ===== 體重相關 =====
def write_weight(weight):
    """記錄體重"""
    try:
        sheet = get_sheet('weight_log')
    except:
        # 如果工作表不存在，建立它
        ss = get_gspread_client().open_by_key(SPREADSHEET_ID)
        sheet = ss.add_worksheet(title='weight_log', rows=1000, cols=2)
        sheet.append_row(['時間', '體重(kg)'])
    
    sheet.append_row([get_now(), weight])
    return weight

def read_weight_history(days=30):
    """讀取體重歷史"""
    try:
        data = get_sheet('weight_log').get_all_values()[1:]
    except:
        return []
    
    cutoff = (datetime.now(TZ) - timedelta(days=days)).strftime('%Y-%m-%d')
    history = []
    
    for row in data:
        if row and len(row) >= 2 and row[0] >= cutoff:
            try:
                weight = float(row[1])
                date = row[0][:10]
                history.append({'date': date, 'weight': weight, 'time': row[0]})
            except:
                pass
    
    return history

def get_weight_stats():
    """取得體重統計"""
    history = read_weight_history(30)
    
    if not history:
        return None
    
    latest = history[-1]
    
    # 找最近 7 天的記錄
    week_ago = (datetime.now(TZ) - timedelta(days=7)).strftime('%Y-%m-%d')
    week_records = [h for h in history if h['date'] >= week_ago]
    
    # 找 30 天前的記錄
    month_ago = (datetime.now(TZ) - timedelta(days=30)).strftime('%Y-%m-%d')
    month_start_records = [h for h in history if h['date'][:10] == month_ago[:10]]
    
    stats = {
        'current': latest['weight'],
        'current_date': latest['date'],
        'records_count': len(history)
    }
    
    # 計算週變化
    if len(week_records) >= 2:
        stats['week_change'] = round(latest['weight'] - week_records[0]['weight'], 1)
    else:
        stats['week_change'] = None
    
    # 計算月變化
    if month_start_records:
        stats['month_change'] = round(latest['weight'] - month_start_records[0]['weight'], 1)
    elif len(history) >= 2:
        stats['month_change'] = round(latest['weight'] - history[0]['weight'], 1)
    else:
        stats['month_change'] = None
    
    # 最高最低
    weights = [h['weight'] for h in history]
    stats['max'] = max(weights)
    stats['min'] = min(weights)
    
    return stats

# ===== 寫入函式（優化版）=====
def write_water():
    """新增喝水記錄（快速版）"""
    today = get_today()
    sheet = get_sheet('water_log')
    
    # 先讀取今日數量
    data = sheet.get_all_values()[1:]
    count = sum(1 for r in data if r and len(r) > 0 and r[0].startswith(today))
    
    # 寫入新記錄
    sheet.append_row([get_now()])
    
    # 返回新數量（不重新讀取）
    return count + 1

def write_stand():
    """新增起身記錄（快速版）"""
    today = get_today()
    sheet = get_sheet('stand_log')
    
    # 先讀取今日數量
    data = sheet.get_all_values()[1:]
    count = sum(1 for r in data if r and len(r) > 0 and r[0].startswith(today))
    
    # 寫入新記錄
    sheet.append_row([get_now()])
    
    return count + 1

def write_exercise(ex_type, duration):
    cal = duration * EXERCISE_TYPES.get(ex_type, 5)
    get_sheet('exercise_log').append_row([get_now(), ex_type, duration, cal])
    return cal

def write_setting(key, value):
    sheet = get_sheet('settings')
    headers = sheet.row_values(1)
    if key in headers:
        sheet.update_cell(2, headers.index(key) + 1, value)
        return True
    return False

def set_count(log_type, target):
    today = get_today()
    sheet = get_sheet(f'{log_type}_log')
    data = sheet.get_all_values()
    
    today_rows = []
    for i, row in enumerate(data):
        if i == 0:
            continue
        if row and len(row) > 0 and row[0].startswith(today):
            today_rows.append(i + 1)
    
    current = len(today_rows)
    
    if target > current:
        now = get_now()
        for _ in range(target - current):
            sheet.append_row([now])
    elif target < current:
        for row_num in sorted(today_rows[target:], reverse=True):
            try:
                sheet.delete_rows(row_num)
            except:
                pass
    return target

def delete_last_exercise():
    today = get_today()
    sheet = get_sheet('exercise_log')
    data = sheet.get_all_values()
    
    last_row, last_info = None, None
    for i, row in enumerate(data):
        if i == 0:
            continue
        if row and len(row) > 0 and row[0].startswith(today):
            last_row = i + 1
            last_info = row
    
    if last_row:
        sheet.delete_rows(last_row)
        return last_info
    return None

def clear_today_exercise():
    today = get_today()
    sheet = get_sheet('exercise_log')
    data = sheet.get_all_values()
    
    today_rows = []
    for i, row in enumerate(data):
        if i == 0:
            continue
        if row and len(row) > 0 and row[0].startswith(today):
            today_rows.append(i + 1)
    
    count = len(today_rows)
    for row_num in sorted(today_rows, reverse=True):
        try:
            sheet.delete_rows(row_num)
        except:
            pass
    return count

# ===== AI 分析 =====
def get_gemini(action, count, extra=""):
    if not GEMINI_API_KEY:
        print("[Gemini] No API key!")
        return None
    prompts = {
        'water': f"用戶今天喝了 {count} 杯水。用繁體中文給予健康建議和鼓勵。語氣活潑正向。250字內，完整段落，不要條列式。",
        'stand': f"用戶今天起身了 {count} 次。用繁體中文說明定時起身的益處並鼓勵。語氣活潑正向。250字內，完整段落，不要條列式。",
        'exercise': f"用戶完成運動：{extra}。用繁體中文分析運動效益並鼓勵。語氣活潑正向。250字內，完整段落，不要條列式。",
        'daily': f"今日健康數據：{extra}。用繁體中文總結今日表現並給明日建議。語氣溫暖鼓勵。280字內，完整段落，不要條列式。",
        'weekly': f"本週健康數據：{extra}。用繁體中文總結本週表現，分析趨勢，給下週建議。語氣溫暖鼓勵。300字內，完整段落，不要條列式。",
        'weight': f"用戶體重記錄：{extra}。用繁體中文給予體重管理建議，語氣專業親切。200字內，完整段落，不要條列式。"
    }
    try:
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}",
            json={"contents": [{"parts": [{"text": prompts.get(action, prompts['daily'])}]}], "generationConfig": {"temperature": 0.8, "maxOutputTokens": 400}}, timeout=15)
        if r.status_code == 200:
            t = r.json().get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')
            return t.strip()[:350] if t else None
        else:
            print(f"[Gemini] API error: {r.status_code} - {r.text[:200]}")
    except Exception as e:
        print(f"[Gemini] Exception: {e}")
    return None

def get_openai(action, count, extra=""):
    if not OPENAI_API_KEY:
        print("[OpenAI] No API key!")
        return None
    prompts = {
        'water': f"用戶今天喝了 {count} 杯水。用繁體中文從科學或中醫角度給予建議。語氣專業親切。250字內，完整段落，不要條列式。",
        'stand': f"用戶今天起身了 {count} 次。用繁體中文從人體工學角度給予建議。語氣專業親切。250字內，完整段落，不要條列式。",
        'exercise': f"用戶完成運動：{extra}。用繁體中文從運動科學角度分析效益。語氣專業親切。250字內，完整段落，不要條列式。",
        'daily': f"今日健康數據：{extra}。用繁體中文從健康管理角度評估並建議改善。語氣專業溫和。280字內，完整段落，不要條列式。",
        'weekly': f"本週健康數據：{extra}。用繁體中文從健康管理角度分析本週表現，指出改善方向。語氣專業溫和。300字內，完整段落，不要條列式。",
        'weight': f"用戶體重記錄：{extra}。用繁體中文從營養學角度給予體重管理建議。語氣專業親切。200字內，完整段落，不要條列式。"
    }
    try:
        r = requests.post("https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompts.get(action, prompts['daily'])}], "max_tokens": 400, "temperature": 0.8}, timeout=15)
        if r.status_code == 200:
            t = r.json().get('choices', [{}])[0].get('message', {}).get('content', '')
            return t.strip()[:350] if t else None
        else:
            print(f"[OpenAI] API error: {r.status_code} - {r.text[:200]}")
    except Exception as e:
        print(f"[OpenAI] Exception: {e}")
    return None

def flex_ai(gemini, openai):
    bubbles = []
    if gemini:
        bubbles.append({"type": "bubble", "size": "mega", "styles": {"body": {"backgroundColor": COLORS['gemini_bg']}},
            "body": {"type": "box", "layout": "vertical", "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "✨", "size": "xl", "flex": 0},
                    {"type": "text", "text": "Gemini 分析", "size": "lg", "weight": "bold", "color": COLORS['gemini_accent'], "margin": "sm"}]},
                {"type": "separator", "margin": "md", "color": COLORS['gemini_accent']},
                {"type": "text", "text": gemini, "size": "sm", "color": COLORS['white'], "margin": "lg", "wrap": True}]}})
    if openai:
        bubbles.append({"type": "bubble", "size": "mega", "styles": {"body": {"backgroundColor": COLORS['openai_bg']}},
            "body": {"type": "box", "layout": "vertical", "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "🤖", "size": "xl", "flex": 0},
                    {"type": "text", "text": "OpenAI 分析", "size": "lg", "weight": "bold", "color": COLORS['openai_accent'], "margin": "sm"}]},
                {"type": "separator", "margin": "md", "color": COLORS['openai_accent']},
                {"type": "text", "text": openai, "size": "sm", "color": COLORS['white'], "margin": "lg", "wrap": True}]}})
    return {"type": "carousel", "contents": bubbles} if bubbles else None

def send_ai_analysis_async(user_id, action, count, extra=""):
    """背景執行 AI 分析並推送"""
    print(f"[AI] Starting async analysis: action={action}, user={user_id[:10]}...")
    
    def task():
        try:
            print(f"[AI] Calling Gemini...")
            gemini = get_gemini(action, count, extra)
            print(f"[AI] Gemini result: {gemini[:50] if gemini else 'None'}...")
            
            print(f"[AI] Calling OpenAI...")
            openai = get_openai(action, count, extra)
            print(f"[AI] OpenAI result: {openai[:50] if openai else 'None'}...")
            
            af = flex_ai(gemini, openai)
            if af and user_id:
                print(f"[AI] Sending push message...")
                with ApiClient(configuration) as api:
                    MessagingApi(api).push_message(PushMessageRequest(
                        to=user_id,
                        messages=[FlexMessage(alt_text='🤖 AI 分析', contents=FlexContainer.from_dict(af))]
                    ))
                print(f"[AI] Push message sent successfully!")
            else:
                print(f"[AI] No AI result or no user_id. af={af is not None}, user_id={user_id is not None}")
        except Exception as e:
            print(f"[AI] Error: {e}")
            import traceback
            traceback.print_exc()
    
    thread = threading.Thread(target=task)
    thread.start()

# ===== Quick Reply =====
def qr(items):
    return QuickReply(items=[QuickReplyItem(action=MessageAction(label=i['label'], text=i['text'])) for i in items])

QR_MAIN = [{'label': '💧 已喝水', 'text': '已喝水'}, {'label': '🧍 已起身', 'text': '已起身'}, {'label': '🏃 記錄運動', 'text': '記錄運動'}, {'label': '📊 今日統計', 'text': '今日統計'}, {'label': '✏️ 修改', 'text': '修改'}]
QR_WATER = [{'label': '💧 再一杯', 'text': '已喝水'}, {'label': '✏️ 修改杯數', 'text': '修改喝水'}, {'label': '📊 統計', 'text': '今日統計'}]
QR_STAND = [{'label': '🧍 再起身', 'text': '已起身'}, {'label': '✏️ 修改次數', 'text': '修改起身'}, {'label': '📊 統計', 'text': '今日統計'}]
QR_EX = [{'label': '🏃 再記一筆', 'text': '記錄運動'}, {'label': '📊 統計', 'text': '今日統計'}, {'label': '💧 喝水', 'text': '已喝水'}]
QR_EX_TYPE = [{'label': '🏃 跑步', 'text': '跑步'}, {'label': '🚶 走路', 'text': '走路'}, {'label': '🏊 游泳', 'text': '游泳'}, {'label': '🚴 騎車', 'text': '騎車'}, {'label': '🏋️ 重訓', 'text': '重訓'}, {'label': '🧘 瑜伽', 'text': '瑜伽'}]
QR_MOD = [{'label': '💧 改喝水', 'text': '修改喝水'}, {'label': '🧍 改起身', 'text': '修改起身'}, {'label': '🏃 改運動', 'text': '修改運動'}, {'label': '↩️ 返回', 'text': '選單'}]
QR_MOD_EX = [{'label': '🗑️ 刪除最後', 'text': '刪除運動'}, {'label': '🧹 清空全部', 'text': '清空運動'}, {'label': '↩️ 返回', 'text': '修改'}]
QR_STATS = [{'label': '📊 今日', 'text': '今日統計'}, {'label': '📅 本週', 'text': '週報'}, {'label': '⚖️ 體重', 'text': '體重紀錄'}, {'label': '🔥 連續達標', 'text': '連續達標'}]
QR_WEIGHT = [{'label': '⚖️ 記錄體重', 'text': '記錄體重'}, {'label': '📊 體重紀錄', 'text': '體重紀錄'}, {'label': '↩️ 返回', 'text': '選單'}]

# ===== Flex Message =====
def flex_water(c):
    p = min(c * 12.5, 100)
    return {"type": "bubble", "size": "kilo", "styles": {"body": {"backgroundColor": COLORS['bg']}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "box", "layout": "horizontal", "alignItems": "center", "contents": [
                {"type": "text", "text": "💧", "size": "3xl", "flex": 0},
                {"type": "box", "layout": "vertical", "paddingStart": "md", "contents": [
                    {"type": "text", "text": "補水成功！", "size": "xl", "weight": "bold", "color": COLORS['cyan']},
                    {"type": "text", "text": f"今日第 {c} 杯", "size": "sm", "color": COLORS['gray']}]}]},
            {"type": "box", "layout": "vertical", "margin": "lg", "contents": [
                {"type": "box", "layout": "horizontal", "backgroundColor": COLORS['bg_light'], "cornerRadius": "4px", "contents": [
                    {"type": "box", "layout": "vertical", "contents": [], "width": f"{p}%", "backgroundColor": COLORS['cyan'], "height": "8px", "cornerRadius": "4px"},
                    {"type": "box", "layout": "vertical", "contents": [], "height": "8px"}]},
                {"type": "text", "text": f"目標 8 杯 ({min(c,8)}/8)", "size": "xs", "color": COLORS['gray'], "align": "end", "margin": "sm"}]}]}}

def flex_stand(c):
    m = ["做得好！", "保持活力！", "繼續動起來！", "太棒了！", "健康滿分！"][c % 5]
    return {"type": "bubble", "size": "kilo", "styles": {"body": {"backgroundColor": COLORS['bg']}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "box", "layout": "horizontal", "alignItems": "center", "contents": [
                {"type": "text", "text": "🧍", "size": "3xl", "flex": 0},
                {"type": "box", "layout": "vertical", "paddingStart": "md", "contents": [
                    {"type": "text", "text": m, "size": "xl", "weight": "bold", "color": COLORS['green']},
                    {"type": "text", "text": f"今日第 {c} 次起身", "size": "sm", "color": COLORS['gray']}]}]},
            {"type": "separator", "margin": "lg", "color": "#333355"},
            {"type": "text", "text": "💡 伸展手臂和肩膀吧！", "size": "sm", "color": COLORS['gray'], "margin": "lg"}]}}

def flex_exercise(t, d, cal):
    return {"type": "bubble", "size": "kilo", "styles": {"body": {"backgroundColor": COLORS['bg']}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "box", "layout": "horizontal", "alignItems": "center", "contents": [
                {"type": "text", "text": "🏃", "size": "3xl", "flex": 0},
                {"type": "box", "layout": "vertical", "paddingStart": "md", "contents": [
                    {"type": "text", "text": "運動紀錄完成！", "size": "xl", "weight": "bold", "color": COLORS['orange']},
                    {"type": "text", "text": f"{t} {d} 分鐘", "size": "sm", "color": COLORS['gray']}]}]},
            {"type": "separator", "margin": "lg", "color": "#333355"},
            {"type": "box", "layout": "horizontal", "margin": "lg", "contents": [
                {"type": "text", "text": "🔥 消耗熱量", "size": "sm", "color": COLORS['gray']},
                {"type": "text", "text": f"{cal} kcal", "size": "lg", "weight": "bold", "color": COLORS['pink'], "align": "end"}]}]}}

def flex_modify_menu():
    return {"type": "bubble", "size": "kilo", "styles": {"body": {"backgroundColor": COLORS['bg']}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": "✏️ 修改紀錄", "weight": "bold", "size": "xl", "color": COLORS['yellow']},
            {"type": "separator", "margin": "md", "color": "#333355"},
            {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm", "contents": [
                {"type": "text", "text": "💧 修改喝水 5 → 設為5杯", "color": COLORS['cyan'], "size": "sm"},
                {"type": "text", "text": "🧍 修改起身 3 → 設為3次", "color": COLORS['green'], "size": "sm"},
                {"type": "text", "text": "🏃 修改運動 → 刪除/清空", "color": COLORS['orange'], "size": "sm"}]},
            {"type": "separator", "margin": "lg", "color": "#333355"},
            {"type": "text", "text": "點選下方按鈕操作", "color": COLORS['gray'], "size": "xs", "margin": "md"}]}}

def flex_modify_prompt(t, cur):
    n, e, c, u = ("喝水", "💧", COLORS['cyan'], "杯") if t == "water" else ("起身", "🧍", COLORS['green'], "次")
    return {"type": "bubble", "size": "kilo", "styles": {"body": {"backgroundColor": COLORS['bg']}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": f"{e} 修改{n}次數", "weight": "bold", "size": "lg", "color": c},
            {"type": "separator", "margin": "md", "color": "#333355"},
            {"type": "text", "text": f"目前：{cur} {u}", "color": COLORS['white'], "margin": "lg", "size": "lg"},
            {"type": "text", "text": f"請輸入新數字\n例如：修改{n} 5", "color": COLORS['gray'], "margin": "md", "size": "sm", "wrap": True}]}}

def flex_modify_exercise(stats):
    details = stats.get('exercise_details', [])
    details_text = "、".join(details) if details else "無運動紀錄"
    return {"type": "bubble", "size": "kilo", "styles": {"body": {"backgroundColor": COLORS['bg']}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": "🏃 修改運動紀錄", "weight": "bold", "size": "lg", "color": COLORS['orange']},
            {"type": "separator", "margin": "md", "color": "#333355"},
            {"type": "text", "text": f"今日運動：{stats.get('exercise_count', 0)} 筆", "color": COLORS['white'], "margin": "lg", "size": "md"},
            {"type": "text", "text": f"📝 {details_text}", "color": COLORS['gray'], "margin": "sm", "size": "sm", "wrap": True},
            {"type": "text", "text": f"🔥 {stats.get('exercise_calories', 0)} kcal", "color": COLORS['pink'], "margin": "sm", "size": "sm"},
            {"type": "separator", "margin": "lg", "color": "#333355"},
            {"type": "text", "text": "選擇：刪除最後 / 清空全部", "color": COLORS['gray'], "size": "xs", "margin": "md"}]}}

def flex_stats(s, streak=0):
    water_count = s.get('water_count', 0) or 0
    stand_count = s.get('stand_count', 0) or 0
    exercise_minutes = s.get('exercise_minutes', 0) or 0
    exercise_calories = s.get('exercise_calories', 0) or 0
    date_str = s.get('date', '今日') or '今日'
    
    wp = min(water_count/8*100, 100)
    sp = min(stand_count/6*100, 100)
    ep = min(exercise_minutes/30*100, 100)
    streak_text = f"🔥 連續 {streak} 天" if streak and streak > 0 else "點擊「連續達標」查看"
    return {"type": "bubble", "size": "mega", "styles": {"body": {"backgroundColor": COLORS['bg']}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "box", "layout": "horizontal", "contents": [
                {"type": "text", "text": f"📊 {date_str}", "weight": "bold", "size": "xl", "color": COLORS['cyan'], "flex": 3},
                {"type": "text", "text": streak_text, "size": "xs", "color": COLORS['orange'], "align": "end", "flex": 2}]},
            {"type": "separator", "margin": "md", "color": "#333355"},
            {"type": "box", "layout": "vertical", "margin": "lg", "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "💧 喝水", "color": COLORS['cyan']},
                    {"type": "text", "text": f"{water_count} / 8 杯", "color": COLORS['white'], "align": "end"}]},
                {"type": "box", "layout": "horizontal", "margin": "sm", "backgroundColor": COLORS['bg_light'], "cornerRadius": "3px", "contents": [
                    {"type": "box", "layout": "vertical", "contents": [], "width": f"{wp}%", "backgroundColor": COLORS['cyan'], "height": "6px", "cornerRadius": "3px"},
                    {"type": "box", "layout": "vertical", "contents": [], "height": "6px"}]}]},
            {"type": "box", "layout": "vertical", "margin": "lg", "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "🧍 起身", "color": COLORS['green']},
                    {"type": "text", "text": f"{stand_count} / 6 次", "color": COLORS['white'], "align": "end"}]},
                {"type": "box", "layout": "horizontal", "margin": "sm", "backgroundColor": COLORS['bg_light'], "cornerRadius": "3px", "contents": [
                    {"type": "box", "layout": "vertical", "contents": [], "width": f"{sp}%", "backgroundColor": COLORS['green'], "height": "6px", "cornerRadius": "3px"},
                    {"type": "box", "layout": "vertical", "contents": [], "height": "6px"}]}]},
            {"type": "box", "layout": "vertical", "margin": "lg", "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "🏃 運動", "color": COLORS['orange']},
                    {"type": "text", "text": f"{exercise_minutes} / 30 分鐘", "color": COLORS['white'], "align": "end"}]},
                {"type": "box", "layout": "horizontal", "margin": "sm", "backgroundColor": COLORS['bg_light'], "cornerRadius": "3px", "contents": [
                    {"type": "box", "layout": "vertical", "contents": [], "width": f"{ep}%", "backgroundColor": COLORS['orange'], "height": "6px", "cornerRadius": "3px"},
                    {"type": "box", "layout": "vertical", "contents": [], "height": "6px"}]}]},
            {"type": "separator", "margin": "lg", "color": "#333355"},
            {"type": "box", "layout": "horizontal", "margin": "lg", "contents": [
                {"type": "text", "text": "🔥 消耗熱量", "color": COLORS['gray']},
                {"type": "text", "text": f"{exercise_calories} kcal", "color": COLORS['pink'], "size": "lg", "weight": "bold", "align": "end"}]}]}}

def flex_week_report(summary):
    """週報 Flex"""
    daily = summary.get('daily_stats', [])
    
    # 建立每日進度條
    day_rows = []
    for d in daily:
        weekday = d.get('weekday', '-') or '-'
        water = d.get('water', 0) or 0
        stand = d.get('stand', 0) or 0
        exercise = d.get('exercise', 0) or 0
        
        wo = "✅" if water >= GOALS['water'] else "⚠️"
        so = "✅" if stand >= GOALS['stand'] else "⚠️"
        eo = "✅" if exercise >= GOALS['exercise'] else "⚠️"
        day_rows.append({
            "type": "box", "layout": "horizontal", "contents": [
                {"type": "text", "text": str(weekday), "size": "sm", "color": COLORS['gray'], "flex": 1},
                {"type": "text", "text": f"{wo}{water}", "size": "sm", "color": COLORS['cyan'], "flex": 2, "align": "center"},
                {"type": "text", "text": f"{so}{stand}", "size": "sm", "color": COLORS['green'], "flex": 2, "align": "center"},
                {"type": "text", "text": f"{eo}{exercise}m", "size": "sm", "color": COLORS['orange'], "flex": 2, "align": "center"}
            ]
        })
    
    week_start = summary.get('week_start', '')[:5] if summary.get('week_start') else '-'
    week_end = summary.get('week_end', '')[5:] if summary.get('week_end') else '-'
    total_water = summary.get('total_water', 0) or 0
    total_stand = summary.get('total_stand', 0) or 0
    total_exercise = summary.get('total_exercise', 0) or 0
    total_calories = summary.get('total_calories', 0) or 0
    days_water_ok = summary.get('days_water_ok', 0) or 0
    days_stand_ok = summary.get('days_stand_ok', 0) or 0
    days_exercise_ok = summary.get('days_exercise_ok', 0) or 0
    days_all_ok = summary.get('days_all_ok', 0) or 0
    
    return {"type": "bubble", "size": "mega", "styles": {"body": {"backgroundColor": COLORS['bg']}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": f"📅 週報 {week_start}~{week_end}", "weight": "bold", "size": "lg", "color": COLORS['gold']},
            {"type": "separator", "margin": "md", "color": COLORS['gold']},
            # 表頭
            {"type": "box", "layout": "horizontal", "margin": "lg", "contents": [
                {"type": "text", "text": "日", "size": "xs", "color": COLORS['gray'], "flex": 1},
                {"type": "text", "text": "💧水", "size": "xs", "color": COLORS['cyan'], "flex": 2, "align": "center"},
                {"type": "text", "text": "🧍站", "size": "xs", "color": COLORS['green'], "flex": 2, "align": "center"},
                {"type": "text", "text": "🏃動", "size": "xs", "color": COLORS['orange'], "flex": 2, "align": "center"}
            ]},
            {"type": "box", "layout": "vertical", "margin": "sm", "spacing": "xs", "contents": day_rows},
            {"type": "separator", "margin": "lg", "color": "#333355"},
            # 總計
            {"type": "box", "layout": "vertical", "margin": "md", "spacing": "sm", "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "本週總計", "size": "sm", "color": COLORS['gray'], "flex": 2},
                    {"type": "text", "text": f"💧{total_water}杯 🧍{total_stand}次 🏃{total_exercise}分", "size": "sm", "color": COLORS['white'], "flex": 4, "align": "end"}
                ]},
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "達標天數", "size": "sm", "color": COLORS['gray'], "flex": 2},
                    {"type": "text", "text": f"💧{days_water_ok}天 🧍{days_stand_ok}天 🏃{days_exercise_ok}天", "size": "sm", "color": COLORS['white'], "flex": 4, "align": "end"}
                ]},
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "🔥 總消耗熱量", "size": "sm", "color": COLORS['pink'], "flex": 2},
                    {"type": "text", "text": f"{total_calories} kcal", "size": "md", "weight": "bold", "color": COLORS['pink'], "flex": 2, "align": "end"}
                ]}
            ]},
            {"type": "separator", "margin": "md", "color": "#333355"},
            {"type": "text", "text": f"🏆 全項達標：{days_all_ok} 天", "size": "sm", "color": COLORS['gold'], "margin": "md", "align": "center"}
        ]}}

def flex_streak(streak):
    """連續達標 Flex"""
    if streak >= 30:
        emoji, msg, color = "🏆", "傳奇等級！", COLORS['gold']
    elif streak >= 14:
        emoji, msg, color = "🥇", "超級厲害！", COLORS['orange']
    elif streak >= 7:
        emoji, msg, color = "🥈", "一週達成！", COLORS['cyan']
    elif streak >= 3:
        emoji, msg, color = "🥉", "持續進步中！", COLORS['green']
    elif streak >= 1:
        emoji, msg, color = "🌱", "好的開始！", COLORS['green']
    else:
        emoji, msg, color = "💪", "今天開始累積！", COLORS['gray']
    
    return {"type": "bubble", "size": "kilo", "styles": {"body": {"backgroundColor": COLORS['bg']}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": f"{emoji} 連續達標", "weight": "bold", "size": "xl", "color": color},
            {"type": "separator", "margin": "md", "color": "#333355"},
            {"type": "text", "text": f"{streak}", "size": "5xl", "weight": "bold", "color": color, "align": "center", "margin": "lg"},
            {"type": "text", "text": "天", "size": "xl", "color": COLORS['gray'], "align": "center"},
            {"type": "separator", "margin": "lg", "color": "#333355"},
            {"type": "text", "text": msg, "size": "md", "color": color, "align": "center", "margin": "md"},
            {"type": "text", "text": "達標標準：喝水8杯 + 起身6次 + 運動30分", "size": "xs", "color": COLORS['gray'], "align": "center", "margin": "md", "wrap": True}
        ]}}

def flex_weight(stats):
    """體重紀錄 Flex"""
    if not stats:
        return {"type": "bubble", "size": "kilo", "styles": {"body": {"backgroundColor": COLORS['bg']}},
            "body": {"type": "box", "layout": "vertical", "contents": [
                {"type": "text", "text": "⚖️ 體重紀錄", "weight": "bold", "size": "xl", "color": COLORS['blue']},
                {"type": "separator", "margin": "md", "color": "#333355"},
                {"type": "text", "text": "尚無紀錄", "color": COLORS['gray'], "margin": "lg", "align": "center"},
                {"type": "text", "text": "輸入「體重 65」開始記錄", "color": COLORS['gray'], "size": "sm", "margin": "md", "align": "center"}
            ]}}
    
    # 變化顯示
    def change_text(val):
        if val is None:
            return "-"
        elif val > 0:
            return f"↑{val}"
        elif val < 0:
            return f"↓{abs(val)}"
        else:
            return "→0"
    
    week_color = COLORS['red'] if stats.get('week_change') and stats['week_change'] > 0 else COLORS['green'] if stats.get('week_change') and stats['week_change'] < 0 else COLORS['gray']
    month_color = COLORS['red'] if stats.get('month_change') and stats['month_change'] > 0 else COLORS['green'] if stats.get('month_change') and stats['month_change'] < 0 else COLORS['gray']
    
    return {"type": "bubble", "size": "kilo", "styles": {"body": {"backgroundColor": COLORS['bg']}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": "⚖️ 體重紀錄", "weight": "bold", "size": "xl", "color": COLORS['blue']},
            {"type": "separator", "margin": "md", "color": "#333355"},
            {"type": "text", "text": f"{stats['current']}", "size": "5xl", "weight": "bold", "color": COLORS['white'], "align": "center", "margin": "lg"},
            {"type": "text", "text": "kg", "size": "lg", "color": COLORS['gray'], "align": "center"},
            {"type": "text", "text": f"更新：{stats['current_date']}", "size": "xs", "color": COLORS['gray'], "align": "center", "margin": "sm"},
            {"type": "separator", "margin": "lg", "color": "#333355"},
            {"type": "box", "layout": "horizontal", "margin": "md", "contents": [
                {"type": "box", "layout": "vertical", "contents": [
                    {"type": "text", "text": "週變化", "size": "xs", "color": COLORS['gray'], "align": "center"},
                    {"type": "text", "text": change_text(stats.get('week_change')), "size": "lg", "weight": "bold", "color": week_color, "align": "center"}
                ], "flex": 1},
                {"type": "box", "layout": "vertical", "contents": [
                    {"type": "text", "text": "月變化", "size": "xs", "color": COLORS['gray'], "align": "center"},
                    {"type": "text", "text": change_text(stats.get('month_change')), "size": "lg", "weight": "bold", "color": month_color, "align": "center"}
                ], "flex": 1},
                {"type": "box", "layout": "vertical", "contents": [
                    {"type": "text", "text": "紀錄數", "size": "xs", "color": COLORS['gray'], "align": "center"},
                    {"type": "text", "text": str(stats.get('records_count', 0)), "size": "lg", "weight": "bold", "color": COLORS['white'], "align": "center"}
                ], "flex": 1}
            ]},
            {"type": "separator", "margin": "md", "color": "#333355"},
            {"type": "text", "text": f"30天範圍：{stats['min']} ~ {stats['max']} kg", "size": "xs", "color": COLORS['gray'], "align": "center", "margin": "md"}
        ]}}

def flex_weight_logged(weight, stats):
    """體重記錄成功 Flex"""
    change_text = ""
    if stats and stats.get('records_count', 0) > 1:
        # 和上一筆比較
        history = read_weight_history(30)
        if len(history) >= 2:
            prev = history[-2]['weight']
            diff = round(weight - prev, 1)
            if diff > 0:
                change_text = f"比上次 +{diff} kg"
            elif diff < 0:
                change_text = f"比上次 {diff} kg"
            else:
                change_text = "和上次相同"
    
    return {"type": "bubble", "size": "kilo", "styles": {"body": {"backgroundColor": COLORS['bg']}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "box", "layout": "horizontal", "alignItems": "center", "contents": [
                {"type": "text", "text": "⚖️", "size": "3xl", "flex": 0},
                {"type": "box", "layout": "vertical", "paddingStart": "md", "contents": [
                    {"type": "text", "text": "體重已記錄！", "size": "xl", "weight": "bold", "color": COLORS['blue']},
                    {"type": "text", "text": f"{weight} kg", "size": "lg", "color": COLORS['white']}
                ]}
            ]},
            {"type": "separator", "margin": "lg", "color": "#333355"},
            {"type": "text", "text": change_text if change_text else "持續記錄，追蹤趨勢！", "size": "sm", "color": COLORS['gray'], "margin": "lg", "align": "center"}
        ]}}

def flex_daily_report(s):
    water_count = s.get('water_count', 0) or 0
    stand_count = s.get('stand_count', 0) or 0
    exercise_minutes = s.get('exercise_minutes', 0) or 0
    exercise_calories = s.get('exercise_calories', 0) or 0
    date_str = s.get('date', '今日') or '今日'
    
    wo = "✅" if water_count >= 8 else "⚠️"
    so = "✅" if stand_count >= 6 else "⚠️"
    eo = "✅" if exercise_minutes >= 30 else "⚠️"
    ex_details = s.get('exercise_details', [])
    ex_text = "、".join(ex_details) if ex_details else "無運動紀錄"
    return {"type": "bubble", "size": "mega", "styles": {"body": {"backgroundColor": "#0a0a1a"}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "box", "layout": "horizontal", "contents": [
                {"type": "text", "text": "🌙", "size": "xl", "flex": 0},
                {"type": "text", "text": f"{date_str} 每日總結", "size": "lg", "weight": "bold", "color": COLORS['gold'], "margin": "sm"}]},
            {"type": "separator", "margin": "md", "color": COLORS['gold']},
            {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "md", "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": f"{wo} 喝水", "color": COLORS['cyan'], "flex": 2},
                    {"type": "text", "text": f"{water_count} 杯", "color": COLORS['white'], "align": "end", "flex": 1}]},
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": f"{so} 起身", "color": COLORS['green'], "flex": 2},
                    {"type": "text", "text": f"{stand_count} 次", "color": COLORS['white'], "align": "end", "flex": 1}]},
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": f"{eo} 運動", "color": COLORS['orange'], "flex": 2},
                    {"type": "text", "text": f"{exercise_minutes} 分鐘", "color": COLORS['white'], "align": "end", "flex": 1}]},
                {"type": "text", "text": f"📝 {ex_text}", "color": COLORS['gray'], "size": "xs", "wrap": True}]},
            {"type": "separator", "margin": "lg", "color": "#333355"},
            {"type": "box", "layout": "horizontal", "margin": "md", "contents": [
                {"type": "text", "text": "🔥 總消耗", "color": COLORS['gray']},
                {"type": "text", "text": f"{exercise_calories} kcal", "color": COLORS['pink'], "size": "lg", "weight": "bold", "align": "end"}]}]}}

def flex_settings(s):
    st = "🟢 開啟" if s.get('enabled') in ['TRUE', True] else "🔴 關閉"
    return {"type": "bubble", "size": "mega", "styles": {"body": {"backgroundColor": COLORS['bg']}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": "⚙️ 目前設定", "weight": "bold", "size": "xl", "color": COLORS['purple']},
            {"type": "separator", "margin": "md", "color": "#333355"},
            {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "md", "contents": [
                {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "提醒狀態", "color": COLORS['gray'], "flex": 2}, {"type": "text", "text": st, "color": COLORS['white'], "align": "end", "flex": 1}]},
                {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "💧 喝水間隔", "color": COLORS['cyan'], "flex": 2}, {"type": "text", "text": f"{s.get('water_interval', 60)} 分鐘", "color": COLORS['white'], "align": "end", "flex": 1}]},
                {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "🧍 久坐間隔", "color": COLORS['green'], "flex": 2}, {"type": "text", "text": f"{s.get('stand_interval', 45)} 分鐘", "color": COLORS['white'], "align": "end", "flex": 1}]},
                {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "🌙 勿擾時段", "color": COLORS['pink'], "flex": 2}, {"type": "text", "text": f"{s.get('dnd_start', '22:00')}-{s.get('dnd_end', '08:00')}", "color": COLORS['white'], "align": "end", "flex": 1}]}]}]}}

def flex_ex_prompt():
    return {"type": "bubble", "size": "mega", "styles": {"body": {"backgroundColor": COLORS['bg']}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": "🏃 記錄運動", "weight": "bold", "size": "xl", "color": COLORS['orange']},
            {"type": "separator", "margin": "md", "color": "#333355"},
            {"type": "text", "text": "請輸入：運動類型 分鐘數", "color": COLORS['gray'], "margin": "lg", "size": "sm"},
            {"type": "text", "text": "📝 範例：跑步 30、游泳 45", "color": COLORS['cyan'], "size": "sm", "margin": "md"}]}}

# ===== Webhook =====
@app.route('/callback', methods=['POST'])
def callback():
    sig = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, sig)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    text = event.message.text.strip()
    user_id = event.source.user_id
    
    with ApiClient(configuration) as api:
        bot = MessagingApi(api)
        msgs = []
        
        try:
            # ===== 已喝水 =====
            if text == '已喝水':
                c = write_water()
                msgs.append(FlexMessage(alt_text=f'💧 第{c}杯', contents=FlexContainer.from_dict(flex_water(c)), quick_reply=qr(QR_WATER)))
                send_ai_analysis_async(user_id, 'water', c)
            
            # ===== 已起身 =====
            elif text == '已起身':
                c = write_stand()
                msgs.append(FlexMessage(alt_text=f'🧍 第{c}次', contents=FlexContainer.from_dict(flex_stand(c)), quick_reply=qr(QR_STAND)))
                send_ai_analysis_async(user_id, 'stand', c)
            
            # ===== 記錄運動 =====
            elif text == '記錄運動':
                msgs.append(FlexMessage(alt_text='記錄運動', contents=FlexContainer.from_dict(flex_ex_prompt()), quick_reply=qr(QR_EX_TYPE)))
            
            # ===== 今日統計 =====
            elif text == '今日統計':
                stats = read_today_stats()
                msgs.append(FlexMessage(alt_text='今日統計', contents=FlexContainer.from_dict(flex_stats(stats, 0)), quick_reply=qr(QR_STATS)))
            
            # ===== 週報 =====
            elif text == '週報' or text == '本週統計':
                summary = read_week_summary()
                msgs.append(FlexMessage(alt_text='📅 週報', contents=FlexContainer.from_dict(flex_week_report(summary)), quick_reply=qr(QR_STATS)))
            
            # ===== 連續達標 =====
            elif text == '連續達標':
                streak = calculate_streak()
                msgs.append(FlexMessage(alt_text=f'🔥 連續{streak}天', contents=FlexContainer.from_dict(flex_streak(streak)), quick_reply=qr(QR_STATS)))
            
            # ===== 體重紀錄 =====
            elif text == '體重紀錄' or text == '體重記錄':
                stats = get_weight_stats()
                msgs.append(FlexMessage(alt_text='⚖️ 體重紀錄', contents=FlexContainer.from_dict(flex_weight(stats)), quick_reply=qr(QR_WEIGHT)))
            
            # ===== 記錄體重提示 =====
            elif text == '記錄體重':
                msgs.append(TextMessage(text="請輸入體重數字\n例如：體重 65 或 體重 65.5", quick_reply=qr(QR_MAIN)))
            
            # ===== 體重 XX =====
            elif text.startswith('體重'):
                parts = text.split()
                if len(parts) >= 2:
                    try:
                        weight = float(parts[-1])
                        if 20 <= weight <= 300:  # 合理範圍
                            write_weight(weight)
                            stats = get_weight_stats()
                            msgs.append(FlexMessage(alt_text=f'⚖️ {weight}kg', contents=FlexContainer.from_dict(flex_weight_logged(weight, stats)), quick_reply=qr(QR_WEIGHT)))
                            send_ai_analysis_async(user_id, 'weight', 0, f"目前體重 {weight} kg")
                        else:
                            msgs.append(TextMessage(text="體重數值似乎不太對，請輸入合理範圍（20-300 kg）", quick_reply=qr(QR_MAIN)))
                    except ValueError:
                        msgs.append(TextMessage(text="請輸入正確的數字\n例如：體重 65", quick_reply=qr(QR_MAIN)))
                else:
                    stats = get_weight_stats()
                    msgs.append(FlexMessage(alt_text='⚖️ 體重紀錄', contents=FlexContainer.from_dict(flex_weight(stats)), quick_reply=qr(QR_WEIGHT)))
            
            # ===== 修改選單 =====
            elif text == '修改' or text == '選單':
                msgs.append(FlexMessage(alt_text='修改選單', contents=FlexContainer.from_dict(flex_modify_menu()), quick_reply=qr(QR_MOD)))
            
            # ===== 修改喝水 =====
            elif text == '修改喝水':
                cur = read_today_count('water')
                msgs.append(FlexMessage(alt_text='修改喝水', contents=FlexContainer.from_dict(flex_modify_prompt('water', cur)), quick_reply=qr(QR_MAIN)))
            
            # ===== 修改起身 =====
            elif text == '修改起身':
                cur = read_today_count('stand')
                msgs.append(FlexMessage(alt_text='修改起身', contents=FlexContainer.from_dict(flex_modify_prompt('stand', cur)), quick_reply=qr(QR_MAIN)))
            
            # ===== 修改運動 =====
            elif text == '修改運動':
                stats = read_today_stats()
                msgs.append(FlexMessage(alt_text='修改運動', contents=FlexContainer.from_dict(flex_modify_exercise(stats)), quick_reply=qr(QR_MOD_EX)))
            
            # ===== 刪除運動 =====
            elif text == '刪除運動':
                deleted = delete_last_exercise()
                if deleted:
                    msgs.append(TextMessage(text=f"✅ 已刪除：{deleted[1]} {deleted[2]}分鐘", quick_reply=qr(QR_MAIN)))
                else:
                    msgs.append(TextMessage(text="⚠️ 今日沒有運動紀錄", quick_reply=qr(QR_MAIN)))
            
            # ===== 清空運動 =====
            elif text == '清空運動':
                count = clear_today_exercise()
                msgs.append(TextMessage(text=f"✅ 已清空今日 {count} 筆運動紀錄", quick_reply=qr(QR_MAIN)))
            
            # ===== 修改喝水 N =====
            elif text.startswith('修改喝水'):
                parts = text.split()
                if len(parts) >= 2 and parts[-1].isdigit():
                    t = int(parts[-1])
                    set_count('water', t)
                    msgs.append(FlexMessage(alt_text=f'已改為{t}杯', contents=FlexContainer.from_dict(flex_water(t)), quick_reply=qr(QR_MAIN)))
                    send_ai_analysis_async(user_id, 'water', t)
                else:
                    cur = read_today_count('water')
                    msgs.append(FlexMessage(alt_text='修改喝水', contents=FlexContainer.from_dict(flex_modify_prompt('water', cur)), quick_reply=qr(QR_MAIN)))
            
            # ===== 修改起身 N =====
            elif text.startswith('修改起身'):
                parts = text.split()
                if len(parts) >= 2 and parts[-1].isdigit():
                    t = int(parts[-1])
                    set_count('stand', t)
                    msgs.append(FlexMessage(alt_text=f'已改為{t}次', contents=FlexContainer.from_dict(flex_stand(t)), quick_reply=qr(QR_MAIN)))
                    send_ai_analysis_async(user_id, 'stand', t)
                else:
                    cur = read_today_count('stand')
                    msgs.append(FlexMessage(alt_text='修改起身', contents=FlexContainer.from_dict(flex_modify_prompt('stand', cur)), quick_reply=qr(QR_MAIN)))
            
            # ===== 運動類型 =====
            elif text in EXERCISE_TYPES:
                msgs.append(TextMessage(text=f"請輸入 {text} 的時間\n例如：{text} 30", quick_reply=qr(QR_MAIN)))
            
            # ===== 運動輸入 =====
            elif any(text.startswith(e) for e in EXERCISE_TYPES):
                parts = text.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    et, dur = parts[0], int(parts[1])
                    cal = write_exercise(et, dur)
                    msgs.append(FlexMessage(alt_text=f'{et}{dur}分鐘', contents=FlexContainer.from_dict(flex_exercise(et, dur, cal)), quick_reply=qr(QR_EX)))
                    send_ai_analysis_async(user_id, 'exercise', 0, f"{et} {dur}分鐘，{cal}卡")
                else:
                    msgs.append(TextMessage(text=f"請輸入時間，例如：{parts[0]} 30", quick_reply=qr(QR_MAIN)))
            
            # ===== 設定 =====
            elif text == '設定':
                msgs.append(FlexMessage(alt_text='設定', contents=FlexContainer.from_dict(flex_settings(read_settings())), quick_reply=qr(QR_MAIN)))
            
            # ===== 修改設定 =====
            elif text.startswith('喝水間隔'):
                p = text.split()
                if len(p) >= 2 and p[1].isdigit():
                    write_setting('water_interval', int(p[1]))
                    msgs.append(TextMessage(text=f"✅ 喝水間隔設為 {p[1]} 分鐘", quick_reply=qr(QR_MAIN)))
                else:
                    msgs.append(TextMessage(text="格式：喝水間隔 數字", quick_reply=qr(QR_MAIN)))
            
            elif text.startswith('久坐間隔'):
                p = text.split()
                if len(p) >= 2 and p[1].isdigit():
                    write_setting('stand_interval', int(p[1]))
                    msgs.append(TextMessage(text=f"✅ 久坐間隔設為 {p[1]} 分鐘", quick_reply=qr(QR_MAIN)))
                else:
                    msgs.append(TextMessage(text="格式：久坐間隔 數字", quick_reply=qr(QR_MAIN)))
            
            elif text.startswith('勿擾'):
                p = text.replace('勿擾', '').strip().split('-')
                if len(p) == 2:
                    write_setting('dnd_start', p[0].strip())
                    write_setting('dnd_end', p[1].strip())
                    msgs.append(TextMessage(text=f"✅ 勿擾：{p[0].strip()}-{p[1].strip()}", quick_reply=qr(QR_MAIN)))
                else:
                    msgs.append(TextMessage(text="格式：勿擾 22:00-08:00", quick_reply=qr(QR_MAIN)))
            
            elif text == '開啟提醒':
                write_setting('enabled', 'TRUE')
                msgs.append(TextMessage(text="✅ 提醒已開啟", quick_reply=qr(QR_MAIN)))
            
            elif text == '關閉提醒':
                write_setting('enabled', 'FALSE')
                msgs.append(TextMessage(text="✅ 提醒已關閉", quick_reply=qr(QR_MAIN)))
            
            else:
                msgs.append(TextMessage(text="🤖 請使用下方按鈕", quick_reply=qr(QR_MAIN)))
            
            if msgs:
                bot.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=msgs))
        
        except Exception as e:
            print(f"Error: {e}")
            try:
                bot.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text="⚠️ 系統忙碌", quick_reply=qr(QR_MAIN))]))
            except:
                pass

# ===== API =====
@app.route('/api/daily-report', methods=['POST'])
def api_daily_report():
    try:
        stats = read_today_stats()
        streak = calculate_streak()
        summary = f"喝水{stats['water_count']}杯、起身{stats['stand_count']}次、運動{stats['exercise_minutes']}分鐘、消耗{stats['exercise_calories']}卡、連續達標{streak}天"
        if stats.get('exercise_details'):
            summary += f"，項目：{', '.join(stats['exercise_details'])}"
        
        gemini = get_gemini('daily', 0, summary)
        openai = get_openai('daily', 0, summary)
        
        msgs = [FlexMessage(alt_text='🌙每日總結', contents=FlexContainer.from_dict(flex_daily_report(stats)))]
        af = flex_ai(gemini, openai)
        if af:
            msgs.append(FlexMessage(alt_text='AI每日分析', contents=FlexContainer.from_dict(af)))
        
        if LINE_USER_ID and msgs:
            with ApiClient(configuration) as api:
                MessagingApi(api).push_message(PushMessageRequest(to=LINE_USER_ID, messages=msgs))
        
        return jsonify({'status': 'ok', 'stats': stats, 'streak': streak})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/weekly-report', methods=['POST'])
def api_weekly_report():
    """週報 API（給 GAS 週日呼叫）"""
    try:
        summary = read_week_summary()
        streak = calculate_streak()
        
        summary_text = f"本週喝水{summary['total_water']}杯、起身{summary['total_stand']}次、運動{summary['total_exercise']}分鐘、消耗{summary['total_calories']}卡、達標{summary['days_all_ok']}天、連續達標{streak}天"
        
        gemini = get_gemini('weekly', 0, summary_text)
        openai = get_openai('weekly', 0, summary_text)
        
        msgs = [FlexMessage(alt_text='📅 週報', contents=FlexContainer.from_dict(flex_week_report(summary)))]
        af = flex_ai(gemini, openai)
        if af:
            msgs.append(FlexMessage(alt_text='AI週報分析', contents=FlexContainer.from_dict(af)))
        
        if LINE_USER_ID and msgs:
            with ApiClient(configuration) as api:
                MessagingApi(api).push_message(PushMessageRequest(to=LINE_USER_ID, messages=msgs))
        
        return jsonify({'status': 'ok', 'summary': summary, 'streak': streak})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/api/today')
def api_today():
    return jsonify(read_today_stats())

@app.route('/api/week')
def api_week():
    return jsonify(read_week_stats())

@app.route('/api/settings')
def api_settings():
    return jsonify(read_settings())

@app.route('/api/streak')
def api_streak():
    return jsonify({'streak': calculate_streak()})

@app.route('/api/weight')
def api_weight():
    return jsonify(get_weight_stats())

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/')
def index():
    return render_template('dashboard.html')

@app.route('/manifest.json')
def manifest():
    return app.send_static_file('manifest.json')

@app.route('/sw.js')
def service_worker():
    return app.send_static_file('sw.js')

@app.route('/health')
def health():
    return jsonify({'status': 'ok', 'service': 'neon-pulse-bot'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
