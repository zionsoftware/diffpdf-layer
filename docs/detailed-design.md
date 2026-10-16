# 詳細設計書

対象: diffpdf-layer 0.1.0。調査基準: 2026-10-16、文書変更前のmain `a6ea83987e17b5361a3c59264d106b39bc0711f2`。

[基本設計書](basic-design.md)の方式を、現行コードへ対応付ける。関数名・属性名は調査時の実装名である。対応条件の一覧は[対応構造一覧](supported-structures.md)、検証対応は[テスト仕様書](test-specification.md)を参照する。

<a id="dd-01"></a>
## 1. モジュールと依存関係（DD-01）

| ソース | 役割・主な依存 |
|---|---|
| [main.py](../main.py) | 引数解析、検索パス設定、runtime確認、GUI/CLI分岐。comparator/reportをCLIから利用 |
| [runtime.py](../src/pdf_layer_compare/runtime.py) | check_environmentでPython・vendor由来・pypdf版・必要時Tkinterを確認 |
| [gui.py](../src/pdf_layer_compare/gui.py) | Application。Tk画面、子プロセス、キュー、reportの読み戻し・共通詳細・保存 |
| [pdf_parser.py](../src/pdf_layer_compare/pdf_parser.py) | open_document/analyze_documentで読込、OCG、本文、注釈、作成者を統合 |
| [ocg_analyzer.py](../src/pdf_layer_compare/ocg_analyzer.py) | OCGAnalyzer。登録・名前・所属・設定とエラー範囲 |
| [base_analyzer.py](../src/pdf_layer_compare/base_analyzer.py) | DrawingAnalyzer、page_attributes、validate_resource。本文・Form・状態・使用資源 |
| [annotation_analyzer.py](../src/pdf_layer_compare/annotation_analyzer.py) | analyze_annotations、annotation_content、appearance、DA/RC/DS |
| [authors.py](../src/pdf_layer_compare/authors.py) | initialize_authors/collect_authors。独立した/T集計 |
| [fonts.py](../src/pdf_layer_compare/fonts.py) | Font、unicode_map、text_value。通常値・安全な文字復元・二次値 |
| [normalize.py](../src/pdf_layer_compare/normalize.py) | resolve、Canonicalizer、stream_data、content_operations。共通検査と正規化 |
| [comparator.py](../src/pdf_layer_compare/comparator.py) | compare_files、author_info、first_difference。基準対各対象・6判定 |
| [model.py](../src/pdf_layer_compare/model.py) | 状態列挙、Content等のデータ、combine、グループ名 |
| [report.py](../src/pdf_layer_compare/report.py) | TXT/CSV/JSON、旧JSON移行、作成者整形、保存先保護 |
| [start.bat](../start.bat)、[run_python.bat](../tools/run_python.bat) | 作業ディレクトリ設定、通常Python選択、-B -S起動、終了コード伝達 |
| [prepare_offline.py](../tools/prepare_offline.py) | 開発側の配布ソース作成補助。オンライン利用者の必須手順にしない |

解析モジュールはmodel/normalizeを共用する。base_analyzerはfontsとOCGを用い、annotation_analyzerはDrawingAnalyzerでAPを検査する。comparatorはparserからSnapshotを得てReportを作る。reportはPDFを読み直さずReportを整形する。

<a id="dd-02"></a>
## 2. データ構造（DD-02）

| 構造 | 実在する主要属性・役割 |
|---|---|
| Status | MATCH、FONT_ONLY、DIFFERENT、ADDED、REMOVED、UNKNOWN。値は日本語の6判定 |
| Content | exact=通常値、semantic=フォントを分離した二次値、fonts=使用名・指紋、font_errors=分離不能理由 |
| Group | values: Contentのリスト、errors: 理由のリスト。content()で順序付きのグループ値へ結合 |
| Snapshot | path、names、ocg、groups、file_error、authors。1入力の解析結果 |
| AuthorInfo | counts、unset_count、unreadable_count、complete、group_present、errors。incomplete(reason)で完全性を下げる |
| Result | left、right、component、status、detail、font_changes、reference_authors、target_authors、authors_changed |
| Report | files、results、errors。全体のstatus属性は持たない |
| Unsupported | 安全に対応できない入力を示すValueError派生例外 |

