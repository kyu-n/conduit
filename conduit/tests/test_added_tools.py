"""Unit tests for the fork-added tools: pha_file_download and
pha_task_relationships. Fully mocked; no live Phorge needed."""

import asyncio
import base64
import unittest
from unittest.mock import Mock

from fastmcp import FastMCP
from fastmcp.utilities.types import Image

from conduit.main_tools import register_tools


def _tool_fn(client, name):
    """Register tools against a mock client and return one tool's callable."""
    mcp = FastMCP("test")
    register_tools(mcp, lambda: client)
    return asyncio.run(mcp.get_tool(name)).fn


class TestPhaFileDownload(unittest.TestCase):
    def _client(self, search_data, download=None):
        client = Mock()
        client.file.search_files.return_value = {"data": search_data}
        client.file.download_file.return_value = download
        return client

    def test_image_by_id_returns_image(self):
        png_b64 = base64.b64encode(b"\x89PNG fake bytes").decode()
        client = self._client(
            [
                {
                    "phid": "PHID-FILE-1",
                    "id": 123,
                    "fields": {
                        "name": "mock.png",
                        "mimeType": "image/png",
                        "byteSize": 15,
                    },
                }
            ],
            download=png_b64,
        )
        result = _tool_fn(client, "pha_file_download")("F123")
        self.assertIsInstance(result, Image)
        client.file.search_files.assert_called_once_with(
            constraints={"ids": [123]}, limit=1
        )
        client.file.download_file.assert_called_once_with(file_phid="PHID-FILE-1")

    def test_image_by_phid(self):
        client = self._client(
            [
                {
                    "phid": "PHID-FILE-9",
                    "id": 9,
                    "fields": {
                        "name": "m.jpg",
                        "mimeType": "image/jpeg",
                        "byteSize": 8,
                    },
                }
            ],
            download=base64.b64encode(b"jpegdata").decode(),
        )
        result = _tool_fn(client, "pha_file_download")("PHID-FILE-9")
        self.assertIsInstance(result, Image)
        client.file.search_files.assert_called_once_with(
            constraints={"phids": ["PHID-FILE-9"]}, limit=1
        )

    def test_image_detected_by_extension_when_mime_absent(self):
        # Phorge's file.search omits mimeType and uses 'size', not 'byteSize'.
        png_b64 = base64.b64encode(b"\x89PNG real-ish").decode()
        client = self._client(
            [
                {
                    "phid": "PHID-FILE-5",
                    "id": 5,
                    "fields": {"name": "grafik.png", "size": 12},
                }
            ],
            download=png_b64,
        )
        result = _tool_fn(client, "pha_file_download")("F5")
        self.assertIsInstance(result, Image)
        self.assertEqual(result._format, "png")
        client.file.download_file.assert_called_once_with(file_phid="PHID-FILE-5")

    def test_non_image_extension_when_mime_absent(self):
        # A video with empty mime and a .mp4 name must not be treated as an image.
        client = self._client(
            [
                {
                    "phid": "PHID-FILE-6",
                    "id": 6,
                    "fields": {"name": "clip.mp4", "size": 5000},
                }
            ]
        )
        result = _tool_fn(client, "pha_file_download")("F6")
        self.assertIsInstance(result, dict)
        self.assertFalse(result["is_image"])
        self.assertEqual(result["file"]["byteSize"], 5000)
        client.file.download_file.assert_not_called()

    def test_non_image_returns_metadata_no_download(self):
        client = self._client(
            [
                {
                    "phid": "PHID-FILE-2",
                    "id": 2,
                    "fields": {
                        "name": "spec.pdf",
                        "mimeType": "application/pdf",
                        "byteSize": 100,
                    },
                }
            ]
        )
        result = _tool_fn(client, "pha_file_download")("F2")
        self.assertIsInstance(result, dict)
        self.assertTrue(result["success"])
        self.assertFalse(result["is_image"])
        self.assertEqual(result["file"]["mimeType"], "application/pdf")
        client.file.download_file.assert_not_called()

    def test_oversize_image_refused(self):
        client = self._client(
            [
                {
                    "phid": "PHID-FILE-3",
                    "id": 3,
                    "fields": {
                        "name": "big.png",
                        "mimeType": "image/png",
                        "byteSize": 11 * 1024 * 1024,
                    },
                }
            ]
        )
        result = _tool_fn(client, "pha_file_download")("F3")
        self.assertFalse(result["success"])
        client.file.download_file.assert_not_called()

    def test_not_found(self):
        client = self._client([])
        result = _tool_fn(client, "pha_file_download")("F404")
        self.assertFalse(result["success"])

    def test_unrecognized_ref(self):
        client = Mock()
        result = _tool_fn(client, "pha_file_download")("not-a-ref")
        self.assertFalse(result["success"])
        client.file.search_files.assert_not_called()

    def test_download_returns_empty(self):
        client = self._client(
            [
                {
                    "phid": "PHID-FILE-4",
                    "id": 4,
                    "fields": {
                        "name": "x.png",
                        "mimeType": "image/png",
                        "byteSize": 5,
                    },
                }
            ],
            download={},
        )
        result = _tool_fn(client, "pha_file_download")("F4")
        self.assertFalse(result["success"])


