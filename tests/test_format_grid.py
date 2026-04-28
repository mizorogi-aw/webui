import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.main as main

SAMPLE_CSV = (
    "Meat1,Meta2,Meta3,Meta4,MyAddressSpace1,MyAddressSpace2\n"
    "NodeClass,BrowsePath,NodeId,ReferenceTypeId,BrowseName,TypeDefinitionId,"
    "HasModellingRule,ReferenceTypeId,ReferenceNodeId,DisplayName,Description,"
    "WriteMask,ObjectType:EventNotifier,VariableType:ObjectType:IsAbstract,"
    "VariableType:Variable:DataType,VariableType:Variable:ValueRank,"
    "VariableType:Variable:ArrayDimensionsSize,VariableType:Variable:Value,"
    "Variable:accessLevel,Variable:minimumSamplingInterval,Variable:historizing,"
    "Method:userExecutable,ReferenceType:symmetric,ReferenceType:inverseName,"
    "Cyclic,Param1,Param2\n"
    "Object,Objects,ns=0;i=10001,Type/ReferenceTypes/References/HierarchicalReferences/Organizes,"
    "Device,Type/ObjectTypes/BaseObjectType/FolderType,Mandatory,,,en:Device,en:Device,0,1,,,,,,,,,,,,,,\n"
    "Variable,Objects/Device,ns=0;i=10002,Type/ReferenceTypes/References/HierarchicalReferences/Organizes,"
    "Sensor1,Type/VariableTypes/BaseVariableType/BaseDataVariableType,Mandatory,,,en:Sensor1,en:Sensor1,"
    "0,,,Type/DataTypes/BaseDataType/Number/Double,-1,0,0.0,5,250,1,,,,120000,,\n"
)


class ParseFormatCsvTests(unittest.TestCase):
    def test_parse_returns_meta_header_data(self):
        parsed = main.parse_format_csv(SAMPLE_CSV)
        self.assertEqual(len(parsed["meta"]), 1)
        self.assertEqual(parsed["meta"][0][0], "Meat1")
        self.assertEqual(parsed["header"][0], "NodeClass")
        self.assertEqual(len(parsed["data"]), 2)
        self.assertEqual(parsed["ns_labels"], ["MyAddressSpace1", "MyAddressSpace2"])

    def test_parse_pads_short_rows(self):
        parsed = main.parse_format_csv(SAMPLE_CSV)
        for row in parsed["data"]:
            self.assertEqual(len(row), main._FC_TOTAL_COLS)

    def test_raises_on_too_few_rows(self):
        with self.assertRaises(ValueError):
            main.parse_format_csv("only,one,row\n")

    def test_roundtrip_preserves_data(self):
        parsed = main.parse_format_csv(SAMPLE_CSV)
        serialized = main.format_csv_serialize(parsed)
        parsed2 = main.parse_format_csv(serialized)
        self.assertEqual(len(parsed2["data"]), len(parsed["data"]))
        self.assertEqual(
            parsed2["data"][0][main._FC_NODE_CLASS],
            parsed["data"][0][main._FC_NODE_CLASS],
        )


class FormatCsvToDtoTests(unittest.TestCase):
    def setUp(self):
        self.parsed = main.parse_format_csv(SAMPLE_CSV)
        self.rows = main.format_csv_to_dto(self.parsed)

    def test_returns_correct_count(self):
        self.assertEqual(len(self.rows), 2)

    def test_object_row_fields(self):
        row = self.rows[0]
        self.assertEqual(row["NodeClass"], "Object")
        self.assertEqual(row["BrowsePath"], "Objects")
        self.assertEqual(row["BrowseName"], "Device")
        self.assertEqual(row["NamespaceIndex"], "0")
        self.assertEqual(row["NodeIdNumber"], "10001")

    def test_variable_row_fields(self):
        row = self.rows[1]
        self.assertEqual(row["NodeClass"], "Variable")
        self.assertEqual(row["DataType"], "DOUBLE")
        self.assertEqual(row["Access"], "1")
        self.assertEqual(row["Historizing"], "1")
        self.assertIn("Param1", row)
        self.assertEqual(row["Cyclic"], "120000")


