import functools
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
import spacy
import requests
from deep_translator import GoogleTranslator 
import re
import time
import sqlite3
import os
from fpdf import FPDF

app = Flask(__name__)
CORS(app)

# 1. 記憶體優化：關閉不必要的 NLP 組件
try:
    nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])
except:
    import spacy.cli
    spacy.cli.download("en_core_web_sm")
    nlp = spacy.load("en_core_web_sm", disable=["ner", "parser"])

# 2. 效能優化：使用快取減少網路延遲
@functools.lru_cache(maxsize=1024)
def get_cached_translation(text):
    if not text or text == "No definition found": return "無解釋"
    return GoogleTranslator(source='auto', target='zh-TW').translate(text)

@functools.lru_cache(maxsize=1024)
def get_cached_word_info(word):
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    try:
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            data = response.json()
            phonetic = data[0].get('phonetic', 'N/A')
            definition = data[0]['meanings'][0]['definitions'][0].get('definition', 'No definition found')
            return phonetic, definition
    except:
        pass
    return "N/A", "No definition found"

def get_word_level(word):
    length = len(word)
    if length <= 4: return "簡單"
    if length <= 7: return "中等"
    return "困難"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    text = data.get('text', '')
    target_level = data.get('level', '全部')
    
    if not text: return jsonify({"error": "No text"}), 400

    doc = nlp(text)
    vocab_results = {}
    
    # 使用 context manager 確保資料庫資源正確釋放
    with sqlite3.connect('learning_data.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS vocab_history 
                     (word TEXT PRIMARY KEY, level TEXT, chinese TEXT, appearance_count INTEGER)''')
        
        for token in doc:
            word_lower = token.text.lower()
            if token.is_alpha and not token.is_stop and len(word_lower) > 2:
                current_level = get_word_level(word_lower)
                
                # 僅處理符合使用者選擇難度的單字
                if target_level == "全部" or current_level == target_level:
                    if word_lower not in vocab_results:
                        phonetic, eng_def = get_cached_word_info(word_lower)
                        try:
                            chinese_word = get_cached_translation(word_lower)
                            chinese_def = get_cached_translation(eng_def)
                        except:
                            chinese_word, chinese_def = "翻譯中", "稍後再試"

                        vocab_results[word_lower] = {
                            "count": 1,
                            "pos": token.pos_,
                            "phonetic": phonetic,
                            "definition": chinese_def,
                            "chinese": chinese_word,
                            "level": current_level
                        }
                        c.execute("INSERT OR REPLACE INTO vocab_history VALUES (?, ?, ?, (SELECT appearance_count FROM vocab_history WHERE word=?)+1)", 
                                  (word_lower, current_level, chinese_word, word_lower))
                    else:
                        vocab_results[word_lower]["count"] += 1

    # 螢光筆標記
    highlighted_text = text
    for word in sorted(vocab_results.keys(), key=len, reverse=True):
        pattern = re.compile(rf'\b({re.escape(word)})\b', re.IGNORECASE)
        highlighted_text = pattern.sub(r'<mark>\1</mark>', highlighted_text)

    return jsonify({"highlighted": highlighted_text, "vocabulary": vocab_results})

@app.route('/export_pdf', methods=['POST'])
def export_pdf():
    data = request.json.get('vocabulary', {})
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(200, 10, txt="Smart English Learning Cards", ln=True, align='C')
    pdf.ln(10)

    for word, info in data.items():
        pdf.set_fill_color(240, 240, 240)
        pdf.set_font("Arial", 'B', 12)
        pdf.cell(0, 10, f" Word: {word.upper()} ({info['level']})", ln=True, fill=True)
        pdf.set_font("Arial", '', 10)
        pdf.cell(0, 8, f" POS: {info['pos']} | Phonetic: {info['phonetic']}", ln=True)
        pdf.multi_cell(0, 8, f" Meaning: {info['chinese']}")
        pdf.ln(5)
        if pdf.get_y() > 250: pdf.add_page()

    output_filename = "learning_cards.pdf"
    pdf.output(output_filename)
    return send_file(output_filename, as_attachment=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
