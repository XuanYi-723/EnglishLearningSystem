import os
import json
import gspread
from google.oauth2.service_account import Credentials
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

class User(UserMixin):
    def __init__(self, user_id, username, password_hash):
        self.id = str(user_id)
        self.username = username
        self.password_hash = password_hash

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

class SheetsDatabase:
    def __init__(self):
        self.client = None
        self.spreadsheet = None
        
        self.users_sheet = None
        self.records_sheet = None
        self.cache_sheet = None
        
        # 記憶體快取，避免頻繁請求 Google Sheets API 導致 Rate Limit
        self.users_cache = {}        # username -> User object
        self.users_id_cache = {}     # user_id -> User object
        self.word_cache = {}         # word -> dict
        
        self.initialized = False
        self.init_db()

    def init_db(self):
        """初始化 Google Sheets 連線與工作表"""
        creds_json = os.environ.get("GOOGLE_CREDS_JSON")
        spreadsheet_key = os.environ.get("SPREADSHEET_KEY")
        spreadsheet_name = os.environ.get("SPREADSHEET_NAME", "EnglishLearningSystemDB")

        # 1. 載入憑證
        creds = None
        if creds_json:
            try:
                info = json.loads(creds_json)
                creds = Credentials.from_service_account_info(
                    info,
                    scopes=[
                        "https://www.googleapis.com/auth/spreadsheets",
                        "https://www.googleapis.com/auth/drive"
                    ]
                )
                print("成功：從環境變數 GOOGLE_CREDS_JSON 載入憑證。")
            except Exception as e:
                print(f"錯誤：解析環境變數 GOOGLE_CREDS_JSON 失敗: {e}")
        elif os.path.exists("credentials.json"):
            try:
                creds = Credentials.from_service_account_file(
                    "credentials.json",
                    scopes=[
                        "https://www.googleapis.com/auth/spreadsheets",
                        "https://www.googleapis.com/auth/drive"
                    ]
                )
                print("成功：從本地 credentials.json 檔案載入憑證。")
            except Exception as e:
                print(f"錯誤：載入本地 credentials.json 失敗: {e}")

        if not creds:
            print("警告：找不到 Google API 憑證，系統將無法連接 Google 試算表資料庫。請在環境變數或專案目錄中提供憑證。")
            return

        # 2. 授權並開啟試算表
        try:
            self.client = gspread.authorize(creds)
            if spreadsheet_key:
                self.spreadsheet = self.client.open_by_key(spreadsheet_key)
                print(f"成功：以金鑰開啟試算表 [{spreadsheet_key}]")
            else:
                # 嘗試以名稱開啟，如果沒找到就丟出 exception
                self.spreadsheet = self.client.open(spreadsheet_name)
                print(f"成功：以名稱開啟試算表 [{spreadsheet_name}]")
        except Exception as e:
            print(f"錯誤：無法開啟 Google 試算表。請確認服務帳戶已具有該試算表的編輯者權限。詳細錯誤: {e}")
            return

        # 3. 確認工作表存在，若不存在則建立
        try:
            self.users_sheet = self._get_or_create_sheet("Users", ["id", "username", "password_hash"])
            self.records_sheet = self._get_or_create_sheet("UsageRecords", ["id", "user_id", "timestamp", "level_requested", "article_snippet"])
            self.cache_sheet = self._get_or_create_sheet("WordCache", ["word", "chinese", "pos", "phonetic", "definition", "created_at"])
            
            # 4. 預載入資料到記憶體快取以提高效能
            self._preload_data()
            self.initialized = True
            print("Google 試算表資料庫初始化成功，資料已預載入記憶體。")
        except Exception as e:
            print(f"錯誤：初始化工作表失敗: {e}")

    def _get_or_create_sheet(self, title, headers):
        """取得工作表，若不存在則建立並填入表頭"""
        try:
            sheet = self.spreadsheet.worksheet(title)
            return sheet
        except gspread.exceptions.WorksheetNotFound:
            print(f"工作表 [{title}] 不存在，正在自動建立並填入表頭...")
            sheet = self.spreadsheet.add_worksheet(title=title, rows="1000", cols=str(len(headers)))
            sheet.append_row(headers)
            return sheet

    def _preload_data(self):
        """將 Users 與 WordCache 預載入至記憶體"""
        # 載入 Users
        try:
            user_rows = self.users_sheet.get_all_records()
            for r in user_rows:
                uid = str(r["id"])
                username = str(r["username"])
                pwd_hash = str(r["password_hash"])
                u = User(uid, username, pwd_hash)
                self.users_cache[username] = u
                self.users_id_cache[uid] = u
            print(f"已從試算表預載入 {len(self.users_cache)} 個使用者帳號。")
        except Exception as e:
            print(f"預載入使用者資料失敗: {e}")

        # 載入 WordCache
        try:
            cache_rows = self.cache_sheet.get_all_records()
            for r in cache_rows:
                word = str(r["word"]).strip().lower()
                self.word_cache[word] = {
                    "chinese": str(r["chinese"]),
                    "pos": str(r["pos"]),
                    "phonetic": str(r["phonetic"]),
                    "definition": str(r["definition"])
                }
            print(f"已從試算表預載入 {len(self.word_cache)} 個單字快取紀錄。")
        except Exception as e:
            print(f"預載入單字快取資料失敗: {e}")

    # ==================== 使用者 (User) 相關操作 ====================

    def get_user_by_id(self, user_id):
        user_id = str(user_id)
        return self.users_id_cache.get(user_id)

    def get_user_by_username(self, username):
        return self.users_cache.get(username)

    def create_user(self, username, password):
        """建立新使用者並寫入 Google Sheets"""
        if not self.initialized:
            raise RuntimeError("資料庫尚未初始化，無法建立使用者。")
        
        if username in self.users_cache:
            return None # 帳號已存在
        
        # 產生新的 id (簡單地用現有帳號數量 + 1)
        new_id = len(self.users_cache) + 1
        
        new_user = User(new_id, username, "")
        new_user.set_password(password)
        
        # 寫入 Google Sheet
        try:
            self.users_sheet.append_row([new_user.id, new_user.username, new_user.password_hash])
            
            # 更新快取
            self.users_cache[username] = new_user
            self.users_id_cache[str(new_user.id)] = new_user
            print(f"使用者 [{username}] 建立成功，並已同步寫入試算表。")
            return new_user
        except Exception as e:
            print(f"寫入使用者到試算表失敗: {e}")
            raise e

    # ==================== 使用紀錄 (UsageRecord) 相關操作 ====================

    def add_usage_record(self, user_id, level_requested, article_snippet):
        """新增使用紀錄 (單向寫入，不需讀取快取)"""
        if not self.initialized:
            print("警告：資料庫未初始化，無法記錄使用狀況。")
            return False
            
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            record_id = datetime.utcnow().strftime("%Y%m%d%H%M%S")
            self.records_sheet.append_row([record_id, str(user_id), timestamp, level_requested, article_snippet])
            return True
        except Exception as e:
            print(f"寫入使用紀錄失敗: {e}")
            return False

    # ==================== 單字快取 (WordCache) 相關操作 ====================

    def get_cached_word(self, word):
        """從記憶體快取查詢單字"""
        word = word.strip().lower()
        return self.word_cache.get(word)

    def get_cached_words(self, word_list):
        """批次查詢單字，回傳已快取的單字 dict 對應"""
        results = {}
        for w in word_list:
            w_lower = w.strip().lower()
            if w_lower in self.word_cache:
                results[w_lower] = self.word_cache[w_lower]
        return results

    def add_word_cache(self, word, chinese, pos, phonetic, definition):
        """新增單字快取，寫入 Google Sheet 並更新記憶體快取"""
        if not self.initialized:
            print("警告：資料庫未初始化，無法寫入單字快取。")
            return False
            
        word_lower = word.strip().lower()
        if word_lower in self.word_cache:
            return True # 已存在快取中，不重複寫入
            
        created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        
        # 寫入 Google Sheet
        try:
            self.cache_sheet.append_row([word_lower, chinese, pos, phonetic, definition, created_at])
            
            # 更新記憶體快取
            self.word_cache[word_lower] = {
                "chinese": chinese,
                "pos": pos,
                "phonetic": phonetic,
                "definition": definition
            }
            return True
        except Exception as e:
            print(f"寫入單字 [{word_lower}] 快取到試算表失敗: {e}")
            return False

# 建立全域的資料庫單例
sheets_db = SheetsDatabase()
