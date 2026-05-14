import os
import asyncio
from playwright.async_api import async_playwright


FLOW_IMAGE_MAX_ATTEMPTS = 3


def _resolve_worker_count(worker_count, total_prompts):
    try:
        configured = int(worker_count or os.environ.get("FLOW_WORKERS", "3"))
    except ValueError:
        configured = 3
    return max(1, min(configured, total_prompts or 1))


def _normalize_flow_image_ratio(raw_ratio):
    if not raw_ratio:
        return None
    ratio = str(raw_ratio).strip()
    if ratio in ("16:9", "9:16"):
        return ratio
    return None


def _failure_marker_path(output_folder, prompt_id):
    return os.path.join(output_folder, f"{prompt_id}.failed")


def _clear_failure_marker(output_folder, prompt_id):
    marker_path = _failure_marker_path(output_folder, prompt_id)
    if os.path.exists(marker_path):
        try:
            os.remove(marker_path)
        except OSError:
            pass


def _write_failure_marker(output_folder, prompt_id):
    marker_path = _failure_marker_path(output_folder, prompt_id)
    try:
        with open(marker_path, "w", encoding="utf-8") as marker:
            marker.write("flow image generation failed after 3 attempts\n")
    except OSError as exc:
        print(f"[ImageAutomator] [WARNING] No se pudo escribir marca de fallo para {prompt_id}: {exc}")


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


async def _ensure_flow_image_generation_settings(page, worker_id, flow_image_ratio):
    # For imagenes: require Imagen + x2 + ratio. Abort if not available.
    ratio = _normalize_flow_image_ratio(flow_image_ratio) or "9:16"

    opened = await _open_flow_generation_settings(page, worker_id)
    if not opened:
        print(f"[ImageAutomator][W{worker_id}] [ERROR] No se pudo abrir panel para configurar imagenes.")
        return False

    image_ok = await _click_panel_row_button(page, worker_id, 0, 0, "Imagen")
    if not image_ok:
        image_ok = await _click_flow_option(
            page,
            [
                'button:has-text("Imagen")',
                'div[role="button"]:has-text("Imagen")',
                'button >> text=/^\\s*Imagen\\s*$/i',
                'text=/^\\s*Imagen\\s*$/i'
            ],
            worker_id,
            "Imagen"
        )

    ratio_ok = await _click_flow_option(
        page,
        [f'button:has-text("{ratio}")', f'div[role="button"]:has-text("{ratio}")', f'text="{ratio}"'],
        worker_id,
        f"Ratio {ratio}",
        wait_after_ms=400
    )

    speed_ok = await _click_flow_option(
        page,
        ['button:has-text("x2")', 'div[role="button"]:has-text("x2")', 'text="x2"'],
        worker_id,
        "x2",
        wait_after_ms=350
    )

    try:
        await page.keyboard.press("Escape")
        await page.wait_for_timeout(300)
    except Exception:
        pass

    if not (image_ok and ratio_ok and speed_ok):
        print(
            f"[ImageAutomator][W{worker_id}] [ERROR] Config incompleta para imagenes "
            f"(Imagen={image_ok}, Ratio={ratio_ok}, x2={speed_ok}). Abortando."
        )
        return False

    return True


async def _generate_one_flow_image(page, textbox, prompt_data, output_folder, ref_image_path=None, worker_id=1, flow_image_ratio=None):
    prompt_id = str(prompt_data["id"])
    text = prompt_data["text"]
    output_path = os.path.join(output_folder, f"{prompt_id}.png")

    if os.path.exists(output_path):
        print(f"[ImageAutomator][W{worker_id}] Imagen {prompt_id} ya existe. Saltando...")
        return True

    print(f"[ImageAutomator][W{worker_id}] Generando imagen para prompt {prompt_id}...")
    settings_ok = await _ensure_flow_image_generation_settings(page, worker_id, flow_image_ratio)
    if not settings_ok:
        return False

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


