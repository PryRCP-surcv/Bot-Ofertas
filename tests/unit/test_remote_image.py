from __future__ import annotations

from typing import Any
from urllib.request import Request

import pytest

from bot_ofertas.notifications import RemoteImageError, SafeRemoteImageFetcher


class FakeImageResponse:
    def __init__(self, content: bytes, headers: dict[str, str]) -> None:
        self._content = content
        self.headers = headers

    def __enter__(self) -> FakeImageResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        return self._content if size < 0 else self._content[:size]


class RecordingImageOpener:
    def __init__(self, response: FakeImageResponse) -> None:
        self.response = response
        self.calls: list[tuple[Request, float]] = []

    def __call__(self, request: Request, *, timeout: float) -> FakeImageResponse:
        self.calls.append((request, timeout))
        return self.response


def public_resolver(*args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
    del args, kwargs
    return [(2, 1, 6, "", ("8.8.8.8", 443))]


def private_resolver(*args: Any, **kwargs: Any) -> list[tuple[Any, ...]]:
    del args, kwargs
    return [(2, 1, 6, "", ("127.0.0.1", 443))]


def test_fetches_valid_public_jpeg_in_memory() -> None:
    content = b"\xff\xd8\xff" + (b"jpeg" * 10)
    opener = RecordingImageOpener(
        FakeImageResponse(
            content,
            {
                "Content-Type": "image/jpeg; charset=binary",
                "Content-Length": str(len(content)),
            },
        )
    )
    fetcher = SafeRemoteImageFetcher(
        resolver=public_resolver,
        open_url=opener,
    )

    downloaded = fetcher.fetch(
        "https://cdn.example.pe/product.jpg#ignored",
        timeout=4.5,
    )

    assert downloaded.content == content
    assert downloaded.content_type == "image/jpeg"
    assert downloaded.filename == "offer.jpg"
    assert len(opener.calls) == 1
    request, timeout = opener.calls[0]
    assert request.full_url == "https://cdn.example.pe/product.jpg"
    assert request.get_method() == "GET"
    assert timeout == 4.5


def test_rejects_private_or_local_image_hosts_before_opening() -> None:
    opener = RecordingImageOpener(
        FakeImageResponse(b"\xff\xd8\xffimage", {"Content-Type": "image/jpeg"})
    )
    fetcher = SafeRemoteImageFetcher(
        resolver=private_resolver,
        open_url=opener,
    )

    with pytest.raises(RemoteImageError) as error:
        fetcher.fetch("https://internal.example/image.jpg", timeout=2)

    assert error.value.category == "non_public_image_host"
    assert opener.calls == []


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"<html>not an image</html>", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\ncontent", "image/jpeg"),
        (b"\xff\xd8\xffcontent", "text/html"),
    ],
)
def test_rejects_declared_or_detected_non_images(
    content: bytes,
    content_type: str,
) -> None:
    opener = RecordingImageOpener(
        FakeImageResponse(content, {"Content-Type": content_type})
    )
    fetcher = SafeRemoteImageFetcher(
        resolver=public_resolver,
        open_url=opener,
    )

    with pytest.raises(RemoteImageError) as error:
        fetcher.fetch("https://cdn.example.pe/product", timeout=2)

    assert error.value.category == "unsupported_image"


def test_rejects_oversized_image_from_header_or_stream() -> None:
    header_opener = RecordingImageOpener(
        FakeImageResponse(
            b"\xff\xd8\xffsmall",
            {
                "Content-Type": "image/jpeg",
                "Content-Length": "11",
            },
        )
    )
    header_fetcher = SafeRemoteImageFetcher(
        max_bytes=10,
        resolver=public_resolver,
        open_url=header_opener,
    )

    with pytest.raises(RemoteImageError) as header_error:
        header_fetcher.fetch("https://cdn.example.pe/product.jpg", timeout=2)

    assert header_error.value.category == "image_too_large"

    stream_opener = RecordingImageOpener(
        FakeImageResponse(
            b"\xff\xd8\xff123456789",
            {"Content-Type": "image/jpeg"},
        )
    )
    stream_fetcher = SafeRemoteImageFetcher(
        max_bytes=10,
        resolver=public_resolver,
        open_url=stream_opener,
    )

    with pytest.raises(RemoteImageError) as stream_error:
        stream_fetcher.fetch("https://cdn.example.pe/product.jpg", timeout=2)

    assert stream_error.value.category == "image_too_large"
