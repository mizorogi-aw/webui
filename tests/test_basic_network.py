import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app.main as main


def fake_run_command(command: list[str]) -> str:
    outputs = {
        ("ip", "-o", "link", "show"): "1: lo: <LOOPBACK> mtu 65536\n2: eth1: <BROADCAST> mtu 1500\n3: eth0: <BROADCAST> mtu 1500\n",
        ("ip", "-4", "route", "show", "default"): "default via 10.0.1.1 dev eth1\n",
        ("ip", "-4", "addr", "show", "dev", "eth0"): "2: eth0    inet 192.168.10.2/24 brd 192.168.10.255 scope global eth0\n",
        ("ip", "-4", "addr", "show", "dev", "eth1"): "3: eth1    inet 10.0.1.2/24 brd 10.0.1.255 scope global eth1\n",
        ("ip", "route", "show", "default", "dev", "eth0"): "",
        ("ip", "route", "show", "default", "dev", "eth1"): "default via 10.0.1.1 dev eth1\n",
    }
    return outputs.get(tuple(command), "")


class BasicNetworkTests(unittest.TestCase):
    def setUp(self):
        self.client = main.app.test_client()
        with self.client.session_transaction() as session:
            session["authenticated"] = True

    def test_write_netplan_preserves_existing_interfaces(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            netplan_path = Path(temp_dir) / "99-webui-config.yaml"
            netplan_path.write_text(
                "network:\n"
                "  version: 2\n"
                "  renderer: networkd\n"
                "  ethernets:\n"
                "    eth0:\n"
                "      dhcp4: false\n"
                "      addresses:\n"
                "        - 192.168.10.2/24\n"
                "      routes:\n"
                "        - to: default\n"
                "          via: 192.168.10.1\n"
                "      nameservers:\n"
                "        addresses: [8.8.8.8, 1.1.1.1]\n",
                encoding="utf-8",
            )

            with patch.object(main, "NETPLAN_PATH", netplan_path):
                main.write_netplan(
                    {
                        "interface": "eth1",
                        "mode": "dhcp",
                        "ipv4": "",
                        "gateway4": "",
                        "dns": "",
                    }
                )

            written = netplan_path.read_text(encoding="utf-8")
            self.assertIn("eth0:", written)
            self.assertIn("eth1:", written)
            self.assertIn("192.168.10.2/24", written)
            self.assertIn("via: 192.168.10.1", written)
            self.assertIn("dhcp4: true", written)

    def test_get_basic_returns_interface_choices_for_two_wired_nics(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            netplan_path = Path(temp_dir) / "99-webui-config.yaml"
            netplan_path.write_text(
                "network:\n"
                "  version: 2\n"
                "  renderer: networkd\n"
                "  ethernets:\n"
                "    eth0:\n"
                "      dhcp4: false\n"
                "      addresses:\n"
                "        - 192.168.10.2/24\n"
                "      routes:\n"
                "        - to: default\n"
                "          via: 192.168.10.1\n"
                "      nameservers:\n"
                "        addresses: [8.8.8.8, 1.1.1.1]\n"
                "    eth1:\n"
                "      dhcp4: true\n",
                encoding="utf-8",
            )

            with patch.object(main, "NETPLAN_PATH", netplan_path), \
                patch.object(main, "run_command", side_effect=fake_run_command), \
                patch.object(main, "read_resolv_nameservers", return_value=""):
                response = self.client.get("/api/basic?interface=eth1")

            self.assertEqual(response.status_code, 200)
            payload = response.get_json()
            self.assertEqual(payload["selected_interface"], "eth1")
            self.assertEqual(payload["network"]["interface"], "eth1")
            self.assertEqual(payload["network"]["mode"], "dhcp")
            self.assertEqual(
                payload["interfaces"],
                [
                    {"value": "eth0", "label": "Ether0 (eth0)"},
                    {"value": "eth1", "label": "Ether1 (eth1)"},
                ],
            )


if __name__ == "__main__":
    unittest.main()