chcp 65001
@echo off
REM =========================================================
REM  AI Image Scorer – Python 3.11 仮想環境セットアップ
REM  * 元スクリプト同様 tensorflow_io は公式バイナリをインストール
REM  * GPU 有無で PyTorch を切り替え
REM =========================================================
setlocal EnableDelayedExpansion

REM --- Python 3.11 実行ファイルへのパスを環境に合わせて修正 ---
set "PYTHON_311_PATH=C:\bot\score_viewer\Python311\python.exe"
REM ---------------------------------------------------------------

set "VENV_DIR=venv"
set "MODEL_TAG=v3-20211112-sgd-e28"
set "MODEL_ZIP=deepdanbooru-%MODEL_TAG%.zip"
set "MODEL_URL=https://github.com/KichangKim/DeepDanbooru/releases/download/%MODEL_TAG%/%MODEL_ZIP%"
set "MODEL_DIR=%~dp0models\deepdanbooru_standard_model"

echo [0/7] Python 3.11 の存在確認...
if not exist "%PYTHON_311_PATH%" (
    echo ERROR: Python 3.11 が見つかりません: %PYTHON_311_PATH%
    pause & exit /b 1
)

echo [1/7] venv 作成／再利用...
if not exist "%VENV_DIR%\Scripts\activate" (
    "%PYTHON_311_PATH%" -m venv "%VENV_DIR%" || (
        echo ERROR: 仮想環境の作成に失敗しました。
        pause & exit /b 1
    )
)
call "%VENV_DIR%\Scripts\activate"
python --version || (
    echo ERROR: 仮想環境が壊れています。
    pause & exit /b 1
)

echo [2/7] pip アップグレード...
python -m pip install --upgrade pip || (
    echo ERROR: pip のアップグレードに失敗しました。
    pause & exit /b 1
)

echo [3/7] 基本パッケージ install...
REM ── torch, torchvision, torchaudio はここに含めず後で分岐インストール ──
set "BASE_PKGS=PySide6 Pillow watchdog PyYAML pandas matplotlib piexif python-dotenv google-generativeai pillow-heif tensorflow tensorflow-io scipy scikit-image scikit-learn tqdm click simple-aesthetics-predictor open-clip-torch ftfy transformers huggingface_hub Jinja2"
pip install %BASE_PKGS%
if errorlevel 1 (
    echo ERROR: 基本パッケージのインストールに失敗しました。
    pause & exit /b 1
)
echo 基本パッケージ インストール完了。

echo [4/7] DeepDanbooru インストール...
pip install deepdanbooru
if errorlevel 1 (
    echo ERROR: DeepDanbooru のインストールに失敗しました。
    pause & exit /b 1
)
echo DeepDanbooru インストール完了。

echo [5/7] PyTorch install (GPU/CPU 判定)...
where nvidia-smi >nul 2>&1
if %errorlevel%==0 (
    echo GPU 検出 → CUDA 12.1 版 PyTorch をインストール...
    pip install --index-url https://download.pytorch.org/whl/cu121 torch torchvision torchaudio
) else (
    echo GPU 未検出 → CPU-only 版 PyTorch をインストール...
    pip install torch torchvision torchaudio
)
if errorlevel 1 (
    echo ERROR: PyTorch のインストールに失敗しました。
    pause & exit /b 1
)
echo PyTorch インストール完了。

echo [6/7] インポートテスト...
for %%M in (tensorflow tensorflow_io torch aesthetics_predictor deepdanbooru) do (
    python -c "import %%M" 2>nul
    if errorlevel 1 (
        echo ERROR: モジュール %%M のインポートに失敗しました。
        pause & exit /b 1
    ) else (
        echo OK: %%M
    )
)

echo [7/7] 学習済みモデルを自動DL...
if not exist "%MODEL_DIR%\project.json" (
    powershell -NoLogo -Command ^
      "New-Item -ItemType Directory -Force -Path '%MODEL_DIR%' | Out-Null; " ^
      "Invoke-WebRequest -Uri '%MODEL_URL%' -OutFile '%MODEL_ZIP%' ; " ^
      "Expand-Archive -Force -Path '%MODEL_ZIP%' -DestinationPath '%MODEL_DIR%' ;" ^
      "Remove-Item '%MODEL_ZIP%'"
) else (
    echo モデル既存 → ダウンロードスキップ
)

echo.
echo === Setup Complete! ===
echo 仮想環境を有効化するには:
echo   call %VENV_DIR%\Scripts\activate
pause
endlocal
