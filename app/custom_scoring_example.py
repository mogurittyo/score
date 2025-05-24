# app/custom_scoring_example.py
# このファイルを app/custom_scoring.py として保存し、
# 以下の関数を独自ロジックで実装してください。

from pathlib import Path
from PIL import Image
import numpy as np
import time

# scoringモジュールのINITIALIZED_SUCCESSFULLYフラグを操作する場合
# from . import scoring as main_scoring_module # scoring.pyをmain_scoring_moduleとしてインポート

# --- グローバル変数 (カスタムモデル用) ---
# MY_CUSTOM_MODEL = None
# MY_DEVICE = "cpu"

def initialize_custom_models(force_cpu=False, progress_callback=None):
    """
    カスタムAIモデルを初期化します。
    Args:
        force_cpu (bool): CPU実行を強制するかどうか。
        progress_callback (Signal(str, int), optional): UIに進捗を通知。
    """
    # global MY_CUSTOM_MODEL, MY_DEVICE # 例
    print("[CustomScorer] カスタムモデルの初期化を開始します...")
    if progress_callback: progress_callback.emit("カスタムモデル初期化中...", 10)

    # --- ここにカスタムモデルのロード処理を記述 ---
    # 例:
    # try:
    #     import torch
    #     MY_DEVICE = "cpu" if force_cpu else ("cuda" if torch.cuda.is_available() else "cpu")
    #     print(f"[CustomScorer] カスタムデバイス: {MY_DEVICE}")
    #     # model_path = Path(__file__).resolve().parent.parent / "models" / "my_custom_model.pth"
    #     # if not model_path.exists():
    #     #     if progress_callback: progress_callback.emit(f"カスタムモデルファイルなし: {model_path}", 80)
    #     #     raise FileNotFoundError(f"カスタムモデルファイルが見つかりません: {model_path}")
    #     # MY_CUSTOM_MODEL = torch.load(model_path, map_location=MY_DEVICE).eval()
    #     # print(f"[CustomScorer] カスタムモデル {model_path} をロードしました。")
    #     if progress_callback: progress_callback.emit("カスタムモデルのロード完了", 90)
    #     # main_scoring_module.INITIALIZED_SUCCESSFULLY = True # scoringモジュールのフラグを更新
    # except Exception as e:
    #     print(f"[CustomScorer] カスタムモデルの初期化に失敗: {e}")
    #     if progress_callback: progress_callback.emit(f"カスタムモデル初期化エラー: {e}", 100)
    #     # main_scoring_module.INITIALIZED_SUCCESSFULLY = False
    #     return
    
    if progress_callback: progress_callback.emit("カスタム設定読み込み...", 30)
    time.sleep(0.2) # ダミー処理
    if progress_callback: progress_callback.emit("カスタムリソース準備...", 60)
    time.sleep(0.3) # ダミー処理
    print("[CustomScorer] (ダミー) カスタムモデル初期化完了。")
    if progress_callback: progress_callback.emit("カスタムモデル初期化完了 (ダミー)", 100)
    
    # scoringモジュールのフラグを操作する場合 (例)
    from . import scoring as main_scoring_module # scoring.pyをmain_scoring_moduleとしてインポート
    main_scoring_module.INITIALIZED_SUCCESSFULLY = True # カスタム初期化が成功したとみなす


def score_one_custom(image_path: Path, penalties_dict: dict):
    """
    カスタムロジックで単一の画像をスコアリングします。
    Returns:
        tuple: (base_score, failure_tags, final_score, applied_penalties)
    """
    print(f"[CustomScorer] カスタムスコアリング処理中: {image_path.name}")
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as e:
        print(f"[CustomScorer] 画像ファイルを開けませんでした: {image_path}, Error: {e}")
        return 0.0, [f"image_open_error:{str(e)[:20]}"], 0.0, {}

    # --- ここにカスタムスコアリングロジックを記述 ---
    base_score = round(np.random.uniform(1.0, 10.0), 2)
    failure_tags = []
    possible_tags = ["custom_blur", "custom_artifact", "custom_bad_lighting"] + list(penalties_dict.keys())
    num_detected = np.random.randint(0, min(4, len(possible_tags)))
    if num_detected > 0 and possible_tags:
        failure_tags = np.random.choice(possible_tags, size=num_detected, replace=False).tolist()

    total_penalty = 0.0; applied_penalties = {}
    for tag in failure_tags:
        penalty_value = float(penalties_dict.get(tag, np.random.uniform(0.2, 1.5))) # ymlになければランダム
        if penalty_value > 0:
            total_penalty += penalty_value
            applied_penalties[tag] = round(penalty_value, 2)
            
    final_score = max(0.0, min(10.0, base_score - total_penalty))
    final_score = round(final_score, 2)
    
    print(f"[CustomScorer] 結果 for {image_path.name} - Base: {base_score}, Tags: {failure_tags}, Final: {final_score}")
    return base_score, failure_tags, final_score, applied_penalties
