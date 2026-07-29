import hashlib
import hmac

import httpx


class MetaEmbeddedSignupError(RuntimeError):
    pass


class MetaEmbeddedSignupClient:
    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        graph_version: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.base_url = f"https://graph.facebook.com/{graph_version}"
        self.transport = transport

    async def exchange_code(self, code: str) -> tuple[str, int | None]:
        try:
            async with httpx.AsyncClient(
                timeout=30, transport=self.transport
            ) as client:
                response = await client.get(
                    f"{self.base_url}/oauth/access_token",
                    params={
                        "client_id": self.app_id,
                        "client_secret": self.app_secret,
                        "code": code,
                    },
                )
            response.raise_for_status()
            payload = response.json()
            token = str(payload["access_token"])
            expires_in = payload.get("expires_in")
            return token, int(expires_in) if expires_in is not None else None
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            raise MetaEmbeddedSignupError(
                "Meta did not exchange the Embedded Signup code"
            ) from exc

    async def verify_and_subscribe(
        self, *, token: str, waba_id: str, phone_number_id: str
    ) -> dict[str, str]:
        proof = hmac.new(
            self.app_secret.encode("utf-8"),
            token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        headers = {"Authorization": f"Bearer {token}"}
        params = {"appsecret_proof": proof}
        try:
            async with httpx.AsyncClient(
                timeout=30, transport=self.transport
            ) as client:
                phones_response = await client.get(
                    f"{self.base_url}/{waba_id}/phone_numbers",
                    headers=headers,
                    params={
                        **params,
                        "fields": "id,display_phone_number,verified_name",
                    },
                )
                phones_response.raise_for_status()
                phones = phones_response.json().get("data") or []
                phone = next(
                    (
                        item
                        for item in phones
                        if str(item.get("id")) == phone_number_id
                    ),
                    None,
                )
                if phone is None:
                    raise MetaEmbeddedSignupError(
                        "The selected phone number does not belong to this WABA"
                    )
                subscribe_response = await client.post(
                    f"{self.base_url}/{waba_id}/subscribed_apps",
                    headers=headers,
                    params=params,
                )
                subscribe_response.raise_for_status()
                if not bool(subscribe_response.json().get("success")):
                    raise MetaEmbeddedSignupError(
                        "Meta did not subscribe Revora to this WABA"
                    )
            return {
                "display_phone_number": str(
                    phone.get("display_phone_number") or ""
                ),
                "verified_name": str(phone.get("verified_name") or ""),
            }
        except MetaEmbeddedSignupError:
            raise
        except (httpx.HTTPError, TypeError, ValueError) as exc:
            raise MetaEmbeddedSignupError(
                "Meta could not verify the WhatsApp assets"
            ) from exc
