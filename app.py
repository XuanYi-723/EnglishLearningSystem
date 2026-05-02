from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import spacy
import spacy.cli
import requests
from deep_translator import GoogleTranslator 
import re
import time

# 建立 Flask 應用程式實例
app = Flask(__name__)
# 啟用 CORS（跨來源資源共用），允許前端發送請求給後端 API
CORS(app)

# 初始化並載入 spacy 英文語言模型
try:
    # 嘗試載入小型英文模型
    nlp = spacy.load("en_core_web_sm")
except:
    # 若模型不存在，則自動進行下載並重新載入
    print("找不到模型，系統正在自動下載中...")
    spacy.cli.download("en_core_web_sm")
    nlp = spacy.load("en_core_web_sm")

# 定義停用詞集合（過濾掉常見且無實際分析價值的單字）
STOP_WORDS = {"i", "me", "my", "myself", "we", "our", "ours", "ourselves", "you", "your", "yours", "he", "him", "his", "she", "her", "hers", "it", "its", "they", "them", "their", "a", "an", "the", "am", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "but", "if", "or", "as", "until", "while", "of", "at", "by", "for", "with", "about", "to", "from", "in", "out", "on", "off", "when", "where", "why", "how", "all"}

def get_word_info(word):
    """
    透過 Dictionary API 取得單字的音標與英文解釋
    """
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{word}"
    try:
        # 發送 GET 請求，設定超時時間為 3 秒
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            # 提取音標，若無則回傳 'N/A'
            phonetic = data[0].get('phonetic', 'N/A')
            # 提取第一組定義，若無則回傳 'No definition found'
            definition = data[0]['meanings'][0]['definitions'][0].get('definition', 'No definition found')
            return phonetic, definition
    except:
        # 發生任何錯誤則忽略並回傳預設值
        pass
    return "N/A", "No definition found"

@app.route('/')
def index():
    """
    首頁路由，渲染前端介面 (index.html)
    """
    return render_template('index.html')

@app.route('/analyze', methods=['POST'])
def analyze():
    """
    接收前端傳來的文本，進行自然語言處理與單字分析
    """
    data = request.json
    text = data.get('text', '')
    
    # 若未提供文本，回傳 400 錯誤
    if not text:
        return jsonify({"error": "No text"}), 400

    # 使用 spacy 解析文本
    doc = nlp(text)
    vocab_results = {}

    # 走訪文本中的每一個 token（詞彙）
    for token in doc:
        word_lower = token.text.lower()
        
        # 過濾條件：必須為純字母字串、不在停用詞內，且長度大於 2
        if token.is_alpha and word_lower not in STOP_WORDS and len(word_lower) > 2:
            if word_lower not in vocab_results:
                # 1. 抓取英文音標與英文解釋
                phonetic, eng_def = get_word_info(word_lower)
                
                # 2. 強制翻譯：單字 & 解釋
                try:
                    # 將英文單字翻譯成繁體中文
                    chinese_word = GoogleTranslator(source='auto', target='zh-TW').translate(word_lower)
                    # 暫停 0.1 秒，避免過度頻繁請求被阻擋
                    time.sleep(0.1) 
                    
                    # 若有抓到英文解釋，則一併將解釋翻譯成繁體中文
                    if eng_def != "No definition found":
                        chinese_def = GoogleTranslator(source='auto', target='zh-TW').translate(eng_def)
                    else:
                        chinese_def = "找不到中文解釋"
                except Exception as e:
                    # 翻譯失敗時的防呆處理
                    print(f"翻譯出錯: {e}")
                    chinese_word = "翻譯超時"
                    chinese_def = "請稍後再試"

                # 將處理好的單字資訊存入結果字典
                vocab_results[word_lower] = {
                    "count": 1,
                    "pos": token.pos_,          # 詞性 (Part of Speech)
                    "phonetic": phonetic,       # 音標
                    "definition": chinese_def,  # 中文解釋
                    "chinese": chinese_word     # 中文翻譯
                }
            else:
                # 若單字已存在於字典中，則出現次數加 1
                vocab_results[word_lower]["count"] += 1

    # 螢光筆邏輯：將分析出的單字在原文中標記起來
    highlighted_text = text
    # 依單字長度由長到短排序，避免短單字替換到長單字的一部分（例如 'are' 與 'care'）
    sorted_keywords = sorted(vocab_results.keys(), key=len, reverse=True)
    
    for word in sorted_keywords:
        # 使用正則表達式，忽略大小寫，匹配完整的單字邊界 (\b)
        pattern = re.compile(rf'\b({re.escape(word)})\b', re.IGNORECASE)
        # 用 <mark> 標籤包覆匹配到的單字
        highlighted_text = pattern.sub(r'<mark>\1</mark>', highlighted_text)

    # 回傳 JSON 格式的分析結果
    return jsonify({
        "highlighted": highlighted_text,
        "vocabulary": vocab_results
    })

if __name__ == '__main__':
    # 啟動 Flask 伺服器，監聽所有 IP 的 5000 埠
    app.run(host='0.0.0.0', port=5000)