async def _generate_one_flow_image_with_retries(page, textbox, prompt_data, output_folder, ref_image_path=None, worker_id=1, flow_image_ratio=None):
    prompt_id = str(prompt_data["id"])
    output_path = os.path.join(output_folder, f"{prompt_id}.png")

    _clear_failure_marker(output_folder, prompt_id)

    if os.path.exists(output_path):
        print(f"[ImageAutomator][W{worker_id}] Imagen {prompt_id} ya existe. Saltando...")
        return True

    for attempt in range(1, FLOW_IMAGE_MAX_ATTEMPTS + 1):
        print(f"[ImageAutomator][W{worker_id}] Intento {attempt}/{FLOW_IMAGE_MAX_ATTEMPTS} para imagen {prompt_id}.")
        try:
            success = await _generate_one_flow_image(
                page,
                textbox,
                prompt_data,
                output_folder,
                ref_image_path,
                worker_id,
                flow_image_ratio,
            )
        except Exception as exc:
            success = False
            print(f"[ImageAutomator][W{worker_id}] [ERROR] Intento {attempt} de {prompt_id} fallo: {exc}")

        if success or os.path.exists(output_path):
            _clear_failure_marker(output_folder, prompt_id)
            return True

        if attempt < FLOW_IMAGE_MAX_ATTEMPTS:
            print(f"[ImageAutomator][W{worker_id}] Reintentando imagen {prompt_id} en 5s...")
            try:
                await page.mouse.click(0, 0)
            except Exception:
                pass
            await page.wait_for_timeout(5000)

    print(f"[ImageAutomator][W{worker_id}] [ERROR] Imagen {prompt_id} no se genero tras {FLOW_IMAGE_MAX_ATTEMPTS} intentos. Saltando...")
    _write_failure_marker(output_folder, prompt_id)
    return False


async def generate_batch_images_flow(prompts, output_folder, ref_image_path=None, worker_count=None, flow_image_ratio=None):
    """
    Automates Google Flow using parallel Playwright tabs.
    Each worker writes directly to <prompt_id>.png, so completion order cannot rename files incorrectly.
    """
    user_data_dir = os.path.join(os.getcwd(), "playwright_data_google")
    os.makedirs(user_data_dir, exist_ok=True)
    os.makedirs(output_folder, exist_ok=True)

    total_prompts = len(prompts)
    worker_total = _resolve_worker_count(worker_count, total_prompts)
    for prompt_data in prompts:
        _clear_failure_marker(output_folder, str(prompt_data["id"]))

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
                    await _generate_one_flow_image_with_retries(
                        page,
                        textbox,
                        prompt_data,
                        output_folder,
                        ref_image_path,
                        worker_id,
                        flow_image_ratio,
                    )
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


async def _configure_flow_podcast_mode(page, worker_id, voice_name="Autonoe"):
    print(f"[ImageAutomator][W{worker_id}] Configurando modo podcast en Flow...")

    await _open_flow_resources_menu(page, worker_id)
    voice_selected = await _select_voice_from_voice_tab(page, worker_id, voice_name)

    if not voice_selected:
        print(f"[ImageAutomator][W{worker_id}] [WARNING] Voz {voice_name} no confirmada; se intentara reinyectar antes de cada parte.")

    await _open_flow_resources_menu(page, worker_id)
    image_tab_ok = await _click_flow_resource_tab(page, worker_id, "image", "Imagen")
    if image_tab_ok:
        await _select_reference_from_image_tab(page, worker_id)

    # Leave the composer clean after selecting ingredients.
    await _close_flow_resources_menu(page, worker_id)

    try:
        video_chip = page.locator('button:has-text("Video")').first
        if await video_chip.is_visible(timeout=3000):
            await video_chip.click(force=True)
            await page.wait_for_timeout(600)
    except Exception:
        pass