class DtoToFormatCsvRowTests(unittest.TestCase):
    def test_updates_display_name_and_description_when_browse_name_changes(self):
        parsed = main.parse_format_csv(SAMPLE_CSV)
        existing = parsed["data"][1]
        dto = {
            "_row": 1,
            "NodeClass": "Variable",
            "BrowsePath": "Objects/Device",
            "BrowseName": "TempSensor",
            "NamespaceIndex": "0",
            "NodeIdNumber": "10002",
            "DataType": "DOUBLE",
            "Access": "1",
            "Historizing": "1",
            "EventNotifier": "",
            "Cyclic": "120000",
            "Param1": "0",
        }

        merged = main.dto_to_format_csv_row(dto, existing)

        self.assertEqual(merged[main._FC_BROWSE_NAME], "TempSensor")
        self.assertEqual(merged[main._FC_DISPLAY_NAME], "en:TempSensor")
        self.assertEqual(merged[main._FC_DESCRIPTION], "en:TempSensor")


class ValidateFormatGridTests(unittest.TestCase):
    def _make_rows(self):
        return [
            {"NodeClass": "Object", "BrowsePath": "Objects", "BrowseName": "Device",
             "NamespaceIndex": "0", "NodeIdNumber": "10001", "DataType": "", "Access": "", "Historizing": "", "EventNotifier": "1", "Cyclic": "", "Param1": ""},
            {"NodeClass": "Variable", "BrowsePath": "Objects/Device", "BrowseName": "Sensor1",
             "NamespaceIndex": "0", "NodeIdNumber": "10002", "DataType": "DOUBLE",
             "Access": "1", "Historizing": "1", "EventNotifier": "", "Cyclic": "1000", "Param1": "0"},
        ]

    def test_valid_rows_return_no_errors(self):
        rows = self._make_rows()
        errors = main.validate_format_grid(rows)
        self.assertEqual(errors, [])

    def test_variable_param1_one_is_valid(self):
        rows = self._make_rows()
        rows[1]["Param1"] = "1"
        errors = main.validate_format_grid(rows)
        self.assertEqual(errors, [])

    def test_variable_param1_invalid_value_returns_error(self):
        rows = self._make_rows()
        rows[1]["Param1"] = "EventObject/Path"
        errors = main.validate_format_grid(rows)
        self.assertTrue(any(e["field"] == "Param1" and e["row"] == 1 for e in errors))

    def test_object_param1_is_not_validated(self):
        """Object rows should not have Param1 validated."""
        rows = self._make_rows()
        rows[0]["Param1"] = "anything"
        errors = main.validate_format_grid(rows)
        # No Param1 error on Object row
        self.assertFalse(any(e["field"] == "Param1" and e["row"] == 0 for e in errors))

    def test_missing_browse_name_returns_error(self):
        rows = self._make_rows()
        rows[1]["BrowseName"] = ""
        errors = main.validate_format_grid(rows)
        self.assertTrue(any(e["field"] == "BrowseName" and e["row"] == 1 for e in errors))

    def test_invalid_node_class_returns_error(self):
        rows = self._make_rows()
        rows[0]["NodeClass"] = "Method"
        errors = main.validate_format_grid(rows)
        self.assertTrue(any(e["field"] == "NodeClass" for e in errors))

    def test_duplicate_browse_path_name_returns_error(self):
        rows = self._make_rows()
        rows[1]["BrowseName"] = "Device"  # same as row 0 under same path
        rows[1]["BrowsePath"] = "Objects"
        errors = main.validate_format_grid(rows)
        self.assertTrue(any(e["field"] == "BrowseName" for e in errors))

    def test_missing_parent_path_returns_error(self):
        rows = self._make_rows()
        rows[1]["BrowsePath"] = "Objects/NonExistent"
        errors = main.validate_format_grid(rows)
        self.assertTrue(any(e["field"] == "BrowsePath" and e["row"] == 1 for e in errors))

    def test_duplicate_node_id_returns_error(self):
        rows = self._make_rows()
        rows[1]["NodeIdNumber"] = "10001"  # same as row 0
        errors = main.validate_format_grid(rows)
        self.assertTrue(any(e["field"] == "NodeIdNumber" for e in errors))

    def test_empty_node_id_allowed(self):
        rows = self._make_rows()
        rows[0]["NodeIdNumber"] = ""
        rows[1]["NodeIdNumber"] = ""
        errors = main.validate_format_grid(rows)
        self.assertEqual(errors, [])

    def test_multiple_event_notifier_objects_returns_error(self):
        rows = self._make_rows()
        rows.insert(1, {
            "NodeClass": "Object", "BrowsePath": "Objects", "BrowseName": "Device2",
            "NamespaceIndex": "0", "NodeIdNumber": "10050", "DataType": "", "Access": "",
            "Historizing": "", "EventNotifier": "1", "Param1": ""
        })
        errors = main.validate_format_grid(rows)
        self.assertTrue(any(e["field"] == "EventNotifier" for e in errors))

    def test_tree_structure_missing_parent_returns_error(self):
        """Variable whose BrowsePath Object was never defined must fail."""
        rows = self._make_rows()
        rows.append({
            "NodeClass": "Variable", "BrowsePath": "Objects/Device/NonExistentGroup",
            "BrowseName": "Orphan", "NamespaceIndex": "0", "NodeIdNumber": "",
            "DataType": "DOUBLE", "Access": "1", "Historizing": "", "EventNotifier": "", "Param1": "0",
        })
        errors = main.validate_format_grid(rows)
        self.assertTrue(any(e["field"] == "BrowsePath" for e in errors))

    def test_no_event_notifier_returns_error(self):
        """At least one Object must have EventNotifier=1."""
        rows = self._make_rows()
        rows[0]["EventNotifier"] = "0"
        errors = main.validate_format_grid(rows)
        self.assertTrue(any(e["field"] == "EventNotifier" for e in errors))

    def test_cyclic_default_valid(self):
        rows = self._make_rows()
        errors = main.validate_format_grid(rows)
        self.assertEqual(errors, [])

    def test_cyclic_boundary_values_valid(self):
        rows = self._make_rows()
        rows[1]["Cyclic"] = "250"
        self.assertEqual(main.validate_format_grid(rows), [])
        rows[1]["Cyclic"] = "300000"
        self.assertEqual(main.validate_format_grid(rows), [])

    def test_cyclic_below_min_returns_error(self):
        rows = self._make_rows()
        rows[1]["Cyclic"] = "249"
        errors = main.validate_format_grid(rows)
        self.assertTrue(any(e["field"] == "Cyclic" and e["row"] == 1 for e in errors))

    def test_cyclic_above_max_returns_error(self):
        rows = self._make_rows()
        rows[1]["Cyclic"] = "300001"
        errors = main.validate_format_grid(rows)
        self.assertTrue(any(e["field"] == "Cyclic" and e["row"] == 1 for e in errors))

    def test_cyclic_non_integer_returns_error(self):
        rows = self._make_rows()
        rows[1]["Cyclic"] = "abc"
        errors = main.validate_format_grid(rows)
        self.assertTrue(any(e["field"] == "Cyclic" and e["row"] == 1 for e in errors))

    def test_cyclic_not_validated_for_object_rows(self):
        rows = self._make_rows()
        rows[0]["Cyclic"] = "abc"  # Object row – should not be validated
        errors = main.validate_format_grid(rows)
        self.assertFalse(any(e["field"] == "Cyclic" and e["row"] == 0 for e in errors))