class TestPhaTaskRelationships(unittest.TestCase):
    def test_parents_and_subtasks_direction(self):
        client = Mock()

        def search(constraints=None, **kwargs):
            if constraints == {"parentIDs": [7229]}:
                return {
                    "data": [
                        {
                            "id": 7300,
                            "fields": {
                                "name": "Child A",
                                "status": {"value": "open"},
                            },
                        }
                    ]
                }
            if constraints == {"subtaskIDs": [7229]}:
                return {
                    "data": [
                        {
                            "id": 7000,
                            "fields": {
                                "name": "Parent",
                                "status": {"value": "resolved"},
                            },
                        }
                    ]
                }
            return {"data": []}

        client.maniphest.search_tasks.side_effect = search
        result = _tool_fn(client, "pha_task_relationships")("T7229")
        self.assertTrue(result["success"])
        self.assertEqual(result["task_id"], 7229)
        # parentIDs query yields subtasks; subtaskIDs query yields parents.
        self.assertEqual(
            result["subtasks"], [{"id": 7300, "title": "Child A", "status": "open"}]
        )
        self.assertEqual(
            result["parents"],
            [{"id": 7000, "title": "Parent", "status": "resolved"}],
        )

    def test_accepts_bare_numeric_id(self):
        client = Mock()
        client.maniphest.search_tasks.return_value = {"data": []}
        result = _tool_fn(client, "pha_task_relationships")("7229")
        self.assertTrue(result["success"])
        self.assertEqual(result["task_id"], 7229)
        self.assertEqual(result["parents"], [])
        self.assertEqual(result["subtasks"], [])

    def test_unrecognized_id(self):
        client = Mock()
        result = _tool_fn(client, "pha_task_relationships")("garbage")
        self.assertFalse(result["success"])
        client.maniphest.search_tasks.assert_not_called()


class TestPhaFileDownloadHardening(unittest.TestCase):
    def _client(self, fields, download=None):
        client = Mock()
        client.file.search_files.return_value = {
            "data": [{"phid": "PHID-FILE-X", "id": 1, "fields": fields}]
        }
        client.file.download_file.return_value = download
        return client

    def test_meta_includes_uri_and_datauri(self):
        client = self._client(
            {
                "name": "spec.pdf",
                "size": 100,
                "uri": "https://example.test/F1",
                "dataURI": "https://example.test/data/F1",
            }
        )
        result = _tool_fn(client, "pha_file_download")("F1")
        self.assertFalse(result["is_image"])
        self.assertEqual(result["file"]["uri"], "https://example.test/F1")
        self.assertEqual(result["file"]["dataURI"], "https://example.test/data/F1")

    def test_extensionless_image_is_sniffed(self):
        # No extension and no mimeType, but PNG magic bytes -> viewable Image.
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"rest").decode()
        client = self._client({"name": "mockup", "size": 12}, download=png)
        result = _tool_fn(client, "pha_file_download")("F1")
        self.assertIsInstance(result, Image)
        self.assertEqual(result._format, "png")

    def test_extensionless_nonimage_returns_meta(self):
        blob = base64.b64encode(b"not an image at all").decode()
        client = self._client(
            {"name": "datafile", "size": 19, "uri": "https://example.test/F1"},
            download=blob,
        )
        result = _tool_fn(client, "pha_file_download")("F1")
        self.assertIsInstance(result, dict)
        self.assertFalse(result["is_image"])
        self.assertEqual(result["file"]["uri"], "https://example.test/F1")

    def test_download_error_is_structured(self):
        from conduit.client import PhabricatorAPIError

        client = Mock()
        client.file.search_files.side_effect = PhabricatorAPIError("boom")
        result = _tool_fn(client, "pha_file_download")("F1")
        self.assertIsInstance(result, dict)
        self.assertFalse(result["success"])
        self.assertIn("boom", result["error"])


