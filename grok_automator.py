import os
import asyncio
import time
import urllib.request
from playwright.async_api import async_playwright


def _resolve_worker_count(worker_count, total_items):
    try:
        configured = int(worker_count or os.environ.get("GROK_WORKERS", "2"))
    except ValueError:
        configured = 2
    return max(1, min(configured, total_items or 1))


def _image_path_for_id(image_folder, image_id):
    png_path = os.path.join(image_folder, f"{image_id}.png")
    jpg_path = os.path.join(image_folder, f"{image_id}.jpg")

    if os.path.exists(png_path):
        return png_path
    if os.path.exists(jpg_path):
        return jpg_path
    return None


async def _prepare_grok_page(browser, worker_id, page=None):
    page = page or await browser.new_page()
    print(f"[GrokAutomator][W{worker_id}] Verificando sesion en Grok...")
    await page.goto("https://grok.com/imagine")

    grok_input = page.locator('textarea, div[contenteditable="true"]').first
    try:
        await grok_input.wait_for(state="visible", timeout=10000)
        print(f"[GrokAutomator][W{worker_id}] [OK] Sesion detectada.")
    except Exception:
        print("\n=======================================================")
        print("[INFO] NECESITAS INICIAR SESION EN GROK")
        print("El bot se pausara hasta que loguees y aparezca la caja de texto (max 5 min)...")
        await grok_input.wait_for(state="visible", timeout=300000)
        print(f"[GrokAutomator][W{worker_id}] [OK] Sesion detectada. Continuamos.\n")

    return page, grok_input


async def _create_project_label(page, prompts_dict):
    project_label = f"Proyecto_{int(time.time())}"
    if prompts_dict:
        first_prompt = list(prompts_dict.values())[0]
        clean_text = "".join([char for char in first_prompt if char.isalnum() or char.isspace()])
        words = clean_text.split()[:5]
        if words:
            project_label = " ".join(words).strip()[:50]

    print(f"[GrokAutomator] Creando etiqueta del proyecto: {project_label}")
    try:
        new_label_btn = page.locator('text="Nueva etiqueta"').first
        if await new_label_btn.is_visible(timeout=5000):
            await new_label_btn.click()
            await page.wait_for_timeout(1000)
            await page.keyboard.insert_text(project_label)
            await page.wait_for_timeout(500)

            create_btn = page.locator('button:has-text("Crear"), div[role="button"]:has-text("Crear")').first
            await create_btn.click()
            await page.wait_for_timeout(2000)

            label = page.locator(f'text="{project_label}"').first
            if await label.is_visible():
                await label.click()
                print(f"[GrokAutomator] [OK] Dentro de la etiqueta {project_label}.")
                await page.wait_for_timeout(1000)
    except Exception as exc:
        print(f"[GrokAutomator] [WARNING] No se pudo crear/entrar a la etiqueta: {exc}. Se generara en 'Todas'.")


async def _wait_for_image(image_folder, image_id, worker_id):
    print(f"[GrokAutomator][W{worker_id}] Esperando imagen {image_id} desde Flow...")
    for _ in range(600):
        image_path = _image_path_for_id(image_folder, image_id)
        if image_path:
            return image_path
        await asyncio.sleep(2)

    return None


