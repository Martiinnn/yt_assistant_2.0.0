import os
import asyncio
from playwright.async_api import async_playwright


def _resolve_worker_count(worker_count, total_prompts):
    try:
        configured = int(worker_count or os.environ.get("FLOW_WORKERS", "3"))
    except ValueError:
        configured = 3
    return max(1, min(configured, total_prompts or 1))


async def _prepare_flow_page(browser, worker_id, ref_image_path=None, page=None):
    page = page or await browser.new_page()

    print(f"[ImageAutomator][W{worker_id}] Navegando a Google Flow...")
    await page.goto("https://labs.google/fx/es/tools/flow")

    textbox = page.locator('div[data-slate-editor="true"]').first

    try:
        await textbox.wait_for(state="visible", timeout=10000)
    except Exception:
        print("\n=======================================================")
        print("[INFO] PARECE QUE NECESITAS INICIAR SESION EN GOOGLE")
        print("=======================================================")
        print("[ATENCION] Google requiere que inicies sesion en tu cuenta para usar Flow.")
        print("Esperando hasta 5 minutos a que inicies sesion y cargue Flow...")
        await textbox.wait_for(state="visible", timeout=300000)
        print("[OK] Sesion detectada en Google Flow. Continuamos.\n")

    if ref_image_path and os.path.exists(ref_image_path):
        print(f"[ImageAutomator][W{worker_id}] Subiendo imagen de referencia...")
        try:
            file_input = page.locator('input[type="file"]').first
            await file_input.wait_for(state="attached", timeout=5000)
            await file_input.set_input_files(ref_image_path)
            print(f"[ImageAutomator][W{worker_id}] [OK] Referencia enviada. Esperando carga...")
            await page.wait_for_timeout(15000)
        except Exception as exc:
            print(f"[ImageAutomator][W{worker_id}] [WARNING] No se pudo subir la referencia: {exc}")
            print(f"[ImageAutomator][W{worker_id}] Puedes subirla manualmente en esta pestana. Esperando 15s...")
            await page.wait_for_timeout(15000)

    return page, textbox


