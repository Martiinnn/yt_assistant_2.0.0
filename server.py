import os
import zipfile
import shutil
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file
from script_parser import parse_script, parse_podcast_script
from fish_automator import generate_batch_fish_audio_playwright
import asyncio
from dotenv import load_dotenv
from supertonic_automator import (
    generate_single_supertonic,
    generate_batch_supertonic,
    check_supertonic_status,
    list_supertonic_voices,
)

load_dotenv()

LOG_LEVEL = os.environ.get("APP_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s %(levelname)s [%(name)s] %(message)s',
    handlers=[
        logging.FileHandler("server.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("yt_assistant")

app = Flask(__name__)
app.config['OUTPUT_FOLDER'] = 'outputs'
app.config['IMAGE_OUTPUT_FOLDER'] = 'image_outputs'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['SCRIPTS_FOLDER'] = 'saved_scripts'
app.config['DEFAULT_FLOW_WORKERS'] = int(os.environ.get('FLOW_WORKERS', '3'))
app.config['DEFAULT_GROK_WORKERS'] = int(os.environ.get('GROK_WORKERS', '2'))

os.makedirs(app.config['OUTPUT_FOLDER'], exist_ok=True)
os.makedirs(app.config['IMAGE_OUTPUT_FOLDER'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['SCRIPTS_FOLDER'], exist_ok=True)

FISH_AUDIO_API_KEY = os.environ.get("FISH_AUDIO_API_KEY")

# Fish Audio helper (backup) — only works if fishaudio SDK + key are present
def _try_import_fishaudio():
    try:
        from fishaudio import FishAudio
        return FishAudio
    except ImportError:
        return None

def parse_worker_count(raw_value, default_value, max_value=5):
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = default_value
    return max(1, min(value, max_value))

def slugify_text(text, fallback="guion", max_length=58):
    safe_text = ''.join(char if char.isalnum() else '_' for char in text.lower()).strip('_')
    safe_text = '_'.join(part for part in safe_text.split('_') if part)
    return safe_text[:max_length] or fallback

def save_script_snapshot(raw_script, parsed):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    phrases = parsed.get("phrases", [])
    first_phrase = phrases[0].get("text", "") if phrases else ""
    safe_title = slugify_text(first_phrase, "frase_1")
    filename = f"frase_1_{safe_title}_{timestamp}.json"
    path = os.path.join(app.config['SCRIPTS_FOLDER'], filename)

    payload = {
        "created_at": datetime.now().isoformat(timespec='seconds'),
        "source": "web_parse",
        "script": raw_script,
        "prompts": parsed.get("prompts", []),
        "phrases": parsed.get("phrases", []),
        "counts": {
            "prompts": len(parsed.get("prompts", [])),
            "phrases": len(parsed.get("phrases", []))
        }
    }

    with open(path, "w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)

    return path

def clear_folder(folder_path, allowed_extensions=None):
    os.makedirs(folder_path, exist_ok=True)
    deleted = 0

    for entry in os.scandir(folder_path):
        if entry.is_dir():
            shutil.rmtree(entry.path)
            deleted += 1
            continue

        if allowed_extensions and not entry.name.lower().endswith(allowed_extensions):
            continue

        os.remove(entry.path)
        deleted += 1

    return deleted


def collect_numbered_stems(folder_path, allowed_extensions):
    os.makedirs(folder_path, exist_ok=True)
    stems = set()

    for entry in os.scandir(folder_path):
        if not entry.is_file():
            continue
        if not entry.name.lower().endswith(allowed_extensions):
            continue

        stem, _ = os.path.splitext(entry.name)
        if stem.isdigit():
            stems.add(stem)

    return stems

def read_script_snapshot(filename):
    safe_filename = os.path.basename(filename)
    if not safe_filename.endswith('.json'):
        raise ValueError("Invalid script file")

    path = os.path.join(app.config['SCRIPTS_FOLDER'], safe_filename)
    if not os.path.exists(path):
        raise FileNotFoundError("Saved script not found")

    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)

    data["saved_script"] = path
    data["filename"] = safe_filename
    return data

def generate_fish_audio(text, output_path):
    if not FISH_AUDIO_API_KEY:
        return False, "Fish Audio API key no configurada. Revisa el archivo .env."
    FishAudioCls = _try_import_fishaudio()
    if FishAudioCls is None:
        return False, "Fish Audio SDK no instalado (pip install fish-audio-sdk)."
    try:
        client = FishAudioCls(api_key=FISH_AUDIO_API_KEY)

        with open(output_path, "wb") as f:
            for chunk in client.tts.stream(text=text):
                f.write(chunk)
        return True, None
    except Exception as e:
        print(f"Fish Audio Error: {e}")
        return False, str(e)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/parse', methods=['POST'])
def parse():
    data = request.json
    if not data or 'script' not in data:
        return jsonify({"error": "No script provided"}), 400
    
    raw_script = data['script']
    parsed = parse_script(raw_script)
    snapshot_path = save_script_snapshot(raw_script, parsed)
    parsed["saved_script"] = snapshot_path
    return jsonify(parsed)

@app.route('/parse-podcast', methods=['POST'])
def parse_podcast():
    data = request.json
    if not data or 'script' not in data:
        return jsonify({"error": "No script provided"}), 400

    raw_script = data['script']
    parsed = parse_podcast_script(raw_script)
    if not parsed.get("prompts"):
        return jsonify({"error": "No se encontraron bloques de 'Parte X (tiempo):'"}), 400

    return jsonify(parsed)

@app.route('/saved-scripts', methods=['GET'])
def saved_scripts():
    scripts = []
    for entry in os.scandir(app.config['SCRIPTS_FOLDER']):
        if not entry.is_file() or not entry.name.endswith('.json'):
            continue

        try:
            with open(entry.path, "r", encoding="utf-8") as file:
                data = json.load(file)
        except Exception:
            data = {}

        scripts.append({
            "filename": entry.name,
            "created_at": data.get("created_at", datetime.fromtimestamp(entry.stat().st_mtime).isoformat(timespec='seconds')),
            "counts": data.get("counts", {}),
            "label": entry.name.replace(".json", "")
        })

    scripts.sort(key=lambda item: item["created_at"], reverse=True)
    return jsonify({"scripts": scripts})

@app.route('/saved-scripts/<path:filename>', methods=['GET'])
def load_saved_script(filename):
    try:
        return jsonify(read_script_snapshot(filename))
    except FileNotFoundError:
        return jsonify({"error": "Saved script not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route('/supertonic-status', methods=['GET'])
def supertonic_status():
    online = check_supertonic_status()
    return jsonify({"online": online})

@app.route('/supertonic-voices', methods=['GET'])
def supertonic_voices():
    data = list_supertonic_voices()
    return jsonify(data)

@app.route('/generate-audio', methods=['POST'])
def generate_audio():
    data = request.json
    text = data.get('text')
    file_id = data.get('id')
    engine = data.get('engine', 'supertonic')
    
    if not text or not file_id:
        return jsonify({"error": "Missing text or id"}), 400

    if engine == 'supertonic':
        voice = data.get('voice', 'M1')
        lang = data.get('lang', 'es')
        speed = float(data.get('speed', 1.05))
        steps = int(data.get('steps', 8))
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], f"{file_id}.wav")
        success, error = generate_single_supertonic(text, output_path,
                                                     voice=voice, lang=lang,
                                                     speed=speed, steps=steps)
    elif engine == 'fish':
        import re
        text = re.sub(r'[\n\r\t]', ' ', text)
        text = re.sub(r'["\u201c\u201d\u2018\u2019`]', '', text)
        text = re.sub(r'[\[\]\(\)\{\}]', '', text)
        text = re.sub(r'[#@$%^\&*+=|\\\/\<\>]', '', text)
        text = re.sub(r'[-]{2,}', ' ', text)
        text = re.sub(r'[.]{2,}', '.', text)
        text = re.sub(r'[,]{2,}', ',', text)
        text = re.sub(r'\s+', ' ', text).strip()
        output_path = os.path.join(app.config['OUTPUT_FOLDER'], f"{file_id}.mp3")
        success, error = generate_fish_audio(text, output_path)
    else:
        return jsonify({"error": f"Motor '{engine}' no soportado."}), 400

    if not success:
        return jsonify({"error": error}), 500
            
    return jsonify({"success": True, "file_id": file_id, "path": output_path})

@app.route('/generate-batch-supertonic', methods=['POST'])
def generate_batch_supertonic_route():
    data = request.json
    phrases = data.get('phrases', [])
    voice = data.get('voice', 'M1')
    lang = data.get('lang', 'es')
    speed = float(data.get('speed', 1.05))
    steps = int(data.get('steps', 8))

    if not phrases:
        return jsonify({"error": "No phrases provided"}), 400

    try:
        result = generate_batch_supertonic(
            phrases, app.config['OUTPUT_FOLDER'],
            voice=voice, lang=lang, speed=speed, steps=steps
        )
        return jsonify({"success": True, **result})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/generate-batch-fish', methods=['POST'])
def generate_batch_fish():
    data = request.json
    phrases = data.get('phrases', [])
    
    if not phrases:
        return jsonify({"error": "No phrases provided"}), 400
        
    try:
        # Run playwright automation
        asyncio.run(generate_batch_fish_audio_playwright(phrases, app.config['OUTPUT_FOLDER']))
        return jsonify({"success": True})
    except Exception as e:
        print(f"Playwright Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/generate-batch-images', methods=['POST'])
def generate_batch_images():
    import json
    prompts_str = request.form.get('prompts', '[]')
    prompts = json.loads(prompts_str)
    
    if not prompts:
        return jsonify({"error": "No prompts provided"}), 400
        
    ref_image_path = None
    if 'ref_image' in request.files:
        file = request.files['ref_image']
        if file.filename != '':
            ref_image_path = os.path.join(app.config['UPLOAD_FOLDER'], 'ref_image.jpg')
            file.save(ref_image_path)

    flow_workers = parse_worker_count(
        request.form.get('flow_workers'),
        app.config['DEFAULT_FLOW_WORKERS']
    )
    flow_image_ratio = request.form.get('flow_image_ratio', 'keep')
            
    try:
        from image_automator import generate_batch_images_flow
        asyncio.run(
            generate_batch_images_flow(
                prompts,
                app.config['IMAGE_OUTPUT_FOLDER'],
                ref_image_path,
                flow_workers,
                flow_image_ratio
            )
        )
        return jsonify({"success": True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Image Automator Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/generate-flow-podcast', methods=['POST'])
def generate_flow_podcast():
    import json
    prompts_str = request.form.get('prompts', '[]')
    prompts = json.loads(prompts_str)

    if not prompts:
        return jsonify({"error": "No prompts provided"}), 400

    ref_image_path = None
    if 'ref_image' in request.files:
        file = request.files['ref_image']
        if file.filename != '':
            ref_image_path = os.path.join(app.config['UPLOAD_FOLDER'], 'ref_image.jpg')
            file.save(ref_image_path)

    try:
        from image_automator import generate_podcast_videos_flow
        app.config['FLOW_PODCAST_OUTPUT_FOLDER'] = 'flow_podcast_outputs'
        os.makedirs(app.config['FLOW_PODCAST_OUTPUT_FOLDER'], exist_ok=True)
        asyncio.run(generate_podcast_videos_flow(prompts, app.config['FLOW_PODCAST_OUTPUT_FOLDER'], ref_image_path))
        return jsonify({"success": True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Flow Podcast Automator Error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/check-missing-images', methods=['POST'])
def check_missing_images():
    data = request.json or {}
    prompts = data.get('prompts', [])

    if not prompts:
        return jsonify({"error": "No prompts provided"}), 400

    expected_ids = []
    for prompt in prompts:
        prompt_id = str(prompt.get('id', '')).strip()
        if prompt_id.isdigit():
            expected_ids.append(prompt_id)

    if not expected_ids:
        return jsonify({"error": "No valid prompt ids provided"}), 400

    existing_ids = collect_numbered_stems(
        app.config['IMAGE_OUTPUT_FOLDER'],
        ('.png', '.jpg', '.jpeg', '.webp')
    )

    missing_ids = [prompt_id for prompt_id in expected_ids if prompt_id not in existing_ids]
    extra_ids = sorted(existing_ids - set(expected_ids), key=lambda item: int(item))

    return jsonify({
        "success": True,
        "expected_count": len(expected_ids),
        "existing_count": len([prompt_id for prompt_id in expected_ids if prompt_id in existing_ids]),
        "missing_ids": missing_ids,
        "extra_ids": extra_ids
    })

@app.route('/generate-all', methods=['POST'])
def generate_all():
    import json
    prompts_str = request.form.get('prompts', '[]')
    phrases_str = request.form.get('phrases', '[]')
    
    prompts = json.loads(prompts_str)
    phrases = json.loads(phrases_str)
    
    if not prompts or not phrases:
        return jsonify({"error": "No prompts or phrases provided"}), 400
        
    ref_image_path = None
    if 'ref_image' in request.files:
        file = request.files['ref_image']
        if file.filename != '':
            ref_image_path = os.path.join(app.config['UPLOAD_FOLDER'], 'ref_image.jpg')
            file.save(ref_image_path)

    flow_workers = parse_worker_count(
        request.form.get('flow_workers'),
        app.config['DEFAULT_FLOW_WORKERS']
    )
    flow_image_ratio = request.form.get('flow_image_ratio', 'keep')
    grok_workers = parse_worker_count(
        request.form.get('grok_workers'),
        app.config['DEFAULT_GROK_WORKERS']
    )
            
    audio_engine = request.form.get('audio_engine', 'supertonic')
    voice = request.form.get('voice', 'M1')
    lang = request.form.get('lang', 'es')
    speed = float(request.form.get('speed', '1.05'))
    steps = int(request.form.get('steps', '8'))

    try:
        from image_automator import generate_batch_images_flow
        from grok_automator import generate_videos_in_grok
        
        async def run_all():
            # Crear las tareas, pero le damos un pequeño retraso al inicio del segundo
            # para evitar que Playwright se congele al abrir dos navegadores a la vez
            task1 = asyncio.create_task(
                generate_batch_images_flow(
                    prompts,
                    app.config['IMAGE_OUTPUT_FOLDER'],
                    ref_image_path,
                    flow_workers,
                    flow_image_ratio
                )
            )
            await asyncio.sleep(3)

            # Audio — Supertonic es síncrono (HTTP), lo lanzamos en un executor
            if audio_engine == 'supertonic':
                import concurrent.futures
                loop = asyncio.get_event_loop()
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    task2 = loop.run_in_executor(
                        pool,
                        lambda: generate_batch_supertonic(
                            phrases, app.config['OUTPUT_FOLDER'],
                            voice=voice, lang=lang, speed=speed, steps=steps
                        )
                    )
            else:
                from fish_automator import generate_batch_fish_audio_playwright
                task2 = asyncio.create_task(
                    generate_batch_fish_audio_playwright(phrases, app.config['OUTPUT_FOLDER'])
                )

            await asyncio.sleep(3)
            
            prompts_dict = {p['id']: p['text'] for p in prompts}
            app.config['GROK_OUTPUT_FOLDER'] = 'image_outputs_animated'
            os.makedirs(app.config['GROK_OUTPUT_FOLDER'], exist_ok=True)
            
            task3 = asyncio.create_task(generate_videos_in_grok(app.config['IMAGE_OUTPUT_FOLDER'], app.config['GROK_OUTPUT_FOLDER'], prompts_dict, grok_workers))
            
            await asyncio.gather(task1, task2, task3)
            
        asyncio.run(run_all())
        return jsonify({"success": True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Parallel Automator Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/generate-grok', methods=['POST'])
def generate_grok():
    import json
    prompts_str = request.form.get('prompts', '{}')
    prompts_dict = json.loads(prompts_str)
    grok_workers = parse_worker_count(
        request.form.get('grok_workers'),
        app.config['DEFAULT_GROK_WORKERS']
    )
    
    try:
        from grok_automator import generate_videos_in_grok
        app.config['GROK_OUTPUT_FOLDER'] = 'image_outputs_animated'
        os.makedirs(app.config['GROK_OUTPUT_FOLDER'], exist_ok=True)
        asyncio.run(generate_videos_in_grok(app.config['IMAGE_OUTPUT_FOLDER'], app.config['GROK_OUTPUT_FOLDER'], prompts_dict, grok_workers))
        return jsonify({"success": True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Grok Automator Error: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/clear-outputs', methods=['POST'])
def clear_outputs():
    try:
        deleted = clear_folder(app.config['OUTPUT_FOLDER'])
        return jsonify({"success": True, "deleted": deleted})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/reset-media', methods=['POST'])
def reset_media():
    try:
        image_deleted = clear_folder(app.config['IMAGE_OUTPUT_FOLDER'], ('.png', '.jpg', '.jpeg', '.webp', '.failed'))
        video_folder = 'image_outputs_animated'
        video_deleted = clear_folder(video_folder, ('.mp4', '.mov', '.webm', '.mkv'))
        return jsonify({
            "success": True,
            "deleted": {
                "images": image_deleted,
                "videos": video_deleted
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route('/download-zip', methods=['GET'])
def download_zip():
    zip_path = os.path.join(app.config['OUTPUT_FOLDER'], 'audios.zip')
    
    with zipfile.ZipFile(zip_path, 'w') as zipf:
        for root, dirs, files in os.walk(app.config['OUTPUT_FOLDER']):
            for file in files:
                if file.endswith(('.mp3', '.wav')):
                    zipf.write(os.path.join(root, file), file)
                    
    return send_file(zip_path, as_attachment=True)

@app.route('/outputs/<filename>')
def serve_output(filename):
    return send_file(os.path.join(app.config['OUTPUT_FOLDER'], filename))

if __name__ == '__main__':
    app_debug = os.environ.get('FLASK_DEBUG', '0') in ('1', 'true', 'True')
    app_port = int(os.environ.get('PORT', '5000'))

    logger.info("Iniciando servidor en puerto %s (debug=%s, reloader=False)", app_port, app_debug)
    try:
        app.run(debug=app_debug, use_reloader=False, port=app_port)
    except Exception:
        logger.exception("Fallo fatal al iniciar o ejecutar el servidor")
        raise
