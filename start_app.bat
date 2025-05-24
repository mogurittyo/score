@echo off
REM カレントディレクトリをC:\bot\score_viewerに移動
cd /d C:\bot\score_viewer

REM 仮想環境を有効化 (venvという名前の仮想環境を想定)
echo Activating virtual environment...
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate
) else (
    echo Virtual environment not found in "venv". Please run setup_env.bat first.
    pause
    exit /b 1
)

REM メインアプリケーションを起動
echo Starting AI Image Scorer application...
REM python app\qt_launcher.py を以下のように変更
python -m app.qt_launcher

REM 仮想環境の無効化は通常、コマンドプロンプトを閉じると自動的に行われます。
REM 必要であれば `call deactivate` を最後に追加してください。
pause
