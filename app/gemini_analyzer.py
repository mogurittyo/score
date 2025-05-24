import os
import google.generativeai as genai
from PySide6.QtCore import QObject, Signal # QObjectとSignalをインポート
import pandas as pd
import json
import time

# APIキーは呼び出し元(qt_launcher)から渡される想定

GENERATION_CONFIG = {"temperature": 0.7, "top_p": 0.95, "top_k": 40, "max_output_tokens": 8192}
SAFETY_SETTINGS = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
]
MODEL_NAME = "gemini-1.5-pro-latest"

class GeminiSignals(QObject): # QObjectを継承
    analysis_progress = Signal(int)
    analysis_finished = Signal(str, bool)
    error_occurred = Signal(str)

class GeminiAnalyzer(QObject): # QObjectを継承
    def __init__(self, api_key_val=None, parent=None): # parent引数を追加
        super().__init__(parent) # QObjectの初期化
        self.signals = GeminiSignals()
        self.model = None
        self.is_cancelled = False
        self.current_api_key = api_key_val

        if not self.current_api_key:
            msg = "GOOGLE_API_KEY が GeminiAnalyzer に渡されませんでした。"
            print(f"[GeminiAnalyzer] Error: {msg}")
            raise ValueError(msg)
        try:
            genai.configure(api_key=self.current_api_key)
            self.model = genai.GenerativeModel(model_name=MODEL_NAME, generation_config=GENERATION_CONFIG, safety_settings=SAFETY_SETTINGS)
            print(f"[GeminiAnalyzer] Geminiモデル ({MODEL_NAME}) の初期化に成功しました。")
        except Exception as e:
            msg = f"Geminiモデルの初期化に失敗: {e}"
            print(f"[GeminiAnalyzer] Error: {msg}")
            raise ConnectionError(msg)

    def _prepare_data_for_prompt(self, data_df_subset: pd.DataFrame, max_rows_for_prompt=150, max_cell_len=80):
        if data_df_subset.empty: return "提供されたデータセットは空です。"
        df_to_convert = data_df_subset.head(max_rows_for_prompt) if len(data_df_subset) > max_rows_for_prompt else data_df_subset
        print(f"[GeminiAnalyzer] プロンプト用にデータを準備中 (最大{max_rows_for_prompt}行, {len(df_to_convert)}行使用)")
        relevant_columns = [
            'score_final', 'score_moe', 'failure_tags_str', 'penalties_applied_str', 
            'prompt', 'negative_prompt', 'steps', 'sampler', 'cfg_scale', 'seed', 
            'model_name', 'width', 'height'
        ]
        cols_to_use = [col for col in relevant_columns if col in df_to_convert.columns]
        if not cols_to_use: return "プロンプトに含める適切なデータ列が見つかりませんでした。"
        df_prompt_data = df_to_convert[cols_to_use].copy()
        for col_name in df_prompt_data.columns:
            if df_prompt_data[col_name].dtype == 'object' or pd.api.types.is_string_dtype(df_prompt_data[col_name]):
                 df_prompt_data[col_name] = df_prompt_data[col_name].apply(
                     lambda x: (str(x)[:max_cell_len] + '...' if isinstance(x, str) and len(x) > max_cell_len + 3 else str(x))
                 )
        try:
            return df_prompt_data.to_markdown(index=False)
        except Exception as e:
            print(f"[GeminiAnalyzer] Markdownテーブルへの変換中にエラー: {e}")
            try: return df_prompt_data.to_json(orient="records", indent=2)
            except: return "データの準備中にエラーが発生しました。"

    def analyze_data(self, data_df_subset: pd.DataFrame, user_prompt_template: str):
        self.is_cancelled = False; self.signals.analysis_progress.emit(5)
        if not self.model: self.signals.error_occurred.emit("Geminiモデルが初期化されていません。"); self.signals.analysis_finished.emit("モデル未初期化エラー", False); return
        if data_df_subset.empty: self.signals.error_occurred.emit("分析対象のデータが空です。"); self.signals.analysis_finished.emit("データなしエラー", False); return

        self.signals.analysis_progress.emit(15)
        prepared_data_str = self._prepare_data_for_prompt(data_df_subset)
        if self.is_cancelled: self.signals.analysis_finished.emit("ユーザーによりキャンセルされました (データ準備中)。", False); return
        self.signals.analysis_progress.emit(25)

        final_prompt = user_prompt_template.replace("{filtered_data_summary}", prepared_data_str) if "{filtered_data_summary}" in user_prompt_template and user_prompt_template else \
                       (f"{user_prompt_template}\n\n分析対象のデータは以下の通りです:\n{prepared_data_str}" if user_prompt_template else \
                        f"以下の画像生成結果データセットを分析し、低品質画像の原因と改善策を提案(Markdown形式)。\nスコア低(<5)画像共通点(プロンプト,パラメータ)、破綻タグ原因と対策も。\nデータ:\n{prepared_data_str}")
        self.signals.analysis_progress.emit(40)
        try:
            response = self.model.generate_content(final_prompt)
            if self.is_cancelled: self.signals.analysis_finished.emit("ユーザーによりキャンセルされました (API応答後)。", False); return
            self.signals.analysis_progress.emit(90)
            report_markdown = response.text
            if response.prompt_feedback and response.prompt_feedback.block_reason:
                msg = f"プロンプトがブロックされました: {response.prompt_feedback.block_reason}"; self.signals.error_occurred.emit(msg); self.signals.analysis_finished.emit(f"解析エラー: {msg}", False); return
            if not report_markdown and response.candidates and response.candidates[0].finish_reason != 'STOP':
                msg = f"レポート生成が不完全です。理由: {response.candidates[0].finish_reason}"; self.signals.error_occurred.emit(msg); self.signals.analysis_finished.emit(f"解析エラー: {msg}", False); return
            if not report_markdown and not (response.candidates and response.candidates[0].finish_reason == 'STOP'):
                 msg = "空の応答を受信しました。プロンプトやデータを見直してください。"
                 self.signals.error_occurred.emit(msg); self.signals.analysis_finished.emit(msg, False); return
            self.signals.analysis_finished.emit(report_markdown, True)
        except Exception as e:
            msg = f"Gemini APIとの通信または応答処理中にエラー: {e}"; print(f"[GeminiAnalyzer] Error: {msg}"); self.signals.error_occurred.emit(msg); self.signals.analysis_finished.emit(f"解析エラー: {msg}", False)
        finally: self.signals.analysis_progress.emit(100)

    def cancel_analysis(self): self.is_cancelled = True

