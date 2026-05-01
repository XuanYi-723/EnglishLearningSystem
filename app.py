from flask import Flask, request, jsonify, render_template #新增render_template
from flask_cors import CORS
import spacy
import requests
from googletrans import Translator
import re
import time

app = Flask(__name__)
CORS(app)

# 初始化
try:
    nlp = spacy.load("en_core_web_sm")
except:
    print("找不到模型，請執行: python -m spacy download en_core_web_sm")

# 初始化翻譯器
translator = Translator()

STOP_WORDS = {"i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your", "yours", "he", "him", "his", "she", "her", "hers", "it", "its", "they", "them", "their", "a", "an", "the", "am", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "but", "if", "or", "as", "until", "while", "of", "at", "by", "for", "with", "about", "to", "from", "in", "out", "on", "off", "when", "where", "why", "how", "all"}

def get_word_info(word):
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    try:
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            phonetic = data[0].get('phonetic', 'N/A')
            # 取得英文解釋
            definition = data[0]['meanings'][0]['definitions'][0].get('definition', 'No definition found')
            return phonetic, definition
    except:
        pass
    return "N/A", "No definition found"

@app.route('/') #新增首頁路由
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

    for token in doc:
        word_lower = token.text.lower()
        if token.is_alpha and word_lower not in STOP_WORDS and len(word_lower) > 2:
            if word_lower not in vocab_results:
                # 1. 抓取英文音標與英文解釋
                phonetic, eng_def = get_word_info(word_lower)
                
                # 2. 強制翻譯：單字 & 解釋 (加入重試機制)
                try:
                    # 翻譯單字
                    chinese_word = translator.translate(word_lower, dest='zh-tw').text
                    time.sleep(0.1) # 稍微停頓，避免被 Google 封鎖
                    
                    # 翻譯解釋 (如果原解釋不是 'No definition found')
                    if eng_def != "No definition found":
                        chinese_def = translator.translate(eng_def, dest='zh-tw').text
                    else:
                        chinese_def = "找不到中文解釋"
                except Exception as e:
                    print(f"翻譯出錯: {e}")
                    chinese_word = "翻譯超時"
                    chinese_def = "請稍後再試 (Google 翻譯繁忙)"

                vocab_results[word_lower] = {
                    "count": 1,
                    "pos": token.pos_,
                    "phonetic": phonetic,
                    "definition": chinese_def, # 這裡已經被替換成中文翻譯結果
                    "chinese": chinese_word
                }
            else:
                vocab_results[word_lower]["count"] += 1

    # 螢光筆邏輯
    highlighted_text = text
    sorted_keywords = sorted(vocab_results.keys(), key=len, reverse=True)
    for word in sorted_keywords:
        pattern = re.compile(rf'\b({re.escape(word)})\b', re.IGNORECASE)
        highlighted_text = pattern.sub(r'<mark>\1</mark>', highlighted_text)

    return jsonify({
        "highlighted": highlighted_text,
        "vocabulary": vocab_results
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)