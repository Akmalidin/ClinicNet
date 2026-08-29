"""DRF wraps 401/403 into a clean JSON response but never logs them — a
permission bug (wrong branch_scope, a missing grant, RBAC regression) is
invisible unless something explicitly writes it to the log. This wraps the
default handler and adds exactly that, at WARNING, with enough context
(who, what endpoint, which branch) to actually diagnose a cross-branch
permission issue from `journalctl -u clinicnet` without a third-party
service.
"""
import logging

from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("clinicnet.security")


def logging_exception_handler(exc, context):
    response = drf_exception_handler(exc, context)

    if response is not None and response.status_code in (401, 403):
        request = context.get("request")
        view = context.get("view")
        user = getattr(request, "user", None)
        is_authenticated = bool(user and getattr(user, "is_authenticated", False))

        branch = None
        if request is not None:
            branch = request.query_params.get("branch")
            if not branch:
                # request.data can itself raise (e.g. malformed JSON body)
                # — never let logging a 403 turn into masking it with a
                # second, unrelated exception.
                try:
                    branch = request.data.get("branch")
                except Exception:
                    branch = None

        logger.warning(
            "%s %s -> %s user=%s view=%s branch=%s detail=%s",
            getattr(request, "method", "?"),
            getattr(request, "path", "?"),
            response.status_code,
            user if is_authenticated else "anonymous",
            type(view).__name__ if view is not None else "?",
            branch,
            response.data,
        )

    return response
