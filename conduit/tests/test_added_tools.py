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
        self.assertIs(result.is_error, True)
        self.assertFalse(result.structured_content["success"])
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
        self.assertIs(result.is_error, True)
        self.assertFalse(result.structured_content["success"])
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
        self.assertIs(result.is_error, True)
        self.assertFalse(result.structured_content["success"])
        self.assertNotIn("Parameter validation failed", result.structured_content["error"])
        self.assertIn("kaboom", result.structured_content["error"])


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


class TestHandleApiErrorsLogging(unittest.TestCase):
    def test_generic_exception_logs_warning_and_returns_failure(self):
        from conduit.tools.handlers import handle_api_errors

        @handle_api_errors
        def boom():
            raise RuntimeError("boom")

        with self.assertLogs("conduit", level="WARNING") as cm:
            result = boom()

        self.assertIs(result.is_error, True)
        self.assertFalse(result.structured_content["success"])
        self.assertIn("boom", result.structured_content["error"])
        self.assertTrue(
            any("boom" in msg for msg in cm.output),
            f"Expected 'boom' in log output, got: {cm.output}",
        )


class TestToolAnnotations(unittest.TestCase):
    """Every @mcp.tool() must carry readOnlyHint; mutators also set destructiveHint."""

    def _get_tool(self, name):
        mcp = FastMCP("test")
        register_tools(mcp, lambda: Mock())
        return asyncio.run(mcp.get_tool(name))

    def test_read_tool_has_readonly_true(self):
        tool = self._get_tool("pha_task_get")
        self.assertIsNotNone(tool.annotations)
        self.assertIs(tool.annotations.readOnlyHint, True)

    def test_mutate_update_has_readonly_false_destructive_true(self):
        tool = self._get_tool("pha_task_update")
        self.assertIsNotNone(tool.annotations)
        self.assertIs(tool.annotations.readOnlyHint, False)
        self.assertIs(tool.annotations.destructiveHint, True)

    def test_mutate_create_has_readonly_false_destructive_false(self):
        tool = self._get_tool("pha_task_create")
        self.assertIsNotNone(tool.annotations)
        self.assertIs(tool.annotations.readOnlyHint, False)
        self.assertIs(tool.annotations.destructiveHint, False)

    def test_all_tools_have_annotations(self):
        mcp = FastMCP("test")
        register_tools(mcp, lambda: Mock())
        tools = asyncio.run(mcp.list_tools())
        for tool in tools:
            self.assertIsNotNone(
                tool.annotations, f"Tool {tool.name} has no annotations"
            )


