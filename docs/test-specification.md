# テスト仕様書・検証結果

対象: diffpdf-layer 0.2.0。整理日: 2026-10-26。文書変更前コード: `a6ea83987e17b5361a3c59264d106b39bc0711f2`。

## 0. 0.2.0の追加試験

[test_workflow.py](../tests/test_workflow.py)で任意工程4パターン、最後の工程の基準化、全6組×7比較項目×不一致/検証不能の業務規則、必須レイヤーの不足・重複・追加、同一パスの複数役割、SHA-256・更新日時・容量、読み込み中の変更、旧JSON移行・不正データ拒否、役割別CLI、日本語PDF・長いパス・複数ページ、PDF依存不足、オフラインPDF配布を検証する。

今回の変更はフォントのみ変更・追加・削除を不一致に統合する。下記の旧版実機履歴にある「フォントのみ変更の一致」等の表記は当時の記録であり、0.2.0の三分類は[工程別比較の仕様](workflow-specification.md)に従う。

## 1. 方針・環境・区分

[要件定義書](software-requirements.md)の受入条件を、既存テストと検証記録に対応付ける。TC番号は本書での試験項目の分類であり、pytestの実行件数と一対一ではない。パラメーター化された関数は複数件として収集される。代表関数を挙げ、当該テストファイルの全ケースはソースを参照する。

既存記録の環境はWindows 11、Python 3.14.8 64bit、Tk 9.0、pypdf 6.20.1、pytest 9.1.1。実出力を作成した編集ソフトはPDF-XChange Editor 11.1.0.0。開発テスト用venvと、利用者向けの通常Python＋vendor起動を区別する。テスト実行時のコピー・出力先はプロジェクト内の一時領域とする。

| 区分 | 確認対象・方法 |
|---|---|
| 単体 | Canonicalizer、CSVエスケープ、JSON読み戻し、状態・文字復元等 |
| 統合 | 生成PDFを解析→グループ比較→レポート化、オフライン配布ソース起動 |
| 回帰 | 順序・作成者・フォント・未知構造・他グループ独立性の反例 |
| GUI・CLI | Tkアプリをプログラムから操作し子プロセス・詳細・中止等を検査、BAT/CLIを起動 |
| Editor実出力 | 実際にEditorで保存した未加工PDFを読み取り比較。生成PDFとは別区分 |
| 原本保護 | 比較前後のSHA256、保存先の同一パス・ハードリンク拒否 |

生成PDFは[conftest.py](../tests/conftest.py)のmake_pdf/pdf_value/streamを中心に作る。意図した属性だけを変え、期待判定と無関係なグループの維持を確認する。生成データはEditorの保存挙動や画面操作の確認には数えない。

私有実出力はGitに含めない。test_xchange_integration.pyとtest_xchange_resumed.pyは、必要なローカルファイルがない場合に該当ケースをスキップする。このため公開リポジトリの取得だけで過去の268件成功を完全再現できるとはしない。元PDFや記録名を公開テストへ追加しない。

<a id="cases"></a>
## 2. 試験項目と期待結果

以下の略号は実在するテストファイルを指す。`test_`から始まる名前はそのファイル内の関数である。

| 略号 | ファイル |
|---|---|
| C | [test_comparison.py](../tests/test_comparison.py) |
| G | [test_group_comparison.py](../tests/test_group_comparison.py) |
| O | [test_order_and_authors.py](../tests/test_order_and_authors.py) |
| R | [test_regressions.py](../tests/test_regressions.py) |
| E | [test_editor_structures.py](../tests/test_editor_structures.py) |
| U | [test_reports_and_gui.py](../tests/test_reports_and_gui.py) |
| X | [test_xchange_integration.py](../tests/test_xchange_integration.py) |
| Y | [test_xchange_resumed.py](../tests/test_xchange_resumed.py) |

### 入力・比較・安全性

