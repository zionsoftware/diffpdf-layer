# 技術調査と設計判断

調査日: 2026-10-15。対象: Python 3.14.8 / pypdf 6.20.1。

## 調査根拠

- [PDF 32000-1:2008、Adobe 公開版](https://opensource.adobe.com/dc-acrobat-sdk-docs/standards/pdfstandards/pdf/PDF32000_2008.pdf): §8.11 の optional content、§8.8 の XObject、§12.5 の注釈を参照。
- [pypdf: Reading PDF Annotations](https://pypdf.readthedocs.io/en/stable/user/reading-pdf-annotations.html): 注釈辞書と参照の走査 API を確認。
- [pypdf: ContentStream 等の実装](https://pypdf.readthedocs.io/en/stable/_modules/pypdf/generic/_data_structures.html): ストリームの展開・命令解析 API を確認。開発環境のインストール済みソースでも確認。
- [PDF Association: graphics errata](https://pdf-issues.pdfa.org/32000-2-2020/clause08.html): Form と optional content が関連することを確認。

## pypdf で可能な処理

Catalog の OCProperties / OCGs / D を直接参照し、間接オブジェクトの同一性からレイヤーを特定できる。注釈の OC、ページの Contents、Resources/Properties と BDC/EMC、Form/Image XObject の OC にアクセスできる。ContentStream.operations で命令と引数を得られる。ストリームのロスレス圧縮は展開して比較可能。

一方、pypdf は OCG と本文を自動で正確に分離するレンダラーではない。単に文字抽出したり注釈辞書を読むだけでは、本文の画像・線・外観・平坦化を比較しきれない。OCMD は複数条件・VE を含み、単一の名前へ割り当てると誤判定になる。

## 採用した分離方式

1. PDF 全体を rb で読み込んだ後、strict モードで解析する。pypdf の警告も検証不能にする。
2. 全ファイルの OCG 構成を検査してから内容を解析する。
3. 通常の本文命令列を正規化し、参照するフォント・画像・ExtGState・色空間・シェーディングを再帰的に取り込む。
4. OCG に属する本文は、q/Q で状態が保存・復元され、パス・テキストが区間外へ漏れず、単一 OCG に明確に属する区間だけを分離する。
5. q/Q は現在のパスを保存しないため、パスと marked content の所有区間も別途検査する。本文・複数レイヤーが混ざる区間は検証不能にする。
6. 独立区間の前にある本文命令もレイヤーの比較データへ含め、CTM・色等の継承状態の変更を見逃さない。精密な描画状態インタープリターを作る代わりに、保守的に不一致が増える方式とした。
7. Form/Image に直接付く OC は呼出区間の所属として扱う。Form の内部 OCG は分離せず検証不能にする。OC のない Form 本文は再帰検査して全体を比較する。
8. 注釈は属性・AP・外観リソース・ページリソースを比較する。OC のない注釈は常に異常。注釈の P はオブジェクト展開ではなく所属ページ参照として検査する。
9. 本文と各レイヤーだけでは重ね順の変更を見逃すため、区間の合成順序も比較する。

## 正規化の限界

画像の画素やフォントの見た目を再構築して比較するのではなく、ストリームと辞書を比較する。JPEG/JPX は符号化データを保持し、再エンコードされた同じ見た目の画像を不一致にすることがある。Form 内部の空白やリソース名の差なども不一致になりうる。

pypdf の FloatObject は内部で float を使い、その repr は PDF 出力用に丸められる。repr の丸めを比較には使わず、float の値から正規化する。さらに、生 PDF と展開後ストリーム (圧縮オブジェクトストリームを含む) の字句を検査し、有効数字 15 桁を超える実数等を拒否する。文字列やバイナリ中の数字にも反応する保守的な検査であり、検証不能の原因になることがある。

## 実出力が必要な項目

PDF-XChange Editor の FreeText の DA/AP とフォント、注釈の Popup / IRT、Form のネスト、Usage / AS、保存最適化、増分保存を優先する。現段階では未入手の実出力に対応できたと主張しない。
