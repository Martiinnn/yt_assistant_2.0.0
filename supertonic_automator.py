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


import subprocess
import time
from urllib.parse import urlparse

def check_supertonic_status():
    """Return True if the local Supertonic server is reachable."""
    try:
        r = requests.get(f"{SUPERTONIC_BASE_URL}/docs", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def ensure_supertonic_server_running():
    """Checks if the Supertonic server is running. If not, starts it automatically."""
    if check_supertonic_status():
        return True

    logger.info("[Supertonic] Servidor offline. Intentando iniciar automaticamente en segundo plano...")
    try:
        parsed_url = urlparse(SUPERTONIC_BASE_URL)
        host = parsed_url.hostname or "127.0.0.1"
        port = str(parsed_url.port or 7788)

        creation_flags = 0
        if os.name == 'nt':
            # Evita levantar ventana de cmd visible en Windows
            creation_flags = subprocess.CREATE_NO_WINDOW

        cmd = ["supertonic", "serve", "--host", host, "--port", port]
        logger.info("[Supertonic] Ejecutando: %s", " ".join(cmd))
        
        subprocess.Popen(
            cmd,
            creationflags=creation_flags,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        # Esperar hasta 10 segundos
        for _ in range(20):
            time.sleep(0.5)
            if check_supertonic_status():
                logger.info("[Supertonic] Servidor levantado con exito en http://%s:%s", host, port)
                return True
                
        logger.error("[Supertonic] El servidor fue ejecutado pero no respondio a tiempo.")
        return False
    except Exception as e:
        logger.error("[Supertonic] Error al iniciar automaticamente: %s", e)
        return False


def list_supertonic_voices():
    """Fetch available voice styles from the running Supertonic server."""
    ensure_supertonic_server_running()
    try:
        r = requests.get(f"{SUPERTONIC_BASE_URL}/v1/styles", timeout=5)
        r.raise_for_status()
        data = r.json()
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
    ensure_supertonic_server_running()
    text = _clean_text(text)
    if not text:
        return False, "Texto vacio despues de limpiar."

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
        logger.info("[Supertonic] Audio guardado: %s (duracion: %ss)", output_path, duration)
        return True, None

    except requests.ConnectionError:
        msg = (
            "No se pudo conectar al servidor Supertonic. "
            "Asegurate de que este corriendo con: supertonic serve --port 7788"
        )
        logger.error(msg)
        return False, msg
    except requests.HTTPError as exc:
        msg = f"Supertonic devolvio error HTTP {exc.response.status_code}: {exc.response.text}"
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
    ensure_supertonic_server_running()
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
