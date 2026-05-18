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
from dotenv import load_dotenv          # 1. 引入讀取 .env 的工具
import google.generativeai as genai

app = Flask(__name__)
CORS(app)

# --- Gemini AI 設定 ---
load_dotenv()  # 2. 優先載入本機 .env 檔案中的環境變數

# 讀取金鑰（不論是來自 .env 還是雲端環境變數，os.environ.get 都能抓到）
GENAI_API_KEY = os.environ.get("GOOGLE_API_KEY")

if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash-001')
    print("成功：已偵測到 GOOGLE_API_KEY，Gemini 模組設定完成。")
else:
    gemini_model = None  # 確保若無金鑰，變數依然存在
    print("警告：找不到 GOOGLE_API_KEY 環境變數，AI 功能將無法運作")

# 載入 NLP 模型進行單字過濾與分析
try:
    nlp = spacy.load("en_core_web_sm")
except:
    import spacy.cli
    spacy.cli.download("en_core_web_sm")
    nlp = spacy.load("en_core_web_sm")

def get_batch_gemini_explanations(word_list):
    """
    批次處理核心：一次將所有單字丟給 Gemini 分析以節省連線時間
    """
    # 3. 確保 gemini_model 有被成功建立才執行
    if not word_list or not gemini_model:
        return {}

    # 設定 AI 導師的 Prompt
    prompt = f"""
    你是一位專門教導高齡者英文的老師。請針對以下英文單字清單，分別提供：
    1. 中文意思
    2. 詞性 (pos)
    3. 音標 (phonetic)
    4. 適合長輩的溫馨解釋與一個關於「健康或快樂生活」的簡單英文例句 (definition)。

    單字清單: {', '.join(word_list)}

    請嚴格以 JSON 格式回傳，格式範例：
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
        response = gemini_model.generate_content(prompt)
        # 清理 Markdown 格式符號
        clean_text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_text)
    except Exception as e:
        print(f"Gemini 批次分析出錯: {e}")
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
    data = request.json
    text = data.get('text', '')
    target_level = data.get('level', '全部')
    
    doc = nlp(text)
    vocab_results = {}
    words_to_ask_ai = []

    # 1. 單字過濾邏輯：排除常用詞、符號，並依照難度篩選
    seen_words = set()
    for token in doc:
        word_lower = token.text.lower()
        if token.is_alpha and not token.is_stop and len(word_lower) > 2:
            if word_lower not in seen_words:
                level = get_word_level(word_lower)
                if target_level == "全部" or level == target_level:
                    words_to_ask_ai.append(word_lower)
                    seen_words.add(word_lower)
        # 限制每次分析最多 12 個單字，確保效能
        if len(words_to_ask_ai) >= 12: break

    # 2. 執行 AI 批次生成
    ai_data = get_batch_gemini_explanations(words_to_ask_ai)

    # 3. 整理分析結果
    for word in words_to_ask_ai:
        if word in ai_data:
            vocab_results[word] = ai_data[word]
            vocab_results[word]["level"] = get_word_level(word)
        else:
            vocab_results[word] = {
                "chinese": "點擊查看", "pos": "n.", "phonetic": "-", 
                "definition": "AI 老師正在備課中。", "level": get_word_level(word)
            }

    # 4. 文章內容高亮標記
    highlighted_text = text
    for word in sorted(vocab_results.keys(), key=len, reverse=True):
        pattern = re.compile(rf'\b({re.escape(word)})\b', re.IGNORECASE)
        highlighted_text = pattern.sub(r'<mark>\1</mark>', highlighted_text)

    return jsonify({"highlighted": highlighted_text, "vocabulary": vocab_results})

@app.route('/export_data', methods=['POST'])
def export_csv():
    data = request.json.get('vocabulary', {})
    output = io.StringIO()
    output.write('\ufeff') # 確保 Excel 開啟時不亂碼
    writer = csv.writer(output)
    writer.writerow(['單字', '難度', '詞性', '音標', '中文翻譯', 'AI老師解釋與例句'])
    for word, info in data.items():
        writer.writerow([word.upper(), info.get('level',''), info.get('pos',''), info.get('phonetic',''), info.get('chinese',''), info.get('definition','')])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')), mimetype='text/csv', as_attachment=True, download_name="智慧學習清單.csv")

if __name__ == '__main__':
    # 支援雲端平台自動分配 Port
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