class TestTextPayloadCapping(unittest.TestCase):
    """Content tools cap responses at 50000 chars and report truncation."""

    BIG = "x" * 60000

    def test_repository_file_content_caps_large_content(self):
        client = Mock()
        client.diffusion.file_content_query.return_value = {"filePHID": "PHID-FILE-1"}
        # Return a base64-encoded big string so the decode path yields BIG.
        import base64
        client.file.download_file.return_value = base64.b64encode(self.BIG.encode()).decode()
        result = _tool_fn(client, "pha_repository_file_content")("REPO", "path/to/file.py")
        self.assertTrue(result["success"])
        self.assertLessEqual(len(result["file_content"]), 50000)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["original_length"], len(self.BIG))

    def test_repository_file_content_not_truncated_when_short(self):
        client = Mock()
        client.diffusion.file_content_query.return_value = {"filePHID": "PHID-FILE-2"}
        import base64
        short = "hello world"
        client.file.download_file.return_value = base64.b64encode(short.encode()).decode()
        result = _tool_fn(client, "pha_repository_file_content")("REPO", "small.py")
        self.assertTrue(result["success"])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["original_length"], len(short))
        self.assertEqual(result["file_content"], short)

    def test_diff_get_content_caps_large_diff(self):
        client = Mock()
        client.differential.search_diffs.return_value = {
            "data": [{"id": 42, "phid": "PHID-DIFF-abc"}]
        }
        client.differential.get_raw_diff.return_value = self.BIG
        result = _tool_fn(client, "pha_diff_get_content")("PHID-DIFF-abc")
        self.assertTrue(result["success"])
        self.assertLessEqual(len(result["diff_content"]), 50000)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["original_length"], len(self.BIG))

    def test_diff_get_content_not_truncated_when_short(self):
        client = Mock()
        client.differential.search_diffs.return_value = {
            "data": [{"id": 7, "phid": "PHID-DIFF-xyz"}]
        }
        short_diff = "--- a\n+++ b\n@@ -1 +1 @@\n+line\n"
        client.differential.get_raw_diff.return_value = short_diff
        result = _tool_fn(client, "pha_diff_get_content")("PHID-DIFF-xyz")
        self.assertTrue(result["success"])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["diff_content"], short_diff)

    def test_diff_get_commit_message_caps_large_message(self):
        client = Mock()
        client.differential.get_commit_message.return_value = self.BIG
        result = _tool_fn(client, "pha_diff_get_commit_message")("D123")
        self.assertTrue(result["success"])
        self.assertLessEqual(len(result["commit_message"]), 50000)
        self.assertTrue(result["truncated"])
        self.assertEqual(result["original_length"], len(self.BIG))

    def test_diff_get_commit_message_not_truncated_when_short(self):
        client = Mock()
        short_msg = "feat: add widget\n\nFixes T999."
        client.differential.get_commit_message.return_value = short_msg
        result = _tool_fn(client, "pha_diff_get_commit_message")("D7")
        self.assertTrue(result["success"])
        self.assertFalse(result["truncated"])
        self.assertEqual(result["commit_message"], short_msg)
        self.assertEqual(result["original_length"], len(short_msg))


class TestPhaTaskSearchAdvancedPagination(unittest.TestCase):
    """next_cursor is surfaced at the top level from the cursor.after field."""

    def _fn(self, client):
        return _tool_fn(client, "pha_task_search_advanced")

    def test_next_cursor_present_when_cursor_after_set(self):
        client = Mock()
        client.maniphest.search_tasks.return_value = {
            "data": [{"id": 1}, {"id": 2}],
            "cursor": {"after": "PAGE2", "before": None, "limit": 5},
        }
        result = self._fn(client)(limit=5)
        self.assertTrue(result["success"])
        self.assertEqual(result["next_cursor"], "PAGE2")

    def test_next_cursor_none_when_no_more_pages(self):
        client = Mock()
        client.maniphest.search_tasks.return_value = {
            "data": [{"id": 3}],
            "cursor": {"after": None, "before": None, "limit": 5},
        }
        result = self._fn(client)(limit=5)
        self.assertIsNone(result["next_cursor"])

    def test_after_forwarded_to_client(self):
        client = Mock()
        client.maniphest.search_tasks.return_value = {
            "data": [],
            "cursor": {"after": None, "before": None, "limit": 5},
        }
        self._fn(client)(after="PAGE2", limit=5)
        _call = client.maniphest.search_tasks.call_args
        self.assertEqual(_call.kwargs.get("after"), "PAGE2")


class TestPhaUserSearchPagination(unittest.TestCase):
    """next_cursor is surfaced at the top level from the cursor.after field."""

    def _fn(self, client):
        return _tool_fn(client, "pha_user_search")

    def test_next_cursor_present_when_cursor_after_set(self):
        client = Mock()
        client.user.search.return_value = {
            "data": [{"id": 10}, {"id": 11}],
            "cursor": {"after": "USERPAGE2", "before": None, "limit": 5},
        }
        result = self._fn(client)(limit=5)
        self.assertTrue(result["success"])
        self.assertEqual(result["next_cursor"], "USERPAGE2")

    def test_next_cursor_none_when_no_more_pages(self):
        client = Mock()
        client.user.search.return_value = {
            "data": [{"id": 12}],
            "cursor": {"after": None, "before": None, "limit": 5},
        }
        result = self._fn(client)(limit=5)
        self.assertIsNone(result["next_cursor"])

    def test_after_forwarded_to_client(self):
        client = Mock()
        client.user.search.return_value = {
            "data": [],
            "cursor": {"after": None, "before": None, "limit": 5},
        }
        self._fn(client)(after="USERPAGE2", limit=5)
        _call = client.user.search.call_args
        self.assertEqual(_call.kwargs.get("after"), "USERPAGE2")