| TC-ID | 要件ID | 条件・代表する既存テスト | 期待結果 |
|---|---|---|---|
| TC-001 | FR-001、FR-002 | C: test_reference_comparison_order、test_input_count | 2～4件では全1/3/6組が得られ、0/1/5件は入力エラー |
| TC-002 | FR-003 | C: test_base_changes、R: test_no_ocg_base_only、E: test_empty_transition_is_default、test_transition_parameters_retained | ページ数・回転・領域・非空Trans差は本体へ。空Trans追加やOCGなしの同一PDFは一致 |
| TC-003 | FR-004 | G: test_unlayered_demo_drawing_and_links_do_not_pollute_layers、test_demo_uri_only_change_is_local、C: test_unassigned_annotation | DEMO・URI・未所属注釈は通常のレイヤーなし。変更を他OCGへ波及させない |
| TC-004 | FR-005、FR-006 | G: test_add_remove_and_duplicate_names、test_visibility_change_only_marks_affected_group、E: test_editor_usage_and_auto_state | 新規追加・削除、重複名の検証不能、関連表示状態の局所差が正しい |
| TC-005 | FR-007 | O: test_independent_objects_can_be_reordered_across_and_within_groups、test_independent_paths_inside_one_saved_interval_can_be_reordered | 矩形・矢印等の単位交換を同一/異なるOCG・レイヤーなしとの間で許容する |
| TC-006 | FR-007 | O: test_duplicate_drawing_objects_keep_multiplicity、G: test_nonoverlapping_annotation_multiset_preserves_counts、R: test_layer_annotation_order、test_cross_layer_annotation_order | 注釈の重なりの有無や配列順によらず内容一致。重複数が変われば不一致 |
| TC-007 | FR-008、FR-009 | C: test_annotation_attribute_changes、test_arrow_shape、test_annotation_add_delete、test_annotation_moved_layer、O: test_nonfont_changes_survive_object_reordering、R: test_image_bytes_change | 文字・形状・座標・サイズ・色・線幅・透明度・画像・所属・個数等の実差を検出 |
| TC-008 | FR-008、NFR-004 | O: test_inherited_state_is_bound_to_each_object、test_matrix_application_order_inside_an_object_is_preserved、test_text_order_inside_an_object_is_preserved、test_td_implicit_leading_is_not_lost_between_objects、G: test_partial_extgstate_updates_retain_prior_opacity | 継承状態・文字順・行列適用順・leading・透明度の差を順序許容で消さない |
| TC-009 | FR-008、FR-009 | O: test_form_invocations_can_move_but_form_internal_order_is_kept、C: test_appearance_changes、G: test_appearance_clipping_is_implicitly_isolated、test_default_colors_are_compared_only_when_used | Form呼出交換は許容し、内部順序・AP・クリップ・使用色空間の差は保持 |
| TC-010 | FR-010 | C: test_object_numbers_and_compression、G: test_generation_number_change、test_storage_order_and_dictionary_order、test_subset_and_reference_names_are_storage_details、O: test_save_metadata_stays_excluded_and_author_counts_stay_exact | 保存識別子・ロスレス圧縮・日時等の対象差だけなら一致 |
| TC-011 | FR-011 | G: test_font_family_changes_are_distinct_matches、test_freetext_and_appearance_font_encoding_change、test_bfrange_cmap_and_text_code_changes、O: test_order_change_with_font_change_still_reports_font_only | 安全文字復元・非フォント一致時にフォントのみ変更と差情報を出す |
| TC-012 | FR-011、NFR-004 | G: test_font_plus_nonfont_change_is_different、test_cid_text_changes_and_unknown_mappings、test_font_mapping_duplicates_fail_closed、test_word_spacing_encoding_rule_is_preserved、test_ligature_cannot_hide_character_spacing_change、test_embedded_base14_name_does_not_prove_implicit_encoding | 文字・位置等の差は不一致、不明マッピングは検証不能。字形単位やTw依存を崩さない |

### 作成者記録

