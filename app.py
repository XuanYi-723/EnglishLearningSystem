import functools
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
import spacy
import requests
import json
import re
import os
import csv
import io
from dotenv import load_dotenv

# 🌟 1. 換成最新版的 Google GenAI 套件，並引入 types 以強制回傳 JSON
from google import genai
from google.genai import types

app = Flask(__name__)
CORS(app)

# --- Gemini AI 設定 (新版寫法) ---
load_dotenv()

GENAI_API_KEY = os.environ.get("GOOGLE_API_KEY")

if GENAI_API_KEY:
    # 🌟 2. 新版寫法：建立 Client
    ai_client = genai.Client(api_key=GENAI_API_KEY)
    print("成功：已偵測到 GOOGLE_API_KEY，Gemini 新版模組設定完成。")
else:
    ai_client = None
    print("警告：找不到 GOOGLE_API_KEY 環境變數，AI 功能將無法運作")

# 🌟 3. 移除容易出錯的動態下載邏輯，直接載入模型 (請透過 requirements.txt 安裝)
nlp = spacy.load("en_core_web_sm")

def get_batch_gemini_explanations(word_list):
    """
    批次處理核心：一次將所有單字丟給 Gemini 分析以節省連線時間
    """
    if not word_list or not ai_client:
        return {}

    # 設定 AI 導師的 Prompt
    prompt = f"""
    你是一位專門教導高齡者英文的老師。請針對以下英文單字清單，分別提供：
    1. 中文意思
    2. 詞性 (pos)
    3. 音標 (phonetic)
    4. 適合長輩的溫馨解釋與一個關於「健康或快樂生活」的簡單英文例句 (definition)。

    單字清單: {', '.join(word_list)}

    請以 JSON 格式回傳，格式範例：
    {{
      "apple": {{ 
        "chinese": "蘋果", 
        "pos": "n.", 
        "phonetic": "/ˈæp.əl/", 
        "definition": "解釋內容..."
      }}
    }}
    """

    try:
        # 🌟 4. 使用 generate_content 並透過 response_mime_type 強制鎖定 JSON 輸出
        response = ai_client.models.generate_content(
            model='gemini-1.5-flash', 
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
            )
        )
        
        print("\n=== AI 原始回覆 ===")
        print(response.text)
        print("===================\n")
        
        # 🌟 5. 直接將 AI 回傳的安全 JSON 字串解析為字典，不再需要 Regex
        return json.loads(response.text)
            
    except Exception as e:
        print(f"Gemini 批次分析出錯的詳細原因: {e}")
        return {}

def get_word_level(word):
    """根據單字長度進行基礎分級"""
    if len(word) <= 4: return "簡單"
    if len(word) <= 7: return "中等"
    return "困難"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    # 🌟 6. 使用 request.get_json(silent=True) 避免前端發錯格式導致 500 錯誤
    data = request.get_json(silent=True) or {}
    text = data.get('text', '')
    target_level = data.get('level', '全部')
    
    if not text:
        return jsonify({"highlighted": "", "vocabulary": {}})
    
    doc = nlp(text)
    vocab_results = {}
    words_to_ask_ai = []

    # 單字過濾邏輯
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
    # 🌟 7. 防呆處理，避免 request.json 取不到值引發 AttributeError
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