async def _generate_one_flow_image(page, textbox, prompt_data, output_folder, ref_image_path=None, worker_id=1):
    prompt_id = str(prompt_data["id"])
    text = prompt_data["text"]
    output_path = os.path.join(output_folder, f"{prompt_id}.png")

    if os.path.exists(output_path):
        print(f"[ImageAutomator][W{worker_id}] Imagen {prompt_id} ya existe. Saltando...")
        return True

    print(f"[ImageAutomator][W{worker_id}] Generando imagen para prompt {prompt_id}...")

    await textbox.click(force=True)
    await page.wait_for_timeout(500)
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await page.wait_for_timeout(500)

    if ref_image_path and os.path.exists(ref_image_path):
        await page.keyboard.type("@", delay=150)
        await page.wait_for_timeout(2000)
        await page.keyboard.type("ref_image", delay=100)
        await page.wait_for_timeout(2000)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(1000)

    await page.keyboard.insert_text(text)
    await page.wait_for_timeout(1000)

    await page.evaluate("""() => {
        window.oldImageSrcs = Array.from(document.querySelectorAll('img')).map(img => img.src).filter(src => src);
        document.querySelectorAll('img').forEach(img => img.classList.add('my-old-image-mark'));
    }""")

    old_errors = page.locator("text=/infringir|vaya, se ha producido un error/i")
    for index in range(await old_errors.count()):
        try:
            await old_errors.nth(index).evaluate('node => node.classList.add("my-old-error-mark")')
        except Exception:
            pass

    print(f"[ImageAutomator][W{worker_id}] Enviando peticion {prompt_id} a Google Flow...")
    await page.keyboard.press("Control+Enter")
    await page.wait_for_timeout(500)

    try:
        await page.keyboard.press("Enter")
    except Exception:
        pass

    policy_error_triggered = False
    for attempt in range(150):
        local_errors = page.locator("text=/infringir|vaya, se ha producido un error/i")
        local_errors_count = 0
        for index in range(await local_errors.count()):
            try:
                if await local_errors.nth(index).is_visible():
                    has_mark = await local_errors.nth(index).evaluate(
                        'node => node.classList.contains("my-old-error-mark")'
                    )
                    if not has_mark:
                        local_errors_count += 1
            except Exception:
                pass

        new_images_count = await page.evaluate("""() => {
            return Array.from(document.querySelectorAll('img')).filter(img => {
                if (img.classList.contains('my-old-image-mark')) return false;
                if (window.oldImageSrcs && img.src && window.oldImageSrcs.includes(img.src)) return false;
                const rect = img.getBoundingClientRect();
                return rect.width >= 100 && rect.height >= 100;
            }).length;
        }""")

        if new_images_count + local_errors_count >= 2:
            if new_images_count > 0:
                print(f"[ImageAutomator][W{worker_id}] {new_images_count} imagenes nuevas para {prompt_id} en {attempt * 2}s.")
                await page.wait_for_timeout(4000)
                break
            print(f"[ImageAutomator][W{worker_id}] [ERROR] Prompt {prompt_id} fallo por politicas o error.")
            policy_error_triggered = True
            break

        await page.wait_for_timeout(2000)
    else:
        print(f"[ImageAutomator][W{worker_id}] [WARNING] Tiempo agotado esperando imagen {prompt_id}.")

    if policy_error_triggered:
        await page.wait_for_timeout(2000)
        return False

    images = page.locator("img")
    for index in range(min(20, await images.count())):
        try:
            img = images.nth(index)
            is_old = await img.evaluate("""node => {
                if (node.classList.contains('my-old-image-mark')) return true;
                if (window.oldImageSrcs && node.src && window.oldImageSrcs.includes(node.src)) return true;
                return false;
            }""")

            if is_old:
                continue

            box = await img.bounding_box()
            if not box or box["width"] < 100 or box["height"] < 100:
                continue

            await img.click(button="right", force=True)
            await page.wait_for_timeout(1000)

            download_btn = page.locator("text=/Descargar|Download/i").first
            if not await download_btn.is_visible():
                await page.mouse.click(0, 0)
                continue

            await download_btn.hover()
            await page.wait_for_timeout(1000)

            btn_1k = page.locator('text="1K"').first
            if not await btn_1k.is_visible():
                await page.mouse.click(0, 0)
                continue

            print(f"[ImageAutomator][W{worker_id}] Descargando imagen {prompt_id}...")
            async with page.expect_download(timeout=60000) as download_info:
                await btn_1k.click()
            download = await download_info.value
            await download.save_as(output_path)
            print(f"[ImageAutomator][W{worker_id}] [OK] Imagen {prompt_id} guardada en {output_path}.")
            await page.mouse.click(0, 0)
            await page.wait_for_timeout(1000)
            return True
        except Exception:
            try:
                await page.mouse.click(0, 0)
            except Exception:
                pass

    print(f"[ImageAutomator][W{worker_id}] [WARNING] No se logro descargar automaticamente la imagen {prompt_id}.")
    print(f"[ImageAutomator][W{worker_id}] Tienes 15 segundos para descargarla manualmente como {prompt_id}.png.")
    await page.wait_for_timeout(15000)
    return os.path.exists(output_path)


async def generate_batch_images_flow(prompts, output_folder, ref_image_path=None, worker_count=None):
    """
    Automates Google Flow using parallel Playwright tabs.
    Each worker writes directly to <prompt_id>.png, so completion order cannot rename files incorrectly.
    """
    user_data_dir = os.path.join(os.getcwd(), "playwright_data_google")
    os.makedirs(user_data_dir, exist_ok=True)
    os.makedirs(output_folder, exist_ok=True)

    total_prompts = len(prompts)
    worker_total = _resolve_worker_count(worker_count, total_prompts)

    print("[ImageAutomator] Iniciando Playwright para Google Flow...")
    print(f"[ImageAutomator] Procesando {total_prompts} prompts con {worker_total} pestana(s).")

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            channel="chrome",
            viewport={"width": 1280, "height": 800},
            ignore_default_args=["--enable-automation"],
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        )

        queue = asyncio.Queue()
        for prompt_data in prompts:
            await queue.put(prompt_data)

        first_page = browser.pages[0] if browser.pages else await browser.new_page()

        async def worker(worker_id, initial_page=None):
            page, textbox = await _prepare_flow_page(browser, worker_id, ref_image_path, initial_page)
            while True:
                try:
                    prompt_data = queue.get_nowait()
                except asyncio.QueueEmpty:
                    break

                try:
                    await _generate_one_flow_image(page, textbox, prompt_data, output_folder, ref_image_path, worker_id)
                except Exception as exc:
                    print(f"[ImageAutomator][W{worker_id}] [ERROR] Prompt {prompt_data.get('id')} fallo: {exc}")
                finally:
                    queue.task_done()

            if initial_page is None:
                await page.close()

        tasks = []
        for worker_id in range(1, worker_total + 1):
            initial_page = first_page if worker_id == 1 else None
            tasks.append(asyncio.create_task(worker(worker_id, initial_page)))
            await asyncio.sleep(1)

        await asyncio.gather(*tasks)

        print("[ImageAutomator] Proceso de imagenes completado.")
        await browser.close()
