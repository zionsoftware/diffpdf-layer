# インストール・セットアップ手順書

対象: diffpdf-layer 0.2.0。更新日: 2026-10-26。

## 1. 動作環境

| 項目 | 必要な準備・検証範囲 |
|---|---|
| OS | Windows。既存の実機検証はWindows 11。Windows各版・別DPIでの網羅確認は未実施 |
| Python | 検証済みは3.14.8 64bitの通常インストール。起動処理は3.14系を許可するが、他のパッチ版・32bitの検証済みを意味しない |
| GUI | PythonのTcl/Tk・Tkinterが必要。検証済みTkは9.0。利用可能な画面セッションが必要 |
| pypdf | **6.20.1**のPythonソースを手動でvendorへ配置する。別の版は起動時に拒否する |
| 権限 | ツールとPDFの読み取り、結果保存先の書き込み。Python本体導入に必要な権限は環境による |

実行環境でのpipインストール・venv作成・外部通信・EXE化は不要です。ソースのZIP自動展開も行いません。開発用pytestは利用者の環境に不要です。PDF-XChange Editorのインストールは本ツールの起動条件ではありません。

## 2. Pythonを準備する

オフライン側で通常のPython 3.14.8 64bitとTcl/Tkが使えることを前提にします。未導入の場合は、[Python公式のWindows配布一覧](https://www.python.org/downloads/windows/)から必要版のWindows installer (64-bit)を別途用意し、オフライン側でPythonとTcl/Tk・Tkinterを含む構成を導入してください。オンライン側でPythonや自作スクリプトを実行する必要はありません。

通常のインストール済みPythonを使用します。embeddable版・独自の最小構成・別アーキテクチャは検証対象としていません。Python導入の制限や権限は実行環境に従ってください。実際の起動確認は後述の--checkと画面起動で行います。

## 3. ソースを入手する

オンライン側では、ブラウザーで次の2つのZIPをダウンロードするだけです。Python・PowerShell・BAT・本ツールをオンライン側で実行する手順はありません。

1. [diffpdf-layerのリポジトリ](https://github.com/zionsoftware/diffpdf-layer)で、必要なリビジョンを選び「Code → Download ZIP」から取得します。取得元のコミットSHAも控えると版を特定できます。
2. [pypdf 6.20.1の公式リリース](https://github.com/py-pdf/pypdf/releases/tag/6.20.1)から「Source code (zip)」を取得します。別バージョンへ読み替えないでください。

ZIPをオフライン側へ持ち込み、利用者が手動で展開します。ツールのZIPにはvendor/pypdfは含まれていないため、pypdfの手動コピーが必要です。Gitや開発環境がなくても配布ソースから起動できます。

<a id="vendor"></a>
## 4. pypdfを手動配置する

ツールのZIPを展開し、main.pyとstart.batがあるフォルダーをルートとします。以下は`C:\tools\diffpdf-layer`を配置例にします。

pypdfのZIPを展開すると、外側の`pypdf-6.20.1`の中に、内側の`pypdf`フォルダーとLICENSEがあります。コピーするのは**内側のpypdfフォルダー全体**です。

| コピー元（pypdf ZIP展開先） | コピー先（ツールのルートから） |
|---|---|
| pypdf-6.20.1\pypdf フォルダー全体 | vendor\pypdf |
| pypdf-6.20.1\LICENSE | vendor\pypdf-LICENSE.txt（コピー時に改名） |

vendorフォルダーがなければ作成します。.pyだけを選別せず、サブフォルダーやpy.typedも含めてコピーしてください。外側のpypdf-6.20.1をそのままvendorへ置く方法や、__init__.pyだけをコピーする方法では動きません。pypdfのtestsやdocs等は不要です。

```text
C:\tools\diffpdf-layer\
├── main.py
├── start.bat
├── LICENSE
├── README.md
├── src\pdf_layer_compare\...
├── tools\run_python.bat
├── docs\...
└── vendor\
    ├── pypdf-LICENSE.txt
    └── pypdf\
        ├── __init__.py
        ├── _reader.py
        ├── _writer.py
        ├── py.typed
        ├── generic\...
        └── その他すべてのファイル・サブフォルダー
```

システムのsite-packagesにpypdfがインストールされていても、vendorの配置は必要です。pypdfのライセンスもコピーして保持してください。ライセンスファイルの有無は起動コードでは検査しないため、配置時に確認します。

<a id="check"></a>
## 5. 環境を確認し、起動する

オフライン側のコマンドプロンプトで、ツールのルートへ移動して確認できます。PowerShellスクリプトは不要です。

```bat
cd /d C:\tools\diffpdf-layer
start.bat --check
```

成功時は「環境確認 OK」、Python・pypdfの版、使用するPythonのフルパス、vendorから読む旨を表示します。--checkはTkinterの読み込み確認までであり、画面セッションの動作確認ではありません。

続いて`start.bat`をダブルクリックするか、同じコマンドプロンプトで次を実行し、GUIが開くことを確認します。

```bat
start.bat
```

担当・確認の欄は必須で指定し、必要に応じて審査・承認も指定します。操作と判定の読み方は[ユーザーマニュアル](user-manual.md)を参照してください。起動用BATは環境確認と起動だけを行い、インストール・ダウンロード・venv作成・ZIP展開をしません。setup.batはありません。

<a id="python-path"></a>
## 6. Pythonの場所を指定する

通常は、起動処理が`py -3.14`、次にPATH上の`python`を探します。仮想環境内のPythonは選びません。ツールの.venvは参照しません。

見つからない場合や別のPythonが選ばれる場合は、環境変数DIFFPDF_PYTHONに、通常インストール済みpython.exeのフルパスを指定します。次は例であり、実際のインストール先へ置き換えてください。

```bat
set "DIFFPDF_PYTHON=C:\Users\ユーザー名\AppData\Local\Programs\Python\Python314\python.exe"
start.bat --check
start.bat
```

このsetは同じコマンドプロンプト内で有効です。ダブルクリック時にも使う場合はWindowsのユーザー環境変数に設定します。DIFFPDF_PYTHONを設定すると、その指定先だけを検査します。無効な指定を残したまま別のPythonへ自動切替はしません。不要な指定は削除してください。

起動処理は-B -Sを付け、pyc生成を抑止しsite-packagesを無効化します。手動配置のvendorが必要な理由はこの方式にもあります。[実際の起動処理](detailed-design.md#dd-10)に詳細を記載しています。

<a id="cli"></a>
## 7. コマンドラインで利用する

GUIを使わない比較には--cliまたは--jsonを指定します。パスに空白がある場合も、下記のように引用符で囲みます。保存先フォルダーは先に作成してください。

```bat
start.bat --cli "C:\PDF\担当.pdf" "C:\PDF\確認.pdf"
start.bat --json --output "C:\結果\比較.json" "C:\PDF\担当.pdf" "C:\PDF\確認.pdf"
start.bat --cli --output "C:\結果\比較.csv" "C:\PDF\担当.pdf" "C:\PDF\確認.pdf" "C:\PDF\審査.pdf"
```

--cliはTXT、--jsonはJSONを標準出力へ出します。--outputで保存する形式は拡張子で選びます。--outputは--cli/--jsonと併用してください。--output単独ではGUIが開き、自動保存しません。--checkは比較せず環境確認を行います。--helpで引数の説明を表示できます。

終了コード0はコマンド処理が完了した意味で、全グループ一致を意味しません。不一致やグループ単位の検証不能でも0となりえます。環境・入力個数・ファイル解析等のエラーは2ですが、通常の保存エラーもerrorsへ記録し2となります。自動処理では終了コードだけでなく、JSONのerrorsと各pairsのoverall・business、およびresultsのstatusも確認してください。CLIにはGUIの180秒待機制限はありません。

## 8. エラーへの対処

| 表示・状況 | 確認すること |
|---|---|
| Python 3.14 outside a virtual environment was not found | Pythonの導入・版とDIFFPDF_PYTHONを確認します。venvのpython.exeやStoreの実行エイリアスを指定しないでください |
| pypdfのソースが見つからない | vendor\pypdf\__init__.pyがあるか、外側フォルダーをコピーしていないか確認します |
| pypdfの読み込み失敗 | 内側のフォルダー全体を再配置します。__init__.pyだけでは不足です |
| pypdfのバージョンが違う | 6.20.1のソースを配置し直します。他の版を混在させないでください |
| Tkinterを読み込めない | 通常PythonのTcl/Tk・Tkinterを含む構成を確認します |
| --checkは成功するがGUIが開かない | 画面セッションやTkの動作を確認します。--checkだけでは表示可能性は検査しません |
| 保存先がない・書き込めない | 保存先フォルダーを作成し、権限・拡張子を確認します |

引数なしのダブルクリック起動でエラーになると、メッセージ確認のためBATが一時停止します。引数付きの起動では同じ一時停止を行わないため、コマンドプロンプトで実行して内容を確認してください。

## 9. バージョン確認・更新・再配置

環境のPython/pypdf版はstart.bat --checkで確認します。本ツールの版は[src/pdf_layer_compare/__init__.py](../src/pdf_layer_compare/__init__.py)の__version__（現行0.2.0）をテキストで確認できます。--versionやGUIの版表示機能はありません。同じ版でも改修があるため、配布元のコミットSHAも記録してください。Gitを利用する開発環境ではgit rev-parse HEADで確認できます。

更新時は新しいツールソースを別フォルダーへ展開し、その版のREADME・本手順で要求されるpypdfを配置して--checkと起動確認を行います。古いソースと新しいソース、複数版のpypdfを混在させないでください。入力PDFと保存結果を更新先へ上書きコピーする必要はありません。比較結果は仕様変更の影響を受けるため、必要なら元PDFから再比較します。

配布時は本ツールの[LICENSE](../LICENSE)とvendorのpypdfライセンスを保持します。実行時のネットワーク断、別Windows版・別DPI等のすべての構成で実機確認済みとするものではありません。検証済み条件と未確認事項は[テスト仕様書](test-specification.md#open-items)を参照してください。

## 10. PDF出力を追加する

比較とTXT保存には不要です。PDF保存を使う環境では、requirements-pdf.txtのReportLab 4.4.9、Pillow 12.3.0、charset-normalizer 3.5.2を、vendorへ追加配置します。実行時のダウンロードやpip実行は行いません。

オンライン側でブラウザーを用いて各パッケージのwheelを取得し、オフライン側でZIPとして展開します。ReportLabはpy3-none-any、Pillowとcharset-normalizerは実行先に合うPython 3.14・Windows・CPU用を選びます。今回の検証対象はcp314・win_amd64です。Pillow等はバイナリを含むため、比較・TXTのみのソース配布とは区別します。

各wheelからreportlab、PIL、charset_normalizerのフォルダーと、各dist-info（LICENSE等を含む）をvendor直下へコピーしてください。wheel内に付属ライブラリ用のフォルダーがある場合も保持します。別Python・別CPU用のファイルを混在させないでください。site-packagesへ置くだけでは、通常の起動が-Sを使用するため読み込まれません。

開発者が同じPython・OS・CPUの環境で配布物を作る場合は、次を実行できます。この手順は開発用で、オフライン利用者が実行する必要はありません。

```bat
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -r requirements-pdf.txt
.venv\Scripts\python.exe tools\prepare_offline.py dist\offline-pdf --with-pdf
```

通常のWindowsではC:\Windows\Fonts\msgothic.ttcを読み込み、使用文字をPDFへ埋め込みます。別フォントを使う場合は、埋め込みを許可された日本語TrueTypeフォントをvendor\fonts\Japanese.ttfへ配置するか、環境変数DIFFPDF_REPORT_FONTに.ttf/.ttcのフルパスを指定します。Windowsのフォントファイルを配布物へコピーする処理はありません。

```bat
set "DIFFPDF_REPORT_FONT=C:\Fonts\Japanese.ttf"
start.bat --cli --responsible "C:\PDF\担当.pdf" --confirmation "C:\PDF\確認.pdf" --approval "C:\PDF\承認.pdf" --output "C:\結果\cmp.pdf"
```

審査を省略して承認を指定する場合は、このように役割別オプションを使います。位置引数では担当・確認・審査・承認の順となるため、3番目は審査です。役割別オプションと位置引数は併用できません。

PDF依存や日本語フォントが不足している場合は保存エラーとなり、比較結果は保持されます。TXTでの保存も利用できます。--checkはPython・Tkinter・pypdfの比較環境の確認です。PDF出力の準備は、実際にcmp.pdfを保存して確認してください。
