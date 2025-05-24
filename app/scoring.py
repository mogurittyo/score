# scoring.py (ユーザー提供修正版)
import os
import json
import yaml
from PIL import Image, PngImagePlugin
import piexif
import datetime
import numpy as np
from pathlib import Path
import hashlib
import sys

# --- AIライブラリのインポート ---
_AestheticPredictorActualClass = None
_aesthetic_predictor_import_error = "AestheticPredictor not attempted to import yet."
_deepdanbooru_module = None
_deepdanbooru_import_error = "DeepDanbooru has not been attempted to import yet."

try:
    import torch
    from transformers import CLIPProcessor, CLIPModel, CLIPConfig
    from huggingface_hub import hf_hub_download, HfFolder
    print("[Scoring] torch, transformers, huggingface_hub のインポートに成功。")

    try:
        # AestheticsPredictorV2Linear を優先的に試す
        from aesthetics_predictor import AestheticsPredictorV2Linear
        _AestheticPredictorActualClass = AestheticsPredictorV2Linear
        _aesthetic_predictor_import_error = None
        print(f"[Scoring] 'aesthetics_predictor.AestheticsPredictorV2Linear' のインポート/選択に成功。")
    except ImportError as e_ap_v2:
        _aesthetic_predictor_import_error = f"Failed to import AestheticsPredictorV2Linear: {e_ap_v2}. "
        print(f"[Scoring] Error: {_aesthetic_predictor_import_error}")
        # V2LinearがダメならV1も試す
        try:
            from aesthetics_predictor import AestheticsPredictorV1
            _AestheticPredictorActualClass = AestheticsPredictorV1
            _aesthetic_predictor_import_error = None
            print(f"[Scoring] Fallback: 'aesthetics_predictor.AestheticsPredictorV1' のインポートに成功。")
        except ImportError as e_ap_v1:
            _aesthetic_predictor_import_error += f" Also failed to import AestheticsPredictorV1: {e_ap_v1}"
            print(f"[Scoring] Error: {_aesthetic_predictor_import_error}")
    except Exception as e_ap_other:
        _aesthetic_predictor_import_error = f"Unexpected error importing from aesthetics_predictor: {e_ap_other}"
        print(f"[Scoring] Error: {_aesthetic_predictor_import_error}")

    try:
        import deepdanbooru as ddb
        _deepdanbooru_module = ddb
        _deepdanbooru_import_error = None
        print(f"[Scoring] 'deepdanbooru' のインポートに成功。")
    except ImportError as e_ddb_import:
        _deepdanbooru_import_error = f"Failed to import deepdanbooru: {e_ddb_import}"
        print(f"[Scoring] Error: {_deepdanbooru_import_error}")
        ddb = None
    except Exception as e_ddb_other:
        _deepdanbooru_import_error = f"Unexpected error importing deepdanbooru: {e_ddb_other}"
        print(f"[Scoring] Error: {_deepdanbooru_import_error}")
        ddb = None

except ImportError as e_main:
    print(f"[Scoring] 必須AIコアライブラリ(torch, transformers等)のインポートに失敗: {e_main}")
    torch = CLIPProcessor = CLIPModel = HfFolder = CLIPConfig = None
    if ddb is None and _deepdanbooru_import_error is None : _deepdanbooru_import_error = str(e_main)
    if _AestheticPredictorActualClass is None and _aesthetic_predictor_import_error is None : _aesthetic_predictor_import_error = str(e_main)
except Exception as e_unexpected_main_import:
    print(f"[Scoring] AIライブラリのインポート中に予期せぬエラー (メインブロック): {e_unexpected_main_import}")
    torch = CLIPProcessor = CLIPModel = HfFolder = ddb = CLIPConfig = None
    _AestheticPredictorActualClass = None

try:
    from pillow_heif import register_heif_opener
    PILLOW_HEIF_AVAILABLE = True
except ImportError: PILLOW_HEIF_AVAILABLE = False