class AssignNodeIdsTests(unittest.TestCase):
    def test_assigns_ids_to_empty_rows(self):
        rows = [
            {"NodeClass": "Object", "BrowsePath": "Objects", "BrowseName": "D",
               "NamespaceIndex": "0", "NodeIdNumber": "", "DataType": "", "Access": "", "Historizing": "", "EventNotifier": "1", "Param1": ""},
            {"NodeClass": "Variable", "BrowsePath": "Objects/D", "BrowseName": "V",
               "NamespaceIndex": "0", "NodeIdNumber": "", "DataType": "", "Access": "", "Historizing": "", "EventNotifier": "", "Param1": "0"},
        ]
        updated = main.assign_format_grid_node_ids(rows)
        self.assertNotEqual(updated[0]["NodeIdNumber"], "")
        self.assertNotEqual(updated[1]["NodeIdNumber"], "")
        self.assertNotEqual(updated[0]["NodeIdNumber"], updated[1]["NodeIdNumber"])

    def test_preserves_existing_ids(self):
        rows = [
            {"NodeClass": "Object", "BrowsePath": "Objects", "BrowseName": "D",
               "NamespaceIndex": "0", "NodeIdNumber": "99999", "DataType": "", "Access": "", "Historizing": "", "EventNotifier": "1", "Param1": ""},
        ]
        updated = main.assign_format_grid_node_ids(rows)
        self.assertEqual(updated[0]["NodeIdNumber"], "99999")

    def test_avoids_conflicts_with_existing(self):
        rows = [
            {"NodeClass": "Object", "BrowsePath": "Objects", "BrowseName": "A",
             "NamespaceIndex": "0", "NodeIdNumber": f"{main._FC_NODE_ID_START}", "DataType": "", "Access": "",
               "Historizing": "", "EventNotifier": "1", "Param1": ""},
            {"NodeClass": "Variable", "BrowsePath": "Objects/A", "BrowseName": "B",
               "NamespaceIndex": "0", "NodeIdNumber": "", "DataType": "", "Access": "", "Historizing": "", "EventNotifier": "", "Param1": ""},
        ]
        updated = main.assign_format_grid_node_ids(rows)
        self.assertNotEqual(updated[1]["NodeIdNumber"], f"{main._FC_NODE_ID_START}")


