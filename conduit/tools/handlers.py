import logging
from functools import wraps
from typing import Any, Callable, Dict

from fastmcp.tools.base import ToolResult

from conduit.client import PhabricatorAPIError
from conduit.utils import ErrorCode


def _classify_conduit_code(raw_code: str) -> ErrorCode:
    """Map a Conduit error_code string to an ErrorCode.

    Conduit uses its own vocabulary (ERR-INVALID-AUTH, ERR-RATE-LIMITING,
    ERR_BAD_TASK, ...) with either '-' or '_' separators, none of which match the
    ErrorCode enum values, so a bare ErrorCode(raw_code) always fails. Classify
    the common actionable cases; anything unrecognized stays UNKNOWN_ERROR.
    """
    try:
        return ErrorCode(raw_code)
    except ValueError:
        pass
    norm = str(raw_code).strip().upper().replace("_", "-")
    if "RATE-LIMIT" in norm:
        return ErrorCode.RATE_LIMIT_ERROR
    if "AUTH" in norm or "SESSION" in norm or norm == "ERR-INVALID-TOKEN":
        return ErrorCode.AUTH_ERROR
    if "TIMEOUT" in norm or "NETWORK" in norm:
        return ErrorCode.NETWORK_ERROR
    return ErrorCode.UNKNOWN_ERROR


def _get_error_details(error: Exception) -> Dict[str, Any]:
    """
    Get simplified error information based on exception type.

    Args:
        error: The exception that occurred

    Returns:
        Dictionary containing error_code, error, and suggestion
    """
    error_code = ErrorCode.UNKNOWN_ERROR
    error_message = str(error)

    # Map exception types to error codes
    if isinstance(error, PhabricatorAPIError):
        if getattr(error, "error_code", None):
            error_code = _classify_conduit_code(error.error_code)
    elif isinstance(error, (ConnectionError, TimeoutError)):
        error_code = ErrorCode.NETWORK_ERROR
    elif isinstance(error, (ValueError, KeyError)):
        error_code = ErrorCode.VALIDATION_ERROR

    # Provide generic suggestions based on error type
    suggestions = {
        ErrorCode.NETWORK_ERROR: "Check your network connection and verify the Phabricator server is accessible",
        ErrorCode.AUTH_ERROR: "Verify your PHABRICATOR_TOKEN environment variable or check token validity",
        ErrorCode.VALIDATION_ERROR: "Provide valid parameters according to the API documentation",
        ErrorCode.RATE_LIMIT_ERROR: "Wait a few minutes before making additional requests",
        ErrorCode.NOT_FOUND: "Verify the resource identifier and check if it exists",
    }

    suggestion = suggestions.get(
        error_code, "An unexpected error occurred. Please check the logs for details."
    )

    return {
        "error_code": error_code.value,
        "error": error_message,
        "suggestion": suggestion,
    }


def handle_api_errors(func: Callable) -> Callable:
    """
    Decorator to handle API errors and provide detailed error information.

    On success, returns the tool's value unchanged. On failure (raised exception
    or tool returning {"success": False, ...}), returns a FastMCP ToolResult
    with is_error=True; the structured_content carries the error body including
    success, error message, error_code, suggestion, and optional error_info fields.

    Args:
        func: The function to decorate

    Returns:
        The wrapped function with error handling

    Example:
        @handle_api_errors
        def some_api_function():
            # API call logic here
            pass

        # Success: returns tool result unchanged
        # {"success": True, "result": {...}}

        # Error: returns ToolResult(is_error=True) with structured_content
        # ToolResult(is_error=True, structured_content={
        #     "success": False,
        #     "error": "Authentication failed: Invalid API token",
        #     "error_code": "AUTH_ERROR",
        #     "suggestion": "Verify your PHABRICATOR_TOKEN environment variable"
        # })
    """

    @wraps(func)
    def wrapper(*args, **kwargs) -> Any:
        try:
            result = func(*args, **kwargs)
            if isinstance(result, ToolResult):
                return result
            if isinstance(result, dict) and "success" in result:
                if result.get("success") is False:
                    return ToolResult(
                        content=str(result.get("error", "tool failed")),
                        structured_content=result,
                        is_error=True,
                    )
                return result
            return {"success": True, "result": result}
        except PhabricatorAPIError as e:
            logging.getLogger("conduit").warning("tool %s failed: %s", func.__name__, e)
            error_details = _get_error_details(e)
            body: Dict[str, Any] = {
                "success": False,
                "error": error_details["error"],
                "error_code": error_details["error_code"],
                "suggestion": error_details["suggestion"],
            }
            if hasattr(e, "error_info") and e.error_info:
                body["error_info"] = e.error_info
            return ToolResult(
                content=str(body["error"]),
                structured_content=body,
                is_error=True,
            )
        except Exception as e:
            logging.getLogger("conduit").warning("tool %s failed: %s", func.__name__, e)
            error_details = _get_error_details(e)
            body = {
                "success": False,
                "error": error_details["error"],
                "error_code": error_details["error_code"],
                "suggestion": error_details["suggestion"],
            }
            return ToolResult(
                content=str(body["error"]),
                structured_content=body,
                is_error=True,
            )

    return wrapper
