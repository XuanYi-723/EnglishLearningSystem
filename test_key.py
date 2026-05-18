import os
from dotenv import load_dotenv
from google import genai

# 載入 .env 檔案中的環境變數
load_dotenv()
api_key = os.environ.get("GOOGLE_API_KEY")

if not api_key:
    print("❌ 找不到 GOOGLE_API_KEY，請確認 .env 檔案設定是否正確。")
else:
    try:
        # 建立 Client 進行連線測試
        client = genai.Client(api_key=api_key)
        print("✅ 金鑰有效！連線成功。\n")
        
        print("這把金鑰支援以下模型 (列出前 10 個)：")
        count = 0
        for model in client.models.list():
            print(f"- {model.name}")
            count += 1
            if count >= 10: 
                break
                
    except Exception as e:
        print(f"❌ 金鑰驗證失敗，發生錯誤：{e}")