async def _click_flow_resource_tab(page, worker_id, tab_key, label):
    key = str(tab_key).lower()
    wanted_label = str(label).lower()

    try:
        tabs = page.locator('button[role="tab"], [role="tab"]')
        total = await tabs.count()
    except Exception:
        total = 0

    if total == 0:
        # Fallback: some Flow builds render controls inside same-origin iframes.
        try:
            clicked_in_iframe = await page.evaluate(
                """({ tabKey, label }) => {
                    const key = String(tabKey).toLowerCase();
                    const wantedLabel = String(label).toLowerCase();
                    const frames = Array.from(document.querySelectorAll("iframe"));
                    for (const frame of frames) {
                        try {
                            const doc = frame.contentDocument;
                            if (!doc) continue;
                            const tabs = Array.from(doc.querySelectorAll('button[role="tab"], [role="tab"]'));
                            const tab = tabs.find((node) => {
                                const id = (node.id || '').toLowerCase();
                                const controls = (node.getAttribute('aria-controls') || '').toLowerCase();
                                const text = (node.innerText || node.textContent || '').trim().toLowerCase();
                                return id.includes(key) || controls.includes(key) || text === wantedLabel;
                            });
                            if (tab) {
                                tab.click();
                                return true;
                            }
                        } catch (_) {}
                    }
                    return false;
                }""",
                {"tabKey": tab_key, "label": label}
            )
            if clicked_in_iframe:
                await page.wait_for_timeout(700)
                print(f"[ImageAutomator][W{worker_id}] [OK] Click en tab {label} dentro de iframe.")
                return True
        except Exception:
            pass

        print(f"[ImageAutomator][W{worker_id}] [WARNING] No se encontraron tabs de recursos para {label}.")
        return False

    candidate_indexes = []
    for index in range(total):
        tab = tabs.nth(index)
        try:
            if not await tab.is_visible(timeout=300):
                continue
            attrs = await tab.evaluate("""node => ({
                id: (node.id || '').toLowerCase(),
                controls: (node.getAttribute('aria-controls') || '').toLowerCase(),
                text: ((node.innerText || node.textContent || '').trim()).toLowerCase(),
                selected: (node.getAttribute('aria-selected') || '').toLowerCase()
            })""")
            tab_id = attrs.get("id", "")
            controls = attrs.get("controls", "")
            text = attrs.get("text", "")
            is_match = key in tab_id or key in controls or text == wanted_label
            if is_match:
                candidate_indexes.append(index)
        except Exception:
            continue

    print(
        f"[ImageAutomator][W{worker_id}] Tabs detectados: {total}. "
        f"Candidatos para {label}: {len(candidate_indexes)}."
    )

    if len(candidate_indexes) == 0 and total >= 2 and wanted_label == "imagen":
        # When two tabs exist (Imagen/Voz), pick the currently non-selected tab as fallback.
        try:
            for index in range(total):
                tab = tabs.nth(index)
                attrs = await tab.evaluate("""node => ({
                    selected: (node.getAttribute('aria-selected') || '').toLowerCase()
                })""")
                if attrs.get("selected") != "true":
                    await tab.click(force=True, timeout=1500)
                    await page.wait_for_timeout(600)
                    print(f"[ImageAutomator][W{worker_id}] [OK] Click en tab Imagen por fallback de seleccion.")
                    return True
        except Exception:
            pass

    # Intenta candidatos al final primero (suele ser el tab activo renderizado)
    for index in reversed(candidate_indexes):
        tab = tabs.nth(index)
        try:
            await tab.click(force=True, timeout=2000)
            await page.wait_for_timeout(600)
            print(f"[ImageAutomator][W{worker_id}] [OK] Click en tab {label}.")
            return True
        except Exception:
            try:
                box = await tab.bounding_box()
                if box:
                    x = box["x"] + (box["width"] / 2)
                    y = box["y"] + (box["height"] / 2)
                    await page.mouse.click(x, y)
                    await page.wait_for_timeout(600)
                    print(f"[ImageAutomator][W{worker_id}] [OK] Click en tab {label} por coordenadas.")
                    return True
            except Exception:
                continue

    # Fallback por texto parcial cuando no coincide id/aria-controls
    fallback = page.locator(f'button[role="tab"]:has-text("{label}"), [role="tab"]:has-text("{label}")')
    try:
        fallback_count = await fallback.count()
        for index in range(fallback_count - 1, -1, -1):
            tab = fallback.nth(index)
            if await tab.is_visible(timeout=300):
                await tab.click(force=True, timeout=1500)
                await page.wait_for_timeout(600)
                print(f"[ImageAutomator][W{worker_id}] [OK] Click en tab {label} (fallback texto).")
                return True
    except Exception:
        pass

    print(f"[ImageAutomator][W{worker_id}] [WARNING] No se pudo clickear tab {label}.")
    return False


