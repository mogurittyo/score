import time
import os
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, LoggingEventHandler
from PySide6.QtCore import QObject, Signal, QThread, Slot
from pathlib import Path

WATCHED_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.heic', '.heif')

class WatcherSignals(QObject):
    new_image_detected = Signal(str)
    watcher_error = Signal(str)

class ImageDirEventHandler(FileSystemEventHandler):
    def __init__(self, signals_emitter):
        super().__init__()
        self.signals = signals_emitter
        self.last_event_time = {}

    def _is_image_file(self, file_path_str: str):
        p = Path(file_path_str)
        return p.is_file() and p.suffix.lower() in WATCHED_EXTENSIONS

    def _should_process_event(self, event_path_str: str):
        current_time = time.time()
        if event_path_str in self.last_event_time and \
           current_time - self.last_event_time[event_path_str] < 1.5:
            return False
        self.last_event_time[event_path_str] = current_time
        return True

    def on_created(self, event):
        if event.is_directory or not self._should_process_event(event.src_path):
            return
        if self._is_image_file(event.src_path):
            print(f"[FS Watcher] New image: {event.src_path}")
            self.signals.new_image_detected.emit(event.src_path)

    def on_moved(self, event):
        if event.is_directory: return
        if self._is_image_file(event.dest_path) and self._should_process_event(event.dest_path):
            print(f"[FS Watcher] Image moved/renamed to: {event.dest_path}")
            self.signals.new_image_detected.emit(event.dest_path)

class FileSystemWatcherThread(QThread):
    new_image_detected = Signal(str)
    watcher_error = Signal(str)

    def __init__(self, watch_path_str: str, parent=None):
        super().__init__(parent)
        self.watch_path = Path(watch_path_str)
        self.observer = None
        self._is_running = False
        self.internal_signals = WatcherSignals()
        self.internal_signals.new_image_detected.connect(self.new_image_detected)
        self.internal_signals.watcher_error.connect(self.watcher_error)

    def run(self):
        self._is_running = True
        print(f"[FS Watcher Thread] Starting watch: {self.watch_path}")
        if not self.watch_path.exists():
            try:
                self.watch_path.mkdir(parents=True, exist_ok=True)
                print(f"[FS Watcher Thread] Created dir: {self.watch_path}")
            except Exception as e:
                msg = f"監視対象ディレクトリ作成失敗: {self.watch_path}, Error: {e}"
                print(f"[FSWT] {msg}")
                self.watcher_error.emit(msg)
                self._is_running = False
                return
        
        event_handler = ImageDirEventHandler(signals_emitter=self.internal_signals)
        self.observer = Observer()
        self.observer.schedule(event_handler, str(self.watch_path), recursive=False)
        try:
            self.observer.start()
            print(f"[FSWT] Observer started for '{self.watch_path}'.")
            while self._is_running and self.observer.is_alive():
                time.sleep(0.5)
        except Exception as e:
            msg = f"ファイル監視エラー: {e}"
            print(f"[FSWT] {msg}")
            self.watcher_error.emit(msg)
        finally:
            if self.observer and self.observer.is_alive():
                self.observer.stop()
            if self.observer:
                self.observer.join()
            print("[FSWT] Observer stopped.")
        self._is_running = False
        print("[FSWT] Thread finished.")

    def stop_watcher(self):
        print("[FSWT] stop_watcher() called.")
        self._is_running = False

if __name__ == '__main__':
    test_dir_name = "images_test_watch_fs_fix3_rerun"
    test_dir = Path(__file__).resolve().parent.parent / test_dir_name
    test_dir.mkdir(parents=True, exist_ok=True)
    print(f"テスト監視対象: {test_dir}")

    def on_new_test_handler_fs(p: str): # 関数名を変更して衝突を避ける
        print(f"*** メイン(テスト): 新規画像！ -> {p} ***")

    def on_err_test_handler_fs(e: str): # 関数名を変更
        print(f"*** メイン(テスト): ウォッチャーエラー！ -> {e} ***")

    watcher_thread_instance_fs = FileSystemWatcherThread(str(test_dir)) # インスタンス名を変更
    watcher_thread_instance_fs.new_image_detected.connect(on_new_test_handler_fs)
    watcher_thread_instance_fs.watcher_error.connect(on_err_test_handler_fs)
    
    print("ウォッチャースレッド開始。ファイル操作でテスト。10秒後に停止。")
    watcher_thread_instance_fs.start()
    
    try:
        for i in range(10): 
            time.sleep(1)
            # print(f"...監視中 {i+1}/10...") # 毎秒のprintはログがうるさいのでコメントアウト
            if i == 2: 
                dummy_file = test_dir / f"dummy_fs_test_rerun_{int(time.time())}.png"
                try:
                    dummy_file.write_text("dummy content for fs test rerun")
                    print(f"\n[テスト] ダミーファイル作成: {dummy_file}\n")
                except Exception as e_write:
                    print(f"[テスト] ダミーファイル作成エラー: {e_write}")
        print("...監視中 (残り時間)...") # ループ後のメッセージ
    except KeyboardInterrupt:
        print("\n中断")
    finally:
        if watcher_thread_instance_fs.isRunning():
            watcher_thread_instance_fs.stop_watcher()
            if not watcher_thread_instance_fs.wait(2000): 
                 print("警告: ウォッチャースレッドが時間内に終了しませんでした。")
        print("テスト終了。")