async def _download_visible_video(page, output_video_path, worker_id):
    try:
        download_buttons = page.locator(
            'button[aria-label*="ownload"], button[aria-label*="escargar"], '
            'a[download], a[aria-label*="ownload"]'
        )
        for index in range(await download_buttons.count()):
            button = download_buttons.nth(index)
            if await button.is_visible():
                print(f"[GrokAutomator][W{worker_id}] Boton de descarga encontrado.")
                async with page.expect_download(timeout=60000) as download_info:
                    await button.click()
                download = await download_info.value
                await download.save_as(output_video_path)
                return True
    except Exception:
        pass

    try:
        videos = page.locator("video")
        if await videos.count() > 0:
            video = videos.last
            await video.click(button="right", force=True)
            await page.wait_for_timeout(1000)

            save_option = page.locator("text=/Save video|Download|Descargar|Guardar video/i").first
            if await save_option.is_visible(timeout=2000):
                print(f"[GrokAutomator][W{worker_id}] Descargando desde menu contextual.")
                async with page.expect_download(timeout=60000) as download_info:
                    await save_option.click()
                download = await download_info.value
                await download.save_as(output_video_path)
                await page.mouse.click(0, 0)
                return True
            await page.mouse.click(0, 0)
    except Exception:
        pass

    try:
        videos = page.locator("video")
        if await videos.count() > 0:
            video = videos.last
            video_src = await video.evaluate('el => el.src || el.querySelector("source")?.src || ""')
            if video_src:
                print(f"[GrokAutomator][W{worker_id}] Descargando video desde URL directa...")
                urllib.request.urlretrieve(video_src, output_video_path)
                return True
    except Exception:
        pass

    return False


async def _animate_one_image(page, grok_input, image_id, image_path, output_folder, prompts_dict, worker_id):
    output_video_path = os.path.join(output_folder, f"{image_id}.mp4")
    if os.path.exists(output_video_path):
        print(f"[GrokAutomator][W{worker_id}] Video {image_id} ya existe. Saltando...")
        return True

    filename = os.path.basename(image_path)
    print(f"[GrokAutomator][W{worker_id}] Animando {filename} en Grok...")

    try:
        video_btn = page.locator('text="Video"').first
        if await video_btn.is_visible(timeout=3000):
            await video_btn.click()
            await page.wait_for_timeout(500)
    except Exception:
        pass

    file_input = page.locator('input[type="file"]').first
    await file_input.set_input_files(image_path)
    await page.wait_for_timeout(2000)

    prompt_text = prompts_dict.get(str(image_id), "Animate this image beautifully") if prompts_dict else "Animate this image beautifully"

    await grok_input.click(force=True)
    await page.wait_for_timeout(500)
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await page.keyboard.insert_text(prompt_text)
    await page.wait_for_timeout(500)

    await page.keyboard.press("Enter")
    print(f"[GrokAutomator][W{worker_id}] Enviado {image_id}. Esperando inicio...")
    await page.wait_for_timeout(5000)

    thumbnail_clicked = False
    for _ in range(30):
        if await page.locator("video").count() > 0:
            thumbnail_clicked = True
            break

        pct_text = page.locator(r"text=/\d+%/")
        if await pct_text.count() > 0:
            try:
                await pct_text.first.click()
                thumbnail_clicked = True
                await page.wait_for_timeout(2000)
                break
            except Exception:
                pass

        make_video_btn = page.locator('text=/Make video/i, button:has-text("Make video")')
        if await make_video_btn.count() > 0 and await make_video_btn.first.is_visible():
            try:
                await make_video_btn.first.click()
                thumbnail_clicked = True
                await page.wait_for_timeout(3000)
                break
            except Exception:
                pass

        await page.wait_for_timeout(2000)

    if not thumbnail_clicked:
        print(f"[GrokAutomator][W{worker_id}] [WARNING] No se encontro thumbnail para {image_id}; continuo esperando.")

    generation_complete = False
    for wait_index in range(150):
        video_count = await page.locator("video").count()
        generating_text = page.locator("text=/Generating|Generando/i")
        still_generating = (await generating_text.count() > 0) and (await generating_text.first.is_visible())
        download_locator = page.locator('button[aria-label*="ownload"], button[aria-label*="escargar"], a[download]')
        download_visible = (await download_locator.count() > 0) and (await download_locator.first.is_visible())

        if download_visible or (video_count > 0 and not still_generating):
            print(f"[GrokAutomator][W{worker_id}] Video {image_id} listo tras {wait_index * 2}s.")
            generation_complete = True
            break

        if still_generating and wait_index % 5 == 0:
            try:
                progress = await generating_text.first.inner_text()
                print(f"[GrokAutomator][W{worker_id}] {image_id}: {progress}...")
            except Exception:
                pass

        await page.wait_for_timeout(2000)

    if not generation_complete:
        print(f"[GrokAutomator][W{worker_id}] [WARNING] Tiempo agotado esperando video {image_id}.")

    await page.wait_for_timeout(3000)
    download_success = await _download_visible_video(page, output_video_path, worker_id)

    if download_success:
        print(f"[GrokAutomator][W{worker_id}] [OK] Guardado: {output_video_path}")
    else:
        print(f"[GrokAutomator][W{worker_id}] [ERROR] Fallo la descarga de {filename}")

    try:
        back_btn = page.locator('button[aria-label*="ack"], a[aria-label*="ack"]').first
        if await back_btn.is_visible(timeout=2000):
            await back_btn.click()
        else:
            await page.keyboard.press("Escape")
    except Exception:
        await page.keyboard.press("Escape")
    await page.wait_for_timeout(2000)

    return download_success