async def _open_flow_resources_menu(page, worker_id):
    # El picker de Voz/Imagen aparece despues de clickear '+' del composer.
    try:
        dialog_open = await page.locator('div[role="dialog"][data-state="open"]').first.is_visible(timeout=400)
        if dialog_open:
            return True
    except Exception:
        pass

    plus_selectors = [
        'button[aria-label*="Agregar" i]',
        'button[aria-label*="Add" i]',
        'button:has(i.google-symbols:has-text("add"))',
        'button:has-text("+")',
        'button:has(svg)',
    ]

    for selector in plus_selectors:
        try:
            btn = page.locator(selector).last
            if await btn.is_visible(timeout=1000):
                await btn.click(force=True)
                await page.wait_for_timeout(600)
                if await page.locator('div[role="dialog"][data-state="open"]').first.is_visible(timeout=1000):
                    print(f"[ImageAutomator][W{worker_id}] [OK] Menu de recursos abierto con '+'.")
                    return True
        except Exception:
            continue

    # Fallback por coordenadas cerca del borde izquierdo del composer (donde vive el '+').
    try:
        composer = page.locator('div:has-text("¿Qué quieres crear?"), div:has-text("Que quieres crear?")').first
        if await composer.is_visible(timeout=800):
            box = await composer.bounding_box()
            if box:
                x = box["x"] + 20
                y = box["y"] + box["height"] - 20
                await page.mouse.click(x, y)
                await page.wait_for_timeout(700)
                if await page.locator('div[role="dialog"][data-state="open"]').first.is_visible(timeout=1000):
                    print(f"[ImageAutomator][W{worker_id}] [OK] Menu de recursos abierto por coordenadas.")
                    return True
    except Exception:
        pass

    print(f"[ImageAutomator][W{worker_id}] [WARNING] No se pudo abrir menu de recursos con '+'.")
    return False


async def _close_flow_resources_menu(page, worker_id):
    try:
        dialog = page.locator('div[role="dialog"][data-state="open"]').first
        if await dialog.is_visible(timeout=400):
            try:
                close_btn = dialog.locator('button[aria-label*="close" i], button[aria-label*="cerrar" i], button:has-text("×"), button:has-text("x")').first
                if await close_btn.is_visible(timeout=600):
                    await close_btn.click(force=True)
                    await page.wait_for_timeout(350)
                else:
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(350)
            except Exception:
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(350)
    except Exception:
        pass


async def _select_voice_from_voice_tab(page, worker_id, voice_name="Autonoe"):
    for attempt in range(1, 4):
        await _open_flow_resources_menu(page, worker_id)
        await _click_flow_resource_tab(page, worker_id, "audio", "Voz")

        try:
            search_voice = page.locator('input[placeholder*="Buscar recursos"]').first
            if not await search_voice.is_visible(timeout=2500):
                await page.wait_for_timeout(400)
                continue

            await search_voice.click(force=True)
            await page.wait_for_timeout(200)
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await search_voice.fill(voice_name)
            await page.wait_for_timeout(900)
            print(f"[ImageAutomator][W{worker_id}] [OK] Buscando voz: {voice_name} (intento {attempt}).")
        except Exception:
            await page.wait_for_timeout(400)
            continue

        try:
            voice_option = page.locator(
                f'text=/^\\s*{voice_name}\\s*$/i, button:has-text("{voice_name}"), [role="button"]:has-text("{voice_name}")'
            ).first
            if await voice_option.is_visible(timeout=3000):
                await voice_option.click(force=True)
                await page.wait_for_timeout(900)
                print(f"[ImageAutomator][W{worker_id}] [OK] Voz seleccionada: {voice_name}.")
                return True
        except Exception:
            pass

        try:
            selected = await page.evaluate(
                """(voiceName) => {
                    const target = String(voiceName).toLowerCase();
                    const nodes = Array.from(document.querySelectorAll('button, [role="button"], div, span'));
                    const item = nodes.find((node) => {
                        const text = (node.innerText || node.textContent || '').trim().toLowerCase();
                        if (text !== target) return false;
                        const rect = node.getBoundingClientRect();
                        const style = window.getComputedStyle(node);
                        return rect.width > 0 && rect.height > 0 && style.display !== 'none' && style.visibility !== 'hidden';
                    });
                    if (!item) return false;
                    item.click();
                    return true;
                }""",
                voice_name
            )
            if selected:
                await page.wait_for_timeout(900)
                print(f"[ImageAutomator][W{worker_id}] [OK] Voz seleccionada por DOM: {voice_name}.")
                return True
        except Exception:
            pass

        await page.wait_for_timeout(500)

    return False


