import os
import requests
import json
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from dotenv import load_dotenv
load_dotenv()

class User(UserMixin):
    def __init__(self, user_id, username, password_hash):
        self.id = str(user_id)
        self.username = username
        self.password_hash = password_hash

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class GASDatabase:
    def __init__(self):
        self.webapp_url = os.environ.get("GAS_WEBAPP_URL")
        
        # 記憶體快取，用以降低對 Google Sheets API 的頻繁呼叫
        self.users_cache = {}        # username -> User object
        self.users_id_cache = {}     # user_id -> User object
        self.word_cache = {}         # word -> dict
        
        self.initialized = False
        if self.webapp_url:
            self.init_db()
        else:
            print("警告：未偵測到環境變數 GAS_WEBAPP_URL。系統將無法與 Google 試算表同步資料。")

    def init_db(self):
        """透過 GAS 網頁應用程式初始化並預先載入資料"""
        print(f"正在連線 Google Apps Script: {self.webapp_url[:45]}...")
        try:
            # 傳送初始化請求
            response = requests.post(
                self.webapp_url, 
                json={"action": "preload_data"}, 
                timeout=15
            )
            if response.status_code == 200:
                # 檢查是否為 HTML 錯誤頁面（例如「找不到以下函式：doPost」）
                if "doPost" in response.text and "Google Apps Script" in response.text:
                    print("\n[嚴重錯誤] 連線成功，但您的 Google Apps Script 尚未部署 doPost 函式！")
                    print("請確保您的 Apps Script 程式碼包含 `function doPost(e)`，並且已使用「新部署」發佈為網頁應用程式。\n")
                    return
                
                try:
                    data = response.json()
                except Exception as json_err:
                    print(f"錯誤：解析 Google Apps Script 回應 JSON 失敗。回應內容為：\n{response.text[:200]}")
                    return
                
                # 載入 Users
                users_list = data.get("users", [])
                for r in users_list:
                    uid = str(r.get("id", ""))
                    username = str(r.get("username", ""))
                    pwd_hash = str(r.get("password_hash", ""))
                    if uid and username:
                        u = User(uid, username, pwd_hash)
                        self.users_cache[username] = u
                        self.users_id_cache[uid] = u
                
                # 載入 WordCache
                cache_list = data.get("word_cache", [])
                for r in cache_list:
                    word = str(r.get("word", "")).strip().lower()
                    if word:
                        self.word_cache[word] = {
                            "chinese": str(r.get("chinese", "未知")),
                            "pos": str(r.get("pos", "-")),
                            "phonetic": str(r.get("phonetic", "-")),
                            "definition": str(r.get("definition", "無"))
                        }
                
                self.initialized = True
                print(f"成功：已從 Google Apps Script 載入 {len(self.users_cache)} 個使用者，{len(self.word_cache)} 個單字快取紀錄。")
            else:
                print(f"錯誤：Google Apps Script 連線失敗，HTTP 狀態碼: {response.status_code}")
        except Exception as e:
            print(f"錯誤：初始化 Google Apps Script 資料庫失敗: {e}")

    # ==================== 使用者 (User) 相關操作 ====================

    def get_user_by_id(self, user_id):
        user_id = str(user_id)
        return self.users_id_cache.get(user_id)

    def get_user_by_username(self, username):
        return self.users_cache.get(username)

    def create_user(self, username, password):
        """建立新使用者並寫入 GAS"""
        if not self.webapp_url:
            print("錯誤：未配置 GAS_WEBAPP_URL，無法寫入使用者。")
            return None
            
        if username in self.users_cache:
            return None
            
        # 本地生成新 ID
        new_id = len(self.users_cache) + 1
        new_user = User(new_id, username, "")
        new_user.set_password(password)
        
        try:
            payload = {
                "action": "create_user",
                "id": str(new_user.id),
                "username": new_user.username,
                "password_hash": new_user.password_hash
            }
            response = requests.post(self.webapp_url, json=payload, timeout=15)
            if response.status_code == 200:
                if "doPost" in response.text and "Google Apps Script" in response.text:
                    print("錯誤：GAS 缺少 doPost 函式，無法寫入使用者。")
                    return None
                
                res_data = response.json()
                if res_data.get("status") == "success":
                    # 同步更新記憶體快取
                    self.users_cache[username] = new_user
                    self.users_id_cache[str(new_user.id)] = new_user
                    print(f"使用者 [{username}] 建立成功，並已同步寫入 Google 試算表。")
                    return new_user
                else:
                    print(f"錯誤：GAS 寫入使用者失敗，回應: {response.text}")
                    return None
            else:
                print(f"錯誤：GAS 回應 HTTP {response.status_code}")
                return None
        except Exception as e:
            print(f"連線 GAS 建立使用者失敗: {e}")
            raise e

    # ==================== 使用紀錄 (UsageRecord) 相關操作 ====================

    def add_usage_record(self, user_id, level_requested, article_snippet):
        """新增使用紀錄 (發送 HTTP 請求給 GAS)"""
        if not self.webapp_url:
            return False
            
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        record_id = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        
        try:
            payload = {
                "action": "add_usage_record",
                "id": record_id,
                "user_id": str(user_id),
                "timestamp": timestamp,
                "level_requested": level_requested,
                "article_snippet": article_snippet
            }
            # 使用較短的 timeout 避免阻塞
            requests.post(self.webapp_url, json=payload, timeout=5)
            return True
        except Exception as e:
            print(f"發送使用紀錄至 GAS 失敗: {e}")
            return False

    # ==================== 單字快取 (WordCache) 相關操作 ====================

    def get_cached_word(self, word):
        """從記憶體快取查詢單字"""
        word = word.strip().lower()
        return self.word_cache.get(word)

    def get_cached_words(self, word_list):
        """批次查詢單字快取"""
        results = {}
        for w in word_list:
            w_lower = w.strip().lower()
            if w_lower in self.word_cache:
                results[w_lower] = self.word_cache[w_lower]
        return results

    def add_word_cache(self, word, chinese, pos, phonetic, definition):
        """將新單字翻譯寫入 Google Sheets 並更新記憶體快取"""
        if not self.webapp_url:
            return False
            
        word_lower = word.strip().lower()
        if word_lower in self.word_cache:
            return True # 已存在記憶體快取中
            
        created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            payload = {
                "action": "add_word_cache",
                "word": word_lower,
                "chinese": chinese,
                "pos": pos,
                "phonetic": phonetic,
                "definition": definition,
                "created_at": created_at
            }
            response = requests.post(self.webapp_url, json=payload, timeout=15)
            if response.status_code == 200:
                if "doPost" in response.text and "Google Apps Script" in response.text:
                    print("錯誤：GAS 缺少 doPost 函式，無法寫入單字快取。")
                    return False
                    
                res_data = response.json()
                if res_data.get("status") == "success":
                    # 同步更新記憶體快取
                    self.word_cache[word_lower] = {
                        "chinese": chinese,
                        "pos": pos,
                        "phonetic": phonetic,
                        "definition": definition
                    }
                    return True
                else:
                    print(f"錯誤：GAS 寫入單字快取 [{word_lower}] 失敗。")
                    return False
            else:
                print(f"錯誤：GAS 寫入單字快取失敗，HTTP {response.status_code}")
                return False
        except Exception as e:
            print(f"連線 GAS 寫入單字快取失敗: {e}")
            return False

# 建立全域的資料庫單例
sheets_db = GASDatabase()