CUSTOM_SCORER_AVAILABLE = False
try:
    from importlib import import_module
    custom_scoring_module = import_module(".custom_scoring", package=__package__)
    if hasattr(custom_scoring_module, 'score_one_custom') and callable(custom_scoring_module.score_one_custom) and \
       hasattr(custom_scoring_module, 'initialize_custom_models') and callable(custom_scoring_module.initialize_custom_models):
        score_one_custom = custom_scoring_module.score_one_custom; initialize_custom_models = custom_scoring_module.initialize_custom_models
        CUSTOM_SCORER_AVAILABLE = True; print("[Scoring] カスタムスコアラー検出、優先。")
except ModuleNotFoundError: pass
except Exception as e_custom: print(f"[Scoring] カスタムスコアラー読込エラー: {e_custom}。標準を使用。")

BASE_DIR = Path(__file__).resolve().parent.parent
MODELS_DIR = BASE_DIR / "models"
AESTHETIC_MODEL_CACHE_DIR = MODELS_DIR / "aesthetic_models_cache"
DEEPDANBOORU_PROJECT_PATH = MODELS_DIR / "deepdanbooru_standard_model"
PENALTIES_YML_PATH = BASE_DIR / "penalties.yml"
METADATA_JSON_PATH = BASE_DIR / "metadata.json"

STD_CLIP_MODEL_AESTHETIC = STD_CLIP_PROCESSOR_AESTHETIC = STD_AESTHETIC_PREDICTOR = STD_DEEPDANBOORU_MODEL = STD_DEEPDANBOORU_TAGS = None
DEVICE = "cpu"; INITIALIZED_SUCCESSFULLY = False
AESTHETIC_CLIP_MODEL_ID = "laion/CLIP-ViT-L-14-laion2B-s32B-b82K"
AESTHETIC_PREDICTOR_V2_HF_MODEL_ID = "shunk031/aesthetics-predictor-v2-ava-logos-l14-linearMSE"

WATCHED_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.webp', '.heic', '.heif')