| TC-ID | 要件ID | 条件・代表する既存テスト | 期待結果 |
|---|---|---|---|
| TC-013 | FR-012 | O: test_author_only_change_is_a_match_and_reference_information、test_save_metadata_stays_excluded_and_author_counts_stay_exact | /Tだけの差は一致＋構成変更。/M・/CreationDate・/NM差は内容へ含めない |
| TC-014 | FR-013 | O: test_authors_are_aggregated_per_pdf_and_group、test_author_names_are_literal_and_csv_quotes_control_characters | 全対象グループで名前別件数と未設定件数が正しく、記録名の空白・大小文字を保つ |
| TC-015 | FR-009、FR-012 | O: test_content_difference_is_not_hidden_by_authors、test_only_t_is_treated_as_author_metadata、test_annotation_count_changes_are_content_changes | 作成者が同じ/異なる場合も内容差を検出し、Contents/Subj/独自属性を残す。件数変化も反映 |
| TC-016 | FR-011、FR-014 | O: test_font_and_author_change_are_independent | フォントのみ変更と作成者構成変更の双方を同時に保持 |
| TC-017 | FR-013 | O: test_duplicate_annotation_author_swap_has_no_invented_correspondence、test_absent_layer_and_unreadable_file_are_explicit | 重複注釈に個別の変更対応を捏造しない。注釈なし・グループなし・存在不明を区別 |
| TC-018 | FR-014 | O: test_unreadable_author_does_not_taint_content_or_claim_complete_counts、test_broken_lazy_author_reference_warnings_are_metadata_only、test_partial_author_counts_keep_known_names_and_other_group_complete、test_unknown_membership_cannot_produce_complete_author_lists、test_unsupported_annotation_content_can_have_complete_author_counts | 既知の部分集計を残し不完全性・理由・nullを表示。作成者だけの失敗で内容を汚染しない |

### 操作・出力・保護

| TC-ID | 要件ID | 条件・代表する既存テスト | 期待結果 |
|---|---|---|---|
| TC-019 | FR-015、FR-023、NFR-004 | G: test_unsupported_isolated_unit_keeps_other_groups、test_unreadable_ocg_registry_is_not_an_empty_matching_registry、C: test_unaffected_pair_continues、test_unsafe_content_unknown、O: test_complex_unseparated_state_is_unknown | 局所失敗は局所化し、登録一覧・状態が不明なら範囲を広げて検証不能 |
| TC-020 | FR-016、FR-017、NFR-006 | U: test_gui_subprocess_and_details | 子プロセス結果・詳細・基準表示・並べ替えが連動し、入力変更で旧結果無効 |
| TC-021 | FR-017、FR-024 | U: test_gui_preserves_all_group_statuses_and_saved_results、test_gui_details_keep_author_changes_separate_from_content | GUIで3判定と作成者詳細を保持し、作成者差でも一致表示を維持。PDF全体と業務判定を分離 |
| TC-022 | FR-018、NFR-006 | U: test_gui_cancel、test_gui_timeout_never_success | 中止後は結果なし。待機上限を極小値に置換した試験で時間超過を成功にしない |
| TC-023 | FR-019、FR-023 | U: test_cli、test_cli_error_exit、test_offline_source_bundle | CLI JSON、--output、--checkを確認。不一致でも0、入力不足・ファイルエラーは2。--cliのTXT分岐と--output単独無効はコード照合 |
| TC-024 | FR-020、FR-024、NFR-007 | U: test_report_roundtrip_and_exports、O: test_reports_include_metadata_and_no_composition_or_identity_claim、G: test_report_separates_pair_summaries_and_roundtrips_fonts | TXT/CSV/JSONの判定・参考情報が整合。明細10列・schema 4・フォント差を保持し、合成順序を出さない |
| TC-025 | FR-021 | O: test_schema2_load_is_explicitly_incomplete_and_requires_recomparison、test_schema3_rejects_truncated_author_counts、test_schema3_rejects_unreliable_author_metadata | 旧判定を現仕様の一致にせず再比較案内。欠落・不正件数・虚偽の完全性/変更フラグを拒否 |
| TC-026 | FR-022、NFR-003、NFR-007 | U: test_source_overwrite_prohibited、test_hardlink_overwrite_prohibited、C: test_identical_and_sources_unchanged | 入力上書き拒否、別名ハードリンクも拒否、比較前後ハッシュ不変 |
| TC-027 | FR-023、NFR-004、NFR-005 | C: test_corrupt_pdf、test_unknown_catalog_structure、R: test_encryption、test_unsupported_or_malformed_ops、test_form_cycle、test_generic_resource_cycle、test_appearance_cycle | 暗号化・破損・未知・循環・数値精度等を検証不能。上限の全境界試験ではない |
| TC-028 | NFR-001、NFR-002、NFR-008 | U: test_offline_source_bundle、test_start_ignores_project_venv、test_gui_on_base_python | 通常Python・vendor・-Sで起動し、venvを使わず作成もしない。ソースだけの配布構成を確認 |
| TC-029 | NFR-002 | U: test_runtime_missing_manual_source、test_runtime_incomplete_manual_source、test_runtime_wrong_manual_source_version、test_invalid_python_override_is_reported | 未配置・コピー不足・誤版・無効Python指定を案内し、黙って別環境へ切り替えない |
| TC-030 | NFR-003 | O: test_reports_include_metadata_and_no_composition_or_identity_claim、X: test_original_hashes_unchanged、Y: test_resumed_native_case_and_outputs | 生成PDF・実出力・原本の比較前後SHA256が不変 |
| TC-031 | NFR-007 | U: test_csv_formula_escape、O: test_author_names_are_literal_and_csv_quotes_control_characters | =/+/-/@開始値をエスケープし、改行・カンマを含む記録も列を壊さない |

