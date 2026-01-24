"""
⚡ Neon Pulse Bot v9
新增：自訂每日目標（喝水杯數、起身次數、運動分鐘）
"""

import os
import json
import re
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

# ===== 資料快取（減少 API 呼叫）=====
_data_cache = {}
_cache_time = {}
DATA_CACHE_TTL = 30  # 快取 30 秒

def get_cached(key, fetch_func):
    """取得快取資料，過期才重新讀取"""
    now = time.time()
    if key in _data_cache and (now - _cache_time.get(key, 0)) < DATA_CACHE_TTL:
        return _data_cache[key]
    try:
        data = fetch_func()
        _data_cache[key] = data
        _cache_time[key] = now
        return data
    except Exception as e:
        print(f"[Cache] Error fetching {key}: {e}")
        # 錯誤時返回舊快取
        if key in _data_cache:
            return _data_cache[key]
        raise

def clear_cache(key=None):
    """清除快取"""
    if key:
        _data_cache.pop(key, None)
        _cache_time.pop(key, None)
    else:
        _data_cache.clear()
        _cache_time.clear()

COLORS = {
    'bg': '#0a0a12', 'bg_light': '#1a1a2e', 'cyan': '#00f5ff',
    'green': '#39ff14', 'orange': '#ff6b00', 'pink': '#ff0080',
    'purple': '#8888ff', 'yellow': '#ffff00', 'gray': '#888888',
    'white': '#ffffff', 'gemini_bg': '#1a0a2e', 'gemini_accent': '#a855f7',
    'openai_bg': '#0a1a1a', 'openai_accent': '#10b981', 'gold': '#ffd700',
    'red': '#ff4444', 'blue': '#4a90d9'
}

EXERCISE_TYPES = {'跑步': 10, '走路': 4, '游泳': 12, '騎車': 8, '重訓': 6, '瑜伽': 4, '跳繩': 12, '籃球': 8, '羽球': 7, '桌球': 5, '其他': 5}

# 預設達標標準
DEFAULT_GOALS = {'water': 8, 'stand': 6, 'exercise': 30}

def get_goals():
    """讀取用戶自訂目標，若無則用預設值"""
    try:
        settings = read_settings()
        return {
            'water': int(settings.get('water_goal', DEFAULT_GOALS['water'])) or DEFAULT_GOALS['water'],
            'stand': int(settings.get('stand_goal', DEFAULT_GOALS['stand'])) or DEFAULT_GOALS['stand'],
            'exercise': int(settings.get('exercise_goal', DEFAULT_GOALS['exercise'])) or DEFAULT_GOALS['exercise']
        }
    except:
        return DEFAULT_GOALS

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
    
    goals = get_goals()
    
    total_water = sum(d['water'] for d in week_stats)
    total_stand = sum(d['stand'] for d in week_stats)
    total_exercise = sum(d['exercise'] for d in week_stats)
    
    # 計算達標天數
    days_water_ok = sum(1 for d in week_stats if d['water'] >= goals['water'])
    days_stand_ok = sum(1 for d in week_stats if d['stand'] >= goals['stand'])
    days_exercise_ok = sum(1 for d in week_stats if d['exercise'] >= goals['exercise'])
    days_all_ok = sum(1 for d in week_stats if d['water'] >= goals['water'] and d['stand'] >= goals['stand'] and d['exercise'] >= goals['exercise'])
    
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
    
    goals = get_goals()
    
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
        if water >= goals['water'] and stand >= goals['stand'] and exercise >= goals['exercise']:
            streak += 1
            check_date -= timedelta(days=1)
        else:
            # 如果是今天還沒達標，不算中斷
            if check_date.date() == today.date():
                check_date -= timedelta(days=1)
                continue
            break
    
    return streak

def normalize_time_format(t):
    """正規化時間格式為 HH:mm"""
    if not t:
        return None
    match = re.search(r'(\d{1,2}):(\d{2})', str(t))
    if match:
        h, m = match.groups()
        return f"{int(h):02d}:{m}"
    return None

def read_settings():
    data = get_sheet('settings').get_all_records()
    if data:
        settings = data[0]
        # 確保有預設值
        settings.setdefault('water_interval', 60)
        settings.setdefault('stand_interval', 45)
        settings.setdefault('dnd_start', '22:00')
        settings.setdefault('dnd_end', '08:00')
        settings.setdefault('enabled', True)
        settings.setdefault('water_goal', 8)
        settings.setdefault('stand_goal', 6)
        settings.setdefault('exercise_goal', 30)
        # 正規化時間格式
        settings['dnd_start'] = normalize_time_format(settings.get('dnd_start')) or '22:00'
        settings['dnd_end'] = normalize_time_format(settings.get('dnd_end')) or '08:00'
        return settings
    return {
        'water_interval': 60, 'stand_interval': 45, 
        'dnd_start': '22:00', 'dnd_end': '08:00', 'enabled': True,
        'water_goal': 8, 'stand_goal': 6, 'exercise_goal': 30
    }

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

# ===== 寫入函式（加入防重複）=====

# ===== 成就系統 =====
ACHIEVEMENTS = {
    'streak_7': {'name': '🔥 七日燃燒', 'desc': '連續達標 7 天'},
    'streak_30': {'name': '💎 鑽石毅力', 'desc': '連續達標 30 天'},
    'streak_100': {'name': '👑 百日王者', 'desc': '連續達標 100 天'},
    'water_100': {'name': '💧 水滴石穿', 'desc': '累計喝水 100 杯'},
    'water_500': {'name': '🌊 涓涓細流', 'desc': '累計喝水 500 杯'},
    'water_1000': {'name': '🏆 千杯達人', 'desc': '累計喝水 1000 杯'},
    'stand_100': {'name': '🧍 初級活力', 'desc': '累計起身 100 次'},
    'stand_500': {'name': '🚶 健步如飛', 'desc': '累計起身 500 次'},
    'exercise_500': {'name': '🏃 運動新手', 'desc': '累計運動 500 分鐘'},
    'exercise_2000': {'name': '💪 運動達人', 'desc': '累計運動 2000 分鐘'},
    'sleep_7': {'name': '😴 規律作息', 'desc': '連續記錄睡眠 7 天'},
    'meal_7': {'name': '🥗 均衡飲食', 'desc': '連續記錄飲食 7 天'},
    'mood_14': {'name': '😊 情緒管理師', 'desc': '連續記錄心情 14 天'},
}

MOOD_OPTIONS = {'😄': 5, '🙂': 4, '😐': 3, '😔': 2, '😢': 1, '😡': 1, '😰': 2, '😴': 2}