def initialize_standard_models(force_cpu=False, progress_callback=None):
    global STD_CLIP_MODEL_AESTHETIC, STD_CLIP_PROCESSOR_AESTHETIC, STD_AESTHETIC_PREDICTOR, \
           STD_DEEPDANBOORU_MODEL, STD_DEEPDANBOORU_TAGS, DEVICE, INITIALIZED_SUCCESSFULLY, _AestheticPredictorActualClass

    if not PILLOW_HEIF_AVAILABLE: print("[Scoring] pillow_heif が見つかりません。HEIF/HEIC形式のサムネイル生成はスキップされます。")
    if not CUSTOM_SCORER_AVAILABLE: print("[Scoring] カスタムスコアラー (custom_scoring.py) なし。標準を使用。")

    required_libs_present = all([torch, CLIPModel, CLIPProcessor, _deepdanbooru_module, _AestheticPredictorActualClass, CLIPConfig])
    if not required_libs_present:
        missing_details = [];
        if not torch: missing_details.append("torch")
        if not CLIPModel: missing_details.append("transformers.CLIPModel/Processor/Config")
        if not _deepdanbooru_module: missing_details.append(f"deepdanbooru (Error: {_deepdanbooru_import_error or 'Unknown'})")
        if not _AestheticPredictorActualClass: missing_details.append(f"AestheticsPredictor (Error: {_aesthetic_predictor_import_error or 'Unknown'})")
        msg = f"標準スコアラー初期化に必要なライブラリ不足: {', '.join(missing_details)}。"
        print(f"[Scoring] {msg}"); INITIALIZED_SUCCESSFULLY = False
        if progress_callback: progress_callback.emit(msg, 100)
        return

    if progress_callback: progress_callback.emit("モデル初期化開始", 0)
    try:
        DEVICE = "cpu" if force_cpu else ("cuda" if torch.cuda.is_available() else "cpu")
        print(f"[Scoring] 標準モデル初期化中... (デバイス: {DEVICE})")
        AESTHETIC_MODEL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

        if progress_callback: progress_callback.emit(f"CLIP ({AESTHETIC_CLIP_MODEL_ID}) ロード中 (Aesthetic用)...", 10)
        try:
            STD_CLIP_PROCESSOR_AESTHETIC = CLIPProcessor.from_pretrained(AESTHETIC_CLIP_MODEL_ID, cache_dir=str(AESTHETIC_MODEL_CACHE_DIR / "clip_for_aesthetic"))
            STD_CLIP_MODEL_AESTHETIC = CLIPModel.from_pretrained(AESTHETIC_CLIP_MODEL_ID, cache_dir=str(AESTHETIC_MODEL_CACHE_DIR / "clip_for_aesthetic")).to(DEVICE).eval()
            print(f"[Scoring] Aesthetic用CLIPモデル ({AESTHETIC_CLIP_MODEL_ID}) ロード完了。")
        except Exception as e_clip_aesth:
            print(f"[Scoring] Aesthetic用CLIPモデルロード失敗: {e_clip_aesth}")
            if progress_callback: progress_callback.emit(f"Aesthetic用CLIPロード失敗", 25); STD_CLIP_MODEL_AESTHETIC = None

        if progress_callback: progress_callback.emit("Aesthetic Predictor インスタンス化中...", 30)
        try:
            if _AestheticPredictorActualClass and STD_CLIP_MODEL_AESTHETIC:
                if _AestheticPredictorActualClass.__name__ == 'AestheticsPredictorV2Linear':
                    print(f"[Scoring] Attempting to load AestheticsPredictorV2Linear from: {AESTHETIC_PREDICTOR_V2_HF_MODEL_ID}")
                    STD_AESTHETIC_PREDICTOR = _AestheticPredictorActualClass.from_pretrained(
                        AESTHETIC_PREDICTOR_V2_HF_MODEL_ID,
                        cache_dir=str(AESTHETIC_MODEL_CACHE_DIR / "aesthetic_v2_model")
                    )
                elif _AestheticPredictorActualClass.__name__ == 'AestheticsPredictorV1':
                    print(f"[Scoring] Attempting to instantiate AestheticsPredictorV1 with CLIP config.")
                    class DummyV1Config: pass
                    try:
                        config_obj = STD_CLIP_MODEL_AESTHETIC.config
                        if not hasattr(config_obj, 'hidden_size') and hasattr(config_obj, 'projection_dim'):
                            config_obj.hidden_size = config_obj.projection_dim
                        STD_AESTHETIC_PREDICTOR = _AestheticPredictorActualClass(config=config_obj)
                    except Exception as e_v1_init:
                         print(f"[Scoring] AestheticsPredictorV1 instantiation with CLIP config failed: {e_v1_init}")
                         STD_AESTHETIC_PREDICTOR = None
                else:
                    print(f"[Scoring] Attempting to instantiate fallback {_AestheticPredictorActualClass.__name__}.")
                    STD_AESTHETIC_PREDICTOR = _AestheticPredictorActualClass(model_name="vit_l_14")

                if STD_AESTHETIC_PREDICTOR:
                    if hasattr(STD_AESTHETIC_PREDICTOR, 'to') and callable(getattr(STD_AESTHETIC_PREDICTOR, 'to')):
                         STD_AESTHETIC_PREDICTOR.to(DEVICE)
                    if hasattr(STD_AESTHETIC_PREDICTOR, 'eval') and callable(getattr(STD_AESTHETIC_PREDICTOR, 'eval')):
                         STD_AESTHETIC_PREDICTOR.eval()
                    print(f"[Scoring] Aesthetic Predictor ({_AestheticPredictorActualClass.__name__ if _AestheticPredictorActualClass else 'None'}) インスタンス化完了。")
            else:
                print("[Scoring] _AestheticPredictorActualClass または Aesthetic用CLIPモデルが未ロードのため、初期化できません。")
                STD_AESTHETIC_PREDICTOR = None
        except Exception as e_ap_init:
            print(f"[Scoring] Aesthetic Predictor のインスタンス化失敗: {e_ap_init}。クラス: {_AestheticPredictorActualClass}")
            STD_AESTHETIC_PREDICTOR = None

        if progress_callback: progress_callback.emit("DeepDanbooruモデル ロード中...", 60)
        if not DEEPDANBOORU_PROJECT_PATH.exists() or not (DEEPDANBOORU_PROJECT_PATH / "project.json").exists():
            print(f"[Scoring] DeepDanbooruプロジェクトなし: {DEEPDANBOORU_PROJECT_PATH}。setup_env.bat実行要。")
        else:
            try:
                if _deepdanbooru_module:
                    STD_DEEPDANBOORU_MODEL = _deepdanbooru_module.project.load_model_from_project(str(DEEPDANBOORU_PROJECT_PATH))
                    STD_DEEPDANBOORU_TAGS = _deepdanbooru_module.project.load_tags_from_project(str(DEEPDANBOORU_PROJECT_PATH))
                    print(f"[Scoring] DeepDanbooruモデルロード完了。 (プロジェクト: {DEEPDANBOORU_PROJECT_PATH})")
                else: print("[Scoring] DeepDanbooruモジュール未インポートのためロードスキップ。")
            except Exception as e_ddb: print(f"[Scoring] DeepDanbooruモデルロード失敗: {e_ddb}")

        INITIALIZED_SUCCESSFULLY = bool(STD_CLIP_MODEL_AESTHETIC and STD_AESTHETIC_PREDICTOR and STD_DEEPDANBOORU_MODEL)
        status_msg = "標準モデル初期化完了。" if INITIALIZED_SUCCESSFULLY else "標準モデル初期化に一部失敗。機能限定。"
        print(f"[Scoring] {status_msg}")
        if progress_callback: progress_callback.emit(status_msg, 100)
    except Exception as e_init_std_models:
        print(f"[Scoring] 標準モデル初期化中に予期せぬエラー: {e_init_std_models}"); INITIALIZED_SUCCESSFULLY = False
        if progress_callback: progress_callback.emit(f"初期化エラー: {e_init_std_models}", 100)

