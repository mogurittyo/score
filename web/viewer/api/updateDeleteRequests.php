<?php
// api/updateDeleteRequests.php

$deleteRequestsFile = dirname(__DIR__) . '/delete_requests.json';

header('Content-Type: application/json');
// 本番環境では、Reactアプリがホストされているドメインのみを許可することを強く推奨します。
// 例: header('Access-Control-Allow-Origin: https://your-react-app-domain.com');
header('Access-Control-Allow-Origin: *'); // 開発用: すべてのオリジンを許可 (本番では非推奨)
header('Access-Control-Allow-Methods: POST, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

// OPTIONSリクエストへの対応 (CORSプリフライトリクエスト)
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

// POSTリクエストのみを許可
if ($_SERVER['REQUEST_METHOD'] !== 'POST') {
    http_response_code(405); // Method Not Allowed
    echo json_encode(['success' => false, 'message' => 'POSTメソッドのみ許可されています。']);
    exit;
}

$jsonPayload = file_get_contents('php://input');
$updatedDeleteRequests = json_decode($jsonPayload, true);

// JSONデコードの検証
if (json_last_error() !== JSON_ERROR_NONE) {
    http_response_code(400); // Bad Request
    echo json_encode(['success' => false, 'message' => '無効なJSONデータです: ' . json_last_error_msg()]);
    exit;
}

// 配列であることを期待
if (!is_array($updatedDeleteRequests)) {
    http_response_code(400); // Bad Request
    echo json_encode(['success' => false, 'message' => 'データは配列である必要があります。']);
    exit;
}

// 各要素が必要なキー（id, filename）を持っているか簡易的に検証 (オプション)
foreach ($updatedDeleteRequests as $item) {
    if (!isset($item['id']) || !isset($item['filename'])) {
        http_response_code(400);
        echo json_encode(['success' => false, 'message' => '各削除リクエストには "id" と "filename" が必要です。']);
        exit;
    }
}

try {
    // パストラバーサル対策として、ファイル名をbasenameで取得し、固定ディレクトリと結合
    $baseDir = realpath(dirname($deleteRequestsFile));
    $fileName = basename($deleteRequestsFile);
    
    // $baseDir が false (ディレクトリが存在しないなど) の場合のエラー処理
    if ($baseDir === false) {
        throw new Exception("親ディレクトリの解決に失敗しました。サーバーのファイル構造を確認してください。");
    }
    $secureFilePath = $baseDir . DIRECTORY_SEPARATOR . $fileName;

    // $deleteRequestsFile と $secureFilePath が一致するか確認 (より厳密なチェック)
    // realpath() はシンボリックリンクを解決するため、意図しないパスになる可能性を低減
    if (realpath($deleteRequestsFile) !== $secureFilePath && $deleteRequestsFile !== $secureFilePath) {
         // $deleteRequestsFile がまだ存在しない場合 realpath は false を返すので、そのケースも考慮
         if (file_exists($deleteRequestsFile) && realpath($deleteRequestsFile) !== $secureFilePath) {
            throw new Exception("ファイルパスの検証に失敗しました (セキュリティチェック)。");
         }
         // まだファイルが存在しない場合は、$secureFilePath を使用する
         if (!file_exists($deleteRequestsFile)) {
             $finalPath = $secureFilePath;
         } else {
             $finalPath = $deleteRequestsFile; // 既存のパスを使用
         }
    } else {
        $finalPath = $secureFilePath;
    }
    
    if (!file_exists($finalPath)) {
        if (file_put_contents($finalPath, "[]") === false) {
            throw new Exception("delete_requests.jsonの新規作成に失敗しました。ディレクトリの書き込み権限を確認してください。");
        }
        // 新規作成時はパーミッションを適切に設定 (環境による)
        // chmod($finalPath, 0664); 
    }
    
    $fileHandle = fopen($finalPath, 'c+'); // 'c+' で読み書き、なければ作成、ポインタは先頭
    if (!$fileHandle) {
        throw new Exception("delete_requests.jsonを開けませんでした。ファイルの書き込み権限を確認してください。");
    }

    if (flock($fileHandle, LOCK_EX)) { // 排他ロックを取得
        ftruncate($fileHandle, 0); // ファイルを空にする
        fwrite($fileHandle, json_encode($updatedDeleteRequests, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE));
        fflush($fileHandle); // バッファをフラッシュ
        flock($fileHandle, LOCK_UN); // ロックを解放
    } else {
        fclose($fileHandle); // ロック失敗でも閉じる
        throw new Exception("delete_requests.jsonのロック取得に失敗しました。");
    }
    fclose($fileHandle);
    
    http_response_code(200);
    echo json_encode([
        'success' => true,
        'message' => '削除リクエストが正常に更新されました。',
        'updatedQueue' => $updatedDeleteRequests,
        'itemsCount' => count($updatedDeleteRequests)
    ]);

} catch (Exception $e) {
    http_response_code(500); // Internal Server Error
    // エラーログにはより詳細な情報を記録
    error_log("Error updating delete_requests.json: " . $e->getMessage() . " (File: " . $deleteRequestsFile . ", Final Path: " . (isset($finalPath) ? $finalPath : 'N/A') . ")");
    echo json_encode([
        'success' => false,
        'message' => 'サーバーエラーが発生しました。詳細はサーバー管理者にご確認ください。'
        // 'debug_message' => $e->getMessage() // デバッグ時のみ有効化
    ]);
}
?>