グループ定数はBODY="PDF本体"、UNLAYERED="レイヤーなし"、layer_key(name)="レイヤー: 名前"である。作成者情報はPDF本体のResultではNoneとなる。

combine(tag, values, unordered=True)は完全なContentのexact/semanticそれぞれをrepr順で並べたタプルを作る。同一値を削除せず重複数を保持する。fonts/font_errorsも集約する。PDF命令そのものを単純ソートする関数ではない。ページ番号・描画/注釈区別は結合タグに保持する。

<a id="dd-03"></a>
## 3. 読み込み・正規化・解析制限（DD-03）

open_documentは絶対パスへ解決し、pypdf 6.20.1を確認してrbでMAX_FILE+1まで読み込む。BytesIOをPdfReader(strict=True)へ渡し、暗号化PDFは空パスワードでも拒否する。オブジェクトストリームも検査し、CatalogとOCGを取得する。例外はSnapshot.file_errorへ記録しreader=Noneを返す。原本へ書き込むハンドルは持たない。

parser_messagesはpypdfのWARNING以上のログを捕捉する。ファイル読み込み時の警告はファイル解析失敗、内容解析中に捕捉した警告は全グループの失敗となる。作成者の独立走査での警告はDD-07の扱いとなる。

| 制限 | 実装箇所・拒否条件 |
|---|---|
| ファイル128 MiB | pdf_parser.MAX_FILE。上限超で読み込み拒否 |
| 1～2000ページ | analyze_document。reader.pagesの取得後に検査 |
| ページツリー | validate_page_tree。循環、depth > 50、未知のPages属性、Countと実数の差を拒否 |
| 展開データ32 MiB | normalize.MAX_STREAM。stream_data/content_operationsの展開・結合後に検査 |
| 命令100,000 | content_operations。取得済みoperationsの長さを検査。1回の呼び出し単位 |
| 正規化 | Canonicalizer.valueでdepth > 70、nodes > 250,000を拒否。nodesはインスタンス内の呼び出し数 |
| 資源再帰 | validate_resourceでdepth > 50・循環を拒否 |
| Form再帰 | DrawingAnalyzer.formの呼び出し前スタック長 > 30、同一Form再入を拒否。ContextVarで追跡 |
| AP・RichText | appearanceとrich_textの再帰でdepth > 50等を拒否 |
| ToUnicode | unicode_map。1ブロック・範囲・全対応数を65,536以下に制限。コード長や文字列長も検査 |
| 数値 | check_numeric_precision。有効数字15桁超、非ゼロ絶対値1e-100未満を字句検査で拒否 |

get_data後のサイズ検査であり、展開前のメモリー上限や解凍攻撃の完全な防止策ではない。100,000命令も構文解析前に処理を打ち切る制御ではない。数値字句検査は生PDF・展開データに適用し、バイナリや文字列中の数字でも保守的に検証不能となりうる。

resolveは間接参照を実値へ解決して循環を検出する。Canonicalizer.valueは辞書キーを整列し、配列順を保持し、有限数値を正規化する。pypdfの出力用丸め表現を用いない。参照番号・Generationを比較値へ入れない。フォントの限定したサブセット接頭辞・資源名等は保存上の識別子として正規化する。

stream_dataは外部ストリーム参照を拒否する。Flate/ASCIIHex/ASCII85/LZW/RunLengthは展開値で比較し、圧縮差を落とす。DCT/JPXは符号化データとパラメーターを保持し、画素として復元しない。他の未対応フィルターは拒否する。辞書のLengthや対応するロスレス圧縮情報を除き、内容・資源をSHA256等の正規化値へ含める。キャッシュは実オブジェクトを保持し、循環検査を省略しない。

<a id="dd-04"></a>
## 4. OCG・ページ構造（DD-04）

OCGAnalyzer.loadはOCPropertiesのOCGsを読み、間接参照・Type=OCG・空でない文字列名を要求する。名前は大文字小文字・空白・Unicodeを勝手に同一化しない。重複名は該当名を曖昧とし、ownerは登録参照のみを名前へ解決する。OCMD/VEや未登録所属をレイヤーなしに分類しない。