def score_one_standard(image_path: Path, penalties_dict: dict):
    if not INITIALIZED_SUCCESSFULLY:
        return round(np.random.uniform(3.0, 7.0), 1), ["dummy_model_not_init"], round(np.random.uniform(10.0, 60.0), 1), {}
    try: img_pil = Image.open(image_path).convert("RGB")
    except Exception as e_img_open: return 0.0, [f"image_open_error:{str(e_img_open)[:20]}"], 0.0, {}

    base_aesthetic_score = 0.0; detected_failure_tags = []
    raw_aesthetic_score = 0.5

    if STD_AESTHETIC_PREDICTOR and STD_CLIP_MODEL_AESTHETIC and STD_CLIP_PROCESSOR_AESTHETIC and torch:
        try:
            # --- 修正版: simple-aesthetics-predictor の推論パターン ---
            # CLIPProcessor で前処理した生画像を直接渡す
            inputs = STD_CLIP_PROCESSOR_AESTHETIC(images=img_pil, return_tensors="pt").to(DEVICE)
            with torch.no_grad():
                outputs = STD_AESTHETIC_PREDICTOR(**inputs)
                # wrapper の出力は logits 属性
                score_tensor = outputs.logits
                # 0〜1 に正規化（必要なら sigmoid、不要なら .item() のみでもOK）
                raw_aesthetic_score = torch.sigmoid(score_tensor).item()
            # 0〜10 スケールに変換
            base_aesthetic_score = raw_aesthetic_score * 10.0

        except ValueError as ve:
             print(f"[Scoring] Aestheticスコア計算中にValueError ({image_path.name}): {ve}. ダミースコアを使用。")
             base_aesthetic_score = np.random.uniform(1.0, 5.0)
        except Exception as e_aesth:
            print(f"[Scoring] Aestheticスコア計算エラー ({image_path.name}): {e_aesth}")
            base_aesthetic_score = np.random.uniform(1.0, 5.0)
    else:
        base_aesthetic_score = np.random.uniform(4.0, 9.0)
        if _aesthetic_predictor_import_error:
            detected_failure_tags.append("aesthetic_predictor_unavailable")

    # DeepDanbooru 評価呼び出しの直前に追加

    # scoring.py の score_one_standard 内 DeepDanbooru 評価部分
    # ────────────────────────────────────────────
    # ─── scoring.py 内の DeepDanbooru 評価部分 ───
    if STD_DEEPDANBOORU_MODEL and STD_DEEPDANBOORU_TAGS:  
        try:  
            # 画像をモデルの入力サイズにリサイズ  
            input_shape = STD_DEEPDANBOORU_MODEL.input_shape  # (None, H, W, 3)  
            target_size = (input_shape[1], input_shape[2])  
            img_resized = img_pil.resize(target_size, Image.Resampling.LANCZOS)  
  
            # 前処理: 0-1 に正規化 + バッチ次元追加  
            img_array = np.asarray(img_resized, dtype=np.float32) / 255.0  
            batch = np.expand_dims(img_array, axis=0)  
  
            # モデル推論  
            preds = STD_DEEPDANBOORU_MODEL.predict(batch)[0]  # shape: (num_tags,)  
  
            # しきい値 0.5 以上を “破綻タグ” として収集  
            threshold = 0.5  
            detected_failure_tags.extend([  
                tag for tag, score in zip(STD_DEEPDANBOORU_TAGS, preds)  
                if score >= threshold  
            ])  
        except Exception as e_infer:  
            print(f"[Scoring] DeepDanbooru 自前推論エラー ({image_path.name}): {e_infer}")  
    else:
        if not _deepdanbooru_module and _deepdanbooru_import_error: detected_failure_tags.append("deepdanbooru_unavailable")

    current_total_penalty = 0.0; applied_penalties_actual = {}
    unique_failure_tags = list(set(detected_failure_tags))
    for tag_name in unique_failure_tags:
        penalty_val = float(penalties_dict.get(tag_name, 0.0))
        if penalty_val > 0: current_total_penalty += penalty_val; applied_penalties_actual[tag_name] = penalty_val
    final_score_calc = base_aesthetic_score - current_total_penalty
    final_score = max(0.0, min(10.0, final_score_calc))
    return round(base_aesthetic_score, 2), unique_failure_tags, round(final_score, 2), applied_penalties_actual

