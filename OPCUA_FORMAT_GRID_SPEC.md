# OPCUA Address Space Grid Specification

## Scope
This document defines the WebUI grid behavior for editing `format.csv` used by OPC UA server initialization.

---

## CSV Layout
- File: `open62541/examples/config/format.csv`
- Total columns: 27 (`0..26`)
- Row 1: Meta row (namespace labels stored from column 5)
- Row 2: Header row
- Row 3+: Node rows

### Column index map

| Index | Field |
|------:|-------|
| 0 | NodeClass |
| 1 | BrowsePath |
| 2 | NodeId (`ns=X;i=Y`) |
| 3 | ReferenceTypeId |
| 4 | BrowseName |
| 5 | TypeDefinitionId |
| 6 | HasModellingRule |
| 9 | DisplayName |
| 10 | Description |
| 11 | WriteMask |
| 12 | Object:EventNotifier |
| 14 | Variable:DataType |
| 15 | Variable:ValueRank |
| 16 | Variable:ArrayDimensionsSize |
| 17 | Variable:Value |
| 18 | Variable:accessLevel |
| 19 | Variable:minimumSamplingInterval (always `250`) |
| 20 | Variable:historizing |
| 24 | Cyclic |
| 25 | Param1 |
| 26 | Param2 (always blank) |

---

## NameSpace Definition Editor

- Location: displayed above the grid, expanded/collapsed together with the grid editor.
- Max namespace entries: **5**.
- Storage: meta row columns `4` (ns=0) through `8` (ns=4).
- Row 1 (ns=0) cannot be deleted (delete button is disabled).
- Deleting a namespace row adjusts all grid rows that referenced higher indices downward by 1.
- Deleted nodes' `NamespaceIndex` is reset to `0` (ns=0).
- Display rule: raw `ns=x` prefixes are never shown to users; labels from the meta row are used.
- Unnamed label fallback: `(unnamed N)` / `（名前なし N）` per locale.
- Insert button is absent from namespace rows (append-only via the "Add" button).

---

## Grid Layout and Interaction

### Column order in UI

| # | Column | Sticky |
|---|--------|--------|
| 1 | NodeClass | ✓ Fixed (left: 0) |
| 2 | BrowsePath | ✓ Fixed (left: 100 px) |
| 3 | BrowseName | ✓ Fixed (left: 270 px) |
| 4 | NameSpace | Scrollable |
| 5 | NodeId | Scrollable |
| 6 | DataType | Scrollable |
| 7 | Access | Scrollable |
| 8 | Hist. | Scrollable |
| 9 | Event | Scrollable |
| 10 | Event Target | Scrollable |
| 11 | Cyclic (ms) | Scrollable |
| 12 | (actions) | Scrollable |

Columns 1–3 are CSS sticky (`position: sticky`) so they remain visible during horizontal scroll.
A visual separator shadow is applied on the right edge of the BrowseName column.

### NodeClass-specific field visibility

| Field | Object | Variable |
|-------|:------:|:--------:|
| DataType | — | ✓ |
| Access | — | ✓ |
| Historizing | — | ✓ |
| Event (EventNotifier) | ✓ | — |
| Event Target (Param1) | — | ✓ |
| Cyclic | — | ✓ |

Fields that are not applicable to the current NodeClass are hidden (`visibility: hidden`) and disabled.

### NodeClass change confirmation
When the user changes NodeClass and existing values would be lost (DataType / Access / Historizing / Param1 for Variable→Object; EventNotifier for Object→Variable), a confirmation dialog is shown.

### Inline validation
- Triggered 250 ms after any grid or namespace change.
- Calls `POST /api/opcua/format-grid/validate`.
- Validation errors highlight the affected row (red background) and cell (red outline).
- A status line below the grid shows pass/fail summary.

---

## Editable Grid Columns (detail)

### NodeClass
- Allowed values: `Object`, `Variable`.

### BrowsePath
- Full path from root, e.g. `Objects/Device`.
- Must form a valid tree; every intermediate segment must be defined as an `Object` row.