class TestHandleApiErrorsToolResult(unittest.TestCase):
    """handle_api_errors wraps all failure paths as ToolResult(is_error=True)."""

    def _decorator(self):
        from conduit.tools.handlers import handle_api_errors
        from fastmcp.tools.base import ToolResult
        return handle_api_errors, ToolResult

    def test_raised_exception_produces_tool_result(self):
        handle_api_errors, ToolResult = self._decorator()

        @handle_api_errors
        def boom():
            raise RuntimeError("boom")

        result = boom()
        self.assertIsInstance(result, ToolResult)
        self.assertIs(result.is_error, True)
        self.assertFalse(result.structured_content["success"])
        self.assertIn("boom", result.structured_content["error"])

    def test_returned_failure_dict_produces_tool_result(self):
        handle_api_errors, ToolResult = self._decorator()

        @handle_api_errors
        def nope():
            return {"success": False, "error": "nope"}

        result = nope()
        self.assertIsInstance(result, ToolResult)
        self.assertIs(result.is_error, True)
        self.assertFalse(result.structured_content["success"])
        self.assertIn("nope", result.structured_content["error"])


class TestPhaTaskGetPersonalIncludeDescription(unittest.TestCase):
    """include_description strips fields.description when False."""

    def _make_result(self, desc="some description"):
        return {
            "data": [
                {"id": 1, "fields": {"name": "Task A", "description": {"raw": desc}}},
                {"id": 2, "fields": {"name": "Task B", "description": {"raw": desc}}},
            ],
            "cursor": {"after": None},
        }

    def _client(self, result):
        client = Mock()
        client.maniphest.search_assigned_tasks.return_value = result
        client.maniphest.search_authored_tasks.return_value = result
        return client

    def test_assigned_description_stripped_when_false(self):
        client = self._client(self._make_result())
        fn = _tool_fn(client, "pha_task_get_personal")
        result = fn(task_type="assigned", include_description=False)
        self.assertTrue(result["success"])
        for task in result["assigned_tasks"]["data"]:
            self.assertNotIn("description", task["fields"])

    def test_assigned_description_kept_when_true(self):
        client = self._client(self._make_result())
        fn = _tool_fn(client, "pha_task_get_personal")
        result = fn(task_type="assigned", include_description=True)
        self.assertTrue(result["success"])
        for task in result["assigned_tasks"]["data"]:
            self.assertIn("description", task["fields"])

    def test_authored_description_stripped_when_false(self):
        client = self._client(self._make_result())
        fn = _tool_fn(client, "pha_task_get_personal")
        result = fn(task_type="authored", include_description=False)
        self.assertTrue(result["success"])
        for task in result["authored_tasks"]["data"]:
            self.assertNotIn("description", task["fields"])

    def test_authored_description_kept_when_true(self):
        client = self._client(self._make_result())
        fn = _tool_fn(client, "pha_task_get_personal")
        result = fn(task_type="authored", include_description=True)
        self.assertTrue(result["success"])
        for task in result["authored_tasks"]["data"]:
            self.assertIn("description", task["fields"])


