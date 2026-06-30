import sys
import os

# 確保可以導入目前目錄的模組
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

def test_db():
    print("=== 開始測試 Google Sheets 資料庫連線 ===")
    
    # 嘗試導入 sheets_db
    try:
        from sheets_db import sheets_db
    except Exception as e:
        print(f"錯誤：導入 sheets_db 失敗: {e}")
        return False
    
    # 檢查是否已初始化
    if not sheets_db.initialized:
        print("\n[提示] 資料庫尚未成功連接到 Google Sheets。")
        print("如果您想測試實際連線，請確保：")
        print("1. 已在環境變數設定 `GOOGLE_CREDS_JSON` (JSON字串) 與 `SPREADSHEET_KEY`。")
        print("2. 或是在此目錄放置 `credentials.json` 憑證檔，並在環境變數設定 `SPREADSHEET_NAME` (預設為 EnglishLearningSystemDB) 或 `SPREADSHEET_KEY`。")
        print("3. 已將您的 Google Sheets 共用給該 Service Account Email。\n")
        print("此狀態下，Flask 應用程式依然可以順利啟動，但需要設定後才能正常使用註冊與單字分析快取功能。")
        return True
    
    print("\n[成功] Google Sheets 已成功連線並初始化！")
    print(f"使用者快取數量: {len(sheets_db.users_cache)}")
    print(f"單字快取數量: {len(sheets_db.word_cache)}")
    
    # 進行簡單的唯讀或寫入測試
    print("\n進行測試：嘗試在記憶體快取查詢測試單字 'apple'...")
    apple_cache = sheets_db.get_cached_word("apple")
    if apple_cache:
        print(f"找到快取: {apple_cache}")
    else:
        print("快取中尚無 'apple'。")
        
    print("\n=== 測試結束 ===")
    return True

if __name__ == "__main__":
    test_db()
