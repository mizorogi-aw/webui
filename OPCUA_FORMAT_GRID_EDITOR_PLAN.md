# OPCUA Format Grid Editor — 仕様書

最終更新: 2026-04-27

OPCUAタブに `format.csv` 直接編集グリッドを実装した仕様・実装状況の記録です。

---

## 1. format.csv 列定義

全27列（0-indexed）。グリッドで編集できる列のみ UI に表示し、それ以外はサーバー側で保持・補完します。

| インデックス | CSV ヘッダ | DTO フィールド | 備考 |
|---|---|---|---|
| 0 | NodeClass | NodeClass | Object / Variable |
| 1 | BrowsePath | BrowsePath | 親ノードのフルパス |
| 2 | NodeId | NamespaceIndex / NodeIdNumber | `ns=X;i=N` を分解 |
| 4 | BrowseName | BrowseName | |
| 12 | ObjectType:EventNotifier | EventNotifier | Object 専用。0 or 1 |
| 14 | VariableType:Variable:DataType | DataType | Variable 専用。短縮名で管理 |
| 18 | Variable:accessLevel | Access | 1=Read / 2=Write / 3=Read/Write（UI表示値） |
| 19 | Variable:minimumSamplingInterval | (非編集) | サーバー側で 250 を補完 |
| 20 | Variable:historizing | Historizing | Variable 専用チェックボックス |
| 25 | Param1 | Param1 | Variable 専用チェックボックス（イベント検出フラグ）。0 or 1 |

### Access ↔ CSV 値の対応

UI のドロップダウンは 1/2/3 の3択。Historizing チェック（+4 オフセット）を加算して CSV に保存します。

| Access (UI) | Historizing | CSV accessLevel |
|---|---|---|
| 1 (Read) | OFF | 1 |
| 2 (Write) | OFF | 2 |
| 3 (Read/Write) | OFF | 3 |
| 1 (Read) | ON | 5 |
| 2 (Write) | ON | 6 |
| 3 (Read/Write) | ON | 7 |

### DataType 短縮名 ↔ CSV パス対応

| UI 表示 | CSV パス |
|---|---|
| BOOL | Type/DataTypes/BaseDataType/Boolean |
| BYTE | Type/DataTypes/BaseDataType/Number/UInteger/Byte |
| INT16 | Type/DataTypes/BaseDataType/Number/Integer/Int16 |
| INT32 | Type/DataTypes/BaseDataType/Number/Integer/Int32 |
| INT64 | Type/DataTypes/BaseDataType/Number/Integer/Int64 |
| UINT16 | Type/DataTypes/BaseDataType/Number/UInteger/UInt16 |
| UINT32 | Type/DataTypes/BaseDataType/Number/UInteger/UInt32 |
| UINT64 | Type/DataTypes/BaseDataType/Number/UInteger/UInt64 |
| FLOAT | Type/DataTypes/BaseDataType/Number/Float |
| DOUBLE | Type/DataTypes/BaseDataType/Number/Double |
| STRING | Type/DataTypes/BaseDataType/String |

---

## 2. UI グリッド列構成

| 列 | 対象 NodeClass | 入力種別 |
|---|---|---|
| NodeClass | 全行 | ドロップダウン（Object / Variable） |
| BrowsePath | 全行 | テキスト入力 |
| BrowseName | 全行 | テキスト入力 |
| NameSpace | 全行 | ドロップダウン（ns_labels から生成） |
| NodeId | 全行 | 数値入力 |
| DataType | Variable のみ | ドロップダウン（上表11種） |
| アクセス | Variable のみ | ドロップダウン（Read / Write / Read/Write） |
| 履歴（Historizing） | Variable のみ | チェックボックス |
| イベント受信（EventNotifier） | Object のみ | チェックボックス（排他：1行のみ ON 可） |
| イベント検出（Param1） | Variable のみ | チェックボックス（ON=1 / OFF=0） |
| 操作 | 全行 | 追加ボタン / 削除ボタン |

### NodeClass 切替時の動作

- Object → Variable: EventNotifier チェックをクリア
- Variable → Object: Historizing・Param1 チェックをクリア
- 適用外セルは非表示（visibility: hidden）または disabled

---

## 3. バックエンド API

| メソッド | エンドポイント | 説明 |
|---|---|---|
| GET | `/api/opcua/format-grid` | format.csv をパースして DTO リスト + ns_labels を返す |
| POST | `/api/opcua/format-grid/validate` | DTO リストを受取り、保存せずにバリデーション結果を返す |
| PUT | `/api/opcua/format-grid` | DTO リストを受取り、バリデーション後 format.csv に書き戻す |
| POST | `/api/opcua/format-grid/assign-node-ids` | NodeIdNumber が空の行に連番を採番して返す |

### PUT レスポンス

- 正常: `{"ok": true, "row_count": N}`
- バリデーションエラー: HTTP 422 + `{"error": "...", "errors": [{row, field, message}, ...]}`

