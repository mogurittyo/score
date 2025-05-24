import sys
import os
import json
import datetime
import time
import pandas as pd
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTabWidget,
    QPushButton, QLabel, QGridLayout, QScrollArea, QSlider,
    QMessageBox, QFileDialog, QProgressDialog, QSplitter,
    QTreeWidget, QTreeWidgetItem, QComboBox, QLineEdit, QGroupBox,
    QTextEdit, QProgressBar, QSpinBox, QDoubleSpinBox, QDialog,
    QDialogButtonBox, QSizePolicy, QInputDialog, QCheckBox, QFormLayout
)
from PySide6.QtGui import QPixmap, QIcon, QPainter, QAction, QDesktopServices, QColor, QBrush
from PySide6.QtCore import Qt, QSize, QTimer, Signal, QThread, Slot, QUrl, QSettings

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

from dotenv import load_dotenv, set_key, find_dotenv

APP_NAME = "AI画像スコアリング & 管理システム"
APP_VERSION = "1.1.3 (Syntax Fix)" # バージョン更新
BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE_PATH = find_dotenv(BASE_DIR / ".env", usecwd=True, raise_error_if_not_found=False)
if not ENV_FILE_PATH:
    ENV_FILE_PATH = str(BASE_DIR / ".env")
    with open(ENV_FILE_PATH, "w") as f:
        f.write("# AI Image Scorer Environment Variables\n")
        f.write("GOOGLE_API_KEY=\n"); f.write("FTP_HOST=\n"); f.write("FTP_USER=\n")
        f.write("FTP_PASS=\n"); f.write("FTP_REMOTE_PATH=/public_html/viewer/\n"); f.write("FTP_USE_TLS=true\n")
load_dotenv(ENV_FILE_PATH)

IMAGES_ORIGINALS_DIR = BASE_DIR / "images" / "originals"
IMAGES_THUMBNAILS_DIR = BASE_DIR / "images" / "thumbnails"
DELETED_DIR = BASE_DIR / "deleted"
SCORES_JSON_PATH = BASE_DIR / "scores.json"
METADATA_JSON_PATH = BASE_DIR / "metadata.json"
DELETE_REQUESTS_JSON_PATH = BASE_DIR / "delete_requests.json"
ASSETS_SOUNDS_DIR = BASE_DIR / "assets" / "sounds"
FILTERS_DIR = BASE_DIR / "filters"
PENALTIES_YML_PATH = BASE_DIR / "penalties.yml"
LOG_DIR = BASE_DIR / "logs"
MODELS_DIR = BASE_DIR / "models"

from . import scoring as scoring_module
from .fs_watcher import FileSystemWatcherThread, WATCHED_EXTENSIONS as FS_WATCHED_EXTENSIONS
from . import sync as sync_module
from . import analysis_dashboard as analysis_dashboard_module
from .gemini_analyzer import GeminiAnalyzer

scoring_module.WATCHED_EXTENSIONS = FS_WATCHED_EXTENSIONS

# --- スレッド定義 ---
class SyncThread(QThread): # 変更なし
    progress = Signal(int); finished = Signal(bool, str)
    def run(self): success, msg = sync_module.synchronize_all(progress_callback=self.progress); self.finished.emit(success, msg)

class ScoringAndMetadataThread(QThread): # 変更なし
    progress = Signal(int, int); image_processed = Signal(str, dict, dict); finished = Signal()
    def __init__(self, image_paths, penalties_config, parent=None):
        super().__init__(parent); self.image_paths = image_paths; self.penalties_config = penalties_config
        self._is_running = True
    def run(self):
        total = len(self.image_paths)
        for i, path_str in enumerate(self.image_paths):
            if not self._is_running: break
            path_obj = Path(path_str)
            if not path_obj.exists(): continue
            img_id, score_d, meta_d = scoring_module.process_single_image(str(path_obj), self.penalties_config)
            thumb_name = f"{img_id}.jpg"; thumb_p_str = str(IMAGES_THUMBNAILS_DIR / thumb_name)
            if scoring_module.generate_thumbnail(str(path_obj), thumb_p_str):
                score_d["thumbnail_path_local"] = thumb_p_str
                score_d["thumbnail_web_path"] = f"cloude_image/thumbnails/{thumb_name}"
            self.image_processed.emit(img_id, score_d, meta_d)
            self.progress.emit(i + 1, total)
        self.finished.emit()
    def stop(self): self._is_running = False

class ModelInitializationThread(QThread): # 変更なし
    initialization_progress = Signal(str, int)
    initialization_finished = Signal(bool)
    def __init__(self, force_cpu, parent=None):
        super().__init__(parent); self.force_cpu = force_cpu
    def run(self):
        try:
            scoring_module.initialize_all_models(force_cpu=self.force_cpu, progress_callback=self.initialization_progress)
            self.initialization_finished.emit(scoring_module.INITIALIZED_SUCCESSFULLY if hasattr(scoring_module, 'INITIALIZED_SUCCESSFULLY') else True)
        except Exception as e:
            self.initialization_progress.emit(f"モデル初期化中に致命的エラー: {e}", 100)
            self.initialization_finished.emit(False)

class GeminiAnalysisRunnerThread(QThread): # 変更なし
    analysis_progress = Signal(int); analysis_finished = Signal(str, bool); error_occurred = Signal(str)
    def __init__(self, data_df, prompt_template, api_key, parent=None):
        super().__init__(parent); self.data_df = data_df; self.prompt_template = prompt_template
        self.api_key = api_key; self.analyzer_instance = None
    def run(self):
        try:
            self.analyzer_instance = GeminiAnalyzer(api_key_val=self.api_key)
            self.analyzer_instance.signals.analysis_progress.connect(self.analysis_progress)
            self.analyzer_instance.signals.analysis_finished.connect(self.analysis_finished)
            self.analyzer_instance.signals.error_occurred.connect(self.error_occurred)
            self.analyzer_instance.analyze_data(self.data_df, self.prompt_template)
        except Exception as e: self.error_occurred.emit(f"Geminiスレッドエラー: {e}")
        finally:
            if self.analyzer_instance:
                for signal_attr, slot in [('analysis_progress', self.analysis_progress),
                                          ('analysis_finished', self.analysis_finished),
                                          ('error_occurred', self.error_occurred)]:
                    try: getattr(self.analyzer_instance.signals, signal_attr).disconnect(slot)
                    except RuntimeError: pass
    def cancel(self):
        if self.analyzer_instance: self.analyzer_instance.cancel_analysis()