class TestPhaWorkboardSearchTasksByColumnIncludeDescription(unittest.TestCase):
    """include_description strips fields.description when False."""

    def _make_result(self, desc="workboard desc"):
        return {
            "data": [
                {"id": 10, "fields": {"name": "Col Task A", "description": {"raw": desc}}},
            ],
            "cursor": {"after": None},
        }

    def _client(self, result):
        client = Mock()
        client.maniphest.search_tasks.return_value = result
        return client

    def test_description_stripped_when_false(self):
        client = self._client(self._make_result())
        fn = _tool_fn(client, "pha_workboard_search_tasks_by_column")
        result = fn(column_phid="PHID-PCOL-abc", include_description=False)
        self.assertTrue(result["success"])
        for task in result["tasks"]["data"]:
            self.assertNotIn("description", task["fields"])

    def test_description_kept_when_true(self):
        client = self._client(self._make_result())
        fn = _tool_fn(client, "pha_workboard_search_tasks_by_column")
        result = fn(column_phid="PHID-PCOL-abc", include_description=True)
        self.assertTrue(result["success"])
        for task in result["tasks"]["data"]:
            self.assertIn("description", task["fields"])


class TestPhaTaskGetTransactionsHasMore(unittest.TestCase):
    """has_more reflects whether cursor.after is set on transactions."""

    def _client_with_cursor(self, after_value):
        client = Mock()
        client.maniphest.search_tasks.return_value = {
            "data": [{"phid": "PHID-TASK-1"}],
        }
        client.maniphest.search_task_transactions.return_value = {
            "data": [{"id": 1}],
            "cursor": {"after": after_value},
        }
        return client

    def test_has_more_true_when_cursor_after_set(self):
        client = self._client_with_cursor("PAGE2")
        fn = _tool_fn(client, "pha_task_get_transactions")
        result = fn(task_id="PHID-TASK-1")
        self.assertTrue(result["success"])
        self.assertIn("has_more", result)
        self.assertTrue(result["has_more"])

    def test_has_more_false_when_cursor_after_none(self):
        client = self._client_with_cursor(None)
        fn = _tool_fn(client, "pha_task_get_transactions")
        result = fn(task_id="PHID-TASK-1")
        self.assertTrue(result["success"])
        self.assertIn("has_more", result)
        self.assertFalse(result["has_more"])

    def test_has_more_false_when_no_cursor_key(self):
        client = Mock()
        client.maniphest.search_task_transactions.return_value = {"data": [{"id": 1}]}
        fn = _tool_fn(client, "pha_task_get_transactions")
        result = fn(task_id="PHID-TASK-1")
        self.assertIn("has_more", result)
        self.assertFalse(result["has_more"])


class TestPhaTaskRelationshipsHasMore(unittest.TestCase):
    """has_more is True if either subtasks or parents search was truncated."""

    def _search_side_effect(self, subtask_cursor=None, parent_cursor=None):
        def search(constraints=None, **kwargs):
            if constraints and "parentIDs" in constraints:
                return {"data": [], "cursor": {"after": subtask_cursor}}
            if constraints and "subtaskIDs" in constraints:
                return {"data": [], "cursor": {"after": parent_cursor}}
            return {"data": []}
        return search

    def test_has_more_false_when_no_truncation(self):
        client = Mock()
        client.maniphest.search_tasks.side_effect = self._search_side_effect(
            subtask_cursor=None, parent_cursor=None
        )
        result = _tool_fn(client, "pha_task_relationships")("T100")
        self.assertTrue(result["success"])
        self.assertIn("has_more", result)
        self.assertFalse(result["has_more"])

    def test_has_more_true_when_subtasks_truncated(self):
        client = Mock()
        client.maniphest.search_tasks.side_effect = self._search_side_effect(
            subtask_cursor="SPAGE2", parent_cursor=None
        )
        result = _tool_fn(client, "pha_task_relationships")("T100")
        self.assertTrue(result["success"])
        self.assertTrue(result["has_more"])

    def test_has_more_true_when_parents_truncated(self):
        client = Mock()
        client.maniphest.search_tasks.side_effect = self._search_side_effect(
            subtask_cursor=None, parent_cursor="PPAGE2"
        )
        result = _tool_fn(client, "pha_task_relationships")("T100")
        self.assertTrue(result["success"])
        self.assertTrue(result["has_more"])

    def test_has_more_true_when_both_truncated(self):
        client = Mock()
        client.maniphest.search_tasks.side_effect = self._search_side_effect(
            subtask_cursor="S2", parent_cursor="P2"
        )
        result = _tool_fn(client, "pha_task_relationships")("T100")
        self.assertTrue(result["success"])
        self.assertTrue(result["has_more"])

    def test_has_more_false_when_no_cursor_key(self):
        client = Mock()
        client.maniphest.search_tasks.return_value = {"data": []}
        result = _tool_fn(client, "pha_task_relationships")("T100")
        self.assertIn("has_more", result)
        self.assertFalse(result["has_more"])


