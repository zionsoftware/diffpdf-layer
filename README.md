# diffpdf-layer
PDFの本体とレイヤーごとの注釈を比較するプログラム

## Python 開発環境

Python 3.14.8 を使用し、プロジェクト直下の `.venv` に仮想環境を作成しています。
依存パッケージは `requirements.txt` に記録しています。`.venv` は Git の管理対象外です。

PowerShell で仮想環境を有効にするには、次を実行します。

```powershell
cd C:\dev\diffpdf-layer
.\.venv\Scripts\Activate.ps1
python --version
python -m pip --version
python -m pip install -r requirements.txt
```

有効化せずに直接実行することもできます。

```powershell
.\.venv\Scripts\python.exe -m pip list
```

仮想環境を再作成する場合は、インストール済みの Python で `python -m venv .venv` を実行してください。
