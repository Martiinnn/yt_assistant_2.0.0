document.addEventListener('DOMContentLoaded', () => {
    const parseBtn = document.getElementById('parse-btn');
    const scriptInput = document.getElementById('script-input');
    const resultsPanel = document.getElementById('results-panel');
    const promptsList = document.getElementById('prompts-list');
    const phrasesList = document.getElementById('phrases-list');
    const copyNextBtn = document.getElementById('copy-next-btn');
    const generateAllBtn = document.getElementById('generate-all-btn');
    const generateFishBtn = document.getElementById('generate-fish-btn');
    const downloadZipBtn = document.getElementById('download-zip-btn');
    const generateAllParallelBtn = document.getElementById('generate-all-parallel-btn');
    const savedScriptStatus = document.getElementById('saved-script-status');
    const clearOutputsBtn = document.getElementById('clear-outputs-btn');
    const resetMediaBtn = document.getElementById('reset-media-btn');
    const savedScriptsSelect = document.getElementById('saved-scripts-select');
    const restoreScriptBtn = document.getElementById('restore-script-btn');
    const checkMissingImagesBtn = document.getElementById('check-missing-images-btn');
    const missingImagesStatus = document.getElementById('missing-images-status');
    const podcastScriptInput = document.getElementById('podcast-script-input');
    const parsePodcastBtn = document.getElementById('parse-podcast-btn');
    const generatePodcastFlowBtn = document.getElementById('generate-podcast-flow-btn');
    const podcastRefImageInput = document.getElementById('podcast-ref-image');
    const podcastPromptsList = document.getElementById('podcast-prompts-list');
    const podcastStatus = document.getElementById('podcast-status');
    const testVoiceBtn = document.getElementById('test-voice-btn');
    const testVoiceAudio = document.getElementById('test-voice-audio');
    const supertonicStatusBadge = document.getElementById('supertonic-status-badge');

    let currentData = null;
    let podcastData = { prompts: [] };
    let nextPromptIndex = 0;

    // ─── Supertonic voice settings helper ───
    function getVoiceSettings() {
        return {
            voice: document.getElementById('supertonic-voice')?.value || 'M1',
            lang: document.getElementById('supertonic-lang')?.value || 'es',
            speed: parseFloat(document.getElementById('supertonic-speed')?.value || '1.05'),
            steps: parseInt(document.getElementById('supertonic-steps')?.value || '8', 10),
        };
    }

    // ─── Supertonic server status ───
    async function checkSupertonicStatus() {
        if (!supertonicStatusBadge) return;
        try {
            const r = await fetch('/supertonic-status');
            const data = await r.json();
            if (data.online) {
                supertonicStatusBadge.textContent = '🟢 Conectado';
                supertonicStatusBadge.className = 'status-badge online';
                supertonicStatusBadge.title = 'Servidor Supertonic activo';
            } else {
                supertonicStatusBadge.textContent = '🔴 Offline';
                supertonicStatusBadge.className = 'status-badge offline';
                supertonicStatusBadge.title = 'Ejecuta: supertonic serve --port 7788';
            }
        } catch {
            supertonicStatusBadge.textContent = '🔴 Offline';
            supertonicStatusBadge.className = 'status-badge offline';
            supertonicStatusBadge.title = 'No se pudo verificar el estado';
        }
    }

    // ─── Load custom voices from server ───
    async function loadSupertonicVoices() {
        try {
            const r = await fetch('/supertonic-voices');
            const data = await r.json();
            const select = document.getElementById('supertonic-voice');
            if (!select || !data.voices) return;

            // Only add custom voices that aren't already in the dropdown
            const existingValues = new Set(Array.from(select.options).map(o => o.value));
            const builtins = new Set(['M1','M2','M3','M4','M5','F1','F2','F3','F4','F5']);

            if (Array.isArray(data.voices)) {
                data.voices.forEach(v => {
                    const name = typeof v === 'string' ? v : v.name || v;
                    if (!existingValues.has(name) && !builtins.has(name)) {
                        const opt = new Option(`${name} (Custom)`, name);
                        select.appendChild(opt);
                    }
                });
            }
        } catch {
            // Voices endpoint may not be available if server is offline
        }
    }

    function appendWorkerSettings(formData) {
        const flowWorkers = document.getElementById('flow-workers')?.value || '3';
        const grokWorkers = document.getElementById('grok-workers')?.value || '2';
        const flowImageRatio = document.getElementById('flow-image-ratio')?.value || 'keep';
        formData.append('flow_workers', flowWorkers);
        formData.append('grok_workers', grokWorkers);
        formData.append('flow_image_ratio', flowImageRatio);
    }

    function appendVoiceSettings(formData) {
        const vs = getVoiceSettings();
        formData.append('voice', vs.voice);
        formData.append('lang', vs.lang);
        formData.append('speed', vs.speed);
        formData.append('steps', vs.steps);
        formData.append('audio_engine', 'supertonic');
    }

    function applyScriptData(data) {
        currentData = {
            prompts: data.prompts || [],
            phrases: data.phrases || []
        };

        scriptInput.value = data.script || '';
        renderPrompts(currentData.prompts);
        renderPhrases(currentData.phrases);
        if (savedScriptStatus && data.saved_script) {
            savedScriptStatus.textContent = data.saved_script;
        }
        resultsPanel.style.display = 'grid';
        nextPromptIndex = 0;
        copyNextBtn.disabled = currentData.prompts.length === 0;
        generateAllBtn.disabled = currentData.phrases.length === 0;
        if (generateFishBtn) generateFishBtn.disabled = currentData.phrases.length === 0;
        downloadZipBtn.disabled = true;
        copyNextBtn.textContent = currentData.prompts.length ? `Copiar Prompt ${currentData.prompts[0].id}` : 'Copiar siguiente';
        if (checkMissingImagesBtn) checkMissingImagesBtn.disabled = currentData.prompts.length === 0;
        if (missingImagesStatus) missingImagesStatus.style.display = 'none';
    }

    async function loadSavedScripts() {
        if (!savedScriptsSelect) return;

        try {
            const response = await fetch('/saved-scripts');
            const data = await response.json();
            if (data.error) throw new Error(data.error);

            const scripts = data.scripts || [];
            savedScriptsSelect.innerHTML = '';

            if (!scripts.length) {
                savedScriptsSelect.innerHTML = '<option value="">No hay guiones guardados</option>';
                if (restoreScriptBtn) restoreScriptBtn.disabled = true;
                return;
            }

            savedScriptsSelect.appendChild(new Option('Elegir guion guardado...', ''));
            scripts.forEach((script) => {
                const counts = script.counts || {};
                const cleanLabel = (script.label || script.filename)
                    .replace(/^frase_1_/, 'Frase 1: ')
                    .replace(/_\d{8}_\d{6}$/, '');
                const label = `${cleanLabel} - ${counts.prompts || 0} prompts / ${counts.phrases || 0} frases`;
                savedScriptsSelect.appendChild(new Option(label, script.filename));
            });

            if (restoreScriptBtn) restoreScriptBtn.disabled = true;
        } catch (err) {
            savedScriptsSelect.innerHTML = '<option value="">No se pudieron cargar guiones</option>';
            if (restoreScriptBtn) restoreScriptBtn.disabled = true;
        }
    }

    parseBtn.addEventListener('click', async () => {
        const script = scriptInput.value.trim();
        if (!script) return alert('Por favor pega un guion primero');

        try {
            const response = await fetch('/parse', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ script })
            });
            const data = await response.json();

            if (data.error) throw new Error(data.error);

            applyScriptData(data);
            loadSavedScripts();

            // Scroll to results
            resultsPanel.scrollIntoView({ behavior: 'smooth' });
        } catch (err) {
            alert('Error: ' + err.message);
        }
    });

    function renderPrompts(prompts) {
        promptsList.innerHTML = '';
        prompts.forEach((p, index) => {
            const div = document.createElement('div');
            div.className = 'item-card prompt-card';
            div.id = `prompt-card-${index}`;
            div.innerHTML = `
                <div class="item-header">
                    <span class="badge">Prompt ${p.id}</span>
                    <button class="btn secondary" onclick="copyPrompt(${index})">Copiar</button>
                </div>
                <div class="item-text">${p.text}</div>
            `;
            promptsList.appendChild(div);
        });
    }

    function renderPhrases(phrases) {
        phrasesList.innerHTML = '';
        phrases.forEach((p, index) => {
            const div = document.createElement('div');
            div.className = 'item-card phrase-card';
            div.id = `phrase-card-${p.id}`;
            div.innerHTML = `
                <div class="item-header">
                    <span class="badge">Frase ${p.id}</span>
                    <span id="phrase-status-${p.id}" class="status-text">Pendiente</span>
                </div>
                <div class="item-text">${p.text}</div>
                <audio id="audio-${p.id}" controls style="display: none; width: 100%; margin-top: 10px;"></audio>
            `;
            phrasesList.appendChild(div);
        });
    }

    function renderPodcastPrompts(prompts) {
        if (!podcastPromptsList) return;
        podcastPromptsList.innerHTML = '';
        prompts.forEach((p) => {
            const div = document.createElement('div');
            div.className = 'item-card';
            div.innerHTML = `
                <div class="item-header">
                    <span class="badge">Parte ${p.id}</span>
                </div>
                <div class="item-text">${p.text}</div>
            `;
            podcastPromptsList.appendChild(div);
        });
    }

    window.copyPrompt = async (index) => {
        if (!currentData || !currentData.prompts[index]) return;

        try {
            await navigator.clipboard.writeText(currentData.prompts[index].text);

            // Highlight card
            document.querySelectorAll('.prompt-card').forEach(c => c.classList.remove('copied'));
            const card = document.getElementById(`prompt-card-${index}`);
            card.classList.add('copied');

            document.getElementById('copy-status').textContent = `Prompt ${currentData.prompts[index].id} copiado!`;
            setTimeout(() => document.getElementById('copy-status').textContent = '', 2000);

            nextPromptIndex = index + 1;
            if (nextPromptIndex >= currentData.prompts.length) {
                copyNextBtn.textContent = 'Todos copiados!';
                copyNextBtn.disabled = true;
            } else {
                copyNextBtn.textContent = `Copiar Prompt ${currentData.prompts[nextPromptIndex].id}`;
            }
        } catch (err) {
            console.error('Failed to copy', err);
        }
    };

    copyNextBtn.addEventListener('click', () => {
        if (nextPromptIndex < currentData.prompts.length) {
            copyPrompt(nextPromptIndex);
        }
    });

    if (savedScriptsSelect && restoreScriptBtn) {
        savedScriptsSelect.addEventListener('change', () => {
            restoreScriptBtn.disabled = !savedScriptsSelect.value;
        });

        restoreScriptBtn.addEventListener('click', async () => {
            const filename = savedScriptsSelect.value;
            if (!filename) return;

            restoreScriptBtn.disabled = true;
            try {
                const response = await fetch(`/saved-scripts/${encodeURIComponent(filename)}`);
                const data = await response.json();
                if (data.error) throw new Error(data.error);
                applyScriptData(data);
                resultsPanel.scrollIntoView({ behavior: 'smooth' });
            } catch (err) {
                alert('Error restaurando guion: ' + err.message);
            } finally {
                restoreScriptBtn.disabled = !savedScriptsSelect.value;
            }
        });
    }

    if (checkMissingImagesBtn) {
        checkMissingImagesBtn.addEventListener('click', async () => {
            if (!currentData || !currentData.prompts.length) return;

            checkMissingImagesBtn.disabled = true;
            try {
                const response = await fetch('/check-missing-images', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompts: currentData.prompts })
                });

                const data = await response.json();
                if (data.error) throw new Error(data.error);

                if (missingImagesStatus) {
                    missingImagesStatus.style.display = 'block';

                    if (!data.missing_ids.length) {
                        const extraText = data.extra_ids.length ? ` Extras detectados: ${data.extra_ids.join(', ')}.` : '';
                        missingImagesStatus.textContent = `No faltan imágenes. Encontradas ${data.existing_count} de ${data.expected_count}.${extraText}`;
                    } else {
                        const extraText = data.extra_ids.length ? ` Extras: ${data.extra_ids.join(', ')}.` : '';
                        missingImagesStatus.textContent = `Faltan ${data.missing_ids.length} imágenes: ${data.missing_ids.join(', ')}.${extraText}`;
                    }
                }
            } catch (err) {
                if (missingImagesStatus) {
                    missingImagesStatus.style.display = 'block';
                    missingImagesStatus.textContent = 'No se pudo revisar la carpeta de imágenes: ' + err.message;
                }
            } finally {
                checkMissingImagesBtn.disabled = false;
            }
        });
    }

    // ─── Test voice ───
    if (testVoiceBtn) {
        testVoiceBtn.addEventListener('click', async () => {
            const vs = getVoiceSettings();
            testVoiceBtn.disabled = true;
            testVoiceBtn.textContent = '⏳ Generando...';

            try {
                const response = await fetch('/generate-audio', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        text: 'Esta es una prueba de voz con Supertonic.',
                        id: '_test_voice',
                        engine: 'supertonic',
                        ...vs,
                    })
                });
                const data = await response.json();
                if (data.error) throw new Error(data.error);

                if (testVoiceAudio) {
                    testVoiceAudio.src = `/outputs/_test_voice.wav?t=${Date.now()}`;
                    testVoiceAudio.style.display = 'block';
                    testVoiceAudio.play();
                }
            } catch (err) {
                alert('Error probando voz: ' + err.message);
            } finally {
                testVoiceBtn.disabled = false;
                testVoiceBtn.textContent = '🔊 Probar voz';
            }
        });
    }

    if (testVoiceAudio) {
        testVoiceAudio.addEventListener('ended', async () => {
            try {
                // Ocultar y limpiar source para liberar el archivo
                testVoiceAudio.style.display = 'none';
                testVoiceAudio.src = '';
                
                await fetch('/delete-test-audio', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: '_test_voice' })
                });
            } catch (err) {
                console.error('Error borrando audio de prueba:', err);
            }
        });
    }

    // ─── Generate audios (Supertonic) ───
    generateAllBtn.addEventListener('click', async () => {
        if (!currentData || !currentData.phrases.length) return;

        generateAllBtn.disabled = true;
        const vs = getVoiceSettings();

        currentData.phrases.forEach(phrase => {
            const card = document.getElementById(`phrase-card-${phrase.id}`);
            const statusLabel = document.getElementById(`phrase-status-${phrase.id}`);
            card.classList.add('generating');
            statusLabel.textContent = 'En cola (Supertonic)...';
        });

        try {
            const response = await fetch('/generate-batch-supertonic', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    phrases: currentData.phrases,
                    ...vs,
                })
            });

            const data = await response.json();
            if (data.error) throw new Error(data.error);

            // Update UI for each phrase based on results
            if (data.results) {
                data.results.forEach(result => {
                    const card = document.getElementById(`phrase-card-${result.id}`);
                    const statusLabel = document.getElementById(`phrase-status-${result.id}`);
                    if (!card) return;

                    card.classList.remove('generating');
                    if (result.success) {
                        card.classList.add('done');
                        statusLabel.textContent = result.skipped ? '⏭️ Ya existía' : '✅ Listo';
                        const audioPlayer = document.getElementById(`audio-${result.id}`);
                        if (audioPlayer) {
                            audioPlayer.src = `/outputs/${result.id}.wav?t=${Date.now()}`;
                            audioPlayer.style.display = 'block';
                        }
                    } else {
                        statusLabel.textContent = `❌ Error: ${result.error || 'desconocido'}`;
                    }
                });
            } else {
                // Fallback: mark all as done
                currentData.phrases.forEach(phrase => {
                    const card = document.getElementById(`phrase-card-${phrase.id}`);
                    const statusLabel = document.getElementById(`phrase-status-${phrase.id}`);
                    card.classList.remove('generating');
                    card.classList.add('done');
                    statusLabel.textContent = '✅ Listo';
                    const audioPlayer = document.getElementById(`audio-${phrase.id}`);
                    if (audioPlayer) {
                        audioPlayer.src = `/outputs/${phrase.id}.wav?t=${Date.now()}`;
                        audioPlayer.style.display = 'block';
                    }
                });
            }
        } catch (err) {
            currentData.phrases.forEach(phrase => {
                const card = document.getElementById(`phrase-card-${phrase.id}`);
                card.classList.remove('generating');
            });
            alert('Error generando audios con Supertonic: ' + err.message);
        }

        generateAllBtn.disabled = false;
        downloadZipBtn.disabled = false;
        generateAllBtn.textContent = 'Regenerar audios (Supertonic)';
    });

    // ─── Generate audios (Fish Audio backup) ───
    if (generateFishBtn) {
        generateFishBtn.addEventListener('click', async () => {
            if (!currentData || !currentData.phrases.length) return;

            generateFishBtn.disabled = true;
            alert('Iniciando Robot Fish.audio (backup). Se abrirá una ventana del navegador si hace falta iniciar sesión.');

            currentData.phrases.forEach(phrase => {
                const card = document.getElementById(`phrase-card-${phrase.id}`);
                const statusLabel = document.getElementById(`phrase-status-${phrase.id}`);
                card.classList.add('generating');
                statusLabel.textContent = 'En cola (Fish)...';
            });

            try {
                const response = await fetch('/generate-batch-fish', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        phrases: currentData.phrases,
                        engine: 'fish'
                    })
                });

                const data = await response.json();
                if (data.error) throw new Error(data.error);

                currentData.phrases.forEach(phrase => {
                    const card = document.getElementById(`phrase-card-${phrase.id}`);
                    const statusLabel = document.getElementById(`phrase-status-${phrase.id}`);
                    card.classList.remove('generating');
                    card.classList.add('done');
                    statusLabel.textContent = '✅ Listo';

                    const audioPlayer = document.getElementById(`audio-${phrase.id}`);
                    audioPlayer.src = `/outputs/${phrase.id}.mp3?t=${Date.now()}`;
                    audioPlayer.style.display = 'block';
                });
            } catch (err) {
                currentData.phrases.forEach(phrase => {
                    const card = document.getElementById(`phrase-card-${phrase.id}`);
                    card.classList.remove('generating');
                });
                alert('Error en el robot Fish: ' + err.message);
            }

            generateFishBtn.disabled = false;
            downloadZipBtn.disabled = false;
        });
    }

    // IMAGE AUTOMATION
    const generateImagesBtn = document.getElementById('generate-images-btn');
    if (generateImagesBtn) {
        generateImagesBtn.addEventListener('click', async () => {
            if (!currentData || !currentData.prompts.length) return;

            generateImagesBtn.disabled = true;
            const refImageInput = document.getElementById('ref-image');

            alert("¡Iniciando Robot de Imágenes (Google Flow)! Se abrirá una ventana de navegador. Si no estás logueado en Google, tendrás 5 minutos para hacerlo.");

            // Marcar todos como generando
            currentData.prompts.forEach((prompt, index) => {
                const card = document.getElementById(`prompt-card-${index}`);
                if (card) card.style.opacity = '0.5';
            });

            try {
                const formData = new FormData();
                formData.append('prompts', JSON.stringify(currentData.prompts));
                appendWorkerSettings(formData);
                if (refImageInput.files.length > 0) {
                    formData.append('ref_image', refImageInput.files[0]);
                }

                const response = await fetch('/generate-batch-images', {
                    method: 'POST',
                    body: formData // No setear Content-Type, fetch lo hace automático con FormData
                });

                const data = await response.json();

                if (data.error) throw new Error(data.error);

                // Marcar todos como listos
                currentData.prompts.forEach((prompt, index) => {
                    const card = document.getElementById(`prompt-card-${index}`);
                    if (card) {
                        card.style.opacity = '1';
                        card.style.borderLeft = '4px solid #10b981';
                    }
                });

                alert("¡Imágenes generadas y guardadas en outputs/ con éxito!");

            } catch (err) {
                currentData.prompts.forEach((prompt, index) => {
                    const card = document.getElementById(`prompt-card-${index}`);
                    if (card) card.style.opacity = '1';
                });
                alert('Error en el robot de imágenes: ' + err.message);
            }

            generateImagesBtn.disabled = false;
        });
    }

    if (parsePodcastBtn) {
        parsePodcastBtn.addEventListener('click', async () => {
            const script = podcastScriptInput?.value?.trim() || '';
            if (!script) return alert('Pega el guion de podcast primero.');

            parsePodcastBtn.disabled = true;
            if (podcastStatus) podcastStatus.textContent = 'Procesando partes de podcast...';
            try {
                const response = await fetch('/parse-podcast', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ script })
                });
                const data = await response.json();
                if (data.error) throw new Error(data.error);

                podcastData = { prompts: data.prompts || [] };
                renderPodcastPrompts(podcastData.prompts);
                if (generatePodcastFlowBtn) generatePodcastFlowBtn.disabled = podcastData.prompts.length === 0;
                if (podcastStatus) podcastStatus.textContent = `${podcastData.prompts.length} partes listas para generar.`;
            } catch (err) {
                if (podcastStatus) podcastStatus.textContent = '';
                alert('Error parseando podcast: ' + err.message);
            } finally {
                parsePodcastBtn.disabled = false;
            }
        });
    }

    if (generatePodcastFlowBtn) {
        generatePodcastFlowBtn.addEventListener('click', async () => {
            if (!podcastData || !podcastData.prompts.length) return;

            generatePodcastFlowBtn.disabled = true;
            if (podcastStatus) podcastStatus.textContent = 'Generando podcast en Flow con 1 sola ventana...';

            try {
                const formData = new FormData();
                formData.append('prompts', JSON.stringify(podcastData.prompts));
                if (podcastRefImageInput && podcastRefImageInput.files.length > 0) {
                    formData.append('ref_image', podcastRefImageInput.files[0]);
                }

                const response = await fetch('/generate-flow-podcast', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();
                if (data.error) throw new Error(data.error);

                if (podcastStatus) podcastStatus.textContent = 'Podcast completado. Videos en flow_podcast_outputs/.';
                alert('Podcast generado con exito en flow_podcast_outputs/.');
            } catch (err) {
                if (podcastStatus) podcastStatus.textContent = '';
                alert('Error en podcast Flow: ' + err.message);
            } finally {
                generatePodcastFlowBtn.disabled = false;
            }
        });
    }

    downloadZipBtn.addEventListener('click', () => {
        window.location.href = '/download-zip';
    });

    async function runCleanup(button, endpoint, confirmMessage, successMessage) {
        if (!confirm(confirmMessage)) return;

        button.disabled = true;
        try {
            const response = await fetch(endpoint, { method: 'POST' });
            const data = await response.json();
            if (data.error) throw new Error(data.error);
            alert(successMessage);
        } catch (err) {
            alert('Error limpiando archivos: ' + err.message);
        } finally {
            button.disabled = false;
        }
    }

    if (clearOutputsBtn) {
        clearOutputsBtn.addEventListener('click', () => {
            runCleanup(
                clearOutputsBtn,
                '/clear-outputs',
                'Esto borrara todos los archivos de outputs/. ¿Continuar?',
                'Outputs borrados correctamente.'
            );
        });
    }

    if (resetMediaBtn) {
        resetMediaBtn.addEventListener('click', () => {
            runCleanup(
                resetMediaBtn,
                '/reset-media',
                'Esto borrara todas las imagenes y videos generados. ¿Continuar?',
                'Imagenes y videos reiniciados correctamente.'
            );
        });
    }

    if (generateAllParallelBtn) {
        generateAllParallelBtn.addEventListener('click', async () => {
            if (!currentData || !currentData.prompts.length || !currentData.phrases.length) return;

            generateAllParallelBtn.disabled = true;
            const refImageInput = document.getElementById('ref-image');

            alert("¡Iniciando robots EN PARALELO!\n\nSe abrirán varias pestañas de Flow y Grok + Supertonic generará audios en local. ¡No toques el teclado ni el ratón mientras operan!");

            currentData.prompts.forEach((p, i) => { const c = document.getElementById(`prompt-card-${i}`); if (c) c.style.opacity = '0.5'; });
            currentData.phrases.forEach(p => {
                const c = document.getElementById(`phrase-card-${p.id}`);
                if (c) c.classList.add('generating');
                const statusLabel = document.getElementById(`phrase-status-${p.id}`);
                if (statusLabel) statusLabel.textContent = 'En cola (Paralelo)...';
            });

            try {
                const formData = new FormData();
                formData.append('prompts', JSON.stringify(currentData.prompts));
                formData.append('phrases', JSON.stringify(currentData.phrases));
                appendWorkerSettings(formData);
                appendVoiceSettings(formData);
                if (refImageInput && refImageInput.files.length > 0) {
                    formData.append('ref_image', refImageInput.files[0]);
                }

                const response = await fetch('/generate-all', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();
                if (data.error) throw new Error(data.error);

                alert("¡Producción en paralelo completada exitosamente!");

                currentData.prompts.forEach((p, i) => { const c = document.getElementById(`prompt-card-${i}`); if (c) { c.style.opacity = '1'; c.style.borderLeft = '4px solid #10b981'; } });
                currentData.phrases.forEach(phrase => {
                    const c = document.getElementById(`phrase-card-${phrase.id}`);
                    if (c) { c.classList.remove('generating'); c.classList.add('done'); }
                    const statusLabel = document.getElementById(`phrase-status-${phrase.id}`);
                    if (statusLabel) statusLabel.textContent = '✅ Listo';
                    const audio = document.getElementById(`audio-${phrase.id}`);
                    if (audio) {
                        audio.src = `/outputs/${phrase.id}.wav?t=${Date.now()}`;
                        audio.style.display = 'block';
                    }
                });

            } catch (err) {
                alert('Error en ejecución paralela: ' + err.message);
            }
            generateAllParallelBtn.disabled = false;
        });
    }

    const generateGrokBtn = document.getElementById('generate-grok-btn');
    if (generateGrokBtn) {
        generateGrokBtn.addEventListener('click', async () => {
            if (!currentData || !currentData.prompts.length) return;
            generateGrokBtn.disabled = true;

            // Convertir prompts a un diccionario id -> text para Grok
            const promptsDict = {};
            currentData.prompts.forEach(p => promptsDict[p.id] = p.text);

            alert("¡Iniciando Robot de Grok!\n\nRecuerda: Deberás tener la sesión iniciada en Grok. Si no es así, tendrás 5 minutos para loguearte.");

            try {
                const formData = new FormData();
                formData.append('prompts', JSON.stringify(promptsDict));
                appendWorkerSettings(formData);

                const response = await fetch('/generate-grok', {
                    method: 'POST',
                    body: formData
                });

                const data = await response.json();
                if (data.error) throw new Error(data.error);
                alert("¡Videos animados y guardados con éxito en la carpeta image_outputs_animated!");
            } catch (e) {
                alert("Error en Grok: " + e.message);
            }
            generateGrokBtn.disabled = false;
        });
    }

    // ─── Init ───
    loadSavedScripts();
    checkSupertonicStatus();
    loadSupertonicVoices();
});