def process_single_image(image_path_str: str, penalties_config: dict):
    image_path = Path(image_path_str); image_id = image_path.stem
    metadata = extract_metadata_from_image(str(image_path))
    if CUSTOM_SCORER_AVAILABLE:
        try: base_s, fail_tags, final_s, applied_pen = score_one_custom(image_path, penalties_config)
        except Exception as e_custom_score:
            print(f"[Scoring] カスタムスコアラーエラー ({image_path.name}): {e_custom_score}。ダミーにフォールバック。")
            base_s, fail_tags, final_s, applied_pen = round(np.random.uniform(3,7),1), ["custom_err"], round(np.random.uniform(1,6),1), {}
    else: base_s, fail_tags, final_s, applied_pen = score_one_standard(image_path, penalties_config)

    score_data = {"id": image_id, "filename": image_path.name, "path": str(image_path),
                  "score_final": final_s, "score_moe": base_s,
                  "score_aesthetic_clip": round(base_s / 10.0, 3) if base_s is not None else 0.0,
                  "failure_tags": fail_tags, "penalties_applied": applied_pen,
                  "last_scored_date": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    return image_id, score_data, metadata

def initialize_all_models(force_cpu=False, progress_callback=None):
    if CUSTOM_SCORER_AVAILABLE:
        print("[Scoring] カスタムモデル初期化...");
        try: initialize_custom_models(force_cpu=force_cpu, progress_callback=progress_callback)
        except Exception as e_init_custom: print(f"[Scoring] カスタムモデル初期化失敗: {e_init_custom}")
    else: print("[Scoring] 標準モデル初期化..."); initialize_standard_models(force_cpu=force_cpu, progress_callback=progress_callback)

def _parse_sd_parameters(params_str):
    metadata = {}; error_keys = []
    try:
        lines = params_str.split('\n'); prompt_lines = []; neg_prompt_lines = []; details_line = ""
        current_section = "prompt"
        for line in lines:
            if line.startswith("Negative prompt:"): current_section = "negative_prompt"; neg_prompt_lines.append(line.replace("Negative prompt:", "").strip())
            elif line.startswith("Steps:"): current_section = "details"; details_line = line
            elif current_section == "prompt": prompt_lines.append(line.strip())
            elif current_section == "negative_prompt": neg_prompt_lines.append(line.strip())
        metadata["prompt"] = " ".join(prompt_lines).strip(); metadata["negative_prompt"] = " ".join(neg_prompt_lines).strip()
        if details_line:
            raw_params = {}
            items = details_line.split(", ")
            for item_pair in items:
                parts = item_pair.split(': ', 1)
                if len(parts) == 2:
                    key = parts[0].strip().lower().replace(" ", "_"); value = parts[1].strip()
                    if key in ['steps', 'seed', 'clip_skip', 'hires_steps', 'hires_second_pass_steps']:
                        try: value = int(value)
                        except ValueError: pass
                    elif key in ['cfg_scale', 'denoising_strength', 'hires_upscale', 'hires_denoising_strength']:
                        try: value = float(value)
                        except ValueError: pass
                    elif key == 'size':
                        try: w_str, h_str = value.split('x'); raw_params['width'] = int(w_str); raw_params['height'] = int(h_str); continue
                        except ValueError: pass
                    raw_params[key] = value
            metadata.update(raw_params)
    except Exception as e_parse: error_keys.append("a1111_parameters_parsing"); metadata["raw_parameters_on_error"] = params_str
    if error_keys: metadata["error_keys"] = list(set(metadata.get("error_keys", []) + error_keys))
    return metadata

def extract_metadata_from_image(image_path_str: str):
    image_path = Path(image_path_str)
    metadata = {"extracted_by": None, "extraction_timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    error_keys = []
    try:
        img = Image.open(image_path); metadata['width_orig'] = img.width; metadata['height_orig'] = img.height
        if img.format == "PNG":
            metadata["extracted_by"] = "Pillow (PNG)"
            if img.info and "parameters" in img.info: metadata.update(_parse_sd_parameters(img.info["parameters"]))
            elif img.info and "prompt" in img.info:
                try: comfy_meta = json.loads(img.info["prompt"]); metadata["comfy_workflow"] = comfy_meta
                except: metadata["raw_png_prompt_key"] = img.info["prompt"]; error_keys.append("comfyui_json_decode_error")
            for k, v in img.text.items():
                if k not in metadata and k not in ["parameters", "prompt"]: metadata[f"png_text_{k.lower().replace(' ', '_')}"] = v
        elif img.format == "JPEG":
            metadata["extracted_by"] = "piexif (JPEG)"
            try:
                exif_dict = piexif.load(img.info.get("exif", b""))
                user_comment_bytes = exif_dict.get("Exif", {}).get(piexif.ExifIFD.UserComment, b"")
                if user_comment_bytes:
                    try:
                        user_comment_str = piexif.helper.UserComment.load(user_comment_bytes)
                        if user_comment_str.strip().startswith("{") and user_comment_str.strip().endswith("}"): metadata.update(json.loads(user_comment_str))
                        else: metadata.update(_parse_sd_parameters(user_comment_str))
                    except Exception as e_exif: metadata["raw_jpeg_user_comment"] = user_comment_bytes.decode('latin-1',errors='ignore'); error_keys.append("jpeg_user_comment_parsing_error")
                if "0th" in exif_dict and piexif.ImageIFD.Software in exif_dict["0th"]: metadata["software"] = exif_dict["0th"][piexif.ImageIFD.Software].decode('utf-8', errors='ignore')
            except Exception as e_piexif_load: error_keys.append("piexif_load_error")
        elif img.format == "WEBP":
            metadata["extracted_by"] = f"Pillow ({img.format})"
            if img.info and "exif" in img.info:
                try:
                    exif_dict = piexif.load(img.info["exif"])
                    user_comment_bytes = exif_dict.get("Exif", {}).get(piexif.ExifIFD.UserComment, b"")
                    if user_comment_bytes:
                        user_comment_str = piexif.helper.UserComment.load(user_comment_bytes)
                        if user_comment_str.strip().startswith("{") and user_comment_str.strip().endswith("}"): metadata.update(json.loads(user_comment_str))
                        else: metadata.update(_parse_sd_parameters(user_comment_str))
                except Exception as e_webp: error_keys.append(f"webp_exif_error:{str(e_webp)[:30]}")
        else: metadata["extracted_by"] = f"Pillow ({img.format})"
    except FileNotFoundError: error_keys.append("file_not_found_for_metadata"); metadata["error"] = "File not found"
    except Exception as e_extract: error_keys.append(f"metadata_extraction_unknown_error:{str(e_extract)[:30]}"); metadata["error"] = str(e_extract)
    if error_keys: metadata["error_keys"] = list(set(metadata.get("error_keys", []) + error_keys))
    metadata['width'] = metadata.get('width', metadata.get('width_orig')); metadata['height'] = metadata.get('height', metadata.get('height_orig'))
    return metadata

def load_penalties():
    if not PENALTIES_YML_PATH.exists(): return {}
    try:
        with open(PENALTIES_YML_PATH, 'r', encoding='utf-8') as f: penalties = yaml.safe_load(f)
        return {str(k): float(v) for k,v in penalties.items()} if penalties else {}
    except Exception as e_penalty_load: print(f"Penalties YMLロード失敗: {e_penalty_load}"); return {}

def update_metadata_json(new_metadata_dict):
    current_metadata = {}
    if METADATA_JSON_PATH.exists():
        try:
            with open(METADATA_JSON_PATH, 'r', encoding='utf-8') as f: current_metadata = json.load(f)
        except: pass
    current_metadata.update(new_metadata_dict)
    try:
        with open(METADATA_JSON_PATH, 'w', encoding='utf-8') as f: json.dump(current_metadata, f, indent=2, ensure_ascii=False)
        return True
    except Exception as e_meta_write: print(f"metadata.json書込エラー: {e_meta_write}"); return False

def generate_thumbnail(original_path_str: str, thumbnail_path_str: str, size=(256, 256)):
    original_path = Path(original_path_str); thumbnail_path = Path(thumbnail_path_str)
    try:
        img = Image.open(original_path)
        if img.format in ["HEIF", "HEIC"]:
            if PILLOW_HEIF_AVAILABLE:
                try: register_heif_opener(); img = Image.open(original_path)
                except Exception as heif_e: print(f"HEIFオープンエラー ({original_path.name}): {heif_e}。スキップ。"); return False
            else: print(f"pillow-heif必要 ({original_path.name})。スキップ。"); return False
        img.thumbnail(size, Image.Resampling.LANCZOS)
        thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
        if img.mode in ("RGBA", "P", "LA"): img = img.convert("RGB")
        img.save(thumbnail_path, "JPEG", quality=85, optimize=True)
        return True
    except FileNotFoundError: print(f"サムネイル生成エラー: 元画像なし - {original_path}"); return False
    except Exception as e_thumb: print(f"サムネイル生成エラー ({original_path.name}): {e_thumb}"); return False

if __name__ == '__main__':
    print("--- Scoring Module Test (v4 Final Fix33) ---")
    initialize_all_models(force_cpu=True, progress_callback=lambda msg, p: print(f"Init Progress: {msg} ({p}%)"))
    if not INITIALIZED_SUCCESSFULLY and not CUSTOM_SCORER_AVAILABLE: print("モデル初期化失敗。テスト限定的。")
    test_img_dir = BASE_DIR / "images_test_scoring_v4_fix33"; test_img_dir.mkdir(parents=True, exist_ok=True)
    dummy_png = test_img_dir / "dummy_score_test_fix33.png"
    if not dummy_png.exists():
        try: Image.new('RGB', (100,100),color='red').save(dummy_png)
        except Exception as e_save: print(f"テスト画像保存エラー: {e_save}")
    penalties_cfg = load_penalties();
    if not penalties_cfg: penalties_cfg = {"blurry": 1.0, "bad_hands": 1.5}
    if dummy_png.exists() and INITIALIZED_SUCCESSFULLY :
        print(f"Testing with dummy image: {dummy_png}")
        img_id, score_d, meta_d = process_single_image(str(dummy_png), penalties_cfg)
        print("\nProcessed Data:\nScore:", json.dumps(score_d, indent=2), "\nMeta:", json.dumps(meta_d, indent=2))
        generate_thumbnail(str(dummy_png), str(test_img_dir / f"{img_id}_thumb.jpg"))
    else: print("テスト画像なし、またはモデル初期化失敗のためスコアリングテストをスキップ。")
    print("\n--- Scoring Module Test End ---")