from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
import spacy
import requests
from deep_translator import GoogleTranslator 
import re
import time
import os
import sqlite3
from fpdf import FPDF

app = Flask(__name__)
CORS(app)

# 1. 初始化資料庫 (對應計畫書：學習數據追蹤)
def init_db():
    conn = sqlite3.connect('learning_data.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS vocab_history 
                 (word TEXT PRIMARY KEY, level TEXT, chinese TEXT, appearance_count INTEGER)''')
    conn.commit()
    conn.close()

init_db()

# 2. 載入 NLP 模型
try:
    nlp = spacy.load("en_core_web_sm")
except:
    import spacy.cli
    spacy.cli.download("en_core_web_sm")
    nlp = spacy.load("en_core_web_sm")

# 3. 難易度分級邏輯 (對應計畫書：適性化學習與分級機制)
def get_word_level(word):
    # 簡單演算法：根據長度與常用度初步判定
    common_basic = {"apple", "banana", "water", "school", "family", "happy", "study"}
    if word in common_basic or len(word) <= 4:
        return "基礎 (Level 1)"
    elif len(word) <= 7:
        return "進階 (Level 2)"
    else:
        return "挑戰 (Level 3)"

def get_word_info(word):
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            phonetic = data[0].get('phonetic', 'N/A')
            definition = data[0]['meanings'][0]['definitions'][0].get('definition', 'No definition found')
            return phonetic, definition
    except:
        pass
    return "N/A", "No definition found"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.json
    text = data.get('text', '')
    if not text:
        return jsonify({"error": "No text"}), 400

    doc = nlp(text)
    vocab_results = {}
    
    conn = sqlite3.connect('learning_data.db')
    c = conn.cursor()

    for token in doc:
        word_lower = token.text.lower()
        # 過濾停用詞與非字母
        if token.is_alpha and not token.is_stop and len(word_lower) > 2:
            if word_lower not in vocab_results:
                phonetic, eng_def = get_word_info(word_lower)
                level = get_word_level(word_lower)
                
                # 執行翻譯
                try:
                    chinese_word = GoogleTranslator(source='auto', target='zh-TW').translate(word_lower)
                    time.sleep(0.05) 
                    chinese_def = GoogleTranslator(source='auto', target='zh-TW').translate(eng_def) if eng_def != "No definition found" else "找不到解釋"
                except:
                    chinese_word, chinese_def = "翻譯超時", "請稍候再試"

                vocab_results[word_lower] = {
                    "count": 1,
                    "pos": token.pos_,
                    "phonetic": phonetic,
                    "definition": chinese_def,
                    "chinese": chinese_word,
                    "level": level
                }
                
                # 存入資料庫
                c.execute("INSERT OR REPLACE INTO vocab_history VALUES (?, ?, ?, (SELECT appearance_count FROM vocab_history WHERE word=?)+1)", 
                          (word_lower, level, chinese_word, word_lower))
            else:
                vocab_results[word_lower]["count"] += 1

    conn.commit()
    conn.close()

    # 螢光筆標記
    highlighted_text = text
    sorted_keywords = sorted(vocab_results.keys(), key=len, reverse=True)
    for word in sorted_keywords:
        pattern = re.compile(rf'\b({re.escape(word)})\b', re.IGNORECASE)
        highlighted_text = pattern.sub(r'<mark>\1</mark>', highlighted_text)

    return jsonify({"highlighted": highlighted_text, "vocabulary": vocab_results})

@app.route('/export_pdf', methods=['POST'])
def export_pdf():
    """對應計畫書：一鍵生成實體教案卡牌 (虛實整合)"""
    data = request.json.get('vocabulary', {})
    if not data:
        return jsonify({"error": "No data"}), 400

    pdf = FPDF()
    pdf.add_page()
    # 注意：PDF 預設不支援中文，若要顯示中文需在此載入字體檔 (.ttf)
    # 這裡先使用 Arial 並輸出英文與符號，中文內容會以拼音或提示呈現，除非你提供字體
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Smart English Learning Cards", ln=True, align='C')
    pdf.ln(10)

    for word, info in data.items():
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, f" Word: {word.upper()} ({info['level']})", ln=True, fill=True)
        
        pdf.set_font("Arial", '', 10)
        pdf.cell(0, 8, f" POS: {info['pos']} | Phonetic: {info['phonetic']}", ln=True)
        # 由於 FPDF 預設字體限制，建議在此輸出重要單字
        pdf.multi_cell(0, 8, f" Meaning: {info['chinese']}")
        pdf.ln(5)
        
        if pdf.get_y() > 250:
            pdf.add_page()

    output_filename = "learning_cards.pdf"
    pdf.output(output_filename)
    return send_file(output_filename, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