group_configはBaseState、ON/OFF、Locked、関連するAS/RBGroups/Intent等をレイヤーごとに射影する。Order/ListModeは構造の妥当性を検査するが、パネル表示順を比較項目にしない。UsageのView/Print/Exportと対応ASは限定対応し、Language等の未知条件は検証不能とする。

analyze_documentは全グループを作成してOCGの局所・全体エラーを付す。未知Catalog属性やページツリー不正は全体へ波及する。root属性からPages/OCProperties/Metadata/AcroFormを除いた対応文書属性とページ数をPDF本体へ格納する。page_attributesはResources/Contents/Annots等を除いたページ属性を検査し、ページ領域・回転等を保持する。空のTransは省略と同一視する。ページ属性の安全性が失われれば全グループにエラーを付す。

AcroFormはFieldsが空、追加はDRだけの限定形を扱う。使用DAフォントをAcroForm DR優先・ページ資源へフォールバックして解決する。未使用フォントは比較へ混入しない。非空FieldsやXFA等はPDF本体・レイヤーなしと、影響する文字注釈を検証不能とする。

<a id="dd-05"></a>
## 5. 本文描画と順序非依存化（DD-05）

DrawingAnalyzer.partitionは命令を順に読み、q/Q、BMC/BDC/EMC、BT/ET、パスの完結を追跡する。q/Qはグラフィックス状態を保存するが、現在のパスまで保存するとは扱わない。unit_ownersで単一所属を確定し、OCG区間には独立した状態保存を要求する。

state_updates、inherited_is_used、graphics_text_state/restore_stateは行列、色空間、線属性、ExtGState、フォント/サイズ、文字描画モード、単語間隔等を追跡する。ExtGStateは一括置換せず属性ごとに更新する。実際に使用した継承状態のみを単位へ付与し、上書きされた未使用状態を他グループの依存としない。TDのleading更新やT*で使用後TLで上書きする依存も保持する。cmは適用順の列を保持し、任意行列の代数的等価性までは証明しない。

independent_childrenはページの単純なq/Q・単一OC囲みに限り、完結したパス・BT/ET・Doへ分割する。追加の入れ子、クリッピング、OC付き呼び出し等は分割条件から外す。一つのBT/ET内の文字列順や単一パス内のサブパスを分割しない。分割後も状態を再走査して各単位に結び付ける。

operationは命令名・引数数・型・状態の妥当性を検査する。resource/font_resource/default_colorsは使用参照と既定色空間を解決する。formは暗黙のq/Qを反映したストリーム全体を順序付きで解析し、ページ用の子分割を適用しない。内部OCG、循環、Pattern、Type3、PostScript、inline image、未知命令等は未対応として扱う。

pdf_parserはページ番号を付け、各グループの本文単位をcombine(..., unordered=True)で結合する。個数・ページ・所属を保った単位全体だけの順序を無視する。安全に残せる複合単位は内部順序付きのまま比較するため、内部順序変更は不一致となることがある。q/Q外のクリッピングや状態の漏れなど、影響を確定できない構造は検証不能とする。

<a id="dd-06"></a>
## 6. 注釈・フォント（DD-06）

analyze_annotationsは注釈辞書と所属を読み、所属確定後の例外を該当グループへ限定する。annotation_contentは対応Subtype、Rect/L/Vertices/InkList等の座標、Pとページの対応を検査する。汎用の実質属性も比較し、作成者らしい独自キーを勝手に除外しない。LinkのActionは限定したURI形のみ値として比較し、開かない。Popup/Parent/IRT/AA、動的Action等は未対応とする。

内容から/T、保存由来の/M・/CreationDate・/NMを除く。/Pはページ対応を検査後に除き、/OCは所属へ反映する。AP/DA/RC/DSは各専用処理へ渡す。appearanceはN/R/Dと外観状態辞書を再帰検査し、Formとして内部命令・資源を保持する。default_appearanceは限定テキスト状態命令と使用フォントを解決する。自動サイズ等でフォント分離が安全でなければfont_errorsを保持する。css/rich_textは限定したfont-familyだけを二次値から分離し、文字・構造・他のstyle属性を残す。