FOOD_CALORIES = {
    # 主食
    '白飯': 280, '飯': 280, '麵': 350, '炒麵': 400, '拌麵': 380, 
    '吐司': 130, '土司': 130, '麵包': 200, '饅頭': 220, '粥': 150,
    '蛋餅': 300, '三明治': 350, '漢堡': 500, '披薩': 250,
    '水餃': 400, '餃子': 400, '包子': 200, '燒餅': 250,
    # 早餐
    '蘿蔔糕': 200, '蔥油餅': 350, '油條': 200, '煎餃': 350,
    # 肉類
    '雞腿': 300, '雞胸': 200, '雞排': 400, '雞塊': 300,
    '豬排': 350, '排骨': 300, '滷肉': 250, '控肉': 350,
    '牛排': 400, '牛肉': 250, '魚': 200, '蝦': 100,
    # 蛋
    '蛋': 80, '荷包蛋': 100, '炒蛋': 150, '蒸蛋': 100,
    # 蔬菜
    '沙拉': 100, '青菜': 50, '燙青菜': 50, '湯': 80,
    # 飲料
    '奶茶': 350, '珍奶': 450, '珍珠奶茶': 450,
    '咖啡': 100, '拿鐵': 150, '美式': 10, '黑咖啡': 10,
    '豆漿': 120, '牛奶': 150, '果汁': 150, '紅茶': 80, '綠茶': 50,
    '可樂': 150, '汽水': 150,
    # 便當/套餐
    '便當': 700, '自助餐': 600, '套餐': 600,
    # 速食
    '薯條': 300, '炸雞': 350, '雞塊': 250, '薯餅': 200,
    # 點心
    '水果': 100, '優格': 150, '餅乾': 150, '蛋糕': 300,
    '布丁': 150, '冰淇淋': 200, '巧克力': 150,
    # 小吃
    '鹹酥雞': 500, '滷味': 300, '臭豆腐': 350, '蚵仔煎': 400,
    '肉圓': 250, '米粉': 300, '貢丸湯': 150, '魚丸湯': 120,
}

def get_or_create_sheet(name, headers):
    """取得或建立工作表"""
    try:
        return get_sheet(name)
    except:
        ss = get_gspread_client().open_by_key(SPREADSHEET_ID)
        sheet = ss.add_worksheet(title=name, rows=1000, cols=len(headers))
        sheet.append_row(headers)
        return sheet

# ===== 睡眠記錄 =====
def write_sleep(hours, quality, note=''):
    """記錄睡眠"""
    sheet = get_or_create_sheet('sleep_log', ['日期', '時數', '品質(1-5)', '備註'])
    today = get_today()
    sheet.append_row([today, hours, quality, note])
    clear_cache()
    return hours, quality

def read_sleep_history(days=30):
    """讀取睡眠歷史"""
    try:
        data = get_sheet('sleep_log').get_all_values()[1:]
    except:
        return []
    
    cutoff = (datetime.now(TZ) - timedelta(days=days)).strftime('%Y-%m-%d')
    return [{'date': r[0], 'hours': float(r[1]), 'quality': int(r[2]), 'note': r[3] if len(r) > 3 else ''} 
            for r in data if r and r[0] >= cutoff]

def get_sleep_stats():
    """取得睡眠統計"""
    history = read_sleep_history(30)
    if not history:
        return None
    
    avg_hours = sum(h['hours'] for h in history) / len(history)
    avg_quality = sum(h['quality'] for h in history) / len(history)
    
    return {
        'avg_hours': round(avg_hours, 1),
        'avg_quality': round(avg_quality, 1),
        'records': len(history),
        'latest': history[-1] if history else None
    }

# ===== 飲食記錄 =====
def write_meal(meal_type, foods, calories=0, note=''):
    """記錄飲食"""
    sheet = get_or_create_sheet('meal_log', ['時間', '餐別', '食物', '熱量', '備註'])
    
    # 自動計算熱量
    if calories == 0 and foods:
        # 支援多種分隔符：、，, 和空格
        food_list = re.split(r'[、，,\s]+', foods)
        for food in food_list:
            food = food.strip()
            if not food:
                continue
            # 精確匹配
            if food in FOOD_CALORIES:
                calories += FOOD_CALORIES[food]
            else:
                # 模糊匹配（食物名稱包含在輸入中）
                for key, cal in FOOD_CALORIES.items():
                    if key in food or food in key:
                        calories += cal
                        break
    
    # 如果還是 0，給個預設值
    if calories == 0 and foods:
        calories = 300  # 預設一餐 300 卡
    
    sheet.append_row([get_now(), meal_type, foods, calories, note])
    clear_cache()
    return calories

def read_meal_today():
    """讀取今日飲食"""
    try:
        data = get_sheet('meal_log').get_all_values()[1:]
    except:
        return []
    
    today = get_today()
    return [{'time': r[0], 'type': r[1], 'foods': r[2], 'calories': int(r[3]) if r[3] else 0} 
            for r in data if r and r[0].startswith(today)]

def get_meal_stats():
    """取得今日飲食統計"""
    meals = read_meal_today()
    total_cal = sum(m['calories'] for m in meals)
    return {
        'meals': meals,
        'total_calories': total_cal,
        'meal_count': len(meals)
    }

# ===== 心情記錄 =====
def write_mood(emoji, note=''):
    """記錄心情"""
    sheet = get_or_create_sheet('mood_log', ['時間', '心情', '分數', '備註'])
    score = MOOD_OPTIONS.get(emoji, 3)
    sheet.append_row([get_now(), emoji, score, note])
    clear_cache()
    return emoji, score

def read_mood_history(days=30):
    """讀取心情歷史"""
    try:
        data = get_sheet('mood_log').get_all_values()[1:]
    except:
        return []
    
    cutoff = (datetime.now(TZ) - timedelta(days=days)).strftime('%Y-%m-%d')
    return [{'time': r[0], 'emoji': r[1], 'score': int(r[2]), 'note': r[3] if len(r) > 3 else ''} 
            for r in data if r and r[0] >= cutoff]

def get_mood_stats():
    """取得心情統計"""
    history = read_mood_history(30)
    if not history:
        return None
    
    avg_score = sum(h['score'] for h in history) / len(history)
    mood_counts = {}
    for h in history:
        mood_counts[h['emoji']] = mood_counts.get(h['emoji'], 0) + 1
    
    return {
        'avg_score': round(avg_score, 1),
        'records': len(history),
        'distribution': mood_counts,
        'latest': history[-1] if history else None
    }

# ===== 成就計算 =====
def get_total_stats():
    """取得累計統計"""
    try:
        water = len(get_sheet('water_log').get_all_values()) - 1
        stand = len(get_sheet('stand_log').get_all_values()) - 1
        exercise_data = get_sheet('exercise_log').get_all_values()[1:]
        exercise = sum(int(r[2]) for r in exercise_data if r and len(r) > 2 and r[2])
    except:
        water, stand, exercise = 0, 0, 0
    
    return {'total_water': water, 'total_stand': stand, 'total_exercise': exercise}