---

## 4. バリデーション仕様

保存時に以下を検証し、エラーのある行・フィールドを UI で赤ハイライト表示します。

| チェック | 対象 | エラーフィールド |
|---|---|---|
| NodeClass が Object または Variable であること | 全行 | NodeClass |
| BrowseName が空でないこと | 全行 | BrowseName |
| BrowsePath + BrowseName の重複がないこと | 全行 | BrowseName |
| BrowsePath の親パスが Objects または定義済み Object のフルパスであること | 全行 | BrowsePath |
| NodeId（ns=X;i=N）の重複がないこと（空は重複チェック対象外） | 全行 | NodeIdNumber |
| EventNotifier=1 の Object が**ちょうど1行**あること | Object 行 | EventNotifier |
| Variable の Param1 が "0" / "1" / "" のいずれかであること | Variable 行 | Param1 |

---

## 5. NameSpace 定義エディタ

- グリッド上部に独立したエディタ領域を設置
- 最大5件のラベルを定義可能
- format.csv メタ行（1行目）の列4〜8 に保存
- グリッドの NameSpace ドロップダウンはこのラベル一覧から生成

---

## 6. 行挿入・行インデックス管理

### 仕様
- 「追加」ボタンで当該行の直後に Variable 行を挿入
- 「削除」ボタンで確認ダイアログ後に当該行を削除
- 挿入・削除後に `tr.dataset.rowIndex` を振り直す

### _row フィールドによる既存行参照

DTO に `_row` フィールドを含めて送信します。

- `_row` = CSV 上の元インデックス（0-based）
- 新規挿入行: `_row = -1`
- PUT 時: `_row >= 0` の場合は既存行の非編集フィールドを保持して上書き
- PUT 時: `_row = -1` の場合は新規行としてデフォルト値を補完

---

## 7. 自動リフレッシュガード

5秒ごとの自動リフレッシュで未保存の編集が上書きされることを防ぎます。

- `lastFormatGridSnapshot` に直前の保存済み状態を JSON として保持
- `hasUnsavedFormatGridChanges()` で現在グリッドと比較
- 自動リフレッシュ時に未保存変更がある場合はグリッド再描画をスキップ

---

## 8. 関連ファイル

| ファイル | 役割 |
|---|---|
| `app/main.py` | format.csv パーサ・シリアライザ・DTO変換・バリデーション・API |
| `templates/index.html` | グリッドテーブル・NameSpace定義エリアの HTML |
| `static/app.js` | グリッド描画・行操作・保存・エラーハイライト・自動リフレッシュガード |
| `static/style.css` | グリッドスタイル・行エラー（赤背景）・セルエラー（赤アウトライン）|
| `static/i18n.js` | グリッド関連文言（日英） |
| `tests/test_format_grid.py` | 29テスト（パース・DTO変換・バリデーション・API正常/異常系） |

---

## 9. 実装済み機能一覧

| 機能 | 状態 |
|---|---|
| format.csv パーサ（メタ/ヘッダ/データ分離） | ✅ 完了 |
| DTO 変換（編集列のみ） | ✅ 完了 |
| NameSpace ラベル読み書き | ✅ 完了 |
| グリッド取得 API (GET) | ✅ 完了 |
| グリッド保存 API (PUT) + バリデーション | ✅ 完了 |
| NodeId 採番 API (POST) | ✅ 完了 |
| バリデーションエラー行・セル赤ハイライト | ✅ 完了 |
| 行挿入（直後に追加）/ 行削除（確認ダイアログ） | ✅ 完了 |
| 行インデックス (_row) による既存行保持 | ✅ 完了 |
| NodeClass ドロップダウン + 切替時の動的表示変更 | ✅ 完了 |
| DataType ドロップダウン（11種） | ✅ 完了 |
| Access ドロップダウン（Read/Write/Read/Write） | ✅ 完了 |
| Historizing チェックボックス（+4 オフセット合成） | ✅ 完了 |
| EventNotifier チェックボックス（排他制御） | ✅ 完了 |
| イベント検出（Param1）チェックボックス（0/1） | ✅ 完了 |
| NameSpace 定義エディタ（最大5件） | ✅ 完了 |
| 自動リフレッシュ未保存ガード | ✅ 完了 |
| 単体テスト 29件 | ✅ 完了 |

## 10. 今後の課題（未実装）

| 機能 | 優先度 | 備考 |
|---|---|---|
| 大量行時の縦スクロール固定ヘッダ | 中 | 現状はページスクロールのみ |
| グリッド内インライン検証（保存前リアルタイム） | ✅ 完了 | `POST /api/opcua/format-grid/validate` を 250ms デバウンスで呼び出し |
| NodeClass 変更時の既存値の保持/クリア確認ダイアログ | ✅ 完了 | 値が失われる切替時のみ確認 |