Fontはフォント辞書・Descriptor・埋め込みデータ等のexactと、内部名・指紋を持つ。Font._mapping/unicode_mapは対応するToUnicode、またはStandard/WinAnsi/MacRomanEncodingと限定Differencesから厳密に復元する。Type0はIdentity-Hと対応ToUnicodeを必要とする。Encoding省略時の暗黙StandardEncodingは、埋め込みなしの限定欧文Base14 Type1に限る。

Font.decode/text_valueは字形コード単位のUnicodeクラスターを保持する。複数字形と1字形の合字を無条件に同一化せず、Twの1バイト0x20規則等も保持する。UseCMap、曖昧なコード長、重複対応、不正UTF-16、未定義コード等は推測しない。復元失敗はfont_errorsへ残し、通常値に差がある場合の二次比較を禁止する。通常値が一致すれば復元エラーだけで一致を取り消さない。

<a id="dd-07"></a>
## 7. 作成者集計（DD-07）

initialize_authorsはレイヤーなし・各OCGのAuthorInfoを作る。登録一覧不完全なら全対象、重複名ならその名前を未完了とする。collect_authorsは内容解析後、独立した警告捕捉の下でページ・Annots・所属・/Tを走査する。

欠落/空文字の/Tはunset_count、TextStringObjectの非空値はcounts[name]へ加算する。空白だけの名前、大文字小文字、前後空白も記録値のまま区別する。読めない/Tで所属が既知ならunreadable_countを増やし当該集計を未完了にする。Annots破損や所属不明なら影響しうる全集計を未完了にし、不明件数を特定レイヤーへ配分しない。内容の未対応だけでは作成者集計を捨てない。

author_infoはファイル失敗時にcomplete=False/group_present=None、登録一覧が確定して存在しないレイヤーにはcomplete=True/group_present=Falseを返す。compare_filesは双方completeの場合だけ(counts, unset_count)を比較してauthors_changedへ格納する。いずれか不完全ならNone。注釈ごとの対応付けや「userA→userB」の推測は行わない。

<a id="dd-08"></a>
## 8. グループ判定・エラー範囲（DD-08）

compare_filesは2～4件を検証し、各入力を一度解析する。1番目を基準に、後続それぞれとPDF本体・レイヤーなし・名前順の各OCGを比較する。各行の作成者情報は内容判定と独立して設定する。

```text
エラーがあれば UNKNOWN（理由を保持）
それ以外でOCGが基準にないなら ADDED、対象にないなら REMOVED
必要グループが取得できなければ UNKNOWN
exact が同じなら MATCH
exact が異なり font_errors があれば UNKNOWN
semantic が同じで使用フォント集合が異なれば FONT_ONLY + font_changes
それ以外は DIFFERENT + first_difference
```

font_changesはbefore/after内部名、source、before_fingerprints/after_fingerprintsを保持する。first_differenceは二次値、必要なら通常値から最初の差を探索する。探索深度12超は一般的な差の説明、末端値は先頭180文字に限定する。全差分や注釈の正確な画面位置を一覧化する機能ではない。

| 失敗 | 内容への主な影響範囲 |
|---|---|
| ファイル読込・暗号化・読込時警告 | そのPDFを含む各組のグループ。Report.errorsにも記録 |
| OCG登録一覧不完全 | そのPDFの全グループ。追加/削除も推測しない |
| OCG局所設定・重複名 | 当該レイヤー。設定全体不明なら対象OCGへ拡大 |
| 所属確定済み本文・注釈の未対応 | 当該グループ |
| ページ本文・注釈一覧の解析例外 | そのページの描画グループ（レイヤーなし・各OCG） |
| 未知Catalog・ページ構造・内容解析時の全体警告 | 全グループ |
| 作成者/Tの失敗 | 作成者集計の完全性のみ。既知なら局所、不明なら集計範囲を拡大 |

全比較の停止や総合不一致への集約は行わない。ただし影響範囲を安全に限定できない失敗は複数行を検証不能にする。

<a id="dd-09"></a>
## 9. レポートと保存（DD-09）

row_detailsはパス、対象、内容判定、差異と双方のauthor_summary、author_change_text、記録値に関する注意を整形する。GUIとTXTで共用する。author_summaryは名前をJSON文字列表現にし、改行等を可視化する。完全な空集計の「注釈なし」、存在しないグループ、集計未完了、未設定・取得不能を区別する。