def get_streak_stats():
    """取得連續記錄統計"""
    streak = calculate_streak()
    
    # 計算睡眠連續天數
    sleep_streak = 0
    try:
        sleep_data = get_sheet('sleep_log').get_all_values()[1:]
        dates = set(r[0] for r in sleep_data if r)
        today = datetime.now(TZ).date()
        for i in range(100):
            check_date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
            if check_date in dates:
                sleep_streak += 1
            else:
                break
    except:
        pass
    
    # 計算飲食連續天數
    meal_streak = 0
    try:
        meal_data = get_sheet('meal_log').get_all_values()[1:]
        dates = set(r[0][:10] for r in meal_data if r)
        today = datetime.now(TZ).date()
        for i in range(100):
            check_date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
            if check_date in dates:
                meal_streak += 1
            else:
                break
    except:
        pass
    
    # 計算心情連續天數
    mood_streak = 0
    try:
        mood_data = get_sheet('mood_log').get_all_values()[1:]
        dates = set(r[0][:10] for r in mood_data if r)
        today = datetime.now(TZ).date()
        for i in range(100):
            check_date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
            if check_date in dates:
                mood_streak += 1
            else:
                break
    except:
        pass
    
    return {'streak': streak, 'sleep_streak': sleep_streak, 'meal_streak': meal_streak, 'mood_streak': mood_streak}

def get_achievements():
    """取得已解鎖成就"""
    totals = get_total_stats()
    streaks = get_streak_stats()
    stats = {**totals, **streaks}
    
    unlocked = []
    for key, ach in ACHIEVEMENTS.items():
        # 檢查條件
        if key == 'streak_7' and stats.get('streak', 0) >= 7:
            unlocked.append({**ach, 'id': key})
        elif key == 'streak_30' and stats.get('streak', 0) >= 30:
            unlocked.append({**ach, 'id': key})
        elif key == 'streak_100' and stats.get('streak', 0) >= 100:
            unlocked.append({**ach, 'id': key})
        elif key == 'water_100' and stats.get('total_water', 0) >= 100:
            unlocked.append({**ach, 'id': key})
        elif key == 'water_500' and stats.get('total_water', 0) >= 500:
            unlocked.append({**ach, 'id': key})
        elif key == 'water_1000' and stats.get('total_water', 0) >= 1000:
            unlocked.append({**ach, 'id': key})
        elif key == 'stand_100' and stats.get('total_stand', 0) >= 100:
            unlocked.append({**ach, 'id': key})
        elif key == 'stand_500' and stats.get('total_stand', 0) >= 500:
            unlocked.append({**ach, 'id': key})
        elif key == 'exercise_500' and stats.get('total_exercise', 0) >= 500:
            unlocked.append({**ach, 'id': key})
        elif key == 'exercise_2000' and stats.get('total_exercise', 0) >= 2000:
            unlocked.append({**ach, 'id': key})
        elif key == 'sleep_7' and stats.get('sleep_streak', 0) >= 7:
            unlocked.append({**ach, 'id': key})
        elif key == 'meal_7' and stats.get('meal_streak', 0) >= 7:
            unlocked.append({**ach, 'id': key})
        elif key == 'mood_14' and stats.get('mood_streak', 0) >= 14:
            unlocked.append({**ach, 'id': key})
    
    return {
        'unlocked': unlocked,
        'total': len(ACHIEVEMENTS),
        'unlocked_count': len(unlocked),
        'stats': stats
    }

def write_water():
    """新增喝水記錄（含防重複）"""
    today = get_today()
    now = datetime.now(TZ)
    sheet = get_sheet('water_log')
    
    # 讀取今日資料
    data = sheet.get_all_values()[1:]
    today_records = [r for r in data if r and len(r) > 0 and r[0].startswith(today)]
    count = len(today_records)
    
    # 防重複：檢查最後一筆是否在 30 秒內
    if today_records:
        try:
            last_time_str = today_records[-1][0]
            last_time = datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=TZ)
            if (now - last_time).total_seconds() < 30:
                print(f"[防重複] 喝水記錄跳過，距上次僅 {(now - last_time).total_seconds():.1f} 秒")
                return count  # 不寫入，返回原本數量
        except:
            pass
    
    # 寫入新記錄
    sheet.append_row([get_now()])
    clear_cache('today')  # 清除快取
    return count + 1

def write_stand():
    """新增起身記錄（含防重複）"""
    today = get_today()
    now = datetime.now(TZ)
    sheet = get_sheet('stand_log')
    
    # 讀取今日資料
    data = sheet.get_all_values()[1:]
    today_records = [r for r in data if r and len(r) > 0 and r[0].startswith(today)]
    count = len(today_records)
    
    # 防重複：檢查最後一筆是否在 30 秒內
    if today_records:
        try:
            last_time_str = today_records[-1][0]
            last_time = datetime.strptime(last_time_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=TZ)
            if (now - last_time).total_seconds() < 30:
                print(f"[防重複] 起身記錄跳過，距上次僅 {(now - last_time).total_seconds():.1f} 秒")
                return count  # 不寫入，返回原本數量
        except:
            pass
    
    # 寫入新記錄
    sheet.append_row([get_now()])
    clear_cache('today')  # 清除快取
    return count + 1

def write_exercise(ex_type, duration):
    cal = duration * EXERCISE_TYPES.get(ex_type, 5)
    get_sheet('exercise_log').append_row([get_now(), ex_type, duration, cal])
    clear_cache('today')  # 清除快取
    return cal

# ===== 護眼記錄 =====
def write_eye(status):
    """記錄護眼（completed=已護眼, ignored=忽略）"""
    sheet = get_or_create_sheet('eye_log', ['時間', '狀態'])
    sheet.append_row([get_now(), status])
    clear_cache()

def get_eye_stats():
    """取得今日護眼統計"""
    try:
        sheet = get_sheet('eye_log')
        data = sheet.get_all_values()[1:]
    except:
        return {'completed': 0, 'ignored': 0, 'total': 0}
    
    today = get_today()
    completed = 0
    ignored = 0
    
    for row in data:
        if row and row[0].startswith(today):
            if len(row) > 1:
                if row[1] == 'completed':
                    completed += 1
                elif row[1] == 'ignored':
                    ignored += 1
    
    return {
        'completed': completed,
        'ignored': ignored,
        'total': completed + ignored
    }