### 検証根拠・ソース照合

| TC-ID | 要件ID | 条件・既存テストまたは確認箇所 | 期待結果・範囲 |
|---|---|---|---|
| TC-032 | NFR-009 | X: test_native_self_comparison_all_groups_match、test_native_unchanged_save、test_native_save_as_preserves_existing_layers_and_annotation_appearances、test_derived_samples_are_checked_separately | 実出力と加工コピーを区別し、未加工保存・既存内容・作成者・原本保護を確認。必要データなしはスキップ |
| TC-033 | NFR-009 | Y: test_resumed_native_case_and_outputsの19組と5関数（下記） | 作成者・文字・図形・順序・フォント・保存の実出力差が期待判定となり、内部構造と照合できる |
| TC-034 | NFR-001、NFR-005、NFR-008 | ソース照合：[DD-01](detailed-design.md#dd-01)、[DD-03](detailed-design.md#dd-03)、[DD-10](detailed-design.md#dd-10) | 今回、依存・制限値・起動経路をコードと照合。自動テスト件数には含めない。上限直前/直後・最悪性能は未検証 |

TC-033の5関数はtest_native_overlapping_order_really_changes_without_content_change、test_native_square_author_edit_changes_only_author_and_save_date、test_native_text_author_save_also_resubsets_font_resources、test_native_font_edit_can_also_change_explicit_text_placement、test_native_normal_save_is_not_mislabeled_as_incrementalである。比較19組に対する内部構造の検査5件であり、追加比較が24組あったという意味ではない。

<a id="traceability"></a>
## 3. 要求 → 要件 → 設計 → テスト

URの定義は[要求定義書](requirements-definition.md)、FR/NFRの受入基準は[要件定義書](software-requirements.md)を参照する。以下で全24機能要件・9非機能要件を対応付ける。TC対応があることと、対象環境・全境界が検証済みであることは同義ではない。

| 要求ID | 要件ID | 基本設計 | 詳細設計 | TC-ID |
|---|---|---|---|---|
| UR-001 | FR-001 | [BD-02](basic-design.md#bd-02) | [DD-08](detailed-design.md#dd-08) | TC-001 |
| UR-001 | FR-002 | [BD-03](basic-design.md#bd-03) | [DD-08](detailed-design.md#dd-08) | TC-001 |
| UR-001 | FR-003 | [BD-03](basic-design.md#bd-03) | [DD-04](detailed-design.md#dd-04) | TC-002 |
| UR-001、UR-002 | FR-004 | [BD-03](basic-design.md#bd-03) | [DD-05](detailed-design.md#dd-05) | TC-003 |
| UR-001、UR-002 | FR-005 | [BD-03](basic-design.md#bd-03) | [DD-04](detailed-design.md#dd-04) | TC-004 |
| UR-001 | FR-006 | [BD-03](basic-design.md#bd-03) | [DD-08](detailed-design.md#dd-08) | TC-004 |
| UR-004 | FR-007 | [BD-04](basic-design.md#bd-04) | [DD-05](detailed-design.md#dd-05) | TC-005、TC-006 |
| UR-003 | FR-008 | [BD-04](basic-design.md#bd-04) | [DD-05](detailed-design.md#dd-05) | TC-007～TC-009 |
| UR-003 | FR-009 | [BD-04](basic-design.md#bd-04) | [DD-06](detailed-design.md#dd-06) | TC-007、TC-009、TC-015 |
| UR-004 | FR-010 | [BD-04](basic-design.md#bd-04) | [DD-03](detailed-design.md#dd-03) | TC-010 |
| UR-006 | FR-011 | [BD-05](basic-design.md#bd-05) | [DD-06](detailed-design.md#dd-06)、[DD-08](detailed-design.md#dd-08) | TC-011、TC-012、TC-016 |
| UR-007 | FR-012 | [BD-06](basic-design.md#bd-06) | [DD-06](detailed-design.md#dd-06) | TC-013、TC-015 |
| UR-007 | FR-013 | [BD-06](basic-design.md#bd-06) | [DD-07](detailed-design.md#dd-07) | TC-014、TC-017 |
| UR-007 | FR-014 | [BD-06](basic-design.md#bd-06) | [DD-07](detailed-design.md#dd-07) | TC-016、TC-018 |
| UR-002、UR-005 | FR-015 | [BD-08](basic-design.md#bd-08) | [DD-08](detailed-design.md#dd-08) | TC-019 |
| UR-008 | FR-016 | [BD-02](basic-design.md#bd-02) | [DD-10](detailed-design.md#dd-10) | TC-020 |
| UR-008 | FR-017 | [BD-02](basic-design.md#bd-02)、[BD-07](basic-design.md#bd-07) | [DD-09](detailed-design.md#dd-09)、[DD-10](detailed-design.md#dd-10) | TC-020、TC-021 |
| UR-008 | FR-018 | [BD-08](basic-design.md#bd-08) | [DD-10](detailed-design.md#dd-10) | TC-022 |
| UR-009 | FR-019 | [BD-07](basic-design.md#bd-07) | [DD-10](detailed-design.md#dd-10) | TC-023 |
| UR-009 | FR-020 | [BD-07](basic-design.md#bd-07) | [DD-09](detailed-design.md#dd-09) | TC-024 |
| UR-009 | FR-021 | [BD-07](basic-design.md#bd-07) | [DD-09](detailed-design.md#dd-09) | TC-025 |
| UR-010 | FR-022 | [BD-09](basic-design.md#bd-09) | [DD-09](detailed-design.md#dd-09) | TC-026 |
| UR-005 | FR-023 | [BD-08](basic-design.md#bd-08) | [DD-03](detailed-design.md#dd-03)、[DD-08](detailed-design.md#dd-08) | TC-019、TC-023、TC-027 |
| UR-009 | FR-024 | [BD-07](basic-design.md#bd-07) | [DD-02](detailed-design.md#dd-02)、[DD-09](detailed-design.md#dd-09) | TC-021、TC-024 |
| UR-011 | NFR-001 | [BD-01](basic-design.md#bd-01) | [DD-10](detailed-design.md#dd-10) | TC-028、TC-034 |
| UR-011 | NFR-002 | [BD-01](basic-design.md#bd-01) | [DD-10](detailed-design.md#dd-10) | TC-028、TC-029 |
| UR-010 | NFR-003 | [BD-09](basic-design.md#bd-09) | [DD-03](detailed-design.md#dd-03)、[DD-09](detailed-design.md#dd-09) | TC-026、TC-030 |
| UR-005 | NFR-004 | [BD-04](basic-design.md#bd-04)、[BD-05](basic-design.md#bd-05) | [DD-05](detailed-design.md#dd-05)、[DD-06](detailed-design.md#dd-06)、[DD-08](detailed-design.md#dd-08) | TC-008、TC-012、TC-019、TC-027 |
| UR-005 | NFR-005 | [BD-08](basic-design.md#bd-08) | [DD-03](detailed-design.md#dd-03) | TC-027、TC-034（境界値は部分検証） |
| UR-008 | NFR-006 | [BD-08](basic-design.md#bd-08) | [DD-10](detailed-design.md#dd-10) | TC-020、TC-022 |
| UR-010 | NFR-007 | [BD-09](basic-design.md#bd-09) | [DD-09](detailed-design.md#dd-09) | TC-024、TC-026、TC-031 |
| UR-011、UR-012 | NFR-008 | [BD-01](basic-design.md#bd-01) | [DD-01](detailed-design.md#dd-01) | TC-028、TC-034 |
| UR-012 | NFR-009 | [BD-07](basic-design.md#bd-07) | [DD-01](detailed-design.md#dd-01) | TC-032、TC-033 |

<a id="results"></a>
## 4. 検証結果と記録の根拠

### 過去の実行記録

| 段階 | 件数・結果 | 根拠・意味 |
|---|---|---|
| 内容順序・作成者分離の実装時 | 243成功、失敗0、スキップ0、65.82秒 | [開発報告](development-report.md)。生成データ等228件＋ローカル15件 |
| 変更なし別名保存の追加時 | 244成功、失敗0、スキップ0、77.54秒 | [実機検証記録](xchange-validation.md)。ローカルが16件へ増加 |
| Editor操作再開後の最終実行 | **268成功、失敗0、スキップ0、1060.90秒** | 同記録と開発報告。228件＋ローカル40件。追加24件は19比較＋内部検査5件 |

上表は以前の開発・実機検証時の記録である。文書整備のために268件すべてを今回新たに実行した結果ではない。記録の対象コードは文書整備前HEADまでの実装・テストであり、今回ソフトウェア本体を変更していない。

### 今回の文書整備での確認

pytest --collect-onlyで**268件を0.13秒で収集**した。これは実行結果ではない。私有実出力の2テストファイルを除いた228件については今回再実行した。

| 今回の実行 | 結果 | 補足 |
|---|---|---|
| 生成データ・GUI・CLI・BAT等228件 | 227成功、失敗0、スキップ1、39.61秒 | ハードリンク作成がWinError 5（アクセス拒否）のため1件スキップ |
| 上記ハードリンク保護1件の再実行 | 1成功、失敗0、スキップ0、0.13秒 | 権限制限の外で、プロジェクト内一時フォルダーだけを使用して確認 |

合算して**228件すべての成功を確認**した。初回にスキップがあった事実を「単一実行で228成功・スキップ0」と書き換えない。私有PDF40件の再実行、Editorの新規操作は今回行っていない。

文書は、要求→要件→基本設計→詳細設計→コード→テスト、GUI項目名、起動処理、相対リンク、ID・実在関数、既存文書との整合、個別事情に依存する記述の有無の順で確認する。実装・BAT・テスト・元PDFのSHA256は開始時と終了時に照合する。これらの文書検査はpytestの件数へ加算しない。

文書検査の最終結果は本書末尾に記録する。

### PDF-XChange Editor実出力の確認範囲

再開後の19組では、作成者だけの変更、作成者変更とフォント再サブセット化、文字変更、フォント変更、図形の追加/削除/移動/拡縮/線幅/色、重なる注釈の順序交換、両レイヤーの独立性、所属変更、空OCG追加/削除、標準設定の最適化保存、通常保存を確認した。各組で作成者名別件数・未設定件数をPDF直読と照合し、出力整合とSHA256不変を検査した。

フォントを変える操作でも文字配置・RichTextが変わった例は不一致で正しい。別の例では非フォント属性を維持してフォントのみ変更の一致を確認した。作成者変更だけのつもりでも埋め込みフォントが再サブセット化された例は、その実差をフォント差として保持する。DEMO・URI増加でレイヤーなしが不一致になることも正常な検出である。

順序変更は/Annotsの実配列順変更を確認したもので、ページ本文の任意命令交換をEditor実出力で確認した意味ではない。Ctrl+Sの通常保存は全体書換えで、増分保存ではなかった。最適化は標準設定・当該サンプルの1条件である。

原本保護は、既存原本・検証資料30ファイルと、新規の未加工PDF21ファイルについてハッシュを照合した記録がある。保存されたレポート57ファイルもGit管理外に保持する。ファイルごとの条件と期待値は[実機検証記録](xchange-validation.md)、追加条件の手順は[手動検証手順](xchange-manual-validation.md)を参照する。

<a id="open-items"></a>
## 5. 未検証事項・既知の制約

- Windows 10/11各版、別DPI、通常権限での導入、通信が切断された実機への新規配置の網羅検証は未完了。-S・通常Pythonでの自動試験は、それら全環境の実証を代替しない。
- 128 MiB/32 MiB/2000ページ/100,000命令、各再帰・ノード数の全境界値には専用テストがそろっていない。NFR-005はコード照合と一部の数値・循環等の試験による部分検証である。最大条件の処理時間・メモリー測定は未実施。
- GUIタイムアウトは待機値を短縮した試験であり、180秒の実時間境界を測定したものではない。GUIのボタン全組合せ、保存ダイアログ全操作、表示倍率・アクセシビリティの網羅試験はない。
- CLIの--cli TXT分岐、--output単独時の扱い、全保存エラーの終了コードには専用の網羅テストがない。現行コードの分岐を設計・マニュアルへ反映した。
- 今回の文書整備でEditorの新規操作・画面キャプチャは行っていない。前回のEditor実操作と、比較ツールGUIを自動操作するテストは別の確認である。前回も実機比較ツール画面の全行目視は未実施。
- Editorの増分保存、別最適化設定、ページ本文描画の実機順序交換は未検証。未知CMap、縦書き、関連注釈、OCMD、複雑な状態等は対応範囲外になりうる。
- 一致は構造比較の結果。レンダリング、可視性、記入内容の正しさ、全入力に共通する改変、作成者本人を証明しない。

これらは現行の検証範囲・設計制約として記録し、文書だけで対応済みにしない。現行仕様を決め直す必要がある矛盾は今回の調査で確認していない。

## 6. 再実行方法

開発用Python 3.14.8、pypdf 6.20.1、pytest 9.1.1を準備した開発環境で、リポジトリのルートから実行する。以下のvenvは**開発テスト用**であり、利用者向けの起動手順ではない。依存の固定値は[requirements-dev.txt](../requirements-dev.txt)と[requirements.txt](../requirements.txt)を参照する。

```bat
.venv\Scripts\python.exe -B -m pytest --collect-only -q
.venv\Scripts\python.exe -B -m pytest -q --basetemp=.venv/pytest-full --tb=short
```

私有データを使う2ファイルを除いた生成データ・GUI・BAT等のみの実行は次のとおり。

```bat
.venv\Scripts\python.exe -B -m pytest -q --ignore=tests/test_xchange_integration.py --ignore=tests/test_xchange_resumed.py --basetemp=.venv/pytest-formal-docs --tb=short
```

GUIには利用可能なTk画面セッションが必要で、利用できない環境ではGUI関連試験がスキップされうる。ハードリンク作成不可の環境でも該当試験はスキップとなる。成功件数だけでなく、失敗・スキップと理由を記録する。過去の実機PDFがない場合、同じ件数を得るために生成PDFへ置き換えて実機検証済みと報告しない。

## 7. 文書と実装の整合性レビュー

| 確認した差異・注意 | 文書での対応 |
|---|---|
| 検証済みPythonは3.14.8 64bitだが、起動コードは3.14系を許可しbit数を強制しない | 検証済み条件と実装の受入条件を全正式文書で区別 |
| 180秒はGUIの子プロセス待機であり、CLIの共通上限ではない | 設計・要件・操作・導入に適用範囲を明記 |
| CLI終了コードは内容の総合判定ではなく、保存例外等も一律2へ変換されない | CLI説明を現行分岐に合わせ、0=一致と解釈させない |
| JSON読み込みはライブラリ/内部通信に存在するが、保存結果を開くGUIはない | 架空の画面操作を追加せず、読込み互換性と利用者の操作を区別 |
| 展開サイズ・命令数の上限は展開/解析後の検査 | 強制メモリー上限や処理時間保証として説明しない |
| 技術調査末尾の最適化全般が未検証という表現が最新記録より古い | 標準設定1例の確認と、別設定・増分保存の未検証を区別して修正 |

以上は現行動作を正確に説明するための整理であり、実装の仕様変更は行っていない。利用者の仕様決定を要する未決事項は今回確認していない。環境別・境界値・性能等の未検証事項は第5節に残す。

今回の最終静的検査では、READMEとdocsの計14 Markdown、相対リンク188件とリンク先アンカー、UR 12件・FR 24件・NFR 9件・TC 34件の定義、全33要件の設計/テスト対応、実在テスト関数103個への参照に不備はなかった。markedのGFM解析で47表・16コードブロックを含む全文書を解析した。Mermaidの3図はソースを確認したが、今回GitHub上での図の描画確認は行っていない。git diff --checkも問題なし。

外部のPython/pypdf公式配布ページを確認し、既存技術資料のPDF仕様書URLはHTTP HEADで200を確認した。リポジトリはgit ls-remoteでmainの一致を再確認した。将来の外部URL変更まで保証するものではない。

開始時の実装・起動処理・テスト・元PDFを含む28ファイルのSHA256と終了時の値が一致した。src、main.py、start.bat、tools、testsは変更していない。既存技術資料5文書は保持し、古い記述の補正等だけを行った。PDF・私有検証出力をGitへ追加していない。


## 0.2.0の再実行手順

PDFを含む開発検証ではrequirements-dev.txtとrequirements-pdf.txtを開発用venvに導入する。

```bat
.venv\Scripts\python.exe -m pytest -q --basetemp=output/pytest-run --junitxml=output/pytest-run.xml
```

--basetempには作業用の新しいフォルダーを指定する。Windowsの制限付き実行環境でハードリンク作成が拒否された場合は該当試験がスキップされる。権限のある環境で同じ試験を別途実行し、入力の別名上書き拒否を確認する。実機PDFがない環境のスキップも実行結果に区別して記録する。

## 0.2.0の実行結果

2026-10-26、Windows・Python 3.14.8・Tk 9.0・pypdf 6.20.1、PDF出力はReportLab 4.4.9・Pillow 12.3.0・charset-normalizer 3.5.2で実行した。最終実行は380件成功、失敗0件、スキップ0件、181.84秒だった。利用可能な既存のPDF-XChange実出力の回帰試験を含むが、新たなEditor操作での実出力作成を意味しない。

GUIの中止・終了時のworker回収とafter解除を確認し、Tkインタープリターの回収を所有スレッドで行うテスト構成とした。追加レイヤーが別入力で検出され、基準PDFを解析できない場合にも、双方に存在しないと断定せず検証不能と表示する回帰試験を含む。

通常Pythonに-B -Sを付けたオフライン配布からPDF保存を確認した。リポジトリ直下のstart.bat --check、およびstart.bat --cliからcmp.txt・cmp.pdfの保存も成功した。生成レポート7ページとWord版マニュアルのレンダリング7ページを全ページ表示し、日本語・表・折り返し・改ページを確認した。全Windows版・全フォント・大量データの性能を網羅検証した結果ではない。
