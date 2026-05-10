document.addEventListener('DOMContentLoaded', () => {
    const parseBtn = document.getElementById('parse-btn');
    const scriptInput = document.getElementById('script-input');
    const resultsPanel = document.getElementById('results-panel');
    const promptsList = document.getElementById('prompts-list');
    const phrasesList = document.getElementById('phrases-list');
    const copyNextBtn = document.getElementById('copy-next-btn');
    const generateAllBtn = document.getElementById('generate-all-btn');
    const downloadZipBtn = document.getElementById('download-zip-btn');
    const generateAllParallelBtn = document.getElementById('generate-all-parallel-btn');
    const savedScriptStatus = document.getElementById('saved-script-status');
    const clearOutputsBtn = document.getElementById('clear-outputs-btn');
    const resetMediaBtn = document.getElementById('reset-media-btn');
    const savedScriptsSelect = document.getElementById('saved-scripts-select');
    const restoreScriptBtn = document.getElementById('restore-script-btn');
    const checkMissingImagesBtn = document.getElementById('check-missing-images-btn');
    const missingImagesStatus = document.getElementById('missing-images-status');

    let currentData = null;
    let nextPromptIndex = 0;

    function appendWorkerSettings(formData) {
        const flowWorkers = document.getElementById('flow-workers')?.value || '3';
        const grokWorkers = document.getElementById('grok-workers')?.value || '2';
        formData.append('flow_workers', flowWorkers);
        formData.append('grok_workers', grokWorkers);
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

    generateAllBtn.addEventListener('click', async () => {
        if (!currentData || !currentData.phrases.length) return;

        generateAllBtn.disabled = true;

        alert('Iniciando Robot Fish.audio. Se abrirá una ventana del navegador si hace falta iniciar sesión.');

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
                audioPlayer.src = `/outputs/${phrase.id}.mp3?t=${new Date().getTime()}`;
                audioPlayer.style.display = 'block';
            });
        } catch (err) {
            currentData.phrases.forEach(phrase => {
                const card = document.getElementById(`phrase-card-${phrase.id}`);
                card.classList.remove('generating');
            });
            alert('Error en el robot Fish: ' + err.message);
        }

        generateAllBtn.disabled = false;
        downloadZipBtn.disabled = false;
        generateAllBtn.textContent = 'Regenerar audios';
    });

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

            alert("¡Iniciando robots EN PARALELO!\n\nSe abrirán varias pestañas de Flow y Grok según la configuración. ¡No toques el teclado ni el ratón mientras operan!");

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
                        audio.src = `/outputs/${phrase.id}.mp3?t=${new Date().getTime()}`;
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

    loadSavedScripts();
});
