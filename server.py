import os
import zipfile
import shutil
import json
from datetime import datetime
from flask import Flask, request, jsonify, render_template, send_file
from script_parser import parse_script
from fish_automator import generate_batch_fish_audio_playwright
import asyncio
import edge_tts
from fishaudio import FishAudio
from dotenv import load_dotenv

load_dotenv()

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

def parse_worker_count(raw_value, default_value, max_value=5):
    try:
        value = int(raw_value)
    except (TypeError, ValueError):
        value = default_value
    return max(1, min(value, max_value))

def save_script_snapshot(raw_script, parsed):
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    first_line = raw_script.strip().splitlines()[0][:48] if raw_script.strip() else 'guion'
    safe_title = ''.join(char if char.isalnum() else '_' for char in first_line.lower()).strip('_')
    safe_title = safe_title[:40] or 'guion'
    filename = f"{timestamp}_{safe_title}.json"
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

async def generate_edge_tts(text, output_path, voice="es-MX-JorgeNeural"):
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(output_path)
        return True
    except Exception as e:
        print(f"Edge TTS Error: {e}")
        return False

def generate_fish_audio(text, output_path, model_id=None):
    if not FISH_AUDIO_API_KEY:
        return False, "Fish Audio API key no configurada. Revisa el archivo .env."
    try:
        client = FishAudio(api_key=FISH_AUDIO_API_KEY)
        
        # Fish Audio TTS request
        # Si model_id está presente, usa reference_id. Si no, default.
        request_args = {"text": text}
        if model_id:
            request_args["reference_id"] = model_id
            
        with open(output_path, "wb") as f:
            for chunk in client.tts.stream(**request_args):
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

@app.route('/generate-audio', methods=['POST'])
def generate_audio():
    data = request.json
    text = data.get('text')
    file_id = data.get('id')
    engine = data.get('engine', 'edge')
    
    if not text or not file_id:
        return jsonify({"error": "Missing text or id"}), 400
        
    # Limpiar el texto igual que en tu script original
    import re
    text = re.sub(r'[\n\r\t]', ' ', text)
    text = re.sub(r'[""''`]', '', text)
    text = re.sub(r'[\[\]\(\)\{\}]', '', text)
    text = re.sub(r'[#@$%^&*+=|\\/<>]', '', text)
    text = re.sub(r'[-]{2,}', ' ', text)
    text = re.sub(r'[.]{2,}', '.', text)
    text = re.sub(r'[,]{2,}', ',', text)
    text = re.sub(r'\s+', ' ', text).strip()
    
    output_path = os.path.join(app.config['OUTPUT_FOLDER'], f"{file_id}.mp3")
    
    if engine == 'fish':
        model_id = data.get('model_id')
        success, error = generate_fish_audio(text, output_path, model_id)
        if not success:
            return jsonify({"error": error}), 500
    else:
        # Edge TTS
        voice = data.get('voice', 'es-MX-JorgeNeural')
        success = asyncio.run(generate_edge_tts(text, output_path, voice))
        if not success:
            return jsonify({"error": "Edge TTS generation failed"}), 500
            
    return jsonify({"success": True, "file_id": file_id, "path": output_path})

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
            
    try:
        from image_automator import generate_batch_images_flow
        asyncio.run(generate_batch_images_flow(prompts, app.config['IMAGE_OUTPUT_FOLDER'], ref_image_path, flow_workers))
        return jsonify({"success": True})
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Image Automator Error: {e}")
        return jsonify({"error": str(e)}), 500

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
    grok_workers = parse_worker_count(
        request.form.get('grok_workers'),
        app.config['DEFAULT_GROK_WORKERS']
    )
            
    try:
        from image_automator import generate_batch_images_flow
        from fish_automator import generate_batch_fish_audio_playwright
        from grok_automator import generate_videos_in_grok
        
        async def run_both():
            # Crear las tareas, pero le damos un pequeño retraso al inicio del segundo
            # para evitar que Playwright se congele al abrir dos navegadores a la vez
            task1 = asyncio.create_task(generate_batch_images_flow(prompts, app.config['IMAGE_OUTPUT_FOLDER'], ref_image_path, flow_workers))
            await asyncio.sleep(3)
            task2 = asyncio.create_task(generate_batch_fish_audio_playwright(phrases, app.config['OUTPUT_FOLDER']))
            await asyncio.sleep(3)
            
            prompts_dict = {p['id']: p['text'] for p in prompts}
            app.config['GROK_OUTPUT_FOLDER'] = 'image_outputs_animated'
            os.makedirs(app.config['GROK_OUTPUT_FOLDER'], exist_ok=True)
            
            task3 = asyncio.create_task(generate_videos_in_grok(app.config['IMAGE_OUTPUT_FOLDER'], app.config['GROK_OUTPUT_FOLDER'], prompts_dict, grok_workers))
            
            await asyncio.gather(task1, task2, task3)
            
        asyncio.run(run_both())
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
        image_deleted = clear_folder(app.config['IMAGE_OUTPUT_FOLDER'], ('.png', '.jpg', '.jpeg', '.webp'))
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
                if file.endswith('.mp3'):
                    zipf.write(os.path.join(root, file), file)
                    
    return send_file(zip_path, as_attachment=True)

@app.route('/outputs/<filename>')
def serve_output(filename):
    return send_file(os.path.join(app.config['OUTPUT_FOLDER'], filename))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