class SettingsDialog(QDialog): # 変更なし
    def __init__(self, parent=None):
        super().__init__(parent); self.setWindowTitle("設定"); self.setMinimumWidth(500)
        layout = QVBoxLayout(self)
        env_group = QGroupBox(".env ファイル設定"); env_layout = QVBoxLayout(env_group)
        env_layout.addWidget(QLabel(f".env パス: {ENV_FILE_PATH}"))
        btn_open_env = QPushButton("テキストエディタで .env を開く"); btn_open_env.clicked.connect(self._open_env_file)
        env_layout.addWidget(btn_open_env)
        env_layout.addWidget(QLabel("FTP設定などを編集後、アプリ再起動で反映されます。"))
        layout.addWidget(env_group)
        gemini_group = QGroupBox("Gemini API 設定"); gemini_layout = QFormLayout(gemini_group)
        self.api_key_edit = QLineEdit(); self.api_key_edit.setPlaceholderText("Google AI Studio APIキー")
        self.api_key_edit.setEchoMode(QLineEdit.Password)
        self.current_api_key = os.getenv("GOOGLE_API_KEY", "")
        self.api_key_edit.setText(self.current_api_key)
        gemini_layout.addRow("Google API Key:", self.api_key_edit)
        layout.addWidget(gemini_group)
        penalties_group = QGroupBox("ペナルティ設定ファイル"); penalties_layout = QVBoxLayout(penalties_group)
        penalties_layout.addWidget(QLabel(f"penalties.yml パス: {PENALTIES_YML_PATH}"))
        btn_open_pen = QPushButton("テキストエディタで penalties.yml を開く"); btn_open_pen.clicked.connect(self._open_penalties_file)
        penalties_layout.addWidget(btn_open_pen)
        penalties_layout.addWidget(QLabel("変更は次回の画像処理時またはアプリ再起動時に反映。"))
        layout.addWidget(penalties_group)
        model_group = QGroupBox("AIモデル設定"); model_layout = QVBoxLayout(model_group)
        self.force_cpu_checkbox = QCheckBox("CPUでAI処理を強制実行 (GPUがあっても使用しない)")
        self.force_cpu_checkbox.setChecked(self.parent().settings.value("force_cpu", False, type=bool))
        model_layout.addWidget(self.force_cpu_checkbox)
        model_layout.addWidget(QLabel("変更はアプリ再起動後に有効になります。"))
        layout.addWidget(model_group)
        button_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept); button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    def _open_env_file(self): QDesktopServices.openUrl(QUrl.fromLocalFile(ENV_FILE_PATH))
    def _open_penalties_file(self): QDesktopServices.openUrl(QUrl.fromLocalFile(str(PENALTIES_YML_PATH)))
    def accept(self):
        new_api_key = self.api_key_edit.text().strip()
        if new_api_key != self.current_api_key:
            try:
                set_key(ENV_FILE_PATH, "GOOGLE_API_KEY", new_api_key); os.environ["GOOGLE_API_KEY"] = new_api_key
                QMessageBox.information(self, "保存完了", "APIキーを.envに保存しました。")
                self.parent().gemini_api_key_loaded = new_api_key
            except Exception as e: QMessageBox.critical(self, "保存エラー", f".envへのAPIキー保存失敗: {e}")
        self.parent().settings.setValue("force_cpu", self.force_cpu_checkbox.isChecked())
        super().accept()