class TestPhaTaskRelationshipsOutputSchema(unittest.TestCase):
    def _mcp(self):
        client = Mock()
        client.maniphest.search_tasks.return_value = {"data": []}
        mcp = FastMCP("schema-test")
        register_tools(mcp, lambda: client)
        return mcp

    def test_output_schema_is_set(self):
        tool = asyncio.run(self._mcp().get_tool("pha_task_relationships"))
        self.assertIsInstance(tool.output_schema, dict)

    def test_output_schema_has_parents_and_subtasks(self):
        tool = asyncio.run(self._mcp().get_tool("pha_task_relationships"))
        props = tool.output_schema.get("properties", {})
        self.assertIn("parents", props)
        self.assertIn("subtasks", props)

    def test_output_schema_is_permissive(self):
        tool = asyncio.run(self._mcp().get_tool("pha_task_relationships"))
        self.assertTrue(tool.output_schema.get("additionalProperties", False))


class TestLiteralEnumTools(unittest.TestCase):
    """pha_diff_add_comment and pha_repository_create register with Literal params."""

    def test_diff_add_comment_registers_and_accepts_valid_action(self):
        client = Mock()
        client.differential.edit_revision.return_value = {"success": True}
        fn = _tool_fn(client, "pha_diff_add_comment")
        result = fn(revision_id="D123", comment="LGTM", action="accept")
        self.assertTrue(result["success"])

    def test_repository_create_registers_and_accepts_valid_vcs_type(self):
        client = Mock()
        client.diffusion.create_repository.return_value = {"id": 1}
        fn = _tool_fn(client, "pha_repository_create")
        result = fn(name="my-repo", vcs_type="git")
        self.assertTrue(result["success"])


class TestPaginateSearchHelper(unittest.TestCase):
    """Unit tests for the _paginate_search module-level helper."""

    def _make_do(self, pages):
        """Return a _do callable that yields each page dict in turn."""
        idx = [0]

        def _do(after_cur):
            result = pages[idx[0]]
            idx[0] += 1
            return result

        return _do

    def test_fetch_all_accumulates_three_pages(self):
        from conduit.main_tools import _paginate_search

        pages = [
            {"data": [1, 2], "cursor": {"after": "p2"}},
            {"data": [3, 4], "cursor": {"after": "p3"}},
            {"data": [5], "cursor": {"after": None}},
        ]
        data, meta = _paginate_search(
            self._make_do(pages), limit=100, after=None, fetch_all=True
        )
        self.assertEqual(data, [1, 2, 3, 4, 5])
        self.assertFalse(meta["hit_cap"])
        self.assertEqual(meta["total"], 5)
        self.assertFalse(meta["has_more"])
        self.assertIsNone(meta["next_cursor"])

    def test_fetch_all_false_returns_page_one_with_note(self):
        from conduit.main_tools import _paginate_search

        pages = [{"data": [1, 2], "cursor": {"after": "p2"}}]
        data, meta = _paginate_search(
            self._make_do(pages), limit=100, after=None, fetch_all=False
        )
        self.assertEqual(data, [1, 2])
        self.assertTrue(meta["has_more"])
        self.assertEqual(meta["next_cursor"], "p2")
        self.assertIn("note", meta)

    def test_fetch_all_false_no_more_no_note(self):
        from conduit.main_tools import _paginate_search

        pages = [{"data": [1, 2], "cursor": {"after": None}}]
        data, meta = _paginate_search(
            self._make_do(pages), limit=100, after=None, fetch_all=False
        )
        self.assertEqual(data, [1, 2])
        self.assertFalse(meta["has_more"])
        self.assertIsNone(meta["next_cursor"])
        self.assertNotIn("note", meta)

    def test_page_cap_stops_loop_with_hit_cap_and_note(self):
        from conduit.main_tools import _paginate_search

        n = [0]

        def _do(after_cur):
            n[0] += 1
            return {"data": [n[0]], "cursor": {"after": f"p{n[0]}"}}

        data, meta = _paginate_search(_do, limit=100, after=None, fetch_all=True, page_cap=25)
        self.assertEqual(len(data), 25)
        self.assertTrue(meta["hit_cap"])
        self.assertTrue(meta["has_more"])
        self.assertIsNotNone(meta["next_cursor"])
        self.assertIn("note", meta)

    def test_mid_loop_error_returns_partial_with_note_not_raised(self):
        from conduit.main_tools import _paginate_search

        n = [0]

        def _do(after_cur):
            n[0] += 1
            if n[0] == 1:
                return {"data": [100], "cursor": {"after": "p2"}}
            raise RuntimeError("mid-loop failure")

        data, meta = _paginate_search(_do, limit=100, after=None, fetch_all=True)
        self.assertEqual(data, [100])
        self.assertTrue(meta["has_more"])
        self.assertIn("note", meta)

    def test_first_page_error_propagates(self):
        from conduit.main_tools import _paginate_search

        def _do(after_cur):
            raise RuntimeError("first page error")

        with self.assertRaises(RuntimeError):
            _paginate_search(_do, limit=100, after=None, fetch_all=True)


