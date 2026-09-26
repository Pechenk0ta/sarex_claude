"""How the app signs in to the mailbox. Only this module changes if the mailbox moves.

Microsoft 365 accepts SMTP/IMAP only with OAuth2 (client credentials of an app registered
in Entra ID with SMTP.SendAsApp and IMAP.AccessAsApp, TZ section 9, decision 1).
"""

import asyncio
from functools import lru_cache
from typing import Any

import msal

from app.config import Settings

M365_SCOPE = ["https://outlook.office365.com/.default"]


class MailAuthError(Exception):
    pass


@lru_cache
def _m365_app(tenant_id: str, client_id: str, client_secret: str) -> Any:
    # msal caches the token in the app object and refreshes it when it expires.
    return msal.ConfidentialClientApplication(
        client_id,
        authority=f"https://login.microsoftonline.com/{tenant_id}",
        client_credential=client_secret,
    )


async def m365_access_token(settings: Settings) -> str:
    if not (settings.ms_tenant_id and settings.ms_client_id and settings.ms_client_secret):
        raise MailAuthError("MS_TENANT_ID, MS_CLIENT_ID and MS_CLIENT_SECRET must be set")
    app = _m365_app(
        settings.ms_tenant_id,
        settings.ms_client_id,
        settings.ms_client_secret.get_secret_value(),
    )
    result: dict[str, Any] = await asyncio.to_thread(
        app.acquire_token_for_client, scopes=M365_SCOPE
    )
    token = result.get("access_token")
    if not isinstance(token, str):
        raise MailAuthError(
            f"Microsoft 365 token error: {result.get('error')}: {result.get('error_description')}"
        )
    return token
