import os
import time
import asyncio
from playwright.async_api import async_playwright

async def generate_batch_fish_audio_playwright(phrases, output_folder):
    """
    Automates fish.audio using Playwright to generate audio for a list of phrases.
    Uses a persistent context so the user stays logged in.
    """
    user_data_dir = os.path.join(os.getcwd(), 'playwright_data_fish')
    os.makedirs(user_data_dir, exist_ok=True)
    os.makedirs(output_folder, exist_ok=True)

    print(f"[FishAutomator] Iniciando Playwright...")
    
    async with async_playwright() as p:
        # Usamos chrome porque la versión de Chromium por defecto falla
        # Añadimos flags para ocultar que es un bot y permitir el login de Google
        browser = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            channel="chrome", 
            viewport={'width': 1280, 'height': 800},
            ignore_default_args=["--enable-automation"],
            args=[
                '--start-maximized',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        
        page = browser.pages[0] if browser.pages else await browser.new_page()
        
        print(f"[FishAutomator] Navegando a fish.audio...")
        # Forzamos el idioma inglés en la URL por si acaso, aunque el selector CSS funcionará en cualquier idioma
        await page.goto('https://fish.audio/app/text-to-speech/')
        
        # El área de texto de ProseMirror es la prueba definitiva de que estamos logueados y en la página correcta
        textbox = page.locator('div.tiptap.ProseMirror').first
        
        try:
            # Esperamos 5 segundos a ver si ya está cargado
            await textbox.wait_for(state="visible", timeout=5000)
        except:
            print("\n=======================================================")
            print("[INFO] PARECE QUE NECESITAS INICIAR SESIÓN EN FISH AUDIO")
            print("=======================================================")
            print("[ATENCION] Google suele bloquear los inicios de sesión en navegadores automáticos.")
            print("[POR FAVOR] Usa Discord, GitHub o Email para iniciar sesión en lugar de Google.")
            print("Esperando hasta 5 minutos a que inicies sesión y cargue la página...")
            # Esperar hasta 5 minutos a que el usuario inicie sesión
            await textbox.wait_for(state="visible", timeout=300000)
            print("[OK] Sesión detectada. Continuamos con la automatización.\n")
        
        print(f"[FishAutomator] Procesando {len(phrases)} frases...")
        
        for phrase in phrases:
            phrase_id = phrase['id']
            text = phrase['text']
            
            output_path = os.path.join(output_folder, f"{phrase_id}.mp3")
            if os.path.exists(output_path):
                print(f"[FishAutomator] Frase {phrase_id} ya existe. Saltando...")
                continue
                
            print(f"[FishAutomator] Escribiendo frase {phrase_id}...")
            
            await textbox.click()
            
            # Select all and delete (Ctrl+A / Cmd+A, Delete)
            await page.keyboard.press('Control+A')
            await page.keyboard.press('Delete')
            
            # Small pause to ensure UI updates
            await page.wait_for_timeout(500)
            
            # Type the new text
            await page.keyboard.insert_text(text)
            await page.wait_for_timeout(1000)
            
            # Click Generate
            print(f"[FishAutomator] Generando audio {phrase_id}...")
            generate_btn = page.locator('button').filter(has_text='Generate speech').first
            await generate_btn.click()
            
            # Wait for generation to complete and trigger download
            try:
                print(f"[FishAutomator] Esperando a que termine de generar (esto puede tardar unos segundos)...")
                
                # Buscar el botón de descarga usando el aria-label exacto que vemos en la captura
                # Como Fish Audio pone las generaciones nuevas arriba, el .first será el recién generado
                download_btn = page.locator('button[aria-label="Download"]').first
                
                # Esperamos hasta 60 segundos a que aparezca el botón (tiempo de generación)
                await download_btn.wait_for(state="visible", timeout=60000)
                
                # Pequeña pausa para asegurar que el botón es interactuable
                await page.wait_for_timeout(1000)
                
                print(f"[FishAutomator] Botón de descarga encontrado, descargando...")
                async with page.expect_download(timeout=60000) as download_info:
                    await download_btn.click()
                        
                download = await download_info.value
                await download.save_as(output_path)
                print(f"[FishAutomator] [OK] Frase {phrase_id} guardada con éxito.")
                
            except Exception as e:
                print(f"[FishAutomator] [ERROR] Error descargando frase {phrase_id}: {e}")
            
            # Wait a bit before the next phrase
            await page.wait_for_timeout(2000)
            
        print("[FishAutomator] ¡Proceso por lotes completado!")
        await browser.close()
