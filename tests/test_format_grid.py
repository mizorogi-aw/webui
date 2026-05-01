import io
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


class ModbusReadTests(unittest.TestCase):
    class _FakeSocket:
        def __init__(self, responses: list[bytes]):
            self._responses = list(responses)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def settimeout(self, _timeout):
            return None

        def sendall(self, _data: bytes):
            return None

        def recv(self, _size: int) -> bytes:
            if not self._responses:
                return b""
            return self._responses.pop(0)

    def test_read_modbus_addr0_to_8_hex_decodes_registers(self):
        # MBAP(7): TID=1 PID=0 LEN=21 UID=1
        mbap = bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x15, 0x01])
        # PDU(20): FC=03 BC=18 + 9 registers (1..9)
        pdu = bytes([
            0x03, 0x12,
            0x00, 0x01,
            0x00, 0x02,
            0x00, 0x03,
            0x00, 0x04,
            0x00, 0x05,
            0x00, 0x06,
            0x00, 0x07,
            0x00, 0x08,
            0x00, 0x09,
        ])

        fake_socket = self._FakeSocket([mbap, pdu])
        with patch.object(main.socket, "create_connection", return_value=fake_socket):
            values = main.read_modbus_addr0_to_8_hex("192.168.100.9", 503, unit_id=1, timeout_seconds=1.0)

        self.assertEqual(
            values,
            [
                "0x0001", "0x0002", "0x0003", "0x0004", "0x0005",
                "0x0006", "0x0007", "0x0008", "0x0009",
            ],
        )

    def test_read_modbus_addr0_to_8_hex_rejects_short_mbap_length(self):
        mbap = bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x01, 0x01])

        fake_socket = self._FakeSocket([mbap])
        with patch.object(main.socket, "create_connection", return_value=fake_socket):
            with self.assertRaisesRegex(OSError, "invalid MBAP length"):
                main.read_modbus_addr0_to_8_hex("192.168.100.9", 503, unit_id=1, timeout_seconds=1.0)

    def test_read_modbus_addr0_to_8_hex_rejects_unexpected_function_code(self):
        mbap = bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x15, 0x01])
        pdu = bytes([
            0x04, 0x12,
            0x00, 0x01,
            0x00, 0x02,
            0x00, 0x03,
            0x00, 0x04,
            0x00, 0x05,
            0x00, 0x06,
            0x00, 0x07,
            0x00, 0x08,
            0x00, 0x09,
        ])

        fake_socket = self._FakeSocket([mbap, pdu])
        with patch.object(main.socket, "create_connection", return_value=fake_socket):
            with self.assertRaisesRegex(OSError, "unexpected function code"):
                main.read_modbus_addr0_to_8_hex("192.168.100.9", 503, unit_id=1, timeout_seconds=1.0)

    def test_read_modbus_addr0_to_8_hex_rejects_byte_count_mismatch(self):
        mbap = bytes([0x00, 0x01, 0x00, 0x00, 0x00, 0x15, 0x01])
        pdu = bytes([
            0x03, 0x10,
            0x00, 0x01,
            0x00, 0x02,
            0x00, 0x03,
            0x00, 0x04,
            0x00, 0x05,
            0x00, 0x06,
            0x00, 0x07,
            0x00, 0x08,
            0x00, 0x09,
        ])

        fake_socket = self._FakeSocket([mbap, pdu])
        with patch.object(main.socket, "create_connection", return_value=fake_socket):
            with self.assertRaisesRegex(OSError, "unexpected payload size"):
                main.read_modbus_addr0_to_8_hex("192.168.100.9", 503, unit_id=1, timeout_seconds=1.0)


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

    def test_trims_whitespace_in_node_class_and_datatype(self):
        csv_text = (
            "Meta1,Meta2,Meta3,Meta4,NS0\n"
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
            "Variable ,Objects/Device,ns=0;i=10002,Type/ReferenceTypes/References/HierarchicalReferences/Organizes,"
            " Sensor1 ,Type/VariableTypes/BaseVariableType/BaseDataVariableType,Mandatory,,,en:Sensor1,en:Sensor1,"
            "0,,,Type/DataTypes/BaseDataType/Number/Float ,-1,0,0.0,5,250,1,,,,1000,0,\n"
        )

        parsed = main.parse_format_csv(csv_text)
        rows = main.format_csv_to_dto(parsed)

        self.assertEqual(rows[1]["NodeClass"], "Variable")
        self.assertEqual(rows[1]["BrowseName"], "Sensor1")
        self.assertEqual(rows[1]["DataType"], "FLOAT")


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

    def test_add_object_variable_then_reload_reflects_in_format_grid(self):
        with tempfile.TemporaryDirectory() as tmp:
            fmt_file = Path(tmp) / "format.csv"
            fmt_file.write_text(SAMPLE_CSV, encoding="utf-8")
            server_bin = Path(tmp) / "ua_server_sample"
            server_bin.touch()

            rows = [
                {
                    "NodeClass": "Object", "BrowsePath": "Objects", "BrowseName": "Device",
                    "NamespaceIndex": "0", "NodeIdNumber": "10001", "DataType": "", "Access": "",
                    "Historizing": "", "EventNotifier": "1", "Param1": "",
                },
                {
                    "NodeClass": "Variable", "BrowsePath": "Objects/Device", "BrowseName": "Sensor1",
                    "NamespaceIndex": "0", "NodeIdNumber": "10002", "DataType": "DOUBLE", "Access": "1",
                    "Historizing": "1", "EventNotifier": "", "Cyclic": "1000", "Param1": "0",
                },
                {
                    "NodeClass": "Object", "BrowsePath": "Objects/Device", "BrowseName": "Unit2",
                    "NamespaceIndex": "0", "NodeIdNumber": "10010", "DataType": "", "Access": "",
                    "Historizing": "", "EventNotifier": "0", "Param1": "",
                },
                {
                    "NodeClass": "Variable", "BrowsePath": "Objects/Device/Unit2", "BrowseName": "power",
                    "NamespaceIndex": "0", "NodeIdNumber": "10011", "DataType": "FLOAT", "Access": "1",
                    "Historizing": "", "EventNotifier": "", "Cyclic": "1000", "Param1": "0",
                },
            ]

            with (
                patch.object(main, "OPCUA_FORMAT_FILE", fmt_file),
                patch.object(main, "OPCUA_SERVER_BIN", server_bin),
                patch.object(main, "ensure_opcua_mutable_paths", return_value=(True, "")),
                patch.object(main, "require_root", return_value=(True, None)),
            ):
                save_res = self.client.put(
                    "/api/opcua/format-grid",
                    json={"rows": rows, "ns_labels": ["NS0"]},
                )
                self.assertEqual(save_res.status_code, 200)

                get_res = self.client.get("/api/opcua/format-grid")
                self.assertEqual(get_res.status_code, 200)
                data = get_res.get_json()

            self.assertTrue(any(
                r.get("NodeClass") == "Variable"
                and r.get("BrowsePath") == "Objects/Device/Unit2"
                and r.get("BrowseName") == "power"
                and r.get("NodeIdNumber") == "10011"
                for r in data.get("rows", [])
            ))

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


