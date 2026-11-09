from io import BytesIO
import json
from base64 import b64decode

import httpx

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from app.services.screenshots import MAX_UPLOAD_BYTES
from app.config import Settings
from app.llm import MockModelGateway, ModelCallError, QwenModelGateway


@pytest.fixture
def conversation_url(client):
    response = client.post(
        "/conversations", json={"customer_name": "合成截图测试客户"}
    )
    assert response.status_code == 201
    return f"/conversations/{response.json()['id']}"


def make_image(image_format, size=(32, 16), **options):
    with Image.new("RGB", size, "white") as image, BytesIO() as output:
        image.save(output, format=image_format, **options)
        return output.getvalue()


@pytest.mark.parametrize("media_type", ["image/png", "image/jpeg"])
def test_preview_returns_clean_png(client, conversation_url, media_type):
    if media_type == "image/png":
        metadata = PngInfo()
        metadata.add_text("comment", "synthetic metadata")
        raw = make_image("PNG", pnginfo=metadata)
        expected_size = (32, 16)
    else:
        exif = Image.Exif()
        exif[274] = 6  # EXIF 方向，顺时针旋转 90 度。
        raw = make_image("JPEG", exif=exif)
        expected_size = (16, 32)

    response = client.post(
        f"{conversation_url}/screenshots/preview",
        content=raw,
        headers={"Content-Type": media_type},
    )

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["cache-control"] == "no-store"

    with Image.open(BytesIO(response.content)) as preview:
        assert preview.format == "PNG"
        assert preview.mode == "RGB"
        assert preview.size == expected_size
        assert "comment" not in preview.info
        assert not preview.getexif()

    assert client.get(conversation_url).json()["version"] == 0
    assert client.get(f"{conversation_url}/messages").json() == []


def test_preview_rejects_invalid_and_mislabeled_content(client, conversation_url):
    for body, media_type, expected_status in [
        (b"not an image", "image/png", 422),
        (make_image("JPEG"), "image/png", 415),
        (make_image("PNG"), "application/octet-stream", 415),
    ]:
        response = client.post(
            f"{conversation_url}/screenshots/preview",
            content=body,
            headers={"Content-Type": media_type},
        )
        assert response.status_code == expected_status


def test_preview_rejects_byte_and_dimension_limits(client, conversation_url):
    for body in [
        b"x" * (MAX_UPLOAD_BYTES + 1),
        make_image("PNG", size=(4097, 1)),
    ]:
        response = client.post(
            f"{conversation_url}/screenshots/preview",
            content=body,
            headers={"Content-Type": "image/png"},
        )
        assert response.status_code == 413


def test_preview_rejects_animated_png(client, conversation_url):
    with Image.new("RGB", (16, 16), "red") as first, \
         Image.new("RGB", (16, 16), "blue") as second, \
         BytesIO() as output:
        first.save(output, format="PNG", save_all=True, append_images=[second])
        response = client.post(
            f"{conversation_url}/screenshots/preview",
            content=output.getvalue(),
            headers={"Content-Type": "image/png"},
        )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("finish_reason", "actor", "expected_error"),
    [
        ("stop", "unknown", None),
        ("stop", "assistant", "model_invalid_transcript"),
        ("length", "unknown", "model_output_incomplete"),
    ],
)
def test_vision_gateway_sends_png_and_validates_output(
    finish_reason, actor, expected_error
):
    png = make_image("PNG")

    def handler(request):
        payload = json.loads(request.content)
        assert payload["model"] == "test-vision-model"
        assert payload["enable_thinking"] is False
        url = payload["messages"][1]["content"][0]["image_url"]["url"]
        assert url.startswith("data:image/png;base64,")
        assert b64decode(url.split(",", 1)[1]) == png

        return httpx.Response(200, json={
            "choices": [{
                "finish_reason": finish_reason,
                "message": {"content": json.dumps({
                    "lines": [{"actor": actor, "text": "合成原话", "unclear": False}]
                })},
            }],
        })

    gateway = QwenModelGateway(
        Settings(
            llm_mode="live",
            llm_base_url="https://model.example.test/v1",
            llm_model="test-text-model",
            llm_vision_model="test-vision-model",
            llm_api_key="synthetic-key",
        ),
        transport=httpx.MockTransport(handler),
    )

    if expected_error is None:
        result = gateway.transcribe_screenshot(png=png)
        assert result.lines[0].actor == "unknown"
        assert result.lines[0].text == "合成原话"
    else:
        with pytest.raises(ModelCallError, match=expected_error):
            gateway.transcribe_screenshot(png=png)


def test_transcription_preview_leaves_conversation_at_same_version(
    client, conversation_url
):
    response = client.post(
        f"{conversation_url}/screenshots/transcribe?based_on_version=0",
        content=make_image("JPEG"),
        headers={"Content-Type": "image/jpeg"},
    )
    assert response.status_code == 200
    assert response.json()["mode"] == "mock"
    assert response.json()["based_on_version"] == 0
    assert client.get(conversation_url).json()["version"] == 0
    assert client.get(f"{conversation_url}/messages").json() == []


def test_transcription_rejects_version_change_during_model_call(
    client, conversation_url, monkeypatch
):
    original = MockModelGateway.transcribe_screenshot

    def change_conversation(self, *, png):
        added = client.post(f"{conversation_url}/messages", json={
            "request_key": "during-transcription",
            "based_on_version": 0,
            "actor": "customer",
            "text": "转录期间手动补录的合成消息",
        })
        assert added.status_code == 201
        return original(self, png=png)

    monkeypatch.setattr(MockModelGateway, "transcribe_screenshot", change_conversation)
    response = client.post(
        f"{conversation_url}/screenshots/transcribe?based_on_version=0",
        content=make_image("PNG"),
        headers={"Content-Type": "image/png"},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "conversation_version_conflict"
    assert len(client.get(f"{conversation_url}/messages").json()) == 1