class FormatGridApiTests(unittest.TestCase):
    def setUp(self):
        self.client = main.app.test_client()
        with self.client.session_transaction() as sess:
            sess["authenticated"] = True

    def test_get_format_grid_not_found_when_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "format.csv"
            with (
                patch.object(main, "OPCUA_FORMAT_FILE", missing),
                patch.object(main, "OPCUA_SERVER_BIN", Path(tmp) / "ua_server_sample"),
            ):
                # Server bin does not exist → 404
                response = self.client.get("/api/opcua/format-grid")
        self.assertEqual(response.status_code, 404)

    def test_get_format_grid_returns_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            fmt_file = Path(tmp) / "format.csv"
            fmt_file.write_text(SAMPLE_CSV, encoding="utf-8")
            server_bin = Path(tmp) / "ua_server_sample"
            server_bin.touch()
            with (
                patch.object(main, "OPCUA_FORMAT_FILE", fmt_file),
                patch.object(main, "OPCUA_SERVER_BIN", server_bin),
            ):
                response = self.client.get("/api/opcua/format-grid")
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("rows", data)
        self.assertIn("ns_labels", data)
        self.assertEqual(len(data["rows"]), 2)

    def test_assign_node_ids_endpoint(self):
        rows = [
            {"NodeClass": "Object", "BrowsePath": "Objects", "BrowseName": "D",
             "NamespaceIndex": "0", "NodeIdNumber": "", "DataType": "", "Access": "", "Historizing": "", "EventNotifier": "1"},
        ]
        response = self.client.post(
            "/api/opcua/format-grid/assign-node-ids",
            json={"rows": rows},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertNotEqual(data["rows"][0]["NodeIdNumber"], "")

    def test_validate_format_grid_endpoint_returns_errors_without_saving(self):
        rows = [
            {"NodeClass": "Object", "BrowsePath": "Objects", "BrowseName": "",
             "NamespaceIndex": "0", "NodeIdNumber": "10001", "DataType": "", "Access": "",
             "Historizing": "", "EventNotifier": "1", "Param1": ""},
        ]

        response = self.client.post(
            "/api/opcua/format-grid/validate",
            json={"rows": rows, "ns_labels": []},
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertFalse(data["ok"])
        self.assertTrue(any(e["field"] == "BrowseName" for e in data["errors"]))

    def test_validate_format_grid_endpoint_rejects_invalid_payload(self):
        response = self.client.post(
            "/api/opcua/format-grid/validate",
            json={"rows": "bad"},
        )

        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data["error"], "rows must be a list")

    def test_save_format_grid_persists_namespace_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            fmt_file = Path(tmp) / "format.csv"
            fmt_file.write_text(SAMPLE_CSV, encoding="utf-8")
            server_bin = Path(tmp) / "ua_server_sample"
            server_bin.touch()
            rows = [
                {"NodeClass": "Object", "BrowsePath": "Objects", "BrowseName": "Device",
                  "NamespaceIndex": "0", "NodeIdNumber": "10001", "DataType": "", "Access": "", "Historizing": "", "EventNotifier": "1", "Param1": ""},
                {"NodeClass": "Variable", "BrowsePath": "Objects/Device", "BrowseName": "Sensor1",
                  "NamespaceIndex": "1", "NodeIdNumber": "10002", "DataType": "DOUBLE", "Access": "1", "Historizing": "1", "EventNotifier": "", "Param1": "1"},
            ]
            with (
                patch.object(main, "OPCUA_FORMAT_FILE", fmt_file),
                patch.object(main, "OPCUA_SERVER_BIN", server_bin),
                patch.object(main, "ensure_opcua_mutable_paths", return_value=(True, "")),
                patch.object(main, "require_root", return_value=(True, None)),
            ):
                response = self.client.put(
                    "/api/opcua/format-grid",
                    json={"rows": rows, "ns_labels": ["NS0", "NS1", "NS2"]},
                )
            self.assertEqual(response.status_code, 200)
            parsed = main.parse_format_csv(fmt_file.read_text(encoding="utf-8"))
            self.assertEqual(parsed["ns_labels"], ["NS0", "NS1", "NS2"])
            self.assertEqual(parsed["data"][1][main._FC_PARAM1], "1")

    def test_save_validation_error_returns_422(self):
        """Saving rows with validation errors returns HTTP 422 with error details."""
        with tempfile.TemporaryDirectory() as tmp:
            fmt_file = Path(tmp) / "format.csv"
            fmt_file.write_text(SAMPLE_CSV, encoding="utf-8")
            server_bin = Path(tmp) / "ua_server_sample"
            server_bin.touch()
            # Row with missing BrowseName should fail validation
            rows = [
                {"NodeClass": "Object", "BrowsePath": "Objects", "BrowseName": "",
                 "NamespaceIndex": "0", "NodeIdNumber": "10001", "DataType": "", "Access": "",
                 "Historizing": "", "EventNotifier": "1", "Param1": ""},
            ]
            with (
                patch.object(main, "OPCUA_FORMAT_FILE", fmt_file),
                patch.object(main, "OPCUA_SERVER_BIN", server_bin),
                patch.object(main, "ensure_opcua_mutable_paths", return_value=(True, "")),
                patch.object(main, "require_root", return_value=(True, None)),
            ):
                response = self.client.put(
                    "/api/opcua/format-grid",
                    json={"rows": rows, "ns_labels": []},
                )
            self.assertEqual(response.status_code, 422)
            data = response.get_json()
            self.assertIn("errors", data)

    def test_save_invalid_param1_returns_422(self):
        """Variable row with non-binary Param1 value returns HTTP 422."""
        with tempfile.TemporaryDirectory() as tmp:
            fmt_file = Path(tmp) / "format.csv"
            fmt_file.write_text(SAMPLE_CSV, encoding="utf-8")
            server_bin = Path(tmp) / "ua_server_sample"
            server_bin.touch()
            rows = [
                {"NodeClass": "Object", "BrowsePath": "Objects", "BrowseName": "Device",
                 "NamespaceIndex": "0", "NodeIdNumber": "10001", "DataType": "", "Access": "",
                 "Historizing": "", "EventNotifier": "1", "Param1": ""},
                {"NodeClass": "Variable", "BrowsePath": "Objects/Device", "BrowseName": "Sensor1",
                 "NamespaceIndex": "0", "NodeIdNumber": "10002", "DataType": "DOUBLE",
                 "Access": "1", "Historizing": "", "EventNotifier": "", "Param1": "EventPath/BadValue"},
            ]
            with (
                patch.object(main, "OPCUA_FORMAT_FILE", fmt_file),
                patch.object(main, "OPCUA_SERVER_BIN", server_bin),
                patch.object(main, "ensure_opcua_mutable_paths", return_value=(True, "")),
                patch.object(main, "require_root", return_value=(True, None)),
            ):
                response = self.client.put(
                    "/api/opcua/format-grid",
                    json={"rows": rows, "ns_labels": []},
                )
            self.assertEqual(response.status_code, 422)
            data = response.get_json()
            self.assertTrue(any(e["field"] == "Param1" for e in data["errors"]))


if __name__ == "__main__":
    unittest.main()
