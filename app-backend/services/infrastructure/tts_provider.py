"""语音请求构造、POST 与返回格式解码；客户端和事务由调用方管理。"""
import base64
import logging

from services.infrastructure.logging_context import log_event


def build_speech_request(text, voice, speed, *, base_url, api_key, model):
    """构造现有 MiMo 请求，不加载运行配置或创建客户端。"""
    url = f"{base_url}/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    # 准备 payload 结构，兼容 MiMo API 规格
    payload = {
        "model": model,
        "messages": [
            {
                "role": "assistant",
                "content": text
            }
        ],
        "audio": {
            "format": "mp3",
            "voice": voice
        }
    }

    # 如果语速不等于默认 1.0，则设置语速参数
    if speed != 1.0:
        payload["audio"]["speed"] = speed

    return url, headers, payload


async def request_speech_async(client, url, headers, payload, *, logger) -> bytes:
    """使用调用方持有的异步客户端，保留状态错误和音频格式兼容。"""
    try:
        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            log_event(logger, logging.ERROR, "tts_provider_rejected", status_code=response.status_code)
        response.raise_for_status()
    except Exception as e:
        log_event(logger, logging.ERROR, "tts_provider_failed", error_type=type(e).__name__)
        raise RuntimeError(f"调用云端语音 API 失败: {str(e)}")

    # 兼容两种返回格式：
    # 1. 代理转换后的直接音频流 (Content-Type: audio/...)
    content_type = response.headers.get("content-type", "").lower()
    if "audio" in content_type:
        audio_bytes = response.content
        log_event(logger, logging.DEBUG, "tts_audio_received", size_bytes=len(audio_bytes))
    else:
        # 2. 小米官方的标准 JSON 响应，包含 Base64 数据
        try:
            res_json = response.json()
            audio_data_base64 = res_json["choices"][0]["message"]["audio"]["data"]
            audio_bytes = base64.b64decode(audio_data_base64)
            log_event(logger, logging.DEBUG, "tts_audio_received", size_bytes=len(audio_bytes))
        except KeyError as e:
            log_event(logger, logging.ERROR, "tts_response_invalid", phase="structure")
            raise RuntimeError("云端语音 API 返回格式异常。")
        except Exception as e:
            log_event(logger, logging.ERROR, "tts_response_invalid", phase="decode", error_type=type(e).__name__)
            raise RuntimeError(f"解析语音数据失败: {str(e)}")

    return audio_bytes


def request_speech_sync(client, url, headers, payload, *, logger) -> bytes:
    """使用调用方持有的同步客户端，不改变原同步异常契约。"""
    try:
        response = client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            log_event(logger, logging.ERROR, "tts_provider_rejected", status_code=response.status_code)
        response.raise_for_status()
    except Exception as e:
        log_event(logger, logging.ERROR, "tts_provider_failed", error_type=type(e).__name__)
        raise RuntimeError(f"调用云端语音 API 失败: {str(e)}")

    content_type = response.headers.get("content-type", "").lower()
    if "audio" in content_type:
        audio_bytes = response.content
    else:
        try:
            res_json = response.json()
            audio_data_base64 = res_json["choices"][0]["message"]["audio"]["data"]
            audio_bytes = base64.b64decode(audio_data_base64)
        except Exception as e:
            log_event(logger, logging.ERROR, "tts_response_invalid", phase="decode", error_type=type(e).__name__)
            raise RuntimeError("解析云端语音响应失败")

    return audio_bytes