def write_setting(key, value):
    try:
        sheet = get_sheet('settings')
        headers = sheet.row_values(1)
        print(f"[Settings] 設定 {key} = {value}, 現有欄位: {headers}")
        
        if key in headers:
            col = headers.index(key) + 1
            sheet.update_cell(2, col, value)
            print(f"[Settings] 更新欄位 {key} 在第 {col} 欄")
            clear_cache()
            return True
        else:
            # 欄位不存在，新增欄位
            new_col = len(headers) + 1
            sheet.update_cell(1, new_col, key)
            sheet.update_cell(2, new_col, value)
            print(f"[Settings] 新增欄位 {key} 在第 {new_col} 欄")
            clear_cache()
            return True
    except Exception as e:
        print(f"[Settings] 錯誤: {e}")
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
QR_EYE = [{'label': '👁️ 已護眼', 'text': '護眼完成'}, {'label': '📊 護眼統計', 'text': '護眼統計'}, {'label': '📊 今日統計', 'text': '今日統計'}]

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

def flex_stats(s, streak=0, goals=None):
    if goals is None:
        goals = get_goals()
    
    water_count = s.get('water_count', 0) or 0
    stand_count = s.get('stand_count', 0) or 0
    exercise_minutes = s.get('exercise_minutes', 0) or 0
    exercise_calories = s.get('exercise_calories', 0) or 0
    date_str = s.get('date', '今日') or '今日'
    
    # 取得護眼統計
    eye_stats = get_eye_stats()
    eye_completed = eye_stats.get('completed', 0)
    eye_ignored = eye_stats.get('ignored', 0)
    
    wg, sg, eg = goals['water'], goals['stand'], goals['exercise']
    wp = min(water_count/wg*100, 100) if wg > 0 else 0
    sp = min(stand_count/sg*100, 100) if sg > 0 else 0
    ep = min(exercise_minutes/eg*100, 100) if eg > 0 else 0
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
                    {"type": "text", "text": f"{water_count} / {wg} 杯", "color": COLORS['white'], "align": "end"}]},
                {"type": "box", "layout": "horizontal", "margin": "sm", "backgroundColor": COLORS['bg_light'], "cornerRadius": "3px", "contents": [
                    {"type": "box", "layout": "vertical", "contents": [], "width": f"{wp}%", "backgroundColor": COLORS['cyan'], "height": "6px", "cornerRadius": "3px"},
                    {"type": "box", "layout": "vertical", "contents": [], "height": "6px"}]}]},
            {"type": "box", "layout": "vertical", "margin": "lg", "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "🧍 起身", "color": COLORS['green']},
                    {"type": "text", "text": f"{stand_count} / {sg} 次", "color": COLORS['white'], "align": "end"}]},
                {"type": "box", "layout": "horizontal", "margin": "sm", "backgroundColor": COLORS['bg_light'], "cornerRadius": "3px", "contents": [
                    {"type": "box", "layout": "vertical", "contents": [], "width": f"{sp}%", "backgroundColor": COLORS['green'], "height": "6px", "cornerRadius": "3px"},
                    {"type": "box", "layout": "vertical", "contents": [], "height": "6px"}]}]},
            {"type": "box", "layout": "vertical", "margin": "lg", "contents": [
                {"type": "box", "layout": "horizontal", "contents": [
                    {"type": "text", "text": "🏃 運動", "color": COLORS['orange']},
                    {"type": "text", "text": f"{exercise_minutes} / {eg} 分鐘", "color": COLORS['white'], "align": "end"}]},
                {"type": "box", "layout": "horizontal", "margin": "sm", "backgroundColor": COLORS['bg_light'], "cornerRadius": "3px", "contents": [
                    {"type": "box", "layout": "vertical", "contents": [], "width": f"{ep}%", "backgroundColor": COLORS['orange'], "height": "6px", "cornerRadius": "3px"},
                    {"type": "box", "layout": "vertical", "contents": [], "height": "6px"}]}]},
            {"type": "separator", "margin": "lg", "color": "#333355"},
            {"type": "box", "layout": "horizontal", "margin": "lg", "contents": [
                {"type": "text", "text": "🔥 消耗熱量", "color": COLORS['gray']},
                {"type": "text", "text": f"{exercise_calories} kcal", "color": COLORS['pink'], "size": "lg", "weight": "bold", "align": "end"}]},
            {"type": "box", "layout": "horizontal", "margin": "md", "contents": [
                {"type": "text", "text": "👁️ 護眼", "color": COLORS['purple']},
                {"type": "text", "text": f"✅{eye_completed} ❌{eye_ignored}", "color": COLORS['white'], "align": "end"}]}]}}

