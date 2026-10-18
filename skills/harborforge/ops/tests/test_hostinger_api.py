import json, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import hostinger_api as ha  # noqa: E402

KEY_MATERIAL = "ssh-ed25519 AAAAC3Nz vps-ops"
ZONE = [
    {"name": "@", "type": "A", "ttl": 14400, "records": [{"content": "1.1.1.1"}]},
    {"name": "www", "type": "A", "ttl": 14400, "records": [{"content": "1.1.1.1"}]},
    {"name": "@", "type": "MX", "ttl": 14400, "records": [{"content": "mx1.example.com"}]},
    {"name": "blog", "type": "CNAME", "ttl": 14400, "records": [{"content": "x.example.com"}]},
]


class RequestTests(unittest.TestCase):
    def test_base_url_and_auth(self):
        req = ha.build_request("tok", "GET", "/api/vps/v1/virtual-machines")
        self.assertEqual(req.full_url, "https://developers.hostinger.com/api/vps/v1/virtual-machines")
        self.assertEqual(req.get_header("Authorization"), "Bearer tok")


class DnsPayloadTests(unittest.TestCase):
    def test_entries_only_for_targets(self):
        entries = ha.a_entries(["@", "www"], "9.9.9.9", 14400)
        self.assertEqual(entries, [
            {"name": "@", "type": "A", "ttl": 14400, "records": [{"content": "9.9.9.9"}]},
            {"name": "www", "type": "A", "ttl": 14400, "records": [{"content": "9.9.9.9"}]},
        ])

    def test_update_payload_overwrite_and_untouched_records(self):
        payload = ha.update_payload(["@", "www"], "9.9.9.9", 14400)
        self.assertTrue(payload["overwrite"])
        names = {(z["name"], z["type"]) for z in payload["zone"]}
        self.assertEqual(names, {("@", "A"), ("www", "A")})  # MX / CNAME never included


def make_http(responses):
    calls = []

    def _f(method, url, token, body):
        calls.append({"method": method, "url": url, "token": token, "body": body})
        if not responses:
            raise AssertionError(f"unexpected extra call: {method} {url}")
        return responses.pop(0)

    _f.calls = calls
    return _f


class EnsureKeyTests(unittest.TestCase):
    def test_existing_key_no_create(self):
        http = make_http([
            (200, {"data": [{"id": 9, "key": KEY_MATERIAL, "name": "old"}]}),   # list
            (200, {"id": 42}),                                                  # attach
        ])
        rc = ha.ensure_key("tok", KEY_MATERIAL, vm_id=123, http=http, name="vps-ops")
        self.assertEqual(rc, 0)
        methods = [c["method"] for c in http.calls]
        self.assertEqual(methods, ["GET", "POST"])
        self.assertIn("/public-keys/attach/123", http.calls[1]["url"])
        self.assertEqual(http.calls[1]["body"], {"ids": [9]})

    def test_missing_key_created_then_attached(self):
        http = make_http([
            (200, {"data": []}),                                     # list -> empty
            (200, {"id": 7, "key": KEY_MATERIAL}),                   # create
            (200, {"id": 42}),                                       # attach
        ])
        rc = ha.ensure_key("tok", KEY_MATERIAL, vm_id=123, http=http, name="vps-ops")
        self.assertEqual(rc, 0)
        methods = [c["method"] for c in http.calls]
        self.assertEqual(methods, ["GET", "POST", "POST"])
        create = http.calls[1]
        self.assertEqual(create["url"], "https://developers.hostinger.com/api/vps/v1/public-keys")
        self.assertEqual(create["body"], {"name": "vps-ops", "key": KEY_MATERIAL})
        self.assertEqual(http.calls[2]["body"], {"ids": [7]})

    def test_bare_list_response_shape(self):
        http = make_http([
            (200, [{"id": 5, "key": KEY_MATERIAL}]),                 # list without {"data": ...} wrapper
            (200, {"id": 42}),
        ])
        rc = ha.ensure_key("tok", KEY_MATERIAL, vm_id=1, http=http, name="n")
        self.assertEqual(rc, 0)
        self.assertEqual(http.calls[1]["body"], {"ids": [5]})


if __name__ == "__main__":
    unittest.main()