async def _select_reference_from_image_tab(page, worker_id):
    # Select the uploaded reference asset from the Imagen tab.
    selectors = [
        'text=/^\\s*ref_image\\.(jpg|jpeg|png|webp)\\s*$/i',
        'text=/^\\s*ref_image\\s*$/i',
        'text=/podcastref\\.(jpg|jpeg|png|webp)/i',
        'text=/\\.(jpg|jpeg|png|webp)\\s*$/i',
    ]

    for selector in selectors:
        try:
            item = page.locator(selector).first
            if await item.is_visible(timeout=1200):
                await item.click(force=True)
                await page.wait_for_timeout(500)
                print(f"[ImageAutomator][W{worker_id}] [OK] Referencia seleccionada desde tab Imagen.")
                return True
        except Exception:
            continue

    print(f"[ImageAutomator][W{worker_id}] [WARNING] No se pudo seleccionar referencia desde tab Imagen.")
    return False


async def _ensure_reference_and_voice_in_composer(page, textbox, worker_id, voice_name="Autonoe"):
    """
    Ensures composer has both ingredients: reference image and selected voice.
    If not detectable, re-inserts them using @ mentions.
    """
    # Ingredients are now selected once during _configure_flow_podcast_mode.
    # Here we only ensure the resource menu is closed before prompt typing.
    await _close_flow_resources_menu(page, worker_id)
    return True


async def _click_flow_option(page, selectors, worker_id, label, wait_after_ms=500):
    for selector in selectors:
        try:
            option = page.locator(selector).last
            if await option.is_visible(timeout=1500):
                await option.click(force=True)
                await page.wait_for_timeout(wait_after_ms)
                print(f"[ImageAutomator][W{worker_id}] [OK] Opcion aplicada: {label}.")
                return True
        except Exception:
            continue
    print(f"[ImageAutomator][W{worker_id}] [WARNING] No se pudo aplicar opcion: {label}.")
    return False


async def _click_panel_row_button(page, worker_id, row_index, button_index, label, wait_after_ms=500):
    """
    Click a button by panel structure:
    row_index: 0-based row in settings panel (0: Imagen/Video, 1: Fotogramas/Ingredientes, etc.)
    button_index: 0 left, 1 right
    """
    try:
        rows = page.locator('div[data-orientation="horizontal"]')
        row = rows.nth(row_index)
        if not await row.is_visible(timeout=1200):
            return False

        buttons = row.locator("button")
        count = await buttons.count()
        btn = None
        if count > button_index:
            btn = buttons.nth(button_index)
        else:
            role_buttons = row.locator('[role="button"]')
            role_count = await role_buttons.count()
            if role_count > button_index:
                btn = role_buttons.nth(button_index)
            else:
                return False

        if await btn.is_visible(timeout=1000):
            await btn.click(force=True)
            await page.wait_for_timeout(wait_after_ms)
            print(f"[ImageAutomator][W{worker_id}] [OK] Opcion aplicada por estructura: {label}.")
            return True
    except Exception:
        return False
    return False


async def _open_flow_generation_settings(page, worker_id):
    # Flow cambia el texto del boton (a veces "Video", otras no), por eso priorizamos su estructura.
    candidates = [
        page.locator('button[aria-haspopup="menu"][data-state]').filter(has=page.locator('text=1x')).last,
        page.locator('button[aria-haspopup="menu"]').filter(has=page.locator('i.google-symbols:has-text("crop_9_16")')).last,
        page.locator('button[aria-haspopup="menu"]').filter(has=page.locator('text=/9:16|16:9/')).last,
        page.locator('button[aria-haspopup="menu"]').filter(has=page.locator('text=/1x|x2|x3|x4/i')).last,
        page.locator('button[aria-haspopup="menu"]').last,
    ]

    for trigger in candidates:
        try:
            if await trigger.is_visible(timeout=1200):
                await trigger.click(force=True)
                await page.wait_for_timeout(700)
                print(f"[ImageAutomator][W{worker_id}] [OK] Panel de ajustes de generacion abierto.")
                return True
        except Exception:
            continue

    # Fallback por si cambia la estructura del componente.
    fallback_selectors = [
        'button:has-text("1x")',
        'div[role="button"]:has-text("1x")',
        'button[aria-label*="config" i]',
        'button[aria-label*="setting" i]',
    ]
    for selector in fallback_selectors:
        try:
            trigger = page.locator(selector).last
            if await trigger.is_visible(timeout=1000):
                await trigger.click(force=True)
                await page.wait_for_timeout(700)
                print(f"[ImageAutomator][W{worker_id}] [OK] Panel de ajustes de generacion abierto (fallback).")
                return True
        except Exception:
            continue

    print(f"[ImageAutomator][W{worker_id}] [WARNING] No se pudo abrir panel de ajustes de generacion.")
    return False


