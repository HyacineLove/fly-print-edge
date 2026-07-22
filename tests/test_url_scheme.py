import unittest

from cloud_api_client import CloudAPIClient
from config_service import ConfigService
from url_scheme import http_url_to_websocket_url, is_http_or_https_url


class UrlSchemeTests(unittest.TestCase):
    def test_is_http_or_https_url(self):
        self.assertTrue(is_http_or_https_url("http://cloud.example.com:8012"))
        self.assertTrue(is_http_or_https_url("https://print.example.com"))
        self.assertFalse(is_http_or_https_url("ftp://cloud.example.com"))
        self.assertFalse(is_http_or_https_url("https://user:pass@cloud.example.com"))
        self.assertFalse(is_http_or_https_url("not-a-url"))

    def test_http_url_to_websocket_url(self):
        self.assertEqual(
            http_url_to_websocket_url("http://cloud.example.com:8012"),
            "ws://cloud.example.com:8012",
        )
        self.assertEqual(
            http_url_to_websocket_url("https://print.example.com/"),
            "wss://print.example.com/",
        )
        with self.assertRaises(ValueError):
            http_url_to_websocket_url("ftp://cloud.example.com")


class CloudAPIClientWebsocketURLTests(unittest.TestCase):
    def test_get_websocket_url_maps_schemes(self):
        http_client = CloudAPIClient("http://cloud.example.com:8012", auth_client=object())
        http_client.node_id = "node-1"
        self.assertEqual(
            http_client.get_websocket_url(),
            "ws://cloud.example.com:8012/api/v1/edge/ws?node_id=node-1",
        )

        https_client = CloudAPIClient("https://print.example.com", auth_client=object())
        https_client.node_id = "node-2"
        self.assertEqual(
            https_client.get_websocket_url(),
            "wss://print.example.com/api/v1/edge/ws?node_id=node-2",
        )


class ConfigServiceURLValidationTests(unittest.TestCase):
    def test_accepts_https_cloud_base_url(self):
        service = ConfigService(config_repo=object())
        self.assertEqual(
            service.validate(
                {
                    "cloud": {"base_url": "https://print.example.com", "heartbeat_interval": 30},
                    "settings": {},
                    "network": {"bind_address": "127.0.0.1", "port": 7860},
                }
            ),
            [],
        )

    def test_rejects_non_http_schemes(self):
        service = ConfigService(config_repo=object())
        errors = service.validate(
            {
                "cloud": {"base_url": "ftp://print.example.com", "heartbeat_interval": 30},
                "settings": {},
                "network": {"bind_address": "127.0.0.1", "port": 7860},
            }
        )
        self.assertTrue(any("cloud.base_url" in item for item in errors))


if __name__ == "__main__":
    unittest.main()
