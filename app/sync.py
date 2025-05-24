import os
import ftplib
import json
import datetime
import time
from pathlib import Path

FTP_HOST = os.getenv("FTP_HOST")
FTP_USER = os.getenv("FTP_USER")
FTP_PASS = os.getenv("FTP_PASS")
FTP_REMOTE_BASE_PATH = os.getenv("FTP_REMOTE_PATH", "/public_html/viewer/")
FTP_USE_TLS = os.getenv("FTP_USE_TLS", "true").lower() == "true"

BASE_DIR_SYNC = Path(__file__).resolve().parent.parent
LOCAL_SCORES_JSON = BASE_DIR_SYNC / "scores.json"
LOCAL_DELETE_REQUESTS_JSON = BASE_DIR_SYNC / "delete_requests.json"
LOCAL_THUMBNAILS_DIR = BASE_DIR_SYNC / "images" / "thumbnails"
LOG_DIR = BASE_DIR_SYNC / "logs"
SYNC_LOG_FILE = LOG_DIR / "sync.log"
ERROR_LOG_FILE = LOG_DIR / "error.log"

REMOTE_SCORES_JSON_STR = str(Path(FTP_REMOTE_BASE_PATH) / "scores.json").replace("\\", "/")
REMOTE_DELETE_REQUESTS_JSON_STR = str(Path(FTP_REMOTE_BASE_PATH) / "delete_requests.json").replace("\\", "/")
REMOTE_THUMBNAILS_DIR_STR = str(Path(FTP_REMOTE_BASE_PATH) / "cloude_image" / "thumbnails").replace("\\", "/")
REMOTE_SYNC_LOCK_FILE_STR = str(Path(FTP_REMOTE_BASE_PATH) / "sync.lock").replace("\\", "/")

LOG_DIR.mkdir(parents=True, exist_ok=True) # LOG_DIRの作成を保証
def log_message(message, is_error=False):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}"
    print(log_entry)
    log_file = ERROR_LOG_FILE if is_error else SYNC_LOG_FILE
    try:
        with open(log_file, 'a', encoding='utf-8') as f: f.write(log_entry + "\n")
    except Exception as e: print(f"ログ書込エラー: {e}")

def get_ftp_connection():
    if not all([FTP_HOST, FTP_USER, FTP_PASS]):
        log_message("FTP接続情報不足 (.env確認)。同期スキップ。", is_error=True); return None
    try:
        ftp = ftplib.FTP_TLS(timeout=15) if FTP_USE_TLS else ftplib.FTP(timeout=15) # タイムアウト設定
        ftp.connect(FTP_HOST) # ポートは通常自動
        ftp.login(FTP_USER, FTP_PASS)
        if FTP_USE_TLS: ftp.prot_p()
        log_message(f"FTP{'S' if FTP_USE_TLS else ''}接続成功: {FTP_HOST}"); return ftp
    except Exception as e: log_message(f"FTP接続失敗: {e}", is_error=True); return None

def ftp_makedirs_recursive(ftp, remote_dir_path_str):
    parts = Path(remote_dir_path_str).parts; current_ftp_path = ""
    if remote_dir_path_str.startswith("/"): current_ftp_path = "/" # 絶対パスの場合
    
    for part in parts:
        if not part or part == '/': continue
        if not current_ftp_path or current_ftp_path == "/": current_ftp_path = part if current_ftp_path == "/" else "/" + part
        else: current_ftp_path = f"{current_ftp_path}/{part}"
        try: ftp.nlst(current_ftp_path)
        except ftplib.error_perm as e_nlst:
            if "550" in str(e_nlst):
                try: ftp.mkd(current_ftp_path); log_message(f"FTPディレクトリ作成: {current_ftp_path}")
                except ftplib.error_perm as e_mkd: log_message(f"FTPディレクトリ作成失敗: {current_ftp_path}, Error: {e_mkd}", is_error=True); return False
            else: log_message(f"FTPディレクトリ確認エラー ({current_ftp_path}): {e_nlst}", is_error=True); return False
    return True

def ftp_upload_file(ftp, local_path_obj: Path, remote_path_full_str: str):
    if not local_path_obj.exists(): log_message(f"アップロード対象なし: {local_path_obj}", is_error=True); return False
    remote_dir_str = str(Path(remote_path_full_str).parent).replace("\\","/")
    remote_filename = Path(remote_path_full_str).name
    tmp_remote_path_str = str(Path(remote_dir_str) / f"tmp_{remote_filename}_{int(time.time())}").replace("\\","/")
    try:
        if not ftp_makedirs_recursive(ftp, remote_dir_str): log_message(f"リモートディレクトリ作成失敗、中止: {remote_dir_str}", is_error=True); return False
        with open(local_path_obj, 'rb') as f: ftp.storbinary(f'STOR {tmp_remote_path_str}', f, blocksize=8192) # blocksize追加
        ftp.rename(tmp_remote_path_str, remote_path_full_str)
        log_message(f"FTPアップロード成功: {local_path_obj.name} -> {remote_path_full_str}"); return True
    except Exception as e:
        log_message(f"FTPアップロード失敗 ({local_path_obj.name} -> {remote_path_full_str}): {e}", is_error=True)
        try: ftp.delete(tmp_remote_path_str)
        except: pass
        return False

