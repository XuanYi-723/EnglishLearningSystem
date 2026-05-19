import functools
from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for, flash
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from models import db, User, UsageRecord
import spacy
import requests
import json
import re
import os
import csv
import io
from dotenv import load_dotenv

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'default-secret-key-for-dev')

# 取得雲端資料庫 URL，若無則預設使用本地 SQLite
database_url = os.environ.get('DATABASE_URL', 'sqlite:///app.db')
# 修復 SQLAlchemy 1.4+ 不支援 postgres:// 的問題 (Render/Heroku 通常給 postgres://)
if database_url.startswith("postgres://"):
    database_url = database_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

with app.app_context():
    db.create_all()

CORS(app)

# 載入環境變數
load_dotenv()
GENAI_API_KEY = os.environ.get("GOOGLE_API_KEY")

if GENAI_API_KEY:
    print("成功：已偵測到 GOOGLE_API_KEY，直連模式配置完成。")
else:
    print("警告：找不到 GOOGLE_API_KEY 環境變數，AI 功能將無法運作")

# 載入 NLP 模型
nlp = spacy.load("en_core_web_sm")

def get_batch_gemini_explanations(word_list):
    """
    核心直連函式：使用 2026 年最新、免費額度最穩定的 gemini-2.5-flash
    """
    if not word_list or not GENAI_API_KEY:
        return {}

    prompt = f"""
    你是一位專門教導高齡者英文的老師。請針對以下英文單字清單，分別提供：
    1. 中文意思
    2. 詞性 (pos)
    3. 音標 (phonetic)
    4. 適合長輩的溫馨解釋與一個關於「健康或快樂生活」的簡單英文例句 (definition)。

    單字清單: {', '.join(word_list)}

    請嚴格以 JSON 格式回傳，絕對不要包含任何前後說明的廢話，格式範例：
    {{
      "apple": {{ 
        "chinese": "蘋果", 
        "pos": "n.", 
        "phonetic": "/ˈæp.əl/", 
        "definition": "解釋內容..."
      }}
    }}
    """

    # 🌟 核心修正：使用最新的 gemini-3-flash-preview 模型
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={GENAI_API_KEY}"
    
    headers = {'Content-Type': 'application/json'}
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }

    try:
        response = requests.post(url, headers=headers, json=payload)
        res_json = response.json()
        
        print("\n=== AI 原始回覆 ===")
        if response.status_code == 200:
            text_response = res_json['candidates'][0]['content']['parts'][0]['text']
            print(text_response)
            print("===================\n")
            
            # 自動清洗 AI 可能附帶的 Markdown 標籤
            cleaned_text = text_response.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            elif cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            cleaned_text = cleaned_text.strip()
            
            return json.loads(cleaned_text)
        else:
            print(f"錯誤代碼: {response.status_code}, 詳細內容: {res_json}")
            print("===================\n")
            return {}
            
    except Exception as e:
        print(f"直連 API 發生異常: {e}")
        return {}

def get_word_level(word):
    """根據單字長度進行基礎分級"""
    if len(word) <= 4: return "簡單"
    if len(word) <= 7: return "中等"
    return "困難"

@app.route('/')
def index():
    return render_template('index.html', current_user=current_user)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            login_user(user)
            return redirect(url_for('index'))
        else:
            flash('登入失敗，帳號或密碼錯誤。', 'error')
    return render_template('login.html')

@app.route('/register', methods=['POST'])
def register():
    username = request.form.get('username')
    password = request.form.get('password')
    user = User.query.filter_by(username=username).first()
    if user:
        flash('帳號已存在，請選擇其他帳號名稱。', 'error')
        return redirect(url_for('login'))
    new_user = User(username=username)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    login_user(new_user)
    return redirect(url_for('index'))

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json(silent=True) or {}
    text = data.get('text', '')
    target_level = data.get('level', '全部')
    
    if not text:
        return jsonify({"highlighted": "", "vocabulary": {}})
        
    if current_user.is_authenticated:
        record = UsageRecord(
            user_id=current_user.id,
            level_requested=target_level,
            article_snippet=text[:100] + ('...' if len(text) > 100 else '')
        )
        db.session.add(record)
        db.session.commit()
    
    doc = nlp(text)
    vocab_results = {}
    words_to_ask_ai = []

    seen_words = set()
    for token in doc:
        word_lower = token.text.lower()
        if token.is_alpha and not token.is_stop and len(word_lower) > 2:
            if word_lower not in seen_words:
                level = get_word_level(word_lower)
                if target_level == "全部" or level == target_level:
                    words_to_ask_ai.append(word_lower)
                    seen_words.add(word_lower)
        if len(words_to_ask_ai) >= 12: break

    # 執行 AI 批次生成
    ai_data = get_batch_gemini_explanations(words_to_ask_ai)

    # 整理分析結果
    for word in words_to_ask_ai:
        if word in ai_data:
            vocab_results[word] = ai_data[word]
            vocab_results[word]["level"] = get_word_level(word)
        else:
            vocab_results[word] = {
                "chinese": "點擊查看", "pos": "n.", "phonetic": "-", 
                "definition": "AI 老師正在備課中。", "level": get_word_level(word)
            }

    # 文章內容高亮標記
    highlighted_text = text
    for word in sorted(vocab_results.keys(), key=len, reverse=True):
        pattern = re.compile(rf'\b({re.escape(word)})\b', re.IGNORECASE)
        highlighted_text = pattern.sub(r'<mark>\1</mark>', highlighted_text)

    return jsonify({"highlighted": highlighted_text, "vocabulary": vocab_results})

@app.route('/export_data', methods=['POST'])
def export_csv():
    req_data = request.get_json(silent=True) or {}
    data = req_data.get('vocabulary', {})
    
    output = io.StringIO()
    output.write('\ufeff') 
    writer = csv.writer(output)
    writer.writerow(['單字', '難度', '詞性', '音標', '中文翻譯', 'AI老師解釋與例句'])
    
    for word, info in data.items():
        writer.writerow([
            word.upper(), 
            info.get('level', ''), 
            info.get('pos', ''), 
            info.get('phonetic', ''), 
            info.get('chinese', ''), 
            info.get('definition', '')
        ])
        
    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8-sig')), 
        mimetype='text/csv', 
        as_attachment=True, 
        download_name="智慧學習清單.csv"
    )

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)