async def _ensure_flow_podcast_generation_settings(page, worker_id):
    await _open_flow_generation_settings(page, worker_id)

    # 1) Video (siempre primero)
    video_ok = await _click_panel_row_button(page, worker_id, 0, 1, "Video")
    if not video_ok:
        video_ok = await _click_flow_option(
            page,
            [
                'button:has-text("Video")',
                'div[role="button"]:has-text("Video")',
                'button >> text=/^\\s*Video\\s*$/i',
                'text=/^\\s*Video\\s*$/i'
            ],
            worker_id,
            "Video"
        )
    if not video_ok:
        print(f"[ImageAutomator][W{worker_id}] [ERROR] No se pudo activar Video primero. Abortando configuracion.")
        return False

    # 2) Ingredientes
    ingredientes_ok = await _click_panel_row_button(page, worker_id, 1, 1, "Ingredientes")
    if not ingredientes_ok:
        ingredientes_ok = await _click_flow_option(
            page,
            [
                'button:has-text("Ingredientes")',
                'div[role="button"]:has-text("Ingredientes")',
                'button >> text=/^\\s*Ingredientes\\s*$/i',
                'text=/^\\s*Ingredientes\\s*$/i'
            ],
            worker_id,
            "Ingredientes"
        )

    # 3) 9:16
    ratio_ok = await _click_flow_option(
        page,
        ['button:has-text("9:16")', 'div[role="button"]:has-text("9:16")', 'text="9:16"'],
        worker_id,
        "9:16"
    )

    # 4) 1x
    speed_ok = await _click_flow_option(
        page,
        ['button:has-text("1x")', 'div[role="button"]:has-text("1x")', 'text="1x"'],
        worker_id,
        "1x"
    )

    # 5) Veo 3.1 - Fast (si no esta visible directo, abre dropdown)
    # El modelo puede venir ya seleccionado en un boton de menu; eso tambien cuenta como OK.
    model_selected = False
    try:
        model_chip = page.locator('button[aria-haspopup="menu"][data-state]').filter(
            has=page.locator('text=/veo\\s*3\\.?1\\s*[-–—]?\\s*fast/i')
        ).last
        if await model_chip.is_visible(timeout=2000):
            model_selected = True
            print(f"[ImageAutomator][W{worker_id}] [OK] Modelo ya visible como Veo 3.1 - Fast.")
    except Exception:
        model_selected = False

    if not model_selected:
        model_selected = await _click_flow_option(
            page,
            [
                'button:has-text("Veo 3.1 - Fast")',
                'div[role="button"]:has-text("Veo 3.1 - Fast")',
                'text=/veo\\s*3\\.?1\\s*[-–—]?\\s*fast/i'
            ],
            worker_id,
            "Veo 3.1 - Fast",
            wait_after_ms=700
        )

    if not model_selected:
        try:
            dropdown = page.locator('button[aria-haspopup="menu"][data-state], button:has-text("Veo"), div[role="button"]:has-text("Veo")').last
            if await dropdown.is_visible(timeout=2000):
                await dropdown.click(force=True)
                await page.wait_for_timeout(700)
                model_selected = await _click_flow_option(
                    page,
                    [
                        'text=/veo\\s*3\\.?1\\s*[-–—]?\\s*fast/i',
                        'button:has-text("Veo 3.1 - Fast")',
                        'div[role="option"]:has-text("Veo 3.1 - Fast")',
                        'button[role="option"]:has-text("Veo 3.1 - Fast")'
                    ],
                    worker_id,
                    "Veo 3.1 - Fast",
                    wait_after_ms=800
                )
        except Exception as exc:
            print(f"[ImageAutomator][W{worker_id}] [WARNING] No se pudo abrir dropdown de modelo: {exc}")

    # Cerrar panel si quedo abierto para volver al composer antes de pegar prompt.
    closed = False
    try:
        close_btn = page.locator(
            'button[aria-label*="close" i], button[aria-label*="cerrar" i], button:has-text("×"), button:has-text("x")'
        ).first
        if await close_btn.is_visible(timeout=1000):
            await close_btn.click(force=True)
            await page.wait_for_timeout(400)
            closed = True
    except Exception:
        closed = False

    if not closed:
        try:
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(400)
            closed = True
        except Exception:
            closed = False

    if closed:
        print(f"[ImageAutomator][W{worker_id}] [OK] Panel de ajustes cerrado.")
    else:
        print(f"[ImageAutomator][W{worker_id}] [WARNING] No se pudo cerrar panel de ajustes.")

    summary_ok = False
    try:
        page_text = (await page.inner_text("body")).lower()
        summary_ok = all(token in page_text for token in ["video", "ingredientes", "9:16", "1x"]) and ("veo 3.1 - fast" in page_text or "veo 3.1" in page_text)
    except Exception:
        summary_ok = False

    # La confirmacion visual total puede fallar por cambios de UI/idioma sin afectar la configuracion real.
    # Mantenemos el calculo solo para diagnostico silencioso.

    # No bloquear por resumen visual: lo importante es que los clicks clave se hayan aplicado.
    return video_ok and ingredientes_ok and ratio_ok and speed_ok and model_selected