def ftp_download_file(ftp, remote_path_full_str: str, local_path_obj: Path):
    local_path_obj.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(local_path_obj, 'wb') as f: ftp.retrbinary(f'RETR {remote_path_full_str}', f.write, blocksize=8192)
        log_message(f"FTPダウンロード成功: {remote_path_full_str} -> {local_path_obj.name}"); return True
    except Exception as e:
        log_message(f"FTPダウンロード失敗 ({remote_path_full_str} -> {local_path_obj.name}): {e}", is_error=True)
        # ダウンロード失敗時はローカルファイルを削除する方が良い場合がある
        if local_path_obj.exists(): local_path_obj.unlink(missing_ok=True)
        return False

def ftp_create_lock(ftp):
    try: from io import BytesIO; ftp.storbinary(f'STOR {REMOTE_SYNC_LOCK_FILE_STR}', BytesIO(b"locked")); return True
    except Exception as e: log_message(f"FTPロック作成失敗: {e}", is_error=True); return False
def ftp_remove_lock(ftp):
    try: ftp.delete(REMOTE_SYNC_LOCK_FILE_STR); return True
    except Exception as e:
        if "550" in str(e): return True # 既にない
        log_message(f"FTPロック削除失敗: {e}", is_error=True); return False
def ftp_check_lock(ftp):
    try: return Path(REMOTE_SYNC_LOCK_FILE_STR).name in ftp.nlst(str(Path(REMOTE_SYNC_LOCK_FILE_STR).parent))
    except ftplib.error_perm as e: return False if "550" in str(e) else True # 不明時はロック有とみなす
    except Exception as e: log_message(f"FTPロック確認エラー: {e}", is_error=True); return True

def synchronize_all(progress_callback=None):
    log_message("同期処理開始..."); ftp = get_ftp_connection()
    if not ftp: return False, "FTP接続失敗"
    if progress_callback: progress_callback.emit(5)
    if ftp_check_lock(ftp): ftp.quit(); return False, "リモートロックあり"
    if not ftp_create_lock(ftp): ftp.quit(); return False, "FTPロック作成失敗"
    if progress_callback: progress_callback.emit(10)

    if not ftp_download_file(ftp, REMOTE_DELETE_REQUESTS_JSON_STR, LOCAL_DELETE_REQUESTS_JSON):
        log_message(f"{REMOTE_DELETE_REQUESTS_JSON_STR} プル失敗。空リクエストとして処理。")
        try: LOCAL_DELETE_REQUESTS_JSON.write_text("[]", encoding='utf-8')
        except Exception as e: log_message(f"ローカル空delete_requests作成失敗: {e}",is_error=True); ftp_remove_lock(ftp); ftp.quit(); return False, "ローカルdelete_requests作成失敗"
    if progress_callback: progress_callback.emit(25)

    if LOCAL_SCORES_JSON.exists():
        if not ftp_upload_file(ftp, LOCAL_SCORES_JSON, REMOTE_SCORES_JSON_STR): log_message("scores.json アップロード失敗", is_error=True)
    else: log_message(f"{LOCAL_SCORES_JSON} ローカルに存在せず。スキップ。")
    if progress_callback: progress_callback.emit(50)

    uploaded_thumbs, failed_thumbs = 0, 0
    if LOCAL_THUMBNAILS_DIR.exists():
        local_thumbs = [f for f in LOCAL_THUMBNAILS_DIR.iterdir() if f.is_file() and f.suffix.lower() == '.jpg']
        total_thumbs = len(local_thumbs)
        for i, thumb_path_obj in enumerate(local_thumbs):
            remote_thumb_path_str = str(Path(REMOTE_THUMBNAILS_DIR_STR) / thumb_path_obj.name).replace("\\","/")
            if ftp_upload_file(ftp, thumb_path_obj, remote_thumb_path_str): uploaded_thumbs +=1
            else: failed_thumbs +=1
            if progress_callback and total_thumbs > 0: progress_callback.emit(50 + int((i+1)/total_thumbs * 35))
    log_message(f"サムネイルアップロード: {uploaded_thumbs}成功, {failed_thumbs}失敗")
    if progress_callback: progress_callback.emit(85)

    temp_empty_del_req = BASE_DIR_SYNC / f"temp_empty_del_{int(time.time())}.json" # 一時ファイル名重複回避
    try:
        temp_empty_del_req.write_text("[]", encoding='utf-8')
        if not ftp_upload_file(ftp, temp_empty_del_req, REMOTE_DELETE_REQUESTS_JSON_STR): log_message("空delete_requests.json プッシュ失敗", is_error=True)
    except Exception as e: log_message(f"空delete_requests準備/プッシュエラー: {e}", is_error=True)
    finally: temp_empty_del_req.unlink(missing_ok=True)
    if progress_callback: progress_callback.emit(95)

    if not ftp_remove_lock(ftp): log_message("FTPロック削除失敗", is_error=True)
    ftp.quit(); log_message("同期処理完了。")
    if progress_callback: progress_callback.emit(100)
    return True, f"同期完了 ({failed_thumbs}サムネイル失敗)" if failed_thumbs > 0 else "同期成功"

if __name__ == '__main__':
    log_message("--- Sync Module Test ---")
    if not all([FTP_HOST, FTP_USER, FTP_PASS]): log_message("FTP認証情報未設定。テストスキップ。", is_error=True)
    else:
        (BASE_DIR_SYNC / "images_test_sync").mkdir(exist_ok=True) # テスト用ディレクトリ
        LOCAL_SCORES_JSON.write_text(json.dumps({"test_sync_main": {"score":1.0}}), encoding='utf-8')
        success, message = synchronize_all(lambda p: print(f"Test Progress: {p}%"))
        log_message(f"テスト同期結果: Success={success}, Message='{message}'")
    log_message("--- Sync Module Test End ---")