def flex_week_report(summary, goals=None):
    """週報 Flex"""
    if goals is None:
        goals = get_goals()
    
    daily = summary.get('daily_stats', [])
    
    # 建立每日進度條
    day_rows = []
    for d in daily:
        weekday = d.get('weekday', '-') or '-'
        water = d.get('water', 0) or 0
        stand = d.get('stand', 0) or 0
        exercise = d.get('exercise', 0) or 0
        
        wo = "✅" if water >= goals['water'] else "⚠️"
        so = "✅" if stand >= goals['stand'] else "⚠️"
        eo = "✅" if exercise >= goals['exercise'] else "⚠️"
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
    wg = s.get('water_goal', 8) or 8
    sg = s.get('stand_goal', 6) or 6
    eg = s.get('exercise_goal', 30) or 30
    return {"type": "bubble", "size": "mega", "styles": {"body": {"backgroundColor": COLORS['bg']}},
        "body": {"type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": "⚙️ 目前設定", "weight": "bold", "size": "xl", "color": COLORS['purple']},
            {"type": "separator", "margin": "md", "color": "#333355"},
            {"type": "text", "text": "📊 每日目標", "color": COLORS['gold'], "margin": "lg", "size": "sm"},
            {"type": "box", "layout": "vertical", "margin": "sm", "spacing": "sm", "contents": [
                {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "💧 喝水目標", "color": COLORS['cyan'], "flex": 2}, {"type": "text", "text": f"{wg} 杯", "color": COLORS['white'], "align": "end", "flex": 1}]},
                {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "🧍 起身目標", "color": COLORS['green'], "flex": 2}, {"type": "text", "text": f"{sg} 次", "color": COLORS['white'], "align": "end", "flex": 1}]},
                {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "🏃 運動目標", "color": COLORS['orange'], "flex": 2}, {"type": "text", "text": f"{eg} 分鐘", "color": COLORS['white'], "align": "end", "flex": 1}]}]},
            {"type": "separator", "margin": "lg", "color": "#333355"},
            {"type": "text", "text": "⏰ 提醒設定", "color": COLORS['gold'], "margin": "lg", "size": "sm"},
            {"type": "box", "layout": "vertical", "margin": "sm", "spacing": "sm", "contents": [
                {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "提醒狀態", "color": COLORS['gray'], "flex": 2}, {"type": "text", "text": st, "color": COLORS['white'], "align": "end", "flex": 1}]},
                {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "💧 喝水間隔", "color": COLORS['cyan'], "flex": 2}, {"type": "text", "text": f"{s.get('water_interval', 60)} 分鐘", "color": COLORS['white'], "align": "end", "flex": 1}]},
                {"type": "box", "layout": "horizontal", "contents": [{"type": "text", "text": "🧍 起身間隔", "color": COLORS['green'], "flex": 2}, {"type": "text", "text": f"{s.get('stand_interval', 45)} 分鐘", "color": COLORS['white'], "align": "end", "flex": 1}]},
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
            
            elif text.startswith('起身間隔') or text.startswith('久坐間隔'):
                p = text.split()
                if len(p) >= 2 and p[1].isdigit():
                    write_setting('stand_interval', int(p[1]))
                    msgs.append(TextMessage(text=f"✅ 起身間隔設為 {p[1]} 分鐘", quick_reply=qr(QR_MAIN)))
                else:
                    msgs.append(TextMessage(text="格式：起身間隔 數字\n例如：起身間隔 45", quick_reply=qr(QR_MAIN)))
            
            elif text.startswith('勿擾'):
                # 用正則提取時間 (支援 6:00 或 06:00 格式)
                times = re.findall(r'(\d{1,2}:\d{2})', text)
                if len(times) == 2:
                    # 正規化為 HH:mm 格式
                    def normalize_time(t):
                        h, m = t.split(':')
                        return f"{int(h):02d}:{m}"
                    start = normalize_time(times[0])
                    end = normalize_time(times[1])
                    write_setting('dnd_start', start)
                    write_setting('dnd_end', end)
                    msgs.append(TextMessage(text=f"✅ 勿擾：{start}-{end}", quick_reply=qr(QR_MAIN)))
                else:
                    msgs.append(TextMessage(text="格式：勿擾 22:00-08:00", quick_reply=qr(QR_MAIN)))
            
            elif text == '開啟提醒':
                write_setting('enabled', 'TRUE')
                msgs.append(TextMessage(text="✅ 提醒已開啟", quick_reply=qr(QR_MAIN)))
            
            elif text == '關閉提醒':
                write_setting('enabled', 'FALSE')
                msgs.append(TextMessage(text="✅ 提醒已關閉", quick_reply=qr(QR_MAIN)))
            
            # ===== 稍後提醒 =====
            elif text == '稍後提醒喝水':
                # 記錄延後時間（10分鐘後）
                delay_time = (datetime.now(TZ) + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
                write_setting('water_snooze', delay_time)
                msgs.append(TextMessage(text="⏰ 好的，10 分鐘後再提醒你喝水！", quick_reply=qr(QR_MAIN)))
            
            elif text == '稍後提醒起身':
                delay_time = (datetime.now(TZ) + timedelta(minutes=10)).strftime('%Y-%m-%d %H:%M:%S')
                write_setting('stand_snooze', delay_time)
                msgs.append(TextMessage(text="⏰ 好的，10 分鐘後再提醒你起身！", quick_reply=qr(QR_MAIN)))
            
            # ===== 今日不提醒 =====
            elif text == '今日不提醒喝水':
                today_end = datetime.now(TZ).strftime('%Y-%m-%d') + ' 23:59:59'
                write_setting('water_snooze', today_end)
                msgs.append(TextMessage(text="🔕 今日不再提醒喝水\n明天會恢復提醒", quick_reply=qr(QR_MAIN)))
            
            elif text == '今日不提醒起身':
                today_end = datetime.now(TZ).strftime('%Y-%m-%d') + ' 23:59:59'
                write_setting('stand_snooze', today_end)
                msgs.append(TextMessage(text="🔕 今日不再提醒起身\n明天會恢復提醒", quick_reply=qr(QR_MAIN)))
            
            elif text == '今日不運動':
                today = datetime.now(TZ).strftime('%Y-%m-%d')
                write_setting('exercise_skip', today)
                msgs.append(TextMessage(text="😴 好的，今天好好休息！\n記得明天要動起來喔", quick_reply=qr(QR_MAIN)))
            
            # ===== 護眼記錄 =====
            elif text == '護眼完成' or text == '已護眼':
                write_eye('completed')
                eye_stats = get_eye_stats()
                msgs.append(TextMessage(text=f"👁️ 護眼完成！做得好！\n\n今日統計：\n✅ 已護眼：{eye_stats['completed']} 次\n❌ 忽略：{eye_stats['ignored']} 次\n\n繼續保持 30-20-20 護眼習慣！", quick_reply=qr(QR_EYE)))
            
            elif text == '護眼忽略':
                write_eye('ignored')
                eye_stats = get_eye_stats()
                msgs.append(TextMessage(text=f"👁️ 已記錄忽略\n\n今日統計：\n✅ 已護眼：{eye_stats['completed']} 次\n❌ 忽略：{eye_stats['ignored']} 次\n\n記得要讓眼睛休息喔！", quick_reply=qr(QR_EYE)))
            
            elif text == '護眼統計':
                eye_stats = get_eye_stats()
                msgs.append(TextMessage(text=f"👁️ 今日護眼統計\n\n✅ 已護眼：{eye_stats['completed']} 次\n❌ 忽略：{eye_stats['ignored']} 次\n📊 總提醒：{eye_stats['total']} 次\n\n20-20-20 法則：\n每 20 分鐘看向 20 英尺（6公尺）遠處 20 秒", quick_reply=qr(QR_EYE)))
            
            # ===== 目標設定 =====
            elif text.startswith('喝水目標'):
                p = text.split()
                if len(p) >= 2 and p[-1].isdigit():
                    val = int(p[-1])
                    if 1 <= val <= 20:
                        write_setting('water_goal', val)
                        msgs.append(TextMessage(text=f"✅ 喝水目標設為 {val} 杯/天", quick_reply=qr(QR_MAIN)))
                    else:
                        msgs.append(TextMessage(text="⚠️ 請輸入 1-20 之間的數字", quick_reply=qr(QR_MAIN)))
                else:
                    goals = get_goals()
                    msgs.append(TextMessage(text=f"目前喝水目標：{goals['water']} 杯\n\n格式：喝水目標 數字\n例如：喝水目標 10", quick_reply=qr(QR_MAIN)))
            
            elif text.startswith('起身目標'):
                p = text.split()
                if len(p) >= 2 and p[-1].isdigit():
                    val = int(p[-1])
                    if 1 <= val <= 20:
                        write_setting('stand_goal', val)
                        msgs.append(TextMessage(text=f"✅ 起身目標設為 {val} 次/天", quick_reply=qr(QR_MAIN)))
                    else:
                        msgs.append(TextMessage(text="⚠️ 請輸入 1-20 之間的數字", quick_reply=qr(QR_MAIN)))
                else:
                    goals = get_goals()
                    msgs.append(TextMessage(text=f"目前起身目標：{goals['stand']} 次\n\n格式：起身目標 數字\n例如：起身目標 8", quick_reply=qr(QR_MAIN)))
            
            elif text.startswith('運動目標'):
                p = text.split()
                if len(p) >= 2 and p[-1].isdigit():
                    val = int(p[-1])
                    if 1 <= val <= 180:
                        write_setting('exercise_goal', val)
                        msgs.append(TextMessage(text=f"✅ 運動目標設為 {val} 分鐘/天", quick_reply=qr(QR_MAIN)))
                    else:
                        msgs.append(TextMessage(text="⚠️ 請輸入 1-180 之間的數字", quick_reply=qr(QR_MAIN)))
                else:
                    goals = get_goals()
                    msgs.append(TextMessage(text=f"目前運動目標：{goals['exercise']} 分鐘\n\n格式：運動目標 數字\n例如：運動目標 45", quick_reply=qr(QR_MAIN)))
            
            elif text == '目標設定' or text == '設定目標':
                goals = get_goals()
                msgs.append(TextMessage(text=f"📊 目前每日目標\n\n💧 喝水：{goals['water']} 杯\n🧍 起身：{goals['stand']} 次\n🏃 運動：{goals['exercise']} 分鐘\n\n修改方式：\n• 喝水目標 10\n• 起身目標 8\n• 運動目標 45", quick_reply=qr(QR_MAIN)))
            
            # ===== V11 新功能 =====
            
            # 睡眠記錄
            elif text == '記錄睡眠' or text == '睡眠':
                msgs.append(TextMessage(text="😴 記錄睡眠\n\n格式：睡眠 時數 品質(1-5)\n例如：睡眠 7.5 4\n\n品質說明：\n5=很好 4=好 3=普通 2=差 1=很差", quick_reply=qr(QR_MAIN)))
            
            elif text.startswith('睡眠 ') or text.startswith('睡眠記錄 '):
                parts = text.split()
                if len(parts) >= 3:
                    try:
                        hours = float(parts[1])
                        quality = int(parts[2])
                        note = ' '.join(parts[3:]) if len(parts) > 3 else ''
                        if 0 < hours <= 24 and 1 <= quality <= 5:
                            write_sleep(hours, quality, note)
                            q_text = ['', '😫很差', '😔差', '😐普通', '🙂好', '😴很好'][quality]
                            msgs.append(TextMessage(text=f"✅ 睡眠記錄成功！\n\n⏰ 時數：{hours} 小時\n😴 品質：{q_text}\n📝 備註：{note if note else '無'}", quick_reply=qr(QR_MAIN)))
                        else:
                            msgs.append(TextMessage(text="⚠️ 時數需在0-24，品質需在1-5", quick_reply=qr(QR_MAIN)))
                    except:
                        msgs.append(TextMessage(text="格式錯誤，例如：睡眠 7.5 4", quick_reply=qr(QR_MAIN)))
                else:
                    msgs.append(TextMessage(text="格式：睡眠 時數 品質\n例如：睡眠 7.5 4", quick_reply=qr(QR_MAIN)))
            
            elif text == '睡眠統計':
                stats = get_sleep_stats()
                if stats:
                    msgs.append(TextMessage(text=f"😴 睡眠統計（近30天）\n\n⏰ 平均時數：{stats['avg_hours']} 小時\n⭐ 平均品質：{stats['avg_quality']}/5\n📊 記錄次數：{stats['records']} 次", quick_reply=qr(QR_MAIN)))
                else:
                    msgs.append(TextMessage(text="還沒有睡眠記錄\n\n輸入「記錄睡眠」開始記錄", quick_reply=qr(QR_MAIN)))
            
            # 飲食記錄
            elif text == '記錄飲食' or text == '飲食':
                msgs.append(TextMessage(text="🍎 記錄飲食\n\n格式：餐別 食物\n例如：早餐 吐司、豆漿\n\n餐別：早餐/午餐/晚餐/點心\n\n或輸入熱量：\n午餐 便當 700卡", quick_reply=qr(QR_MAIN)))
            
            elif any(text.startswith(m) for m in ['早餐', '午餐', '晚餐', '點心']):
                parts = text.split(maxsplit=1)
                if len(parts) >= 2:
                    meal_type = parts[0]
                    rest = parts[1]
                    
                    # 檢查是否有自訂熱量
                    cal_match = re.search(r'(\d+)\s*[卡kcal]', rest)
                    if cal_match:
                        calories = int(cal_match.group(1))
                        foods = re.sub(r'\d+\s*[卡kcal]', '', rest).strip()
                    else:
                        calories = 0
                        foods = rest
                    
                    cal = write_meal(meal_type, foods, calories)
                    
                    # 顯示個別食物熱量
                    food_details = []
                    food_list = re.split(r'[、，,\s]+', foods)
                    for food in food_list:
                        food = food.strip()
                        if not food:
                            continue
                        food_cal = FOOD_CALORIES.get(food, 0)
                        if food_cal == 0:
                            for key, val in FOOD_CALORIES.items():
                                if key in food or food in key:
                                    food_cal = val
                                    break
                        if food_cal > 0:
                            food_details.append(f"{food}({food_cal}卡)")
                        else:
                            food_details.append(food)
                    
                    food_str = '、'.join(food_details)
                    msgs.append(TextMessage(text=f"✅ {meal_type}記錄成功！\n\n🍽️ 食物：{food_str}\n🔥 總熱量：約 {cal} 大卡", quick_reply=qr(QR_MAIN)))
                else:
                    msgs.append(TextMessage(text=f"請輸入食物內容\n例如：{parts[0]} 便當", quick_reply=qr(QR_MAIN)))
            
            elif text == '今日飲食' or text == '飲食統計':
                stats = get_meal_stats()
                if stats['meals']:
                    # 分類顯示
                    by_type = {'早餐': [], '午餐': [], '晚餐': [], '點心': []}
                    for m in stats['meals']:
                        t = m['type'] if m['type'] in by_type else '點心'
                        by_type[t].append(m)
                    
                    meal_text = ''
                    for meal_type in ['早餐', '午餐', '晚餐', '點心']:
                        items = by_type[meal_type]
                        if items:
                            # 解析每個食物並顯示獨立熱量
                            all_foods = []
                            for m in items:
                                food_list = re.split(r'[、，,\s]+', m['foods'])
                                for food in food_list:
                                    food = food.strip()
                                    if not food:
                                        continue
                                    # 查詢熱量
                                    cal = FOOD_CALORIES.get(food, 0)
                                    if cal == 0:
                                        for key, val in FOOD_CALORIES.items():
                                            if key in food or food in key:
                                                cal = val
                                                break
                                    if cal > 0:
                                        all_foods.append(f"{food}({cal}卡)")
                                    else:
                                        all_foods.append(food)
                            
                            cal_sum = sum(m['calories'] for m in items)
                            meal_text += f"🍽️ {meal_type}：{'、'.join(all_foods)} = {cal_sum}卡\n"
                    
                    msgs.append(TextMessage(text=f"🍎 今日飲食\n\n{meal_text.strip()}\n\n📊 總熱量：{stats['total_calories']} 大卡", quick_reply=qr(QR_MAIN)))
                else:
                    msgs.append(TextMessage(text="今天還沒有飲食記錄\n\n輸入「記錄飲食」開始記錄", quick_reply=qr(QR_MAIN)))
            
            # 心情記錄
            elif text == '記錄心情' or text == '心情':
                msgs.append(TextMessage(text="😊 記錄心情\n\n輸入表情或文字：\n😄 或「開心」\n🙂 或「普通」\n😐 或「平靜」\n😔 或「低落」\n😢 或「難過」\n😡 或「生氣」\n😰 或「焦慮」\n😴 或「疲憊」\n\n可加備註：開心 今天很棒", quick_reply=qr(QR_MAIN)))
            
            elif len(text) > 0 and text[0] in MOOD_OPTIONS:
                emoji = text[0]
                note = text[1:].strip()
                write_mood(emoji, note)
                score = MOOD_OPTIONS[emoji]
                msgs.append(TextMessage(text=f"✅ 心情記錄成功！\n\n{emoji} 分數：{score}/5\n📝 備註：{note if note else '無'}", quick_reply=qr(QR_MAIN)))
            
            # 心情文字輸入
            elif text.startswith('開心') or text.startswith('很開心'):
                note = text.replace('開心', '').replace('很', '').strip()
                write_mood('😄', note)
                msgs.append(TextMessage(text=f"✅ 心情記錄成功！\n\n😄 分數：5/5\n📝 備註：{note if note else '無'}", quick_reply=qr(QR_MAIN)))
            
            elif text.startswith('普通'):
                note = text.replace('普通', '').strip()
                write_mood('🙂', note)
                msgs.append(TextMessage(text=f"✅ 心情記錄成功！\n\n🙂 分數：4/5\n📝 備註：{note if note else '無'}", quick_reply=qr(QR_MAIN)))
            
            elif text.startswith('平靜'):
                note = text.replace('平靜', '').strip()
                write_mood('😐', note)
                msgs.append(TextMessage(text=f"✅ 心情記錄成功！\n\n😐 分數：3/5\n📝 備註：{note if note else '無'}", quick_reply=qr(QR_MAIN)))
            
            elif text.startswith('低落') or text.startswith('不開心'):
                note = text.replace('低落', '').replace('不開心', '').strip()
                write_mood('😔', note)
                msgs.append(TextMessage(text=f"✅ 心情記錄成功！\n\n😔 分數：2/5\n📝 備註：{note if note else '無'}", quick_reply=qr(QR_MAIN)))
            
            elif text.startswith('難過') or text.startswith('傷心'):
                note = text.replace('難過', '').replace('傷心', '').strip()
                write_mood('😢', note)
                msgs.append(TextMessage(text=f"✅ 心情記錄成功！\n\n😢 分數：1/5\n📝 備註：{note if note else '無'}", quick_reply=qr(QR_MAIN)))
            
            elif text.startswith('生氣') or text.startswith('憤怒'):
                note = text.replace('生氣', '').replace('憤怒', '').strip()
                write_mood('😡', note)
                msgs.append(TextMessage(text=f"✅ 心情記錄成功！\n\n😡 分數：1/5\n📝 備註：{note if note else '無'}", quick_reply=qr(QR_MAIN)))
            
            elif text.startswith('焦慮') or text.startswith('緊張'):
                note = text.replace('焦慮', '').replace('緊張', '').strip()
                write_mood('😰', note)
                msgs.append(TextMessage(text=f"✅ 心情記錄成功！\n\n😰 分數：2/5\n📝 備註：{note if note else '無'}", quick_reply=qr(QR_MAIN)))
            
            elif text.startswith('疲憊') or text.startswith('累') or text.startswith('好累'):
                note = text.replace('疲憊', '').replace('累', '').replace('好', '').strip()
                write_mood('😴', note)
                msgs.append(TextMessage(text=f"✅ 心情記錄成功！\n\n😴 分數：2/5\n📝 備註：{note if note else '無'}", quick_reply=qr(QR_MAIN)))
            
            elif text == '心情統計':
                stats = get_mood_stats()
                if stats:
                    dist = ' '.join([f"{e}{c}次" for e, c in stats['distribution'].items()])
                    msgs.append(TextMessage(text=f"😊 心情統計（近30天）\n\n⭐ 平均分數：{stats['avg_score']}/5\n📊 記錄次數：{stats['records']} 次\n\n分布：{dist}", quick_reply=qr(QR_MAIN)))
                else:
                    msgs.append(TextMessage(text="還沒有心情記錄\n\n輸入「記錄心情」開始記錄", quick_reply=qr(QR_MAIN)))
            
            # 成就系統
            elif text == '成就' or text == '徽章':
                ach = get_achievements()
                if ach['unlocked']:
                    badges = '\n'.join([f"{a['name']} - {a['desc']}" for a in ach['unlocked']])
                    msgs.append(TextMessage(text=f"🏆 已解鎖成就 ({ach['unlocked_count']}/{ach['total']})\n\n{badges}\n\n📊 累計統計：\n💧 喝水 {ach['stats']['total_water']} 杯\n🧍 起身 {ach['stats']['total_stand']} 次\n🏃 運動 {ach['stats']['total_exercise']} 分鐘", quick_reply=qr(QR_MAIN)))
                else:
                    msgs.append(TextMessage(text=f"🏆 成就系統\n\n尚未解鎖任何成就\n繼續努力！\n\n📊 累計統計：\n💧 喝水 {ach['stats']['total_water']} 杯\n🧍 起身 {ach['stats']['total_stand']} 次\n🏃 運動 {ach['stats']['total_exercise']} 分鐘", quick_reply=qr(QR_MAIN)))
            
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
    try:
        return jsonify(get_cached('today', read_today_stats))
    except:
        return jsonify({'water_count': 0, 'stand_count': 0, 'exercise_minutes': 0, 'exercise_calories': 0})

@app.route('/api/week')
def api_week():
    try:
        return jsonify(get_cached('week', read_week_stats))
    except:
        return jsonify([])

@app.route('/api/settings')
def api_settings():
    try:
        return jsonify(get_cached('settings', read_settings))
    except:
        return jsonify({'water_interval': 60, 'stand_interval': 45, 'enabled': True, 'water_goal': 8, 'stand_goal': 6, 'exercise_goal': 30})

@app.route('/api/goals')
def api_goals():
    try:
        return jsonify(get_cached('goals', get_goals))
    except:
        return jsonify({'water': 8, 'stand': 6, 'exercise': 30})

@app.route('/api/streak')
def api_streak():
    try:
        return jsonify({'streak': get_cached('streak', calculate_streak)})
    except:
        return jsonify({'streak': 0})

@app.route('/api/weight')
def api_weight():
    try:
        return jsonify(get_cached('weight', get_weight_stats))
    except:
        return jsonify({'current': None, 'week_change': None, 'month_change': None})

# ===== V11 新功能 API =====
@app.route('/api/sleep')
def api_sleep():
    try:
        return jsonify(get_sleep_stats() or {})
    except:
        return jsonify({})

@app.route('/api/meal')
def api_meal():
    try:
        return jsonify(get_meal_stats())
    except:
        return jsonify({'meals': [], 'total_calories': 0})

@app.route('/api/mood')
def api_mood():
    try:
        return jsonify(get_mood_stats() or {})
    except:
        return jsonify({})

@app.route('/api/achievements')
def api_achievements():
    try:
        return jsonify(get_achievements())
    except:
        return jsonify({'unlocked': [], 'total': 0, 'unlocked_count': 0})

@app.route('/api/log/sleep', methods=['POST'])
def api_log_sleep():
    try:
        data = request.get_json() or {}
        hours = float(data.get('hours', 0))
        quality = int(data.get('quality', 3))
        note = data.get('note', '')
        
        if hours <= 0 or hours > 24:
            return jsonify({'success': False, 'error': '時數需在0-24之間'}), 400
        if quality < 1 or quality > 5:
            return jsonify({'success': False, 'error': '品質需在1-5之間'}), 400
        
        write_sleep(hours, quality, note)
        return jsonify({'success': True, 'hours': hours, 'quality': quality, 'message': f'已記錄睡眠 {hours} 小時，品質 {quality}/5'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/log/meal', methods=['POST'])
def api_log_meal():
    try:
        data = request.get_json() or {}
        meal_type = data.get('type', '其他')
        foods = data.get('foods', '')
        calories = int(data.get('calories', 0))
        note = data.get('note', '')
        
        cal = write_meal(meal_type, foods, calories, note)
        return jsonify({'success': True, 'type': meal_type, 'foods': foods, 'calories': cal, 'message': f'{meal_type}記錄成功，約 {cal} 大卡'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/log/mood', methods=['POST'])
def api_log_mood():
    try:
        data = request.get_json() or {}
        emoji = data.get('emoji', '😐')
        note = data.get('note', '')
        
        write_mood(emoji, note)
        score = MOOD_OPTIONS.get(emoji, 3)
        return jsonify({'success': True, 'emoji': emoji, 'score': score, 'message': f'心情記錄成功 {emoji}'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ===== PWA 記錄 API =====
@app.route('/api/log/water', methods=['POST'])
def api_log_water():
    """PWA 記錄喝水"""
    try:
        count = write_water()
        return jsonify({'success': True, 'count': count, 'message': f'已記錄！今日第 {count} 杯'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/log/stand', methods=['POST'])
def api_log_stand():
    """PWA 記錄起身"""
    try:
        count = write_stand()
        return jsonify({'success': True, 'count': count, 'message': f'已記錄！今日第 {count} 次'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/log/exercise', methods=['POST'])
def api_log_exercise():
    """PWA 記錄運動"""
    try:
        data = request.get_json() or {}
        ex_type = data.get('type', '其他')
        duration = int(data.get('duration', 30))
        cal = write_exercise(ex_type, duration)
        return jsonify({'success': True, 'type': ex_type, 'duration': duration, 'calories': cal, 'message': f'{ex_type} {duration}分鐘，消耗 {cal} 大卡'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/log/weight', methods=['POST'])
def api_log_weight():
    """PWA 記錄體重"""
    try:
        data = request.get_json() or {}
        weight = float(data.get('weight', 0))
        if weight <= 0:
            return jsonify({'success': False, 'error': '請輸入有效體重'}), 400
        
        sheet = get_sheet('weight_log')
        sheet.append_row([get_now(), weight])
        return jsonify({'success': True, 'weight': weight, 'message': f'已記錄體重 {weight} kg'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/update/goals', methods=['POST'])
def api_update_goals():
    """PWA 更新目標"""
    try:
        data = request.get_json() or {}
        updated = []
        
        if 'water' in data:
            val = int(data['water'])
            if 1 <= val <= 20:
                write_setting('water_goal', val)
                updated.append(f'喝水 {val} 杯')
        
        if 'stand' in data:
            val = int(data['stand'])
            if 1 <= val <= 20:
                write_setting('stand_goal', val)
                updated.append(f'起身 {val} 次')
        
        if 'exercise' in data:
            val = int(data['exercise'])
            if 1 <= val <= 180:
                write_setting('exercise_goal', val)
                updated.append(f'運動 {val} 分鐘')
        
        return jsonify({'success': True, 'updated': updated, 'message': '目標已更新：' + '、'.join(updated)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/update/settings', methods=['POST'])
def api_update_settings():
    """PWA 更新設定"""
    try:
        data = request.get_json() or {}
        updated = []
        
        if 'water_interval' in data:
            val = int(data['water_interval'])
            if 10 <= val <= 180:
                write_setting('water_interval', val)
                updated.append(f'喝水間隔 {val} 分鐘')
        
        if 'stand_interval' in data:
            val = int(data['stand_interval'])
            if 10 <= val <= 120:
                write_setting('stand_interval', val)
                updated.append(f'起身間隔 {val} 分鐘')
        
        if 'enabled' in data:
            val = 'TRUE' if data['enabled'] else 'FALSE'
            write_setting('enabled', val)
            updated.append('提醒 ' + ('開啟' if data['enabled'] else '關閉'))
        
        if 'dnd_start' in data and 'dnd_end' in data:
            write_setting('dnd_start', data['dnd_start'])
            write_setting('dnd_end', data['dnd_end'])
            updated.append(f"勿擾 {data['dnd_start']}-{data['dnd_end']}")
        
        return jsonify({'success': True, 'updated': updated, 'message': '設定已更新'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/modify/water', methods=['POST'])
def api_modify_water():
    """PWA 修改喝水次數"""
    try:
        data = request.get_json() or {}
        target = int(data.get('count', 0))
        if target < 0:
            return jsonify({'success': False, 'error': '次數不能為負'}), 400
        
        set_count('water', target)
        return jsonify({'success': True, 'count': target, 'message': f'喝水已設為 {target} 杯'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/modify/stand', methods=['POST'])
def api_modify_stand():
    """PWA 修改起身次數"""
    try:
        data = request.get_json() or {}
        target = int(data.get('count', 0))
        if target < 0:
            return jsonify({'success': False, 'error': '次數不能為負'}), 400
        
        set_count('stand', target)
        return jsonify({'success': True, 'count': target, 'message': f'起身已設為 {target} 次'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

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