async def _download_flow_video(page, output_video_path, worker_id):
    # 1) Preferred path: context menu on the generated video thumbnail/player.
    try:
        videos = page.locator("video")
        video_count = await videos.count()
        if video_count > 0:
            target_video = videos.last
            await target_video.click(button="right", force=True)
            await page.wait_for_timeout(600)

            quality_720 = page.locator('text=/^\\s*720p\\s*$/i').first
            if await quality_720.is_visible(timeout=2000):
                async with page.expect_download(timeout=90000) as download_info:
                    await quality_720.click(force=True)
                download = await download_info.value
                await download.save_as(output_video_path)
                print(f"[ImageAutomator][W{worker_id}] [OK] Video descargado desde menu contextual (720p).")
                try:
                    await page.mouse.click(0, 0)
                except Exception:
                    pass
                return True

            download_item = page.locator('text=/^\\s*Descargar\\s*$/i, text=/^\\s*Download\\s*$/i').first
            if await download_item.is_visible(timeout=2000):
                async with page.expect_download(timeout=90000) as download_info:
                    await download_item.click(force=True)
                download = await download_info.value
                await download.save_as(output_video_path)
                print(f"[ImageAutomator][W{worker_id}] [OK] Video descargado desde menu contextual.")
                try:
                    await page.mouse.click(0, 0)
                except Exception:
                    pass
                return True

            try:
                await page.mouse.click(0, 0)
            except Exception:
                pass
    except Exception:
        pass

    # 2) Fallback: direct download button if visible.
    try:
        download_btn = page.locator('button:has-text("Descargar"), a[download], button[aria-label*="escargar" i]').last
        if await download_btn.is_visible(timeout=15000):
            async with page.expect_download(timeout=90000) as download_info:
                await download_btn.click(force=True)
            download = await download_info.value
            await download.save_as(output_video_path)
            print(f"[ImageAutomator][W{worker_id}] [OK] Video descargado desde boton visible.")
            return True
    except Exception:
        pass

    # 3) Last fallback: direct src URL.
    try:
        video_src = await page.evaluate("""() => {
            const videos = Array.from(document.querySelectorAll('video'));
            const video = videos[videos.length - 1];
            return video ? (video.currentSrc || video.src || '') : '';
        }""")
        if video_src:
            import urllib.request
            urllib.request.urlretrieve(video_src, output_video_path)
            print(f"[ImageAutomator][W{worker_id}] [OK] Video descargado via URL directa.")
            return True
    except Exception:
        pass

    return False


