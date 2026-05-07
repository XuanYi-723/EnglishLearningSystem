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
import csv
import io
import random

app = Flask(__name__)
CORS(app)

try:
    nlp = spacy.load("en_core_web_sm")
except:
    import spacy.cli
    spacy.cli.download("en_core_web_sm")
    nlp = spacy.load("en_core_web_sm")

@functools.lru_cache(maxsize=1024)
def get_cached_translation(text):
    if not text or text == "No definition found": return "無解釋"
    try:
        return GoogleTranslator(source='auto', target='zh-TW').translate(text)
    except:
        return "翻譯中..."

@functools.lru_cache(maxsize=1024)
def get_cached_word_info(word):
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    try:
        response = requests.get(url, timeout=2)
        if response.status_code == 200:
            data = response.json()
            phonetic = data[0].get('phonetic', 'N/A')
            # 抓取第一筆例句
            example = "No example available."
            for meaning in data[0]['meanings']:
                for definition in meaning['definitions']:
                    if definition.get('example'):
                        example = definition.get('example')
                        break
            definition = data[0]['meanings'][0]['definitions'][0].get('definition', 'No definition found')
            return phonetic, definition, example
    except:
        pass
    return "N/A", "No definition found", "No example available."

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
    
    with sqlite3.connect('learning_data.db') as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS vocab_history 
                     (word TEXT PRIMARY KEY, level TEXT, chinese TEXT, appearance_count INTEGER)''')
        
        for token in doc:
            word_lower = token.text.lower()
            if token.is_alpha and not token.is_stop and len(word_lower) > 2:
                current_level = get_word_level(word_lower)
                if target_level == "全部" or current_level == target_level:
                    if word_lower not in vocab_results:
                        phonetic, eng_def, example = get_cached_word_info(word_lower)
                        chinese_word = get_cached_translation(word_lower)
                        chinese_def = get_cached_translation(eng_def)

                        # 判斷是否為抽象詞 (非名詞則視為抽象)
                        is_abstract = token.pos_ not in ["NOUN", "PROPN"]

                        vocab_results[word_lower] = {
                            "count": 1, "pos": token.pos_, "phonetic": phonetic,
                            "definition": chinese_def, "chinese": chinese_word, 
                            "level": current_level, "example": example,
                            "is_abstract": is_abstract
                        }
                        c.execute("INSERT OR REPLACE INTO vocab_history VALUES (?, ?, ?, (SELECT appearance_count FROM vocab_history WHERE word=?)+1)", 
                                  (word_lower, current_level, chinese_word, word_lower))
                    else:
                        vocab_results[word_lower]["count"] += 1

    highlighted_text = text
    for word in sorted(vocab_results.keys(), key=len, reverse=True):
        pattern = re.compile(rf'\b({re.escape(word)})\b', re.IGNORECASE)
        highlighted_text = pattern.sub(r'<mark>\1</mark>', highlighted_text)

    return jsonify({"highlighted": highlighted_text, "vocabulary": vocab_results})

@app.route('/export_data', methods=['POST'])
def export_csv():
    data = request.json.get('vocabulary', {})
    output = io.StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)
    writer.writerow(['單字', '難度', '詞性', '音標', '中文翻譯', '例句'])
    for word, info in data.items():
        writer.writerow([word.upper(), info['level'], info['pos'], info['phonetic'], info['chinese'], info['example']])
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode('utf-8-sig')), mimetype='text/csv', as_attachment=True, download_name='智慧單字學習清單.csv')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