if __name__ == '__main__':
    print("--- Gemini Analyzer Module Test ---")
    API_KEY_TEST = os.getenv("GOOGLE_API_KEY")
    if not API_KEY_TEST: print("テスト中止: GOOGLE_API_KEY環境変数が設定されていません。"); exit()
    
    dummy_data = {'score_final': [3.5, 7.8], 'prompt': ["1girl", "cat"], 'failure_tags_str': ["blurry", ""]}
    df_test = pd.DataFrame(dummy_data)
    analyzer_test = None
    try: analyzer_test = GeminiAnalyzer(api_key_val=API_KEY_TEST)
    except Exception as e_init: print(f"Analyzer初期化失敗: {e_init}"); exit()

    # PySide6.QtCore.QTimer を使わずにテストするための簡易的なシグナルハンドラ
    # 実際のアプリケーションでは qt_launcher.py 内で QThread と連携してシグナルを処理します。
    def handle_progress_test(p): print(f"[Test Progress] {p}%")
    def handle_finished_test(report, success_flag):
        print(f"\n--- [Test Finished] ---"); print(f"Success: {success_flag}")
        print("Report (first 100):\n", (report[:100] + "..." if report and len(report) > 100 else report) if report else "N/A")
        if success_flag and report:
            with open("test_gemini_report_final_fix1.md", "w", encoding="utf-8") as f: f.write(report)
            print("\nレポートを test_gemini_report_final_fix1.md に保存しました。")
        elif not success_flag: print(f"失敗レポート: {report}")
    def handle_error_test(err_msg): print(f"[Test Error] {err_msg}")

    analyzer_test.signals.analysis_progress.connect(handle_progress_test)
    analyzer_test.signals.analysis_finished.connect(handle_finished_test)
    analyzer_test.signals.error_occurred.connect(handle_error_test)
    
    print("\nGemini分析テスト開始...")
    analyzer_test.analyze_data(df_test, "データ傾向分析と改善案:\n{filtered_data_summary}")
    print("\n--- Gemini Analyzer Module Test End ---")