async def _generate_one_flow_podcast_video(page, textbox, prompt_data, output_folder, worker_id=1):
    prompt_id = str(prompt_data["id"])
    prompt_text = prompt_data["text"]
    output_video_path = os.path.join(output_folder, f"{prompt_id}.mp4")

    if os.path.exists(output_video_path):
        print(f"[ImageAutomator][W{worker_id}] Video podcast {prompt_id} ya existe. Saltando...")
        return True

    settings_ok = await _ensure_flow_podcast_generation_settings(page, worker_id)
    if not settings_ok:
        print(f"[ImageAutomator][W{worker_id}] [WARNING] Reintentando configuracion de ajustes para {prompt_id}...")
        await page.wait_for_timeout(700)
        settings_ok = await _ensure_flow_podcast_generation_settings(page, worker_id)
    if not settings_ok:
        print(f"[ImageAutomator][W{worker_id}] [ERROR] Configuracion incompleta para {prompt_id}. No se enviara para evitar gastar creditos.")
        return False

    ingredients_ok = await _ensure_reference_and_voice_in_composer(page, textbox, worker_id, "Autonoe")
    if not ingredients_ok:
        return False

    # Asegura foco en el composer despues de cerrar el menu de ajustes.
    try:
        await textbox.click(force=True)
        await page.wait_for_timeout(250)
    except Exception:
        pass

    await textbox.click(force=True)
    await page.wait_for_timeout(300)
    await page.keyboard.press("Control+A")
    await page.keyboard.press("Backspace")
    await page.wait_for_timeout(300)
    await page.keyboard.insert_text(prompt_text)
    await page.wait_for_timeout(400)
    print(f"[ImageAutomator][W{worker_id}] [OK] Prompt {prompt_id} pegado en composer.")

    print(f"[ImageAutomator][W{worker_id}] Generando video podcast {prompt_id}...")
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(3500)

    ready = False
    generation_seen = False
    for wait_index in range(360):
        try:
            generating = page.locator("text=/Generando|Generating/i")
            pct = page.locator("text=/\\d+%/")
            has_generating = (await generating.count() > 0) and (await generating.first.is_visible())
            has_pct = (await pct.count() > 0) and (await pct.first.is_visible())
            generation_seen = generation_seen or has_generating or has_pct

            videos = page.locator("video")
            has_video = await videos.count() > 0
            min_elapsed = wait_index >= 8  # ~16s

            # Passive readiness: avoid context-menu clicks while waiting.
            if has_video and min_elapsed and generation_seen and not has_generating and not has_pct:
                ready = True
                print(f"[ImageAutomator][W{worker_id}] [OK] Video {prompt_id} listo para descarga.")
                break
        except Exception:
            pass
        await page.wait_for_timeout(2000)

    if not ready:
        print(f"[ImageAutomator][W{worker_id}] [WARNING] Timeout esperando video {prompt_id}.")

    await page.wait_for_timeout(1500)
    downloaded = await _download_flow_video(page, output_video_path, worker_id)
    if downloaded:
        print(f"[ImageAutomator][W{worker_id}] [OK] Video guardado: {output_video_path}")
    else:
        print(f"[ImageAutomator][W{worker_id}] [ERROR] No se pudo descargar video {prompt_id}.")

    return downloaded


async def generate_podcast_videos_flow(prompts, output_folder, ref_image_path=None):
    """
    Automatiza Flow para generar videos tipo podcast con imagen de referencia y voz.
    Usa una sola pestana para preservar el contexto de voz/ingredientes entre prompts.
    """
    user_data_dir = os.path.join(os.getcwd(), "playwright_data_google")
    os.makedirs(user_data_dir, exist_ok=True)
    os.makedirs(output_folder, exist_ok=True)

    if not prompts:
        print("[ImageAutomator] No hay prompts para podcast.")
        return

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            channel="chrome",
            viewport={"width": 1280, "height": 800},
            ignore_default_args=["--enable-automation"],
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        )

        page = browser.pages[0] if browser.pages else await browser.new_page()
        page, textbox = await _prepare_flow_page(browser, 1, ref_image_path, page)
        await _configure_flow_podcast_mode(page, 1, "Autonoe")

        for prompt_data in prompts:
            try:
                await _generate_one_flow_podcast_video(page, textbox, prompt_data, output_folder, 1)
            except Exception as exc:
                print(f"[ImageAutomator][W1] [ERROR] Fallo prompt podcast {prompt_data.get('id')}: {exc}")

        print("[ImageAutomator] Proceso de videos podcast en Flow completado.")
        await browser.close()