class MainWindow(QMainWindow): # _update_dataframes_and_combined_view 以外は変更なし
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} - {APP_VERSION}"); self.setGeometry(50, 50, 1600, 900)
        self.settings = QSettings("AIImageScorerOrg", APP_NAME)
        self.all_scores_data = {}; self.all_metadata = {}; self.df_scores = pd.DataFrame()
        self.df_metadata = pd.DataFrame(); self.df_combined = pd.DataFrame()
        self.current_display_image_ids = []; self.delete_mode = False; self.penalties_config = {}
        self.gemini_api_key_loaded = os.getenv("GOOGLE_API_KEY", "")
        self.models_initialized_properly = False
        self._init_dirs_and_files(); self.penalties_config = scoring_module.load_penalties()
        self._init_ui(); self._load_all_data_from_json(); self._update_dataframes_and_combined_view()
        self.model_init_thread = ModelInitializationThread(force_cpu=self.settings.value("force_cpu", False, type=bool))
        self.model_init_thread.initialization_progress.connect(self.handle_model_init_progress)
        self.model_init_thread.initialization_finished.connect(self.handle_model_init_finished)
        self.model_init_thread.start()
        self.restoreGeometry(self.settings.value("geometry", self.saveGeometry(), type=bytes))
        self.restoreState(self.settings.value("windowState", self.saveState(), type=bytes))

    def _init_dirs_and_files(self):
        for p in [IMAGES_ORIGINALS_DIR, IMAGES_THUMBNAILS_DIR, DELETED_DIR, ASSETS_SOUNDS_DIR, LOG_DIR, FILTERS_DIR, MODELS_DIR]:
            p.mkdir(parents=True, exist_ok=True)
        if not PENALTIES_YML_PATH.exists():
            try:
                with open(PENALTIES_YML_PATH, 'w', encoding='utf-8') as f: f.write("# tags: penalty_value\n# example_tag: 1.0\n")
            except Exception as e: print(f"penalties.yml作成失敗: {e}")
        for p_obj, default_content_generator in [(SCORES_JSON_PATH, lambda: {}), (METADATA_JSON_PATH, lambda: {}), (DELETE_REQUESTS_JSON_PATH, lambda: [])]:
            if not p_obj.exists():
                try:
                    with open(p_obj, 'w', encoding='utf-8') as f: json.dump(default_content_generator(), f, indent=2)
                    print(f"空の {p_obj.name} を作成しました。")
                except Exception as e: print(f"{p_obj.name}作成失敗: {e}")

    def _init_ui(self):
        main_widget = QWidget(); self.setCentralWidget(main_widget); layout = QVBoxLayout(main_widget)
        menubar = self.menuBar(); file_menu = menubar.addMenu("&ファイル")
        settings_action = QAction(QIcon.fromTheme("preferences-system"), "設定(&S)...", self); settings_action.triggered.connect(self.open_settings_dialog)
        file_menu.addAction(settings_action); file_menu.addSeparator()
        exit_action = QAction(QIcon.fromTheme("application-exit"), "終了(&X)", self); exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        help_menu = menubar.addMenu("&ヘルプ")
        about_action = QAction(QIcon.fromTheme("help-about"),"このアプリについて(&A)", self); about_action.triggered.connect(self.show_about_dialog)
        help_menu.addAction(about_action)
        self.tab_widget = QTabWidget(); self.gallery_tab_widget = QWidget(); gallery_layout = QVBoxLayout(self.gallery_tab_widget)
        top_controls_layout = QHBoxLayout()
        self.sync_button = QPushButton(QIcon.fromTheme("view-refresh"), "サーバーと同期🔄"); self.sync_button.clicked.connect(self.perform_manual_sync)
        top_controls_layout.addWidget(self.sync_button)
        self.rescan_button = QPushButton(QIcon.fromTheme("document-open-recent"),"ローカル再スキャン"); self.rescan_button.clicked.connect(self._scan_and_process_new_images)
        top_controls_layout.addWidget(self.rescan_button)
        top_controls_layout.addWidget(QLabel("列数:"))
        self.columns_slider = QSlider(Qt.Horizontal)
        self.columns_slider.setMinimum(1); self.columns_slider.setMaximum(12); self.columns_slider.setValue(self.settings.value("gallery_columns", 4, type=int))
        self.columns_slider.valueChanged.connect(self.update_gallery_view); self.columns_slider.setFixedWidth(150)
        top_controls_layout.addWidget(self.columns_slider)
        self.delete_mode_button = QPushButton("削除モード OFF"); self.delete_mode_button.setCheckable(True); self.delete_mode_button.toggled.connect(self.toggle_delete_mode)
        top_controls_layout.addWidget(self.delete_mode_button); top_controls_layout.addStretch(); gallery_layout.addLayout(top_controls_layout)
        self.scroll_area = QScrollArea(); self.scroll_area.setWidgetResizable(True)
        self.gallery_widget_container = QWidget(); self.gallery_grid_layout = QGridLayout(self.gallery_widget_container)
        self.gallery_grid_layout.setAlignment(Qt.AlignTop | Qt.AlignLeft); self.scroll_area.setWidget(self.gallery_widget_container)
        gallery_layout.addWidget(self.scroll_area); self.tab_widget.addTab(self.gallery_tab_widget, "🖼️ ギャラリー")
        self.analysis_tab = AnalysisTab(self); self.tab_widget.addTab(self.analysis_tab, "📊 分析")
        layout.addWidget(self.tab_widget); self.status_bar_label = QLabel("準備完了"); self.statusBar().addWidget(self.status_bar_label)
        self.status_bar_progress = QProgressBar(); self.status_bar_progress.setVisible(False); self.status_bar_progress.setMaximumHeight(15)
        self.status_bar_progress.setMaximumWidth(200); self.statusBar().addPermanentWidget(self.status_bar_progress)

    @Slot(str, int)
    def handle_model_init_progress(self, message, percent):
        self.show_status_message(f"モデル初期化中: {message} ({percent}%)", 0)
        self.status_bar_progress.setVisible(True); self.status_bar_progress.setRange(0,100)
        self.status_bar_progress.setValue(percent)
    @Slot(bool)
    def handle_model_init_finished(self, success):
        self.status_bar_progress.setVisible(False); self.models_initialized_properly = success
        if success:
            self.show_status_message("AIモデルの初期化が完了しました。", 5000)
            self.perform_initial_sync(); self.start_fs_watcher()
            if not self.all_scores_data: self._scan_and_process_new_images()
        else:
            self.show_status_message("AIモデルの初期化に失敗。機能が限定されます。", 0)
            QMessageBox.warning(self, "モデル初期化エラー", "AIモデルの初期化に失敗しました。\nsetup_env.batの実行、モデル配置、ライブラリ互換性を確認してください。")
            self.perform_initial_sync(); self.start_fs_watcher()
    def show_status_message(self, message, timeout=3000):
        self.status_bar_label.setText(message)
        if timeout > 0: QTimer.singleShot(timeout, lambda: self.status_bar_label.setText("準備完了") if self.status_bar_label.text() == message else None)
    def _load_all_data_from_json(self):
        for path, attr_name, default_val_gen in [(SCORES_JSON_PATH, 'all_scores_data', lambda: {}), (METADATA_JSON_PATH, 'all_metadata', lambda: {}), (DELETE_REQUESTS_JSON_PATH, 'delete_requests_loaded_from_file', lambda: [])]:
            data = default_val_gen()
            if path.exists():
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if content.strip(): data = json.loads(content)
                        if attr_name.endswith('_data') and not isinstance(data, dict): data = default_val_gen()
                        if attr_name.startswith('delete_requests') and not isinstance(data, list): data = default_val_gen()
                except json.JSONDecodeError: print(f"JSONデコードエラー: {path}。デフォルト値を使用。")
                except Exception as e: print(f"ファイル読込エラー ({path}): {e}。デフォルト値を使用。")
            setattr(self, attr_name, data)
        self.show_status_message(f"{len(self.all_scores_data)}スコア, {len(self.all_metadata)}メタデータロード", 3000)

    def _update_dataframes_and_combined_view(self):
        # scores.json から DataFrame を作成
        if self.all_scores_data:
            df_s = pd.DataFrame.from_dict(self.all_scores_data, orient='index')
            if 'id' not in df_s.columns: # インデックスが 'id' になっていない場合 (通常はなる)
                df_s.index.name = 'id'
                self.df_scores = df_s.reset_index()
            else: # 'id' カラムが既に存在する場合 (キーも 'id' だった場合など)
                self.df_scores = df_s # そのまま使用
                if self.df_scores.index.name == 'id': # もしインデックス名も 'id' ならリセット
                    self.df_scores = self.df_scores.reset_index(drop=True) # 古いインデックスは削除
        else:
            self.df_scores = pd.DataFrame(columns=['id'])

        # metadata.json から DataFrame を作成
        if self.all_metadata:
            df_m = pd.DataFrame.from_dict(self.all_metadata, orient='index')
            if 'id' not in df_m.columns:
                df_m.index.name = 'id'
                self.df_metadata = df_m.reset_index()
            else:
                self.df_metadata = df_m
                if self.df_metadata.index.name == 'id':
                    self.df_metadata = self.df_metadata.reset_index(drop=True)
        else:
            self.df_metadata = pd.DataFrame(columns=['id'])

        # 結合 DataFrame を作成 (id をキーに)
        if not self.df_scores.empty and 'id' in self.df_scores.columns:
            if not self.df_metadata.empty and 'id' in self.df_metadata.columns:
                try:
                    # 両方に 'id' カラムがあることを確認してからマージ
                    self.df_combined = pd.merge(self.df_scores, self.df_metadata, on='id', how='left', suffixes=('_score', '_meta'))
                except Exception as e_merge:
                    print(f"DataFrameのマージ中にエラー: {e_merge}")
                    self.df_combined = self.df_scores.copy() # エラー時はスコアデータのみ
            else: # df_metadataが空かidカラムがない
                self.df_combined = self.df_scores.copy()
        elif not self.df_metadata.empty and 'id' in self.df_metadata.columns: # スコアが空でメタデータのみある場合
            self.df_combined = self.df_metadata.copy()
        else: # 両方空か、idカラムがない
            self.df_combined = pd.DataFrame()
        
        print(f"DataFrame更新: scores={len(self.df_scores)}, metadata={len(self.df_metadata)}, combined={len(self.df_combined)}")

        self.current_display_image_ids = list(self.all_scores_data.keys())
        if not self.df_scores.empty and 'score_final' in self.df_scores.columns and 'id' in self.df_scores.columns: # idカラムも確認
            try:
                sorted_ids = self.df_scores.sort_values(by='score_final', ascending=False)['id'].tolist()
                self.current_display_image_ids = [id_val for id_val in sorted_ids if id_val in self.all_scores_data]
            except Exception as e_sort:
                print(f"スコアでのソート中にエラー: {e_sort}. デフォルト順序を使用します。")
                self.current_display_image_ids.sort(key=lambda img_id: self.all_scores_data[img_id].get('score_final', 0), reverse=True)
        else:
            self.current_display_image_ids.sort(key=lambda img_id: self.all_scores_data[img_id].get('score_final', 0), reverse=True)
        self.update_gallery_view()
        if hasattr(self, 'analysis_tab') and self.analysis_tab:
            self.analysis_tab.update_dashboard(); self.analysis_tab.populate_filter_fields()

    def update_gallery_view(self):
        while self.gallery_grid_layout.count():
            item = self.gallery_grid_layout.takeAt(0); widget = item.widget();
            if widget: widget.deleteLater()
        num_cols = self.columns_slider.value();
        if num_cols == 0: num_cols = 1
        for i, img_id in enumerate(self.current_display_image_ids):
            data = self.all_scores_data.get(img_id)
            if not data: continue
            thumb_p_str = data.get("thumbnail_path_local")
            pix = QPixmap(thumb_p_str) if thumb_p_str and Path(thumb_p_str).exists() else None
            item_w = self._create_gallery_item_widget(img_id, pix, data.get("score_final", 0.0), data.get('filename', img_id))
            self.gallery_grid_layout.addWidget(item_w, i // num_cols, i % num_cols)
        self.gallery_widget_container.adjustSize()
    def _create_gallery_item_widget(self, image_id, pixmap, score, filename_hint):
        item_widget = QWidget(); item_layout = QVBoxLayout(item_widget)
        item_layout.setContentsMargins(3,3,3,3); item_widget.setFixedSize(150, 170)
        img_label = QLabel(); img_label.setFixedSize(140,140); img_label.setAlignment(Qt.AlignCenter)
        if pixmap and not pixmap.isNull(): img_label.setPixmap(pixmap.scaled(140, 140, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else: img_label.setText(f"{filename_hint[:15]}...\n(No Thumb)"); img_label.setStyleSheet("border: 1px dashed gray; color: gray; font-size: 8pt;")
        img_label.mousePressEvent = lambda event, img_id=image_id: self.on_image_clicked(event, img_id)
        item_layout.addWidget(img_label)
        info_layout = QHBoxLayout(); score_label = QLabel(f"S: {score:.2f}"); info_layout.addWidget(score_label)
        info_layout.addStretch(); item_layout.addLayout(info_layout)
        return item_widget
    def on_image_clicked(self, event, image_id):
        if self.delete_mode and event.button() == Qt.LeftButton: self.confirm_delete_single_image(image_id)
        elif not self.delete_mode : self.show_image_preview(image_id)
    def confirm_delete_single_image(self, image_id):
        if image_id not in self.all_scores_data: return
        filename = self.all_scores_data[image_id].get("filename", image_id)
        if QMessageBox.question(self, "画像削除の確認", f"'{filename}' を削除しますか？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self._perform_local_delete_and_request_web(image_id)
    def _perform_local_delete_and_request_web(self, image_id):
        if image_id not in self.all_scores_data: return
        data = self.all_scores_data[image_id]
        orig_p_str = data.get("path", str(IMAGES_ORIGINALS_DIR / data.get("filename","")))
        thumb_p_str = data.get("thumbnail_path_local")
        del_subdir = DELETED_DIR / datetime.datetime.now().strftime("%Y%m%d"); del_subdir.mkdir(exist_ok=True)
        try:
            orig_p = Path(orig_p_str)
            if orig_p.exists(): os.rename(orig_p, del_subdir / orig_p.name)
            if thumb_p_str and Path(thumb_p_str).exists(): Path(thumb_p_str).unlink(missing_ok=True)
        except Exception as e: print(f"ローカルファイル移動/削除エラー ({image_id}): {e}")
        if image_id in self.all_scores_data: del self.all_scores_data[image_id]
        if image_id in self.all_metadata: del self.all_metadata[image_id]
        del_reqs = []
        if DELETE_REQUESTS_JSON_PATH.exists():
            try:
                with open(DELETE_REQUESTS_JSON_PATH, 'r', encoding='utf-8') as f: del_reqs = json.load(f)
                if not isinstance(del_reqs, list): del_reqs = []
            except: del_reqs = []
        if not any(item.get("id") == image_id for item in del_reqs):
            del_reqs.append({"id": image_id, "filename": data.get("filename")})
        try:
            with open(DELETE_REQUESTS_JSON_PATH, 'w', encoding='utf-8') as f: json.dump(del_reqs, f, indent=2)
        except Exception as e: print(f"delete_requests.json書込エラー: {e}")
        self._save_all_data_to_json(); self._update_dataframes_and_combined_view()
        self.show_status_message(f"画像 '{data.get('filename', image_id)}' を削除しました。"); self.play_sound("delete_sound.wav")
    def _save_all_data_to_json(self):
        for path, data_dict in [(SCORES_JSON_PATH, self.all_scores_data), (METADATA_JSON_PATH, self.all_metadata)]:
            try:
                with open(path, 'w', encoding='utf-8') as f: json.dump(data_dict, f, indent=2, ensure_ascii=False)
            except Exception as e: QMessageBox.critical(self, "保存エラー", f"{path.name} 書込失敗: {e}")
    def perform_initial_sync(self):
        if not self.models_initialized_properly: self.show_status_message("モデル未初期化のため一部同期処理スキップの可能性", 0)
        self.show_sync_progress_dialog("起動時同期")
    def perform_manual_sync(self):
        if not self.models_initialized_properly: QMessageBox.warning(self, "モデル未初期化", "AIモデル未初期化。スコアリング関連同期は不完全かも。")
        self.show_sync_progress_dialog("手動同期")
    def show_sync_progress_dialog(self, title):
        self.status_bar_progress.setRange(0,100); self.status_bar_progress.setValue(0)
        self.status_bar_progress.setVisible(True); self.show_status_message(f"{title}開始...", 0)
        self.sync_thread = SyncThread(self)
        self.sync_thread.progress.connect(self.status_bar_progress.setValue)
        self.sync_thread.finished.connect(self.on_sync_finished)
        self.sync_thread.start()
    @Slot(bool, str)
    def on_sync_finished(self, success, message):
        self.status_bar_progress.setVisible(False)
        if success:
            self.show_status_message(f"最終同期: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} - {message}", 5000)
            self._process_pulled_delete_requests()
            if self.models_initialized_properly: self._scan_and_process_new_images()
            else: self.show_status_message("モデル未初期化のため新規画像スキャンはスキップ。", 0)
            self._save_all_data_to_json(); self._load_all_data_from_json(); self._update_dataframes_and_combined_view()
        else: self.show_status_message(f"同期失敗: {message}", 0)
    def _process_pulled_delete_requests(self):
        if not DELETE_REQUESTS_JSON_PATH.exists(): return
        try:
            with open(DELETE_REQUESTS_JSON_PATH, 'r', encoding='utf-8') as f: del_reqs = json.load(f)
            if not isinstance(del_reqs, list): del_reqs = []
        except: del_reqs = []
        if not del_reqs: return
        deleted_count = 0
        for item in list(del_reqs):
            img_id = item.get("id")
            if img_id and img_id in self.all_scores_data:
                self._perform_local_delete_and_request_web(img_id); deleted_count += 1
        if deleted_count > 0: self.show_status_message(f"{deleted_count}件の削除リクエスト処理完了。")
    def _scan_and_process_new_images(self):
        if not self.models_initialized_properly:
            QMessageBox.information(self, "処理スキップ", "AIモデルが初期化されていないため、新規画像のスコアリングは実行できません。"); self.show_status_message("モデル未初期化",0); return
        self.show_status_message("新規画像をスキャン中...", 0)
        to_process = [str(p) for p in IMAGES_ORIGINALS_DIR.glob("*") if p.suffix.lower() in FS_WATCHED_EXTENSIONS and p.stem not in self.all_scores_data]
        if not to_process: self.show_status_message("処理対象の新規画像なし。"); return
        self.status_bar_progress.setRange(0, len(to_process)); self.status_bar_progress.setValue(0)
        self.status_bar_progress.setVisible(True); self.show_status_message(f"{len(to_process)}件の新規画像を処理中...", 0)
        if hasattr(self, 'scoring_thread') and self.scoring_thread and self.scoring_thread.isRunning():
            QMessageBox.information(self, "処理中", "現在別の画像処理が実行中です。完了後に再度お試しください。"); return
        self.scoring_thread = ScoringAndMetadataThread(to_process, self.penalties_config)
        self.scoring_thread.progress.connect(lambda curr, total: self.status_bar_progress.setValue(curr))
        self.scoring_thread.image_processed.connect(self.on_single_image_processed)
        self.scoring_thread.finished.connect(self.on_all_images_processed)
        self.scoring_thread.start()
    @Slot(str, dict, dict)
    def on_single_image_processed(self, image_id, score_data, metadata):
        self.all_scores_data[image_id] = score_data; self.all_metadata[image_id] = metadata
    @Slot()
    def on_all_images_processed(self):
        self.status_bar_progress.setVisible(False); self.show_status_message("新規画像の処理完了。", 3000)
        self._save_all_data_to_json(); self._update_dataframes_and_combined_view()
        QMessageBox.information(self, "処理完了", "新規画像の処理が完了しました。")
    def start_fs_watcher(self):
        self.fs_watcher_thread = FileSystemWatcherThread(str(IMAGES_ORIGINALS_DIR))
        self.fs_watcher_thread.new_image_detected.connect(self.handle_new_image_from_watcher)
        self.fs_watcher_thread.watcher_error.connect(lambda err_msg: self.show_status_message(f"監視エラー: {err_msg}", 0))
        self.fs_watcher_thread.start()
        self.show_status_message(f"{IMAGES_ORIGINALS_DIR.name} の監視を開始。", 3000)
    @Slot(str)
    def handle_new_image_from_watcher(self, image_path_str):
        self.show_status_message(f"新規画像検出: {Path(image_path_str).name}", 0)
        if self.models_initialized_properly: self._scan_and_process_new_images()
        else: self.show_status_message(f"モデル未初期化のため、{Path(image_path_str).name}の自動処理スキップ。",0)
    def toggle_delete_mode(self, checked):
        self.delete_mode = checked; self.delete_mode_button.setText("削除モード ON" if checked else "削除モード OFF")
        self.delete_mode_button.setStyleSheet("background-color: red; color: white;" if checked else "")
        self.show_status_message("削除モード " + ("有効" if checked else "無効"))
    def open_settings_dialog(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            self.gemini_api_key_loaded = os.getenv("GOOGLE_API_KEY", "")
            self.penalties_config = scoring_module.load_penalties()
            self.show_status_message("設定を保存。一部は再起動後に有効。", 3000)
            if hasattr(self.analysis_tab, 'gemini_thread') and self.analysis_tab.gemini_thread:
                 if self.analysis_tab.gemini_thread.isRunning(): self.analysis_tab.gemini_thread.cancel()
                 self.analysis_tab.gemini_thread = None
    def play_sound(self, sound_filename):
        try:
            from PySide6.QtMultimedia import QSoundEffect
            sound_path = str(ASSETS_SOUNDS_DIR / sound_filename)
            if Path(sound_path).exists():
                effect = QSoundEffect(); effect.setSource(QUrl.fromLocalFile(sound_path))
                effect.setVolume(self.settings.value("sound_volume", 0.7, type=float))
                effect.play()
        except ImportError: print("QtMultimediaモジュールが見つかりません。効果音は再生されません。")
        except Exception as e: print(f"効果音再生エラー: {e}")
    def show_image_preview(self, image_id):
        if image_id not in self.all_scores_data: return
        orig_p_str = self.all_scores_data[image_id].get("path", "")
        if not orig_p_str or not Path(orig_p_str).exists(): QMessageBox.warning(self, "エラー", "元画像なし"); return
        dialog = QDialog(self); dialog.setWindowTitle(f"拡大表示: {Path(orig_p_str).name}"); dialog.setMinimumSize(800, 600)
        layout = QVBoxLayout(dialog); from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem
        scene = QGraphicsScene(); pixmap = QPixmap(orig_p_str)
        if pixmap.isNull(): QMessageBox.warning(self, "エラー", "画像読込失敗"); return
        item = QGraphicsPixmapItem(pixmap); scene.addItem(item); view = QGraphicsView(scene)
        view.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform); view.setDragMode(QGraphicsView.ScrollHandDrag)
        view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse); layout.addWidget(view)
        dialog.resize(min(pixmap.width() + 40, self.width() - 100), min(pixmap.height() + 40, self.height() - 100))
        view.fitInView(item, Qt.KeepAspectRatio); dialog.exec()
    def show_about_dialog(self):
        QMessageBox.about(self, "このアプリについて", f"{APP_NAME} - Ver {APP_VERSION}\n\nAI生成画像のスコアリングと管理システム。\n(C) 2024-2025")
    def closeEvent(self, event):
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.settings.setValue("gallery_columns", self.columns_slider.value())
        active_threads = []
        for thread_attr in ['fs_watcher_thread', 'model_init_thread', 'scoring_thread', 'sync_thread']:
            thread = getattr(self, thread_attr, None)
            if thread and thread.isRunning(): active_threads.append(thread)
        if hasattr(self.analysis_tab, 'gemini_thread') and self.analysis_tab.gemini_thread and self.analysis_tab.gemini_thread.isRunning():
            active_threads.append(self.analysis_tab.gemini_thread)
        if active_threads:
            self.show_status_message("バックグラウンド処理を終了中...", 0)
            for thread in active_threads:
                if hasattr(thread, 'stop_watcher'): thread.stop_watcher()
                elif hasattr(thread, 'stop'): thread.stop()
                elif hasattr(thread, 'cancel'): thread.cancel()
                thread.quit(); thread.wait(1500)
        QApplication.instance().quit(); event.accept()

class AnalysisTab(QWidget): # _update_filter_status, apply_filters 以外は変更なし
    def __init__(self, main_window_ref):
        super().__init__(); self.main_window = main_window_ref; self.filtered_df = pd.DataFrame()
        self.gemini_thread = None; self._init_ui()
    def _init_ui(self):
        layout = QVBoxLayout(self); splitter = QSplitter(Qt.Vertical)
        dashboard_group = QGroupBox("全量ビュー (自動更新)"); dashboard_layout = QHBoxLayout(dashboard_group)
        self.hist_canvas = FigureCanvas(Figure(figsize=(5,3))); dashboard_layout.addWidget(self.hist_canvas, 1)
        self.tags_text_edit = QTextEdit(); self.tags_text_edit.setReadOnly(True); dashboard_layout.addWidget(self.tags_text_edit, 1)
        splitter.addWidget(dashboard_group)
        filter_group = QGroupBox("サブセットフィルタ"); filter_main_layout = QVBoxLayout(filter_group)
        self.filter_builder_tree = QTreeWidget(); self.filter_builder_tree.setHeaderLabels(["フィールド", "演算子", "値", "AND/OR", "削除"])
        self.filter_builder_tree.setColumnWidth(0, 180); self.filter_builder_tree.setColumnWidth(1, 120)
        self.filter_builder_tree.setColumnWidth(2, 180); self.filter_builder_tree.setColumnWidth(3, 80)
        filter_main_layout.addWidget(self.filter_builder_tree); filter_controls_layout = QHBoxLayout()
        self.add_filter_row_button = QPushButton(QIcon.fromTheme("list-add"),"条件行を追加"); self.add_filter_row_button.clicked.connect(self.add_filter_condition_row)
        filter_controls_layout.addWidget(self.add_filter_row_button)
        self.apply_filter_button = QPushButton(QIcon.fromTheme("system-search"),"フィルタ適用"); self.apply_filter_button.clicked.connect(self.apply_filters)
        filter_controls_layout.addWidget(self.apply_filter_button)
        self.save_filter_button = QPushButton(QIcon.fromTheme("document-save"),"条件保存"); self.save_filter_button.clicked.connect(self.save_filter_set)
        filter_controls_layout.addWidget(self.save_filter_button)
        self.load_filter_button = QPushButton(QIcon.fromTheme("document-open"),"条件呼出"); self.load_filter_button.clicked.connect(self.load_filter_set)
        filter_controls_layout.addWidget(self.load_filter_button); filter_controls_layout.addStretch()
        self.filter_status_label = QLabel("件数: 0  推定Token: 0"); filter_controls_layout.addWidget(self.filter_status_label)
        filter_main_layout.addLayout(filter_controls_layout); splitter.addWidget(filter_group)
        gemini_group = QGroupBox("Gemini 解析"); gemini_layout = QVBoxLayout(gemini_group)
        gemini_layout.addWidget(QLabel("LLMプロンプト (空の場合はデフォルトテンプレートを使用):"))
        self.gemini_prompt_template_edit = QTextEdit(); self.gemini_prompt_template_edit.setPlaceholderText("例: スコアが低い画像の原因と改善策を提案してください。\nデータ:\n{filtered_data_summary}")
        self.gemini_prompt_template_edit.setFixedHeight(80); gemini_layout.addWidget(self.gemini_prompt_template_edit)
        gemini_run_layout = QHBoxLayout()
        self.run_gemini_button = QPushButton(QIcon.fromTheme("system-run"),"Gemini解析実行"); self.run_gemini_button.clicked.connect(self.run_gemini_analysis)
        gemini_run_layout.addWidget(self.run_gemini_button)
        self.cancel_gemini_button = QPushButton(QIcon.fromTheme("process-stop"),"キャンセル"); self.cancel_gemini_button.clicked.connect(self.cancel_gemini_analysis)
        self.cancel_gemini_button.setEnabled(False); gemini_run_layout.addWidget(self.cancel_gemini_button)
        gemini_run_layout.addStretch(); gemini_layout.addLayout(gemini_run_layout)
        self.gemini_progress_bar = QProgressBar(); self.gemini_progress_bar.setVisible(False); gemini_layout.addWidget(self.gemini_progress_bar)
        self.gemini_result_edit = QTextEdit(); self.gemini_result_edit.setReadOnly(True); gemini_layout.addWidget(self.gemini_result_edit)
        splitter.addWidget(gemini_group); layout.addWidget(splitter)
        splitter.setStretchFactor(0,1); splitter.setStretchFactor(1,1); splitter.setStretchFactor(2,2)

    def update_dashboard(self): #変更なし
        df_scores = self.main_window.df_scores; self.hist_canvas.figure.clear()
        hist_fig = analysis_dashboard_module.create_score_histogram(df_scores, 'score_final')
        self.hist_canvas.figure = hist_fig; self.hist_canvas.draw(); self.tags_text_edit.clear()
        if not df_scores.empty and 'failure_tags' in df_scores.columns:
            tag_counts = analysis_dashboard_module.get_top_failure_tags(df_scores, top_n=20)
            if not tag_counts.empty:
                self.tags_text_edit.append("--- 破綻タグ TOP20 ---")
                for tag, count in tag_counts.items(): self.tags_text_edit.append(f"{tag}: {count}件")
            else: self.tags_text_edit.setText("破綻タグデータなし。")
        else: self.tags_text_edit.setText("スコア/破綻タグ列なし。")
    def populate_filter_fields(self): #変更なし
        self.available_fields = sorted(self.main_window.df_combined.columns.tolist()) if not self.main_window.df_combined.empty else []
        if self.filter_builder_tree.topLevelItemCount() == 0 and self.available_fields: self.add_filter_condition_row()
    def add_filter_condition_row(self, field_name=None, operator=None, value=None, and_or="AND"): #変更なし
        item = QTreeWidgetItem(self.filter_builder_tree); field_combo = QComboBox(); field_combo.addItems(self.available_fields)
        if field_name and field_name in self.available_fields: field_combo.setCurrentText(field_name)
        elif self.available_fields : field_combo.setCurrentText(self.available_fields[0])
        self.filter_builder_tree.setItemWidget(item, 0, field_combo)
        field_combo.currentTextChanged.connect(lambda text, current_item=item: self.on_field_changed(text, current_item))
        op_combo = QComboBox(); self.filter_builder_tree.setItemWidget(item, 1, op_combo)
        value_edit_container = QWidget(); value_edit_layout = QHBoxLayout(value_edit_container); value_edit_layout.setContentsMargins(0,0,0,0)
        self.filter_builder_tree.setItemWidget(item, 2, value_edit_container)
        and_or_combo = QComboBox(); and_or_combo.addItems(["AND", "OR"]); and_or_combo.setCurrentText(and_or)
        if self.filter_builder_tree.topLevelItemCount() == 1: and_or_combo.setEnabled(False)
        self.filter_builder_tree.setItemWidget(item, 3, and_or_combo)
        delete_button = QPushButton(QIcon.fromTheme("list-remove"),""); delete_button.setToolTip("この条件行を削除")
        delete_button.clicked.connect(lambda: self.filter_builder_tree.takeTopLevelItem(self.filter_builder_tree.indexOfTopLevelItem(item)))
        self.filter_builder_tree.setItemWidget(item, 4, delete_button)
        self.on_field_changed(field_combo.currentText(), item)
        if value is not None:
            value_widget_retrieved = value_edit_container.layout().itemAt(0).widget()
            if isinstance(value_widget_retrieved, QLineEdit): value_widget_retrieved.setText(str(value))
            elif isinstance(value_widget_retrieved, (QSpinBox, QDoubleSpinBox)): value_widget_retrieved.setValue(float(value))
            elif isinstance(value_widget_retrieved, QComboBox): value_widget_retrieved.setCurrentText(str(value))
    def on_field_changed(self, field_name, tree_item): #変更なし
        if not field_name or self.main_window.df_combined.empty or field_name not in self.main_window.df_combined.columns: return
        dtype = self.main_window.df_combined[field_name].dtype; op_combo = self.filter_builder_tree.itemWidget(tree_item, 1)
        value_container = self.filter_builder_tree.itemWidget(tree_item, 2)
        while value_container.layout().count(): value_container.layout().takeAt(0).widget().deleteLater()
        op_combo.clear(); new_value_widget = None
        if pd.api.types.is_numeric_dtype(dtype): op_combo.addItems(['==', '!=', '>', '<', '>=', '<=']); new_value_widget = QDoubleSpinBox() if pd.api.types.is_float_dtype(dtype) else QSpinBox(); new_value_widget.setRange(-1e12, 1e12); new_value_widget.setDecimals(3 if pd.api.types.is_float_dtype(dtype) else 0)
        elif pd.api.types.is_bool_dtype(dtype): op_combo.addItems(['==', '!=']); combo_val = QComboBox(); combo_val.addItems(["True", "False"]); new_value_widget = combo_val
        elif field_name == 'failure_tags' or (hasattr(dtype, 'name') and 'list' in dtype.name.lower()) or (not self.main_window.df_combined[field_name].empty and isinstance(self.main_window.df_combined[field_name].dropna().iloc[0] if not self.main_window.df_combined[field_name].dropna().empty else None, list)): op_combo.addItems(['contains', 'not contains']); new_value_widget = QLineEdit(); new_value_widget.setPlaceholderText("例: extra_fingers")
        elif pd.api.types.is_string_dtype(dtype) or dtype == 'object': op_combo.addItems(['==', '!=', 'contains', 'not contains', 'startswith', 'endswith']); new_value_widget = QLineEdit()
        else: op_combo.addItems(['==', '!=']); new_value_widget = QLineEdit(); new_value_widget.setPlaceholderText(f"Unknown: {dtype}")
        op_combo.addItems(['is null', 'is not null'])
        if new_value_widget: value_container.layout().addWidget(new_value_widget)

    def apply_filters(self): #変更なし
        if self.main_window.df_combined.empty: QMessageBox.information(self, "情報", "データなし"); return
        current_df = self.main_window.df_combined.copy(); conditions_applied_count = 0
        for i in range(self.filter_builder_tree.topLevelItemCount()):
            item = self.filter_builder_tree.topLevelItem(i); field = self.filter_builder_tree.itemWidget(item, 0).currentText()
            op = self.filter_builder_tree.itemWidget(item, 1).currentText(); value_container = self.filter_builder_tree.itemWidget(item, 2)
            value_widget = value_container.layout().itemAt(0).widget() if value_container.layout().count() > 0 else None
            val_str = ""; actual_val = None
            if isinstance(value_widget, QLineEdit): val_str = value_widget.text(); actual_val = val_str
            elif isinstance(value_widget, (QSpinBox, QDoubleSpinBox)): val_str = str(value_widget.value()); actual_val = value_widget.value()
            elif isinstance(value_widget, QComboBox): val_str = value_widget.currentText(); actual_val = (val_str.lower() == 'true') if self.main_window.df_combined[field].dtype == 'bool' else val_str
            if op not in ['is null', 'is not null'] and (actual_val is None or val_str == ""): continue
            conditions_applied_count += 1
            try:
                if op == 'is null': current_df = current_df[current_df[field].isnull()]
                elif op == 'is not null': current_df = current_df[current_df[field].notnull()]
                elif op == '==': current_df = current_df[current_df[field] == actual_val]
                elif op == '!=': current_df = current_df[current_df[field] != actual_val]
                elif op == '>': current_df = current_df[current_df[field] > actual_val]
                elif op == '<': current_df = current_df[current_df[field] < actual_val]
                elif op == '>=': current_df = current_df[current_df[field] >= actual_val]
                elif op == '<=': current_df = current_df[current_df[field] <= actual_val]
                elif op == 'contains':
                    if field == 'failure_tags' or (not current_df[field].empty and isinstance(current_df[field].dropna().iloc[0] if not current_df[field].dropna().empty else None, list)):
                        current_df = current_df[current_df[field].apply(lambda x: str(actual_val).lower() in [str(tag).lower() for tag in x] if isinstance(x, list) and actual_val else False)]
                    else: current_df = current_df[current_df[field].astype(str).str.contains(str(actual_val), case=False, na=False)]
                elif op == 'not contains':
                    if field == 'failure_tags' or (not current_df[field].empty and isinstance(current_df[field].dropna().iloc[0] if not current_df[field].dropna().empty else None, list)):
                         current_df = current_df[current_df[field].apply(lambda x: str(actual_val).lower() not in [str(tag).lower() for tag in x] if isinstance(x, list) and actual_val else True)]
                    else: current_df = current_df[~current_df[field].astype(str).str.contains(str(actual_val), case=False, na=False)]
                elif op == 'startswith': current_df = current_df[current_df[field].astype(str).str.startswith(str(actual_val), na=False)]
                elif op == 'endswith': current_df = current_df[current_df[field].astype(str).str.endswith(str(actual_val), na=False)]
            except Exception as e: QMessageBox.warning(self, "フィルタエラー", f"条件 '{field} {op} {val_str}' 適用エラー: {e}"); self.filtered_df = pd.DataFrame(); self.update_filter_status(); return
        if conditions_applied_count == 0 and self.filter_builder_tree.topLevelItemCount() > 0 :
             QMessageBox.information(self, "フィルタ情報", "有効なフィルタ条件が入力されていません。全件表示します。"); self.filtered_df = self.main_window.df_combined.copy()
        else: self.filtered_df = current_df
        self.update_filter_status(); QMessageBox.information(self, "フィルタ適用完了", f"{len(self.filtered_df)} 件該当")

    def update_filter_status(self): # ★★★ ここを修正 ★★★
        n = len(self.filtered_df)
        tokens = 0
        if 0 < n < 15000: # この行が line 689 に相当する
            try:
                # 文字列型の列のみを対象にトークン数を概算
                str_cols = self.filtered_df.select_dtypes(include=['object', 'string'])
                if not str_cols.empty:
                    total_chars = str_cols.astype(str).applymap(len).sum().sum()
                    tokens = total_chars // 3 # 1トークン約3文字と仮定 (より正確にはトークナイザを使う)
                else:
                    tokens = 0
            except Exception as e_token:
                print(f"トークン数計算エラー: {e_token}")
                tokens = "計算不可"
        elif n == 0:
            tokens = 0
        else: # 15000件以上の場合
            tokens = "多数のため計算省略"
            
        self.filter_status_label.setText(f"件数: {n}  推定Token: {tokens if isinstance(tokens, str) else f'{tokens:,}'}")

    def save_filter_set(self): #変更なし
        if self.filter_builder_tree.topLevelItemCount() == 0: return
        fp, _ = QFileDialog.getSaveFileName(self, "フィルタ保存", str(FILTERS_DIR), "JSON files (*.json)")
        if not fp: return; conditions = []
        for i in range(self.filter_builder_tree.topLevelItemCount()):
            item = self.filter_builder_tree.topLevelItem(i); value_container = self.filter_builder_tree.itemWidget(item, 2)
            value_widget = value_container.layout().itemAt(0).widget() if value_container.layout().count() > 0 else None; value_content = ""
            if isinstance(value_widget, QLineEdit): value_content = value_widget.text()
            elif isinstance(value_widget, (QSpinBox, QDoubleSpinBox)): value_content = value_widget.value()
            elif isinstance(value_widget, QComboBox): value_content = value_widget.currentText()
            conditions.append({"field": self.filter_builder_tree.itemWidget(item, 0).currentText(), "operator": self.filter_builder_tree.itemWidget(item, 1).currentText(), "value": value_content, "and_or": self.filter_builder_tree.itemWidget(item, 3).currentText()})
        try:
            with open(fp, 'w', encoding='utf-8') as f: json.dump(conditions, f, indent=2); QMessageBox.information(self, "保存完了", f"フィルタを {Path(fp).name} に保存。")
        except Exception as e: QMessageBox.critical(self, "保存エラー", f"保存失敗: {e}")
    def load_filter_set(self): #変更なし
        fp, _ = QFileDialog.getOpenFileName(self, "フィルタ読込", str(FILTERS_DIR), "JSON files (*.json)")
        if not fp: return
        try:
            with open(fp, 'r', encoding='utf-8') as f: conditions = json.load(f)
            self.filter_builder_tree.clear()
            for cond in conditions: self.add_filter_condition_row(cond.get("field"), cond.get("operator"), cond.get("value"), cond.get("and_or", "AND"))
            QMessageBox.information(self, "読込完了", f"フィルタ {Path(fp).name} を読込。")
        except Exception as e: QMessageBox.critical(self, "読込エラー", f"読込失敗: {e}")
    def run_gemini_analysis(self): #変更なし
        api_key = self.main_window.gemini_api_key_loaded
        if not api_key: QMessageBox.critical(self, "APIキー未設定", "Gemini APIキーを設定してください。"); return
        if self.filtered_df.empty: QMessageBox.warning(self, "警告", "解析データなし"); return
        if len(self.filtered_df) > 10000:
            if QMessageBox.question(self, "確認", f"{len(self.filtered_df)}件は多すぎます。実行しますか？", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.No: return
        user_prompt = self.gemini_prompt_template_edit.toPlainText()
        self.gemini_result_edit.clear(); self.gemini_progress_bar.setValue(0); self.gemini_progress_bar.setVisible(True)
        self.run_gemini_button.setEnabled(False); self.cancel_gemini_button.setEnabled(True)
        cols_for_gemini = ['score_final', 'score_moe', 'failure_tags_str', 'penalties_applied_str', 'prompt', 'negative_prompt', 'steps', 'sampler', 'cfg_scale', 'seed', 'model_name', 'width', 'height']
        existing_cols = [col for col in cols_for_gemini if col in self.filtered_df.columns]
        data_for_gemini = self.filtered_df[existing_cols].copy()
        for col in ['failure_tags', 'penalties_applied']:
            if col in data_for_gemini and f"{col}_str" not in data_for_gemini: # _str カラムがまだない場合のみ
                data_for_gemini[f"{col}_str"] = data_for_gemini[col].apply(lambda x: (', '.join(map(str,x)) if isinstance(x, list) else (json.dumps(x) if isinstance(x, dict) else str(x))) )
        if self.gemini_thread and self.gemini_thread.isRunning(): self.gemini_thread.cancel(); self.gemini_thread.wait(500)
        self.gemini_thread = GeminiAnalysisRunnerThread(data_for_gemini, user_prompt, api_key)
        self.gemini_thread.analysis_progress.connect(self.gemini_progress_bar.setValue)
        self.gemini_thread.analysis_finished.connect(self.on_gemini_analysis_finished)
        self.gemini_thread.error_occurred.connect(lambda err_msg: QMessageBox.critical(self, "Gemini解析エラー(Signal)", err_msg))
        self.gemini_thread.start()
    @Slot(str, bool)
    def on_gemini_analysis_finished(self, report_markdown, success): #変更なし
        self.gemini_progress_bar.setVisible(False); self.run_gemini_button.setEnabled(True); self.cancel_gemini_button.setEnabled(False)
        if success: self.gemini_result_edit.setMarkdown(report_markdown); QMessageBox.information(self, "Gemini解析完了", "レポート生成完了。")
        else: self.gemini_result_edit.setText(f"Gemini解析失敗。\n\n{report_markdown}"); QMessageBox.critical(self, "Gemini解析エラー", "解析処理中にエラー発生。")
        self.gemini_thread = None
    def cancel_gemini_analysis(self): #変更なし
        if self.gemini_thread and self.gemini_thread.isRunning(): self.gemini_thread.cancel()
        self.gemini_progress_bar.setVisible(False); self.run_gemini_button.setEnabled(True); self.cancel_gemini_button.setEnabled(False)
        self.gemini_result_edit.append("\n\n[ユーザーにより解析がキャンセルされました]")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    main_win = MainWindow()
    main_win.show()
    sys.exit(app.exec())

