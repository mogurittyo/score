from flask import Flask, request, jsonify
import json, datetime
from pathlib import Path
import os

app = Flask(__name__)

@app.after_request
def add_cors_headers(resp):
    resp.headers['Access-Control-Allow-Origin'] = '*'
    resp.headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS'
    resp.headers['Access-Control-Allow-Headers'] = 'Content-Type'
    return resp

BASE_DIR = Path(__file__).resolve().parents[3]
VIEWER_DIR = BASE_DIR / 'web' / 'viewer'
IMAGES_ORIGINALS_DIR = BASE_DIR / 'images' / 'originals'
DELETED_DIR = BASE_DIR / 'deleted'
SCORES_JSON_PATH = BASE_DIR / 'scores.json'
METADATA_JSON_PATH = BASE_DIR / 'metadata.json'
SCORES_JSON_WEB_PATH = VIEWER_DIR / 'scores.json'
METADATA_JSON_WEB_PATH = VIEWER_DIR / 'metadata.json'
DELETE_REQUESTS_JSON_PATH = BASE_DIR / 'delete_requests.json'
DELETE_REQUESTS_WEB_PATH = VIEWER_DIR / 'delete_requests.json'

def load_json(path, default):
    if path.exists():
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data if isinstance(data, type(default)) else default
        except Exception:
            return default
    return default


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

@app.route('/api/delete_image', methods=['POST', 'OPTIONS'])
def delete_image():
    if request.method == 'OPTIONS':
        return ('', 200)
    payload = request.get_json(silent=True) or {}
    image_id = payload.get('id')
    if not image_id:
        return jsonify(success=False, message='id required'), 400

    scores = load_json(SCORES_JSON_PATH, {})
    metadata = load_json(METADATA_JSON_PATH, {})
    if image_id not in scores:
        return jsonify(success=False, message='image not found'), 404

    data = scores.get(image_id, {})
    filename = data.get('filename', image_id)
    orig_path = Path(data.get('path', IMAGES_ORIGINALS_DIR / filename))
    thumb_path = data.get('thumbnail_path_local')
    dest_dir = DELETED_DIR / datetime.datetime.now().strftime('%Y%m%d')
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        if orig_path.exists():
            os.rename(orig_path, dest_dir / orig_path.name)
    except Exception:
        pass
    if thumb_path:
        tp = Path(thumb_path)
        try:
            if tp.exists():
                tp.unlink()
        except Exception:
            pass

    scores.pop(image_id, None)
    metadata.pop(image_id, None)
    for path in [SCORES_JSON_PATH, SCORES_JSON_WEB_PATH]:
        save_json(path, scores)
    for path in [METADATA_JSON_PATH, METADATA_JSON_WEB_PATH]:
        save_json(path, metadata)

    delete_requests = load_json(DELETE_REQUESTS_JSON_PATH, [])
    if not any(item.get('id') == image_id for item in delete_requests):
        delete_requests.append({'id': image_id, 'filename': filename})
        for path in [DELETE_REQUESTS_JSON_PATH, DELETE_REQUESTS_WEB_PATH]:
            save_json(path, delete_requests)

    return jsonify(success=True, message='deleted')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