| 形式 | 実際の構造 |
|---|---|
| TXT | to_text。入力順・ファイルエラー・各行の共通詳細。UTF-8 |
| CSV | to_csv。基準PDF、比較対象PDF、対象、内容判定、詳細、基準PDF 注釈の作成者名（PDF記録値）、比較対象PDF 注釈の作成者名（PDF記録値）、作成者名の構成の変更の8列。UTF-8 BOM付き |
| JSON | to_json。schema_version=3、files、reference、targets、results、errors。Result/AuthorInfoの属性を構造化。UTF-8 |

CSVの集計は1セルの文字列であり、名前ごとに別行を設けない。font_changes専用構造はJSON、TXT/CSV/GUIにはフォント差の説明を保持する。CSVではReport.errorsを「ファイル解析」の検証不能行として出す。

from_jsonはversion 3の必須集計属性、正の名前別件数、非負の未設定/取得不能件数、完全性、存在、構成変更の整合等を検査する。version 2は旧合成順序行を除去し、各行をUNKNOWNへ変換して旧判定を詳細に残し、Report.errorsへ再比較案内を追加する。これはライブラリとGUI内部通信の機能で、利用者向けの保存JSONを開く画面はない。

save_reportは拡張子を.txt/.csv/.jsonに限定する。resolveしたパスのnormcase比較と、既存ファイルのos.path.samefileで入力PDFへの上書きを拒否する。CSVのcsv_cellは左側空白を除いた先頭が=、+、-、@なら引用符を先置する。保存先の親フォルダーは作らず、通常のwrite_textで書く。入力でない既存ファイルは上書きされうる。原子的な置換・履歴保存は実装していない。

<a id="dd-10"></a>
## 10. 起動・GUI・CLI制御（DD-10）

main.pyはsrc/vendorをsys.pathへ追加し、vendorを優先する。runtime.check_environmentはvendor/pypdf/__init__.pyの存在、Python 3.14系、実際のpypdf読込元と版6.20.1を確認する。GUI/--checkではTkinterもインポートする。CLI/--jsonにはTk確認を要求しない。LICENSE配置は手順上の義務であり、runtimeによるファイル検査はない。

start.batはツールの場所へcdし、run_python.batに引数を渡す。DIFFPDF_PYTHONがあれば指定実行ファイルだけを検査し、不正でも別候補へ自動切替しない。未指定ならpy -3.14、次にPATHのpythonを調べる。sys.prefix == sys.base_prefixと3.14系を要求する。-Bでpyc作成を抑止し、-Sでsite-packagesを使わない。引数なし起動でエラーの場合は表示確認のためpauseする。

Application.startはmain.py --jsonを同じPythonの-S付き子プロセスで起動する。workerはcommunicate(timeout=180)でUTF-8出力を受信し、from_jsonでReport化してキューへ入れる。pollが100ms間隔で世代番号を確認して画面更新する。Tk操作をworkerへ渡さない。cancelは世代を更新して子を停止し、結果なしへ戻す。closeも停止後に画面を閉じる。

GUIタイムアウト・読めないJSON・起動失敗時はreport=Noneとし、「検証不能：処理失敗または制限時間超過」を画面の状態表示へ出す。各グループのResultを捏造しない。GUIのsaveはOSError/ValueErrorを保存エラーとして表示する。

| CLI引数・結果 | 挙動 |
|---|---|
| --check | 環境確認だけを行い、成功時にPython/pypdf版・実行ファイル・vendor方式を表示 |
| --cli | GUIを開かず比較し、TXTを標準出力へ出す |
| --json | GUIを開かず比較し、JSONを標準出力へ出す |
| --output | --cli/--jsonと併用し、拡張子で保存形式を選ぶ。単独ではGUI起動で保存されない |
| 終了コード0 | コマンド処理成功。内容不一致・グループ検証不能を含む場合がある |
| 終了コード2 | 環境確認失敗、入力個数・ファイル解析等のReport.errors、argparseの引数エラー |
| 保存例外等 | CLIでは一括捕捉せず異常終了しうる。すべての失敗が2になる保証はない |

ソフトウェア版は[__init__.py](../src/pdf_layer_compare/__init__.py)の__version__="0.1.0"。CLIの--versionやGUIの版表示は実装していない。導入手順は[インストール手順書](installation-guide.md)を参照する。