async def generate_videos_in_grok(image_folder, output_folder, prompts_dict=None, worker_count=None):
    """
    Automates Grok to convert images to videos using parallel tabs.
    Each worker saves to <image_id>.mp4, preserving final order by filename.
    """
    prompts_dict = {str(key): value for key, value in prompts_dict.items()} if prompts_dict else {}
    user_data_dir = os.path.join(os.getcwd(), "playwright_data_grok")
    os.makedirs(user_data_dir, exist_ok=True)
    os.makedirs(output_folder, exist_ok=True)

    expected_ids = list(prompts_dict.keys()) if prompts_dict else []
    if not expected_ids:
        images = [file for file in os.listdir(image_folder) if file.endswith((".png", ".jpg"))]
        expected_ids = [os.path.splitext(file)[0] for file in images]

    if not expected_ids:
        print("[GrokAutomator] No hay imagenes esperadas para animar.")
        return

    worker_total = _resolve_worker_count(worker_count, len(expected_ids))
    print("[GrokAutomator] Iniciando Playwright para Grok...")
    print(f"[GrokAutomator] Procesando {len(expected_ids)} imagenes con {worker_total} pestana(s).")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            channel="chrome",
            viewport={"width": 1280, "height": 800},
            ignore_default_args=["--enable-automation"],
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        )

        first_page = browser.pages[0] if browser.pages else await browser.new_page()
        first_page, first_input = await _prepare_grok_page(browser, 1, first_page)
        await _create_project_label(first_page, prompts_dict)

        queue = asyncio.Queue()
        for image_id in expected_ids:
            await queue.put(str(image_id))

        async def worker(worker_id, initial_page=None, initial_input=None):
            if initial_page is None:
                page, grok_input = await _prepare_grok_page(browser, worker_id)
            else:
                page, grok_input = initial_page, initial_input

            while True:
                try:
                    image_id = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                try:
                    output_video_path = os.path.join(output_folder, f"{image_id}.mp4")
                    if os.path.exists(output_video_path):
                        print(f"[GrokAutomator][W{worker_id}] Video {image_id} ya existe. Saltando...")
                        continue

                    image_path = await _wait_for_image(image_folder, image_id, worker_id)
                    if not image_path:
                        print(f"[GrokAutomator][W{worker_id}] [WARNING] No aparecio imagen {image_id}. Saltando...")
                        continue

                    await _animate_one_image(page, grok_input, image_id, image_path, output_folder, prompts_dict or {}, worker_id)
                except Exception as exc:
                    print(f"[GrokAutomator][W{worker_id}] [ERROR] Imagen {image_id} fallo: {exc}")
                finally:
                    queue.task_done()

            if initial_page is None:
                await page.close()

        tasks = [asyncio.create_task(worker(1, first_page, first_input))]
        for worker_id in range(2, worker_total + 1):
            tasks.append(asyncio.create_task(worker(worker_id)))
            await asyncio.sleep(1)

        await asyncio.gather(*tasks)

        print("\n[GrokAutomator] Proceso completado.")
        await browser.close()
