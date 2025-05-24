@echo off
rem ============================================================
rem  viewer_setup.bat
rem  Web公開用フォルダ構造をまとめて作るスクリプトだよ！
rem  置いたフォルダを「ドキュメントルート」と想定して動くから、
rem  例えば C:\xampp\htdocs の直下で実行 → /public_html/viewer/ が出来る感じ！
rem ============================================================

::-------------------------
:: 作る場所を決める
::-------------------------
setlocal enableextensions
set "ROOT=%cd%\viewer"

echo.
echo === Webフォルダ生成スクリプト ===
echo  ★ ターゲット : %ROOT%
echo.

::-------------------------
:: メインディレクトリ
::-------------------------
if not exist "%ROOT%" (
    mkdir "%ROOT%"
)
cd /d "%ROOT%"

::-------------------------
:: JSON／ロックファイル
::-------------------------
for %%F in (scores.json delete_requests.json sync.lock) do (
    if not exist "%%F" type nul > "%%F"
)

::-------------------------
:: 静的ファイル
::-------------------------
for %%F in (index.html style.css script.js favicon.ico manifest.json robots.txt) do (
    if not exist "%%F" type nul > "%%F"
)

::-------------------------
:: 画像ディレクトリ
::-------------------------
mkdir "cloude_image\originals"    2>nul
mkdir "cloude_image\thumbnails"   2>nul

::-------------------------
:: カスタムサウンド
::-------------------------
:: ユーザーごとに UUID でサブディレクトリを作る仕様だけど、
:: 見本フォルダを１個だけ用意しとくね！
mkdir "custom_sounds\sample-uuid" 2>nul

::-------------------------
:: API (PHP)
::-------------------------
mkdir "api" 2>nul
if not exist "api\updateDeleteRequests.php" type nul > "api\updateDeleteRequests.php"

echo.
echo === 完 了！ ===
echo  これでフォルダもファイルもそろったよ。好きなエディタで中身を書いてねっ☆
echo.

endlocal
pause
