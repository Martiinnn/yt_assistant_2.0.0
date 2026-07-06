import os
import re
import requests
import logging

logger = logging.getLogger("yt_assistant.supertonic")

SUPERTONIC_BASE_URL = os.environ.get("SUPERTONIC_URL", "http://127.0.0.1:7788")


def _clean_text(text):
    """Sanitize text before sending to TTS — same rules the project already uses."""
    text = re.sub(r'[\n\r\t]', ' ', text)
    text = re.sub(r'[""''`]', '', text)
    text = re.sub(r'[\[\]\(\)\{\}]', '', text)
    text = re.sub(r'[#@$%^&*+=|\\/\<\>]', '', text)
    text = re.sub(r'[-]{2,}', ' ', text)
    text = re.sub(r'[.]{2,}', '.', text)
    text = re.sub(r'[,]{2,}', ',', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def check_supertonic_status():
    """Return True if the local Supertonic server is reachable."""
    try:
        r = requests.get(f"{SUPERTONIC_BASE_URL}/docs", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def list_supertonic_voices():
    """Fetch available voice styles from the running Supertonic server."""
    try:
        r = requests.get(f"{SUPERTONIC_BASE_URL}/v1/styles", timeout=5)
        r.raise_for_status()
        data = r.json()
        # API returns {"styles": [{"name": "M1", "kind": "builtin", "path": null}, ...]}
        styles = data.get("styles", [])
        return {
            "voices": [s["name"] for s in styles if isinstance(s, dict) and "name" in s]
        }
    except Exception as exc:
        logger.warning("No se pudieron listar voces de Supertonic: %s", exc)
        return {"voices": ["M1", "M2", "M3", "M4", "M5", "F1", "F2", "F3", "F4", "F5"]}


def generate_single_supertonic(text, output_path, voice="M1", lang="es",
                                speed=1.05, steps=8, response_format="wav"):
    """
    Generate a single audio file via the Supertonic local server.

    Returns (success: bool, error: str | None).
    """
    text = _clean_text(text)
    if not text:
        return False, "Texto vacío después de limpiar."

    payload = {
        "text": text,
        "voice": voice,
        "lang": lang,
        "speed": speed,
        "steps": steps,
        "response_format": response_format,
    }

    try:
        r = requests.post(
            f"{SUPERTONIC_BASE_URL}/v1/tts",
            json=payload,
            timeout=120,
        )
        r.raise_for_status()

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(r.content)

        duration = r.headers.get("X-Audio-Duration", "?")
        logger.info("[Supertonic] Audio guardado: %s (duración: %ss)", output_path, duration)
        return True, None

    except requests.ConnectionError:
        msg = (
            "No se pudo conectar al servidor Supertonic. "
            "Asegúrate de que esté corriendo con: supertonic serve --port 7788"
        )
        logger.error(msg)
        return False, msg
    except requests.HTTPError as exc:
        msg = f"Supertonic devolvió error HTTP {exc.response.status_code}: {exc.response.text}"
        logger.error(msg)
        return False, msg
    except Exception as exc:
        msg = f"Error inesperado de Supertonic: {exc}"
        logger.error(msg)
        return False, msg


def generate_batch_supertonic(phrases, output_folder, voice="M1", lang="es",
                               speed=1.05, steps=8):
    """
    Generate audio for a list of phrases sequentially.

    Each phrase dict must contain 'id' and 'text'.
    Returns a dict with 'results': list of {id, success, error?}.
    """
    os.makedirs(output_folder, exist_ok=True)
    results = []

    logger.info("[Supertonic] Iniciando lote de %d frases (voz=%s, lang=%s, speed=%s, steps=%s)",
                len(phrases), voice, lang, speed, steps)

    for phrase in phrases:
        phrase_id = phrase["id"]
        text = phrase["text"]
        output_path = os.path.join(output_folder, f"{phrase_id}.wav")

        if os.path.exists(output_path):
            logger.info("[Supertonic] Frase %s ya existe. Saltando.", phrase_id)
            results.append({"id": phrase_id, "success": True, "skipped": True})
            continue

        success, error = generate_single_supertonic(
            text, output_path,
            voice=voice, lang=lang, speed=speed, steps=steps,
        )
        result = {"id": phrase_id, "success": success}
        if error:
            result["error"] = error
        results.append(result)

    ok_count = sum(1 for r in results if r["success"])
    logger.info("[Supertonic] Lote completo: %d/%d exitosos.", ok_count, len(results))
    return {"results": results, "total": len(results), "success_count": ok_count}