### BrowseName
- Must not be empty.
- Must be unique within the same BrowsePath parent.

### NameSpace
- Dropdown populated from the NameSpace Definition Editor.
- Stored as a zero-based integer index in the CSV.

### NodeId (numeric part)
- Optional. Leave blank to auto-assign on server startup.
- Must be unique across all rows when specified.
- Serialized as `ns=X;i=Y` in the CSV.

### DataType (Variable only)
Allowed short names in UI:

| UI name | CSV path suffix |
|---------|-----------------|
| Boolean | …/Boolean |
| INT16 | …/Integer/Int16 |
| UINT16 | …/Number/UInteger/UInt16 |
| INT32 | …/Integer/Int32 |
| UINT32 | …/Number/UInteger/UInt32 |
| FLOAT | …/Number/Float |
| INT64 | …/Integer/Int64 |
| UINT64 | …/Number/UInteger/UInt64 |
| DOUBLE | …/Number/Double |
| String | …/String |

### Access (Variable only)
Mapped to `accessLevel` byte in the CSV. UI offers a fixed set of numeric options.

### Historizing (Variable only)
Checkbox. Stored as `"1"` / `""` in `Variable:historizing` (column 20).

### Event / EventNotifier (Object only)
Checkbox. Exactly one Object row must have `EventNotifier=1`.

### Event Target / Param1 (Variable only)
Checkbox. Stored as `"1"` or `"0"` in column 25.

### minimumSamplingInterval (column 19)
Always written as `"250"` (fixed). Not editable in the UI.

### Cyclic (column 24, Variable only)
- Editable numeric field.
- Minimum: `250`, Maximum: `300000`, Default: `1000`.
- Must be a positive integer within range.
- Stored in CSV column 24.
- Reset to default (`1000`) when switching from Variable to Object, then back.

---

## Event Rules
- Object event receiver:
  - `EventNotifier` must be `1` on exactly one Object row.
- Variable event target:
  - `Param1` stores `"1"` (detect) or `"0"` (no detect).
- `Param2` remains blank.

---

## UI Panel Structure (OPCUA tab)

1. OPCUA status and service controls
2. OPCUA server settings (port, user, etc.)
3. User certificate upload (`opcua-cert-form`)
4. Address Space file upload (`opcua-format-form`) — includes **"Edit Address Space"** toggle button
5. Grid editor panel (`opcua-grid-card`) — hidden by default, shown via toggle
6. Status/message area

The toggle button cycles between `"Edit Address Space"` / `"Close Editor"` labels (i18n).

---

## API Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/opcua/format-grid` | Load current format.csv as DTO rows + namespace labels |
| `PUT` | `/api/opcua/format-grid` | Save edited rows and namespace labels to format.csv |
| `POST` | `/api/opcua/format-grid/validate` | Validate rows without saving; returns error list |
| `POST` | `/api/opcua/format-grid/assign-node-ids` | Auto-assign missing NodeId numbers |

### Validate response
```json
{ "errors": [{ "row": 1, "field": "BrowsePath", "message": "…" }] }
```

---

## Buttons / i18n Keys

| Key | en | ja |
|-----|----|----|
| `opcua.grid.insert_row` | Insert | 追加 |
| `opcua.grid.delete_row` | Delete | 削除 |
| `opcua.grid.edit_open` | Edit Address Space | アドレス空間を編集 |
| `opcua.grid.edit_close` | Close Editor | 編集を閉じる |
| `opcua.grid.col.cyclic` | Cyclic (ms) | サイクル(ms) |
| `opcua.grid.hint.cyclic` | Cyclic interval in ms (Variable rows only, 250–300000) | サイクル周期ms（Variable行のみ、250〜300000） |

---

## Round-trip Requirement
When loading `format.csv` in the WebUI and saving without edits:
- Output must remain semantically identical.
- `Param1`, `Cyclic` values must be preserved.
- Namespace labels in the meta row must be preserved.
- `minimumSamplingInterval` is always overwritten to `"250"` on save.
