import functools
import concurrent.futures
from flask import Flask, request, jsonify, render_template, send_file, redirect, url_for, flash
from flask_cors import CORS
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

from sheets_db import User, sheets_db
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

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return sheets_db.get_user_by_id(user_id)

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

#更改的二元樹
class WordNode:
    def __init__(self, word):
        self.word = word
        self.count = 1       
        self.left = None
        self.right = None

def insert_bst(root, word):
    if root is None:
        return WordNode(word), True
    
    current = root
    while True:
        if word < current.word:
            if current.left is None:
                current.left = WordNode(word)
                return root, True
            current = current.left
        elif word > current.word:
            if current.right is None:
                current.right = WordNode(word)
                return root, True
            current = current.right
        else:
            current.count += 1
            return root, False


def get_sorted_words_inorder(root, result_list):
    stack = []
    current = root
    while stack or current:
        while current:
            stack.append(current)
            current = current.left
        current = stack.pop()
        result_list.append((current.word, current.count))
        current = current.right


def serialize_bst(node):
    if node is None:
        return None
    return {
        "word": node.word,
        "count": node.count,
        "level": get_word_level(node.word),
        "left": serialize_bst(node.left),
        "right": serialize_bst(node.right)
    }


def fetch_gemini_chunk(word_chunk):
    prompt = f"""
    你是一位專門教導高齡者英文的老師。請針對以下英文單字清單，分別提供：
    1. 中文意思
    2. 詞性 (pos)
    3. 音標 (phonetic)
    4. 適合長輩的溫馨解釋與一個關於「健康或快樂生活」的簡單英文例句 (definition)。

    單字清單: {', '.join(word_chunk)}

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
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3-flash-preview:generateContent?key={GENAI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        if response.status_code == 200:
            res_json = response.json()
            text_response = res_json['candidates'][0]['content']['parts'][0]['text']
            
            cleaned_text = text_response.strip()
            if cleaned_text.startswith("```json"):
                cleaned_text = cleaned_text[7:]
            elif cleaned_text.startswith("```"):
                cleaned_text = cleaned_text[3:]
            if cleaned_text.endswith("```"):
                cleaned_text = cleaned_text[:-3]
            
            return json.loads(cleaned_text.strip())
        else:
            print(f"API 錯誤代碼: {response.status_code}")
            return {}
    except Exception as e:
        print(f"API 請求異常: {e}")
        return {}


def get_batch_gemini_explanations(word_list, chunk_size=10):
    if not word_list or not GENAI_API_KEY:
        return {}
    
    chunks = [word_list[i:i + chunk_size] for i in range(0, len(word_list), chunk_size)]
    combined_results = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_chunk = {executor.submit(fetch_gemini_chunk, chunk): chunk for chunk in chunks}
        for future in concurrent.futures.as_completed(future_to_chunk):
            chunk_result = future.result()
            if chunk_result:
                combined_results.update(chunk_result)

    return combined_results

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
        user = sheets_db.get_user_by_username(username)
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
    user = sheets_db.get_user_by_username(username)
    if user:
        flash('帳號已存在，請選擇其他帳號名稱。', 'error')
        return redirect(url_for('login'))
    try:
        new_user = sheets_db.create_user(username, password)
        if new_user:
            login_user(new_user)
            return redirect(url_for('index'))
        else:
            flash('註冊失敗，請重試。', 'error')
            return redirect(url_for('login'))
    except Exception as e:
        flash(f'註冊錯誤: {e}', 'error')
        return redirect(url_for('login'))

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
        sheets_db.add_usage_record(
            user_id=current_user.id,
            level_requested=target_level,
            article_snippet=text[:100] + ('...' if len(text) > 100 else '')
        )
    
    doc = nlp(text)
    vocab_results = {}
    words_to_ask_ai = []
    
    bst_root = None
    extracted_words = []

    for token in doc:
        word_lower = token.text.lower()
        if token.is_alpha and not token.is_stop and len(word_lower) > 2:
            
            if bst_root is None:
                bst_root = WordNode(word_lower)
                level = get_word_level(word_lower)
                if target_level == "全部" or level == target_level:
                    extracted_words.append(word_lower)
            else:
                bst_root, is_new_word = insert_bst(bst_root, word_lower)
                if is_new_word:
                    level = get_word_level(word_lower)
                    if target_level == "全部" or level == target_level:
                        extracted_words.append(word_lower)


    all_sorted_words = []
    if bst_root:
        get_sorted_words_inorder(bst_root, all_sorted_words)
    words_to_process = [w for w in all_sorted_words if w[0] in extracted_words]

    if not words_to_process:
        return jsonify({"highlighted": text, "vocabulary": {}})

    word_strings = [w[0] for w in words_to_process]

    # === 快取機制 第一步：查詢 Google Sheets 快取 ===
    cached_map = sheets_db.get_cached_words(word_strings)

    # === 快取機制 第二步：找出未命中、真的需要問 AI 的「新單字」 ===
    words_to_ask_ai_all = [w for w in words_to_process if w[0] not in cached_map]
    # 依單字出現頻率降序排列
    words_to_ask_ai_all.sort(key=lambda x: x[1], reverse=True)

    # 限制第一步同步呼叫 AI 翻譯的數量上限為 12 個，其餘單字之後點擊再查
    MAX_SYNC_WORDS = 12
    sync_ask_set = set(w[0] for w in words_to_ask_ai_all[:MAX_SYNC_WORDS])
    words_to_ask_ai = list(sync_ask_set)

    ai_data = {}
    # === 快取機制 第三步：呼叫AI並將新單字寫入 Google Sheets ===
    if words_to_ask_ai:
        print(f"[{len(words_to_ask_ai)}] 個未在試算表且頻率高的單字，呼叫 AI 分析...")
        ai_data = get_batch_gemini_explanations(words_to_ask_ai, chunk_size=10)
        
        for word in words_to_ask_ai:
            if word in ai_data:
                info = ai_data[word]
                sheets_db.add_word_cache(
                    word=word,
                    chinese=info.get("chinese", "未知"),
                    pos=info.get("pos", "n."),
                    phonetic=info.get("phonetic", "-"),
                    definition=info.get("definition", "暫無解釋")
                )
        print("新單字已成功寫入 Google Sheets 資料庫並更新快取")
    else:
        print("所有單字均在資料庫中或已被延遲翻譯，無須同步呼叫 AI")

    # === 快取機制 第四步：組裝 Alphabetical 排序的 vocab_results ===
    vocab_results = {}
    for word, count in words_to_process:
        if word in cached_map:
            entry = cached_map[word]
            vocab_results[word] = {
                "chinese": entry.get("chinese", "未知"),
                "pos": entry.get("pos", "n."),
                "phonetic": entry.get("phonetic", "-"),
                "definition": entry.get("definition", "暫無解釋")
            }
            vocab_results[word]["level"] = get_word_level(word)
            vocab_results[word]["status"] = "cached"
        elif word in sync_ask_set and word in ai_data:
            vocab_results[word] = ai_data[word]
            vocab_results[word]["level"] = get_word_level(word)
            vocab_results[word]["status"] = "cached"
        else:
            # 延遲翻譯的單字，或是 AI 呼叫失敗的單字
            vocab_results[word] = {
                "chinese": "點擊翻譯",
                "pos": "-",
                "phonetic": "-",
                "definition": "請點擊按鈕獲取 AI 解釋與例句。",
                "level": get_word_level(word),
                "status": "untranslated"
            }


    # 文章內容高亮標記
    highlighted_text = text
    for word in sorted(vocab_results.keys(), key=len, reverse=True):
        pattern = re.compile(rf'\b({re.escape(word)})\b', re.IGNORECASE)
        highlighted_text = pattern.sub('<mark style="cursor:pointer;" onclick="scrollToWord(\'\\1\')">\\1</mark>', highlighted_text)

    return jsonify({
        "highlighted": highlighted_text, 
        "vocabulary": vocab_results, 
        "bst": serialize_bst(bst_root)
    })

@app.route('/explain_word', methods=['POST'])
def explain_word():
    data = request.get_json(silent=True) or {}
    word = data.get('word', '').strip().lower()
    
    if not word:
        return jsonify({"error": "單字不能為空"}), 400
        
    # 先從快取尋找
    entry = sheets_db.get_cached_word(word)
    if entry:
        res = {
            "chinese": entry.get("chinese", "未知"),
            "pos": entry.get("pos", "n."),
            "phonetic": entry.get("phonetic", "-"),
            "definition": entry.get("definition", "暫無解釋")
        }
        res["level"] = get_word_level(word)
        res["status"] = "cached"
        return jsonify(res)
        
    # 快取未命中，呼叫 Gemini API
    if not GENAI_API_KEY:
        return jsonify({"error": "找不到 GOOGLE_API_KEY 環境變數，AI 功能將無法運作"}), 500
        
    ai_data = get_batch_gemini_explanations([word], chunk_size=1)
    if word in ai_data:
        info = ai_data[word]
        # 寫入 Google Sheets 快取
        sheets_db.add_word_cache(
            word=word,
            chinese=info.get("chinese", "未知"),
            pos=info.get("pos", "n."),
            phonetic=info.get("phonetic", "-"),
            definition=info.get("definition", "暫無解釋")
        )
        print(f"單字 [{word}] 的 AI 解釋已寫入 Google Sheets 快取")
            
        info["level"] = get_word_level(word)
        info["status"] = "cached"
        return jsonify(info)
    else:
        return jsonify({"error": f"AI 翻譯單字 [{word}] 失敗，請重試。"}), 500

@app.route('/export_data', methods=['POST'])
def export_csv():
    req_data = request.get_json(silent=True) or {}
    data = req_data.get('vocabulary', {})
    
    output = io.StringIO()
    output.write('\ufeff') 
    writer = csv.writer(output)
    writer.writerow(['單字', '難度', '詞性', '音標', '中文翻譯', '解釋與例句'])
    
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