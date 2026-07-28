"""Temporary audio storage and guarded recording downloads."""
import asyncio
from io import BytesIO
import ipaddress
import socket
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from minio import Minio

from app.core.config import Settings
from app.modules.ai.call_quality.intelligence import CallIntelligenceError


ALLOWED_AUDIO_TYPES = {
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
}


class TemporaryAudioStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key.get_secret_value(),
            secure=settings.minio_secure,
        )

    async def put(self, tenant_id: UUID, data: bytes, content_type: str) -> str:
        suffix = ALLOWED_AUDIO_TYPES.get(content_type)
        if suffix is None:
            raise CallIntelligenceError("AUDIO_TYPE_UNSUPPORTED", "Unsupported audio format", retryable=False)
        key = f"temporary-call-audio/{tenant_id}/{uuid4()}{suffix}"

        def upload() -> None:
            if not self.client.bucket_exists(self.settings.minio_bucket):
                self.client.make_bucket(self.settings.minio_bucket)
            self.client.put_object(
                self.settings.minio_bucket,
                key,
                BytesIO(data),
                len(data),
                content_type=content_type,
            )

        await asyncio.to_thread(upload)
        return f"minio://{self.settings.minio_bucket}/{key}"

    async def get(self, uri: str, max_bytes: int) -> tuple[bytes, str, str]:
        parsed = urlparse(uri)
        bucket, key = parsed.netloc, parsed.path.lstrip("/")

        def download() -> bytes:
            response = self.client.get_object(bucket, key)
            try:
                return response.read(max_bytes + 1)
            finally:
                response.close()
                response.release_conn()

        data = await asyncio.to_thread(download)
        if len(data) > max_bytes:
            raise CallIntelligenceError("AUDIO_TOO_LARGE", "Audio file exceeds the configured size limit", retryable=False)
        suffix = key.rsplit(".", 1)[-1].lower() if "." in key else "mp3"
        content_type = {
            "mp3": "audio/mpeg", "m4a": "audio/mp4", "wav": "audio/wav",
            "ogg": "audio/ogg", "webm": "audio/webm",
        }.get(suffix, "audio/mpeg")
        return data, key.rsplit("/", 1)[-1], content_type

    async def delete(self, uri: str) -> None:
        parsed = urlparse(uri)
        if parsed.scheme != "minio":
            return
        await asyncio.to_thread(
            self.client.remove_object, parsed.netloc, parsed.path.lstrip("/")
        )


class RecordingLoader:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        temporary_store: TemporaryAudioStore | None = None,
    ) -> None:
        self.settings = settings
        self.transport = transport
        self.temporary_store = temporary_store or TemporaryAudioStore(settings)

    async def load(self, uri: str) -> tuple[bytes, str, str]:
        if uri.startswith("minio://"):
            return await self.temporary_store.get(uri, self.settings.call_max_audio_bytes)
        parsed = urlparse(uri)
        if parsed.scheme != "https" or not parsed.hostname:
            raise CallIntelligenceError("RECORDING_URL_FORBIDDEN", "Recording URL must use public HTTPS", retryable=False)
        if self.transport is None:
            await self._require_public_host(parsed.hostname)
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.call_analysis_timeout_seconds,
                follow_redirects=False,
                transport=self.transport,
            ) as client:
                async with client.stream("GET", uri) as response:
                    if response.status_code == 429 or response.status_code >= 500:
                        raise CallIntelligenceError("RECORDING_UNAVAILABLE", "Recording provider is temporarily unavailable", retryable=True)
                    if response.status_code >= 400:
                        raise CallIntelligenceError("RECORDING_REJECTED", f"Recording provider returned HTTP {response.status_code}", retryable=response.status_code == 404)
                    declared = int(response.headers.get("content-length", "0") or 0)
                    if declared > self.settings.call_max_audio_bytes:
                        raise CallIntelligenceError("AUDIO_TOO_LARGE", "Audio file exceeds the configured size limit", retryable=False)
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > self.settings.call_max_audio_bytes:
                            raise CallIntelligenceError("AUDIO_TOO_LARGE", "Audio file exceeds the configured size limit", retryable=False)
                        chunks.append(chunk)
        except CallIntelligenceError:
            raise
        except (httpx.TimeoutException, httpx.HTTPError) as exc:
            raise CallIntelligenceError("RECORDING_UNAVAILABLE", "Recording could not be downloaded", retryable=True) from exc
        filename = parsed.path.rsplit("/", 1)[-1] or "recording.mp3"
        content_type = response.headers.get("content-type", "audio/mpeg").split(";", 1)[0]
        if content_type not in ALLOWED_AUDIO_TYPES:
            content_type = "audio/mpeg"
        return b"".join(chunks), filename, content_type

    async def delete_if_temporary(self, uri: str) -> None:
        if uri.startswith("minio://"):
            await self.temporary_store.delete(uri)

    @staticmethod
    async def _require_public_host(hostname: str) -> None:
        try:
            records = await asyncio.to_thread(socket.getaddrinfo, hostname, 443)
        except socket.gaierror as exc:
            raise CallIntelligenceError("RECORDING_UNAVAILABLE", "Recording hostname could not be resolved", retryable=True) from exc
        for record in records:
            address = ipaddress.ip_address(record[4][0])
            if not address.is_global:
                raise CallIntelligenceError("RECORDING_URL_FORBIDDEN", "Recording URL resolves to a private address", retryable=False)