class TestPhaTaskGet(unittest.TestCase):
    def test_strips_t_prefix(self):
        client = Mock()
        client.maniphest.get_task.return_value = {"objectName": "T7298"}
        result = _tool_fn(client, "pha_task_get")("T7298")
        self.assertTrue(result["success"])
        client.maniphest.get_task.assert_called_once_with(7298)

    def test_accepts_bare_numeric(self):
        client = Mock()
        client.maniphest.get_task.return_value = {"objectName": "T7298"}
        result = _tool_fn(client, "pha_task_get")("7298")
        self.assertTrue(result["success"])
        client.maniphest.get_task.assert_called_once_with(7298)

    def test_rejects_phid_and_garbage(self):
        client = Mock()
        result = _tool_fn(client, "pha_task_get")("PHID-TASK-abc")
        self.assertFalse(result["success"])
        client.maniphest.get_task.assert_not_called()


class TestErrorClassification(unittest.TestCase):
    def test_classify_conduit_codes(self):
        from conduit.tools.handlers import _classify_conduit_code
        from conduit.utils import ErrorCode

        self.assertEqual(
            _classify_conduit_code("ERR-INVALID-AUTH"), ErrorCode.AUTH_ERROR
        )
        self.assertEqual(
            _classify_conduit_code("ERR_INVALID_SESSION"), ErrorCode.AUTH_ERROR
        )
        self.assertEqual(
            _classify_conduit_code("ERR-RATE-LIMITING"), ErrorCode.RATE_LIMIT_ERROR
        )
        self.assertEqual(
            _classify_conduit_code("ERR-TIMEOUT"), ErrorCode.NETWORK_ERROR
        )
        # Unrecognized conduit codes stay UNKNOWN (preserves prior behavior).
        self.assertEqual(
            _classify_conduit_code("ERR-CONDUIT-CORE"), ErrorCode.UNKNOWN_ERROR
        )
        # An already-canonical enum value still resolves.
        self.assertEqual(_classify_conduit_code("AUTH_ERROR"), ErrorCode.AUTH_ERROR)

    def test_internal_error_not_mislabeled_as_validation(self):
        from conduit.tools.handlers import handle_api_errors

        @handle_api_errors
        def boom():
            raise RuntimeError("kaboom")

        result = boom()
        self.assertFalse(result["success"])
        self.assertNotIn("Parameter validation failed", result["error"])
        self.assertIn("kaboom", result["error"])


class TestBaseHttpErrorCodes(unittest.TestCase):
    """base.py classifies httpx failures with a Conduit-style error_code."""

    def _client(self):
        from conduit.client.file import FileClient

        return FileClient(api_url="http://example.test/api/", api_token="t")

    def test_timeout_sets_err_timeout(self):
        import httpx
        from conduit.client import PhabricatorAPIError

        c = self._client()
        c.client = Mock()
        c.client.post.side_effect = httpx.TimeoutException("slow")
        with self.assertRaises(PhabricatorAPIError) as ctx:
            c._make_request("file.search", {})
        self.assertEqual(ctx.exception.error_code, "ERR-TIMEOUT")

    def test_429_sets_rate_limiting(self):
        import httpx
        from conduit.client import PhabricatorAPIError

        c = self._client()
        resp = httpx.Response(
            429, request=httpx.Request("POST", "http://example.test/api/file.search")
        )
        c.client = Mock()
        c.client.post.return_value = resp
        with self.assertRaises(PhabricatorAPIError) as ctx:
            c._make_request("file.search", {})
        self.assertEqual(ctx.exception.error_code, "ERR-RATE-LIMITING")


if __name__ == "__main__":
    unittest.main()
