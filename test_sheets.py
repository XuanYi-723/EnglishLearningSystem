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
    
    # 檢查是否已配置 URL
    if not sheets_db.webapp_url:
        print("\n[提示] 尚未設定 Google Apps Script 網頁應用程式網址。")
        print("請在您的專案根目錄中，打開或建立 `.env` 檔案並加入以下設定：")
        print("GAS_WEBAPP_URL=https://script.google.com/macros/s/您的網頁應用程式ID/exec\n")
        return False
    
    # 檢查連線狀態
    if not sheets_db.initialized:
        print("\n[失敗] 無法連線到 Google Apps Script 網址。")
        print("請確認：")
        print("1. 您的 Apps Script 網址是否正確（結尾必須為 /exec，且不可為編輯器網址）。")
        print("2. 您在 Apps Script 專案中是否實作了 `function doPost(e)` 函式。")
        print("3. 在部署 Apps Script 時，「誰有權限存取 (Who has access)」是否設定為「任何人 (Anyone)」。")
        print("4. 每次修改 Apps Script 程式碼後，您是否有進行「新部署 (Manage Deployments -> Edit -> New Version)」以發佈最新代碼。")
        return False
    
    print("\n[成功] Google Apps Script 雲端資料庫連線成功！")
    print(f"已從試算表預載入的使用者數量: {len(sheets_db.users_cache)}")
    print(f"已從試算表預載入的單字快取數量: {len(sheets_db.word_cache)}")
    
    print("\n進行測試：嘗試在記憶體快取中查詢單字 'apple'...")
    apple_cache = sheets_db.get_cached_word("apple")
    if apple_cache:
        print(f"-> 找到快取: {apple_cache}")
    else:
        print("-> 快取中尚無 'apple'。")
        
    print("\n=== 測試結束 ===")
    return True

if __name__ == "__main__":
    test_db()