class TestPhaTaskSearchAdvancedFetchAll(unittest.TestCase):
    """pha_task_search_advanced: fetch_all accumulates pages and forces description off."""

    def _fn(self, client):
        return _tool_fn(client, "pha_task_search_advanced")

    def _multi_page_client(self):
        client = Mock()
        pages = [
            {
                "data": [
                    {"id": i, "fields": {"description": {"raw": "d"}}}
                    for i in range(1, 4)
                ],
                "cursor": {"after": "p2"},
            },
            {
                "data": [
                    {"id": i, "fields": {"description": {"raw": "d"}}}
                    for i in range(4, 7)
                ],
                "cursor": {"after": None},
            },
        ]
        n = [0]

        def search(**kw):
            result = pages[n[0]]
            n[0] += 1
            return result

        client.maniphest.search_tasks.side_effect = search
        return client

    def test_fetch_all_accumulates_all_pages(self):
        client = self._multi_page_client()
        result = self._fn(client)(fetch_all=True)
        self.assertTrue(result["success"])
        self.assertIsInstance(result["results"], list)
        self.assertEqual(len(result["results"]), 6)
        self.assertEqual(result["total"], 6)
        self.assertFalse(result["has_more"])

    def test_fetch_all_forces_description_off(self):
        client = self._multi_page_client()
        result = self._fn(client)(fetch_all=True, include_description=True)
        self.assertTrue(result["success"])
        for task in result["results"]:
            self.assertNotIn("description", task.get("fields", {}))

    def test_results_is_list_not_dict(self):
        client = Mock()
        client.maniphest.search_tasks.return_value = {
            "data": [{"id": 1}],
            "cursor": {"after": None},
        }
        result = self._fn(client)(limit=5)
        self.assertTrue(result["success"])
        self.assertIsInstance(result["results"], list)

    def test_fetch_all_false_has_more_and_note_when_more_pages(self):
        client = Mock()
        client.maniphest.search_tasks.return_value = {
            "data": [{"id": 1}, {"id": 2}],
            "cursor": {"after": "PAGE2"},
        }
        result = self._fn(client)(limit=2)
        self.assertTrue(result["has_more"])
        self.assertEqual(result["next_cursor"], "PAGE2")
        self.assertIn("note", result)


if __name__ == "__main__":
    unittest.main()
