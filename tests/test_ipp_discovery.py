import unittest

from printing.discovery import _decode_txt, _host_for_uri


class IppDiscoveryPolicyTests(unittest.TestCase):
    def test_dns_sd_txt_and_ipv6_uri_parts_are_normalized(self):
        self.assertEqual(
            {"rp": "ipp/print", "ty": "Printer"},
            _decode_txt({b"RP": b"ipp/print", b"ty": b"Printer"}),
        )
        self.assertEqual("[fe80::1]", _host_for_uri("fe80::1"))
        self.assertEqual("192.0.2.2", _host_for_uri("192.0.2.2"))


if __name__ == "__main__":
    unittest.main()
