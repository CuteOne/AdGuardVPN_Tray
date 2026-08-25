import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

from adguardvpn_tray.models.types import ConnectionState
from adguardvpn_tray.parsers.config_parser import parse_config_show, unwrap_default
from adguardvpn_tray.parsers.license_parser import parse_license
from adguardvpn_tray.parsers.locations_parser import parse_locations
from adguardvpn_tray.parsers.status_parser import parse_status

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


class StatusParserTests(unittest.TestCase):
    def test_disconnected(self):
        status = parse_status(read_fixture("status_disconnected.txt"), exit_code=0)
        self.assertEqual(status.state, ConnectionState.DISCONNECTED)

    def test_connected(self):
        status = parse_status(read_fixture("status_connected.txt"), exit_code=0)
        self.assertEqual(status.state, ConnectionState.CONNECTED)
        self.assertEqual(status.location, "ATLANTA")
        self.assertEqual(status.mode, "TUN")
        self.assertEqual(status.interface, "tun0")

    def test_active_but_unavailable_exit_code_10(self):
        status = parse_status("VPN active, but status unavailable", exit_code=10)
        self.assertEqual(status.state, ConnectionState.CONNECTED)

    def test_garbage_is_error(self):
        status = parse_status("some unexpected output", exit_code=1)
        self.assertEqual(status.state, ConnectionState.ERROR)


class LocationsParserTests(unittest.TestCase):
    def test_parses_real_output(self):
        locations = parse_locations(read_fixture("list_locations.txt"))
        self.assertGreater(len(locations), 10)
        first = locations[0]
        self.assertEqual(first.iso, "US")
        self.assertEqual(first.country, "United States")
        self.assertEqual(first.city, "Atlanta")
        self.assertEqual(first.ping_ms, 12)

    def test_skips_header(self):
        locations = parse_locations(read_fixture("list_locations.txt"))
        self.assertTrue(all(loc.iso != "ISO" for loc in locations))

    def test_sorted_by_ping_ascending_in_source(self):
        locations = parse_locations(read_fixture("list_locations.txt"))
        pings = [loc.ping_ms for loc in locations]
        self.assertEqual(pings, sorted(pings))


class LicenseParserTests(unittest.TestCase):
    def test_logged_in(self):
        info = parse_license(read_fixture("license_logged_in.txt"))
        self.assertTrue(info.logged_in)
        self.assertEqual(info.email, "user@example.com")
        self.assertEqual(info.tier, "PREMIUM")
        self.assertEqual(info.renewal_date, "2027-12-29")

    def test_not_logged_in(self):
        info = parse_license("You are not logged in")
        self.assertFalse(info.logged_in)


class ConfigParserTests(unittest.TestCase):
    def test_parses_known_keys(self):
        config = parse_config_show(read_fixture("config_show.txt"))
        self.assertEqual(config.values["Mode"], "tun")
        self.assertEqual(config.values["Change system DNS"], "on")
        self.assertEqual(config.values["Protocol"], "Default (auto)")

    def test_unwrap_default(self):
        self.assertEqual(unwrap_default("Default (auto)"), "auto")
        self.assertEqual(unwrap_default("Default (provided by AdGuard VPN)"), "")
        self.assertEqual(unwrap_default("on"), "on")


if __name__ == "__main__":
    unittest.main()