class ModbusSettingsTests(unittest.TestCase):
    def setUp(self):
        self.client = main.app.test_client()
        with self.client.session_transaction() as sess:
            sess["authenticated"] = True

    def test_parse_modbus_settings_csv_supports_property_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            fmt_file = Path(tmp) / "format.csv"
            fmt_file.write_text(SAMPLE_CSV, encoding="utf-8")
            csv_text = (
                "modbus.server.setting1.name,SlaveA\n"
                "modbus.server.setting1.ip,192.168.0.10\n"
                "modbus.server.setting1.port,502\n"
                "modbus.server.setting1.type,holding\n"
                "modbus.server.setting1.unitid,7\n"
                "modbus.connection.value1.SlaveA,40001,ns=0;i=10002,DOUBLE\n"
            )
            with patch.object(main, "OPCUA_FORMAT_FILE", fmt_file):
                settings = main.parse_modbus_settings_csv(csv_text)

        self.assertEqual(settings["slaves"][0]["name"], "SlaveA")
        self.assertEqual(settings["slaves"][0]["ip"], "192.168.0.10")
        self.assertEqual(settings["slaves"][0]["unitId"], 7)
        self.assertEqual(settings["mappings"][0]["nodeId"], "ns=0;i=10002")
        self.assertEqual(settings["mappings"][0]["browsePath"], "Objects/Device")

    def test_parse_modbus_settings_csv_keeps_backward_compat_without_unitid(self):
        with tempfile.TemporaryDirectory() as tmp:
            fmt_file = Path(tmp) / "format.csv"
            fmt_file.write_text(SAMPLE_CSV, encoding="utf-8")
            csv_text = (
                "modbus.server.setting1.name,SlaveA\n"
                "modbus.server.setting1.ip,192.168.0.10\n"
                "modbus.server.setting1.port,502\n"
                "modbus.server.setting1.type,holding\n"
                "modbus.connection.value1.SlaveA,40001,ns=0;i=10002,DOUBLE\n"
            )
            with patch.object(main, "OPCUA_FORMAT_FILE", fmt_file):
                settings = main.parse_modbus_settings_csv(csv_text)

        self.assertEqual(settings["slaves"][0]["unitId"], 1)
        self.assertEqual(len(settings["mappings"]), 1)
        self.assertEqual(settings["mappings"][0]["address"], "40001")

    def test_get_modbus_uses_saved_draft_when_csv_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                '{\n'
                '  "upload_dir": "/tmp/uploads",\n'
                '  "custom_pages": {\n'
                '    "modbus-tcp": {\n'
                '      "slaves": [{"name": "DraftA", "ip": "10.0.0.1", "port": "502", "type": "holding", "unitId": 3}],\n'
                '      "mappings": []\n'
                '    }\n'
                '  },\n'
                '  "auth": {"enabled": true, "username": "admin", "password_hash": "x"}\n'
                '}\n',
                encoding="utf-8",
            )
            with (
                patch.object(main, "MODBUS_TCP_FILE", Path(tmp) / "modbustcp.csv"),
                patch.object(main, "get_existing_config_path", return_value=config_path),
            ):
                response = self.client.get("/api/modbus")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["source"], "draft")
        self.assertEqual(data["settings"]["slaves"][0]["name"], "DraftA")
        self.assertEqual(data["settings"]["slaves"][0]["unitId"], 3)

    def test_save_modbus_writes_csv_and_prunes_deleted_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            fmt_file = Path(tmp) / "format.csv"
            fmt_file.write_text(SAMPLE_CSV, encoding="utf-8")
            server_bin = Path(tmp) / "ua_server_sample"
            server_bin.touch()
            modbus_file = Path(tmp) / "modbustcp.csv"
            config_path = Path(tmp) / "config.json"
            config_path.write_text(
                '{"upload_dir": "/tmp/uploads", "custom_pages": {}, "auth": {"enabled": true, "username": "admin", "password_hash": "x"}}',
                encoding="utf-8",
            )
            payload = {
                "slaves": [
                    {"name": "SlaveA", "ip": "192.168.0.10", "port": "502", "type": "holding", "unitId": 9},
                ],
                "mappings": [
                    {"nodeId": "ns=0;i=10002", "browsePath": "Objects/Device", "browseName": "Sensor1", "dataType": "DOUBLE", "slaveName": "SlaveA", "address": "40001"},
                    {"nodeId": "ns=0;i=99999", "browsePath": "Objects/Device", "browseName": "Stale", "dataType": "DOUBLE", "slaveName": "SlaveA", "address": "40002"},
                ],
            }
            with (
                patch.object(main, "OPCUA_FORMAT_FILE", fmt_file),
                patch.object(main, "OPCUA_SERVER_BIN", server_bin),
                patch.object(main, "MODBUS_TCP_FILE", modbus_file),
                patch.object(main, "get_existing_config_path", return_value=config_path),
                patch.object(main, "ensure_opcua_mutable_paths", return_value=(True, "")),
                patch.object(main, "require_root", return_value=(True, None)),
                patch.object(main, "save_modbus_draft", return_value=None),
            ):
                response = self.client.put("/api/modbus", json=payload)

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(len(data["settings"]["mappings"]), 1)
            written = modbus_file.read_text(encoding="utf-8")
            self.assertIn("modbus.server.setting1.name,SlaveA", written)
            self.assertIn("modbus.server.setting1.unitid,9", written)
            self.assertIn("modbus.connection.value1.SlaveA,40001,ns=0;i=10002,DOUBLE", written)
            self.assertNotIn("99999", written)

    def test_save_format_grid_prunes_modbus_mappings_for_deleted_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            fmt_file = Path(tmp) / "format.csv"
            fmt_file.write_text(SAMPLE_CSV, encoding="utf-8")
            server_bin = Path(tmp) / "ua_server_sample"
            server_bin.touch()
            modbus_file = Path(tmp) / "modbustcp.csv"
            modbus_file.write_text(
                "modbus.server.setting1.name,SlaveA\n"
                "modbus.server.setting1.ip,192.168.0.10\n"
                "modbus.server.setting1.port,502\n"
                "modbus.server.setting1.type,holding\n"
                "modbus.server.setting1.unitid,7\n"
                "modbus.connection.value1.SlaveA,40001,ns=0;i=10002,DOUBLE\n"
                "modbus.connection.value2.SlaveA,40002,ns=0;i=99999,DOUBLE\n",
                encoding="utf-8",
            )

            # Delete action equivalent: save format-grid without the deleted Variable node (ns=0;i=10002)
            rows_after_delete = [
                {
                    "NodeClass": "Object", "BrowsePath": "Objects", "BrowseName": "Device",
                    "NamespaceIndex": "0", "NodeIdNumber": "10001", "DataType": "", "Access": "",
                    "Historizing": "", "EventNotifier": "1", "Param1": "",
                },
            ]

            with (
                patch.object(main, "OPCUA_FORMAT_FILE", fmt_file),
                patch.object(main, "OPCUA_SERVER_BIN", server_bin),
                patch.object(main, "MODBUS_TCP_FILE", modbus_file),
                patch.object(main, "ensure_opcua_mutable_paths", return_value=(True, "")),
                patch.object(main, "require_root", return_value=(True, None)),
                patch.object(main, "save_modbus_draft", return_value=None),
            ):
                response = self.client.put(
                    "/api/opcua/format-grid",
                    json={"rows": rows_after_delete, "ns_labels": ["NS0"]},
                )

            self.assertEqual(response.status_code, 200)
            data = response.get_json()
            self.assertEqual(data.get("modbus_mapping_count"), 0)
            serialized = modbus_file.read_text(encoding="utf-8")
            self.assertNotIn("ns=0;i=10002", serialized)
            self.assertNotIn("ns=0;i=99999", serialized)

            pruned = main.parse_modbus_settings_csv(serialized)
            self.assertEqual(len(pruned["mappings"]), 0)

    def test_modbus_roundtrip_keeps_mapping_unchanged_when_unitid_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            fmt_file = Path(tmp) / "format.csv"
            fmt_file.write_text(SAMPLE_CSV, encoding="utf-8")
            csv_text = (
                "modbus.server.setting1.name,SlaveA\n"
                "modbus.server.setting1.ip,192.168.0.10\n"
                "modbus.server.setting1.port,502\n"
                "modbus.server.setting1.type,holding\n"
                "modbus.server.setting1.unitid,5\n"
                "modbus.connection.value1.SlaveA,40001,ns=0;i=10002,DOUBLE\n"
            )
            with patch.object(main, "OPCUA_FORMAT_FILE", fmt_file):
                parsed1 = main.parse_modbus_settings_csv(csv_text)
                serialized = main.serialize_modbus_settings_csv(parsed1)
                parsed2 = main.parse_modbus_settings_csv(serialized)

        self.assertEqual(parsed2["slaves"][0]["unitId"], 5)
        self.assertEqual(len(parsed1["mappings"]), len(parsed2["mappings"]))
        self.assertEqual(parsed1["mappings"][0]["nodeId"], parsed2["mappings"][0]["nodeId"])
        self.assertEqual(parsed1["mappings"][0]["address"], parsed2["mappings"][0]["address"])
        self.assertEqual(parsed1["mappings"][0]["dataType"], parsed2["mappings"][0]["dataType"])

    def test_parse_modbus_settings_csv_compact_row_with_unitid(self):
        with tempfile.TemporaryDirectory() as tmp:
            fmt_file = Path(tmp) / "format.csv"
            fmt_file.write_text(SAMPLE_CSV, encoding="utf-8")
            csv_text = (
                "modbus.server.setting1.SlaveA,192.168.0.10,502,holding,11\n"
                "modbus.connection.value1.SlaveA,40001,ns=0;i=10002,DOUBLE\n"
            )
            with patch.object(main, "OPCUA_FORMAT_FILE", fmt_file):
                settings = main.parse_modbus_settings_csv(csv_text)

        self.assertEqual(settings["slaves"][0]["name"], "SlaveA")
        self.assertEqual(settings["slaves"][0]["unitId"], 11)
        self.assertEqual(settings["mappings"][0]["address"], "40001")

    def test_upload_modbus_file_saves_as_fixed_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            modbus_file = Path(tmp) / "modbustcp.csv"
            server_bin = Path(tmp) / "ua_server_sample"
            server_bin.touch()
            with (
                patch.object(main, "MODBUS_TCP_FILE", modbus_file),
                patch.object(main, "OPCUA_SERVER_BIN", server_bin),
                patch.object(main, "ensure_opcua_mutable_paths", return_value=(True, "")),
                patch.object(main, "require_root", return_value=(True, None)),
            ):
                response = self.client.post(
                    "/api/modbus/file",
                    data={"file": (io.BytesIO(b"k,v\na,b\n"), "custom-name.csv")},
                    content_type="multipart/form-data",
                )

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["filename"], "modbustcp.csv")
        self.assertTrue(modbus_file.is_file())
        self.assertEqual(modbus_file.read_text(encoding="utf-8"), "k,v\na,b\n")

    def test_download_modbus_file_returns_attachment(self):
        with tempfile.TemporaryDirectory() as tmp:
            modbus_file = Path(tmp) / "modbustcp.csv"
            modbus_file.write_text("a,b\n1,2\n", encoding="utf-8")
            server_bin = Path(tmp) / "ua_server_sample"
            server_bin.touch()
            with (
                patch.object(main, "MODBUS_TCP_FILE", modbus_file),
                patch.object(main, "OPCUA_SERVER_BIN", server_bin),
            ):
                response = self.client.get("/api/modbus/file/download")

        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers.get("Content-Disposition", ""))
        self.assertIn("modbustcp.csv", response.headers.get("Content-Disposition", ""))
        self.assertEqual(response.data, b"a,b\n1,2\n")

    def test_modbus_connection_endpoint_success(self):
        with patch.object(main, "read_modbus_addr0_to_8_hex", return_value=["0x0001", "0x0002"]):
            response = self.client.post(
                "/api/modbus/test-connection",
                json={"ip": "192.168.100.9", "port": "503", "unit_id": 1, "timeout_ms": 500},
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["ip"], "192.168.100.9")
        self.assertEqual(data["port"], 503)
        self.assertEqual(data["unit_id"], 1)
        self.assertEqual(data["hex_values"], ["0x0001", "0x0002"])

    def test_modbus_connection_endpoint_failure(self):
        with patch.object(main, "read_modbus_addr0_to_8_hex", side_effect=OSError("timed out")):
            response = self.client.post(
                "/api/modbus/test-connection",
                json={"ip": "192.168.100.9", "port": "503", "unit_id": 1, "timeout_ms": 500},
            )

        self.assertEqual(response.status_code, 502)
        data = response.get_json()
        self.assertIn("connection/read failed", data["error"])

    def test_modbus_connection_endpoint_returns_hex_values_in_addr_format(self):
        """hex_values must be "0x{XXXX}" (4 uppercase hex digits), one entry per register."""
        import re
        pattern = re.compile(r"^0x[0-9A-F]{4}$")
        fake_registers = [0x0000, 0x0001, 0x00FF, 0xABCD, 0xFFFF, 0x1234, 0x5678, 0x9ABC, 0xDEF0]
        expected = [f"0x{v:04X}" for v in fake_registers]
        with patch.object(main, "read_modbus_addr0_to_8_hex", return_value=expected):
            response = self.client.post(
                "/api/modbus/test-connection",
                json={"ip": "10.0.0.1", "port": "502", "unit_id": 5, "timeout_ms": 500},
            )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["unit_id"], 5)
        hex_values = data["hex_values"]
        self.assertEqual(len(hex_values), len(fake_registers))
        for i, value in enumerate(hex_values):
            self.assertRegex(value, pattern, msg=f"hex_values[{i}]={value!r} does not match 0x[0-9A-F]{{4}}")
        # Verify the JS formatAddrHexValues format: ADDR0=0x.... ADDR1=0x.... ...
        addr_strs = [f"ADDR{i}={v}" for i, v in enumerate(hex_values)]
        formatted = " ".join(addr_strs)
        self.assertIn("ADDR0=0x0000", formatted)
        self.assertIn("ADDR4=0xFFFF", formatted)
        self.assertIn("ADDR8=0xDEF0", formatted)


if __name__ == "__main__":
    unittest.main()
