# English Learning App

這是一個基於 Flask 開發的英文學習輔助應用程式。它可以分析使用者輸入的英文文本，提取關鍵單字，並自動獲取音標、英文解釋以及繁體中文翻譯。

## 功能特色
- **文本分析**: 使用 `spaCy` 進行自然語言處理，自動過濾常見的停用詞（Stop Words），提取有學習價值的英文單字。
- **單字資訊提取**: 整合 [Dictionary API](https://dictionaryapi.dev/)，自動獲取單字的音標與英文解釋。
- **自動翻譯**: 透過 `deep-translator` (Google Translate) 自動將單字和英文解釋翻譯為繁體中文。
- **單字高亮 (Highlighting)**: 自動在原始文本中將提取出的關鍵單字標記醒目提示。
- **跨域支援**: 使用 `Flask-CORS` 支援前端跨來源請求。

## 技術棧
- **後端**: Python, Flask, Flask-CORS
- **NLP 處理**: spaCy (`en_core_web_sm` 模型)
- **翻譯模組**: deep-translator
- **前端**: HTML/JS (渲染位於 `templates/index.html` 的介面)

## 安裝與執行

1. **安裝依賴套件**:
   請確認已安裝 Python 環境，然後在終端機執行以下指令安裝所需套件：
   ```bash
   pip install -r requirements.txt
   ```

2. **啟動伺服器**:
   ```bash
   python app.py
   ```
   > **注意**: 首次執行時，若系統找不到 `spaCy` 的英文語言模型 (`en_core_web_sm`)，會自動進行下載，可能需要稍候片刻。

3. **開啟應用程式**:
   伺服器啟動後，請開啟瀏覽器並前往 `http://localhost:5000` 即可開始使用。

## 專案結構
- `app.py`: Flask 後端主程式，處理路由、API 請求與文本分析邏輯。
- `requirements.txt`: 專案所需的 Python 套件列表。
- `templates/index.html`: 前端使用者介面。
