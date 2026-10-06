"""Interpret explicit platform restrictions without duplicating tier policy."""

from dataclasses import dataclass

import httpx

from deeporigin.exceptions import PlatformRestrictionError

_RESTRICTION_CODES = {
    "LICENSE.FEATURE_NOT_LICENSED",
    "LICENSE.INSUFFICIENT_AVAILABILITY",
    "LICENSE.RESERVE.FEATURE_NOT_LICENSED",
    "LICENSE.RESERVE.EXCEEDS_MAX",
    "MASON.TOOL_EXECUTION.BILLING_REJECTED",
    "MASON.TOOL_EXECUTION.TIER_LIMIT_EXCEEDED",
    "CREDITS_TX.PREPARE.INSUFFICIENT",
}


@dataclass(frozen=True)
class _PlatformRejection:
    message: str
    action: str | None = None


def _text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _join(values) -> str | None:
    return "; ".join(dict.fromkeys(value for value in values if value)) or None


def _reason(data: dict) -> _PlatformRejection:
    items = data.get("items")
    items = (
        [item for item in items if isinstance(item, dict)]
        if isinstance(items, list)
        else []
    )
    message = (
        _text(data.get("purchase_approval_comment"))
        or _text(data.get("message"))
        or _text(data.get("detail"))
        or _text(data.get("title"))
        or _join(_text(item.get("purchaseApprovalComment")) for item in items)
        or "The platform rejected this operation under its licensing or billing rules."
    )
    action = (
        _text(data.get("action_request"))
        or _text(data.get("actionRequest"))
        or _join(_text(item.get("actionRequest")) for item in items)
    )
    return _PlatformRejection(message, action)


def _parse_platform_rejection(response_data: object) -> _PlatformRejection | None:
    """Read JSON:API errors, legacy billing denials, or rejected execution DTOs."""
    if not isinstance(response_data, dict):
        return None
    code = response_data.get("code")
    if isinstance(code, str) and code in _RESTRICTION_CODES:
        return _reason(response_data)
    if (
        response_data.get("purchase_approved") is False
        or response_data.get("is_approved") is False
    ):
        return _reason(response_data)

    reason = response_data.get("statusReason")
    if response_data.get("status") == "InsufficientFunds":
        return _reason(reason if isinstance(reason, dict) else {"message": reason})
    if isinstance(reason, dict):
        code = reason.get("code")
        if isinstance(code, str) and code in _RESTRICTION_CODES:
            return _reason(reason)

    errors = response_data.get("errors")
    if not isinstance(errors, list):
        return None
    rejections = [
        _reason(error)
        for error in errors
        if isinstance(error, dict)
        and isinstance(error.get("code"), str)
        and error["code"] in _RESTRICTION_CODES
    ]
    if not rejections:
        return None
    return _PlatformRejection(
        _join(r.message for r in rejections),
        _join(r.action for r in rejections),
    )


def raise_for_platform_restriction(
    response_data: object, *, http_status: int | None = None
) -> None:
    """Raise a user-facing SDK exception for an explicit platform restriction.

    Shared by SDK transports and execution lifecycle methods. Integrations with
    a separate HTTP client can use this same response contract.
    """
    rejection = _parse_platform_rejection(response_data)
    if rejection:
        raise PlatformRestrictionError(
            rejection.message,
            action=rejection.action,
            http_status=http_status,
            response_data=response_data,
        )


def _json_or_none(response: httpx.Response) -> object:
    """Read optional error evidence without masking the original HTTP failure."""
    try:
        response.read()
        return response.json()
    except (ValueError, httpx.HTTPError, httpx.StreamError):
        return None
