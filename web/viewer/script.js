// script.js
document.addEventListener('DOMContentLoaded', () => {
    const gallery = document.getElementById('imageGallery');
    const loadingMessage = document.getElementById('loadingMessage');
    const errorMessageElement = document.getElementById('errorMessage');
    const noImagesMessage = document.getElementById('noImagesMessage');
    const lastSyncTimeEl = document.getElementById('lastSyncTime');
    const deleteQueueCountEl = document.getElementById('deleteQueueCount');
    const currentYearEl = document.getElementById('currentYear');

    const refreshDataBtn = document.getElementById('refreshDataBtn');
    const settingsBtn = document.getElementById('settingsBtn');

    // Controls
    const sortBySelect = document.getElementById('sortBy');
    const sortOrderSelect = document.getElementById('sortOrder');
    const scoreThresholdRange = document.getElementById('scoreThreshold');
    const scoreThresholdValueEl = document.getElementById('scoreThresholdValue');
    const showLowScoreToggle = document.getElementById('showLowScoreToggle');
    const galleryColumnsInput = document.getElementById('galleryColumns');

    // Lightbox
    const lightboxModal = document.getElementById('lightboxModal');
    const lightboxImage = document.getElementById('lightboxImage');
    const lightboxCaption = document.getElementById('lightboxCaption');
    const lightboxCloseBtn = document.querySelector('.lightbox-close-btn');

    let allImagesData = {};
    let currentDeleteQueue = [];
    let uiSettings = {
        sortBy: 'score_final',
        sortOrder: 'desc',
        scoreThreshold: 0,
        showLowScore: true,
        galleryColumns: 4,
        soundEffects: true,
        vibration: true
    };

    const SCORES_JSON_URL = './scores.json';
    const DELETE_REQUESTS_JSON_URL = './delete_requests.json';
    const UPDATE_DELETE_REQUESTS_API_URL = './api/updateDeleteRequests.php';
    const DELETE_IMAGE_API_URL = './api/delete_image';

    function initializeApp() {
        if (currentYearEl) currentYearEl.textContent = new Date().getFullYear();
        loadSettings();
        updateGalleryColumnsCssVar(); // CSS変数を初期設定
        fetchData(true);

        refreshDataBtn.addEventListener('click', () => fetchData(false));
        sortBySelect.addEventListener('change', handleSortFilterChange);
        sortOrderSelect.addEventListener('change', handleSortFilterChange);
        scoreThresholdRange.addEventListener('input', handleScoreThresholdInput);
        scoreThresholdRange.addEventListener('change', handleSortFilterChange); // 最終値でフィルタ
        showLowScoreToggle.addEventListener('change', handleSortFilterChange);
        galleryColumnsInput.addEventListener('input', handleGalleryColumnsInput);
        galleryColumnsInput.addEventListener('change', handleGalleryColumnsChangeFinal); // 最終値で保存とCSS更新

        if (lightboxModal && lightboxCloseBtn && lightboxImage) {
            lightboxCloseBtn.addEventListener('click', closeLightbox);
            lightboxModal.addEventListener('click', (e) => {
                if (e.target === lightboxModal) closeLightbox();
            });
        }
        settingsBtn.addEventListener('click', openSimpleSettings);
        
        adjustControlsBarTop();
        window.addEventListener('resize', adjustControlsBarTop);
        // 初期ロード時にも実行
        setTimeout(adjustControlsBarTop, 100); // DOMレンダリング後に実行
    }
    
    function adjustControlsBarTop() {
        const header = document.querySelector('header');
        const controlsBar = document.querySelector('.controls-bar');
        if (header && controlsBar) {
            controlsBar.style.top = `${header.offsetHeight}px`;
        }
    }

    function loadSettings() {
        const savedSettings = localStorage.getItem('plainImageViewerSettings');
        if (savedSettings) {
            try {
                uiSettings = { ...uiSettings, ...JSON.parse(savedSettings) };
            } catch(e) {
                console.error("設定の読み込みに失敗:", e);
                localStorage.removeItem('plainImageViewerSettings');
            }
        }
        sortBySelect.value = uiSettings.sortBy;
        sortOrderSelect.value = uiSettings.sortOrder;
        scoreThresholdRange.value = uiSettings.scoreThreshold;
        scoreThresholdValueEl.textContent = uiSettings.scoreThreshold.toFixed(1);
        showLowScoreToggle.checked = uiSettings.showLowScore;
        galleryColumnsInput.value = uiSettings.galleryColumns;
        scoreThresholdRange.disabled = uiSettings.showLowScore;
    }

    function saveSettings() {
        localStorage.setItem('plainImageViewerSettings', JSON.stringify(uiSettings));
    }
    
    function handleSortFilterChange() {
        uiSettings.sortBy = sortBySelect.value;
        uiSettings.sortOrder = sortOrderSelect.value;
        uiSettings.showLowScore = showLowScoreToggle.checked;
        uiSettings.scoreThreshold = parseFloat(scoreThresholdRange.value);
        scoreThresholdValueEl.textContent = uiSettings.scoreThreshold.toFixed(1);
        scoreThresholdRange.disabled = uiSettings.showLowScore;
        saveSettings();
        renderGallery();
    }

    function handleScoreThresholdInput() { // inputイベント用
        scoreThresholdValueEl.textContent = parseFloat(scoreThresholdRange.value).toFixed(1);
    }
    
    function handleGalleryColumnsInput() { // inputイベント用
        const newCols = parseInt(galleryColumnsInput.value);
        if (newCols >= 1 && newCols <= 12) {
            document.documentElement.style.setProperty('--gallery-columns', newCols);
        }
    }
    function handleGalleryColumnsChangeFinal() { // changeイベント用
        const newCols = parseInt(galleryColumnsInput.value);
        if (newCols >= 1 && newCols <= 12) {
            uiSettings.galleryColumns = newCols;
            saveSettings();
            updateGalleryColumnsCssVar(); // CSS変数を最終値で更新
        } else {
            galleryColumnsInput.value = uiSettings.galleryColumns; // 無効な値なら元に戻す
        }
    }

    function updateGalleryColumnsCssVar() {
        let cols = parseInt(uiSettings.galleryColumns);
        if (window.innerWidth <= 768 && window.innerWidth > 480) { // タブレットサイズ
            cols = Math.min(cols, 3); // 最大3列
        } else if (window.innerWidth <= 480) { // モバイルサイズ
            cols = Math.min(cols, 2); // 最大2列
        }
        document.documentElement.style.setProperty('--gallery-columns', cols);
    }
    window.addEventListener('resize', updateGalleryColumnsCssVar); // リサイズ時にも列数を調整


    async function fetchData(isInitialLoad = false) {
        if (isInitialLoad) {
            loadingMessage.style.display = 'block';
            errorMessageElement.style.display = 'none';
            noImagesMessage.style.display = 'none';
            gallery.innerHTML = '';
        }
        try {
            const timestamp = new Date().getTime();
            const scoresRes = await fetch(`${SCORES_JSON_URL}?t=${timestamp}`);
            if (!scoresRes.ok) throw new Error(`スコアファイル取得エラー: ${scoresRes.status} ${scoresRes.statusText}`);
            allImagesData = await scoresRes.json() || {};

            try {
                const deleteRes = await fetch(`${DELETE_REQUESTS_JSON_URL}?t=${timestamp}`);
                if (deleteRes.ok) {
                    currentDeleteQueue = await deleteRes.json() || [];
                    if (!Array.isArray(currentDeleteQueue)) currentDeleteQueue = [];
                } else if (deleteRes.status === 404) { currentDeleteQueue = []; }
            } catch (e) { currentDeleteQueue = []; }
            
            const lastModified = scoresRes.headers.get('Last-Modified');
            lastSyncTimeEl.textContent = lastModified ? new Date(lastModified).toLocaleString('ja-JP') : new Date().toLocaleString('ja-JP');
            deleteQueueCountEl.textContent = currentDeleteQueue.length;
            renderGallery();
        } catch (error) {
            errorMessageElement.textContent = `エラー: ${error.message}`;
            errorMessageElement.style.display = 'block'; gallery.innerHTML = '';
        } finally {
            if (isInitialLoad) loadingMessage.style.display = 'none';
        }
    }

    function renderGallery() {
        gallery.innerHTML = '';
        let imagesToDisplay = Object.entries(allImagesData).map(([id, data]) => ({ id, ...data }));
        const deleteQueueIds = new Set(currentDeleteQueue.map(item => item.id));
        imagesToDisplay = imagesToDisplay.filter(img => !deleteQueueIds.has(img.id));

        if (!uiSettings.showLowScore) {
            imagesToDisplay = imagesToDisplay.filter(img => (img.score_final || 0) >= uiSettings.scoreThreshold);
        }
        imagesToDisplay = imagesToDisplay.filter(img => typeof img.score_final === 'number');

        imagesToDisplay.sort((a, b) => {
            let valA = a[uiSettings.sortBy]; let valB = b[uiSettings.sortBy];
            if (uiSettings.sortBy === 'score_final') { valA = valA || 0; valB = valB || 0; }
            else if (typeof valA === 'string' && typeof valB === 'string') { valA = valA.toLowerCase(); valB = valB.toLowerCase(); }
            else if (valA === undefined || valA === null) return uiSettings.sortOrder === 'asc' ? 1 : -1;
            else if (valB === undefined || valB === null) return uiSettings.sortOrder === 'asc' ? -1 : 1;
            if (valA < valB) return uiSettings.sortOrder === 'asc' ? -1 : 1;
            if (valA > valB) return uiSettings.sortOrder === 'asc' ? 1 : -1;
            return 0;
        });

        if (imagesToDisplay.length === 0) {
            noImagesMessage.style.display = 'block'; errorMessageElement.style.display = 'none'; loadingMessage.style.display = 'none'; return;
        } else { noImagesMessage.style.display = 'none'; }

        imagesToDisplay.forEach(imgData => {
            const item = document.createElement('div');
            item.className = 'gallery-item'; item.dataset.id = imgData.id;
            item.addEventListener('click', () => openLightbox(imgData));

            const imgElement = document.createElement('img');
            imgElement.src = imgData.thumbnail_web_path || `./cloude_image/thumbnails/${imgData.filename.replace(/\.[^/.]+$/, ".jpg")}`;
            imgElement.alt = imgData.filename; imgElement.loading = 'lazy';
            imgElement.onerror = function() {
                this.style.display = 'none';
                const errorPlaceholder = document.createElement('div');
                errorPlaceholder.className = 'image-error-placeholder';
                errorPlaceholder.innerHTML = `<svg viewBox="0 0 24 24"><path d="M21 19V5c0-1.1-.9-2-2-2H5c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h14c1.1 0 2-.9 2-2zM8.5 13.5l2.5 3.01L14.5 12l4.5 6H5l3.5-4.5z"/></svg><p>読込エラー</p><p class="filename-placeholder">${imgData.filename}</p>`;
                item.appendChild(errorPlaceholder);
            };
            item.appendChild(imgElement);

            const infoDiv = document.createElement('div'); infoDiv.className = 'item-info';
            infoDiv.innerHTML = `<p class="filename" title="${imgData.filename}">${imgData.filename}</p><p class="score">${imgData.score_final ? imgData.score_final.toFixed(2) : 'N/A'}</p>`;
            item.appendChild(infoDiv);

            const deleteBtn = document.createElement('button'); deleteBtn.className = 'delete-btn';
            deleteBtn.innerHTML = '🗑️'; deleteBtn.title = 'この画像を削除';
            deleteBtn.addEventListener('click', (e) => { e.stopPropagation(); deleteImage(imgData.id, imgData.filename, item); });
            item.appendChild(deleteBtn);
            gallery.appendChild(item);
        });
    }

    async function handleDeleteRequest(imageId, filename) {
        if (!confirm(`画像「${filename}」を削除リクエストに追加しますか？\nこの操作はサーバー上の delete_requests.json を更新します。`)) return;
        const newItem = { id: imageId, filename: filename };
        let updatedDeleteQueue = [...currentDeleteQueue];
        if (!updatedDeleteQueue.some(item => item.id === imageId)) updatedDeleteQueue.push(newItem);

        try {
            const response = await fetch(UPDATE_DELETE_REQUESTS_API_URL, {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(updatedDeleteQueue)
            });
            if (!response.ok) { let errBody = await response.text(); throw new Error(`サーバーエラー: ${response.status}. ${errBody}`);}
            const result = await response.json();
            if (result.success) {
                currentDeleteQueue = result.updatedQueue || updatedDeleteQueue;
                deleteQueueCountEl.textContent = currentDeleteQueue.length;
                if(uiSettings.soundEffects) playDeleteSound();
                if (uiSettings.vibration && navigator.vibrate) navigator.vibrate(100);
                renderGallery(); // UIを即時更新
            } else { throw new Error(result.message || "サーバー処理失敗。"); }
        } catch (error) { console.error('削除リクエストエラー:', error); alert(`削除リクエストエラー: ${error.message}`); }
    }

    async function deleteImage(imageId, filename, element) {
        if (!confirm(`画像「${filename}」を完全に削除しますか？`)) return;
        try {
            const response = await fetch(DELETE_IMAGE_API_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id: imageId })
            });
            if (!response.ok) throw new Error(`サーバーエラー: ${response.status} ${response.statusText}`);
            const result = await response.json();
            if (result.success) {
                delete allImagesData[imageId];
                element.classList.add('fade-out');
                element.addEventListener('transitionend', () => element.remove());
            } else {
                throw new Error(result.message || '削除に失敗しました');
            }
        } catch (err) {
            console.error('画像削除エラー:', err);
            alert(`画像削除エラー: ${err.message}`);
        }
    }
    
    function playDeleteSound() {
        try {
            const audioCtx = new (window.AudioContext || window.webkitAudioContext)(); if (!audioCtx) return;
            const osc = audioCtx.createOscillator(); const gain = audioCtx.createGain();
            osc.connect(gain); gain.connect(audioCtx.destination);
            osc.type = 'triangle'; osc.frequency.setValueAtTime(200, audioCtx.currentTime);
            gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.001, audioCtx.currentTime + 0.2);
            osc.start(); osc.stop(audioCtx.currentTime + 0.2);
        } catch(e) { console.warn("効果音再生失敗:", e); }
    }

    function openLightbox(imgData) {
        if (!imgData || !lightboxModal || !lightboxImage || !lightboxCaption) return;
        const imagePath = imgData.original_web_path || `./cloude_image/originals/${imgData.filename}`;
        lightboxImage.src = imagePath;
        lightboxImage.alt = `拡大画像: ${imgData.filename}`;
        lightboxImage.onerror = function() { this.onerror = null; this.src = `https://placehold.co/800x600/333333/cccccc?text=画像表示エラー%0A${encodeURIComponent(imgData.filename)}`; }
        lightboxCaption.textContent = `${imgData.filename} (Score: ${imgData.score_final ? imgData.score_final.toFixed(2) : 'N/A'})`;
        lightboxModal.style.display = 'flex'; document.body.style.overflow = 'hidden';
    }
    function closeLightbox() {
        if (!lightboxModal) return;
        lightboxModal.style.display = 'none'; document.body.style.overflow = 'auto';
    }

    function openSimpleSettings() {
        let newSoundSetting = prompt(`効果音を有効にしますか？ (現在の値: ${uiSettings.soundEffects})\n「true」または「false」で入力してください。`, uiSettings.soundEffects);
        if (newSoundSetting !== null) {
            uiSettings.soundEffects = newSoundSetting.trim().toLowerCase() === 'true';
        }

        let newVibeSetting = prompt(`バイブレーションを有効にしますか？ (現在の値: ${uiSettings.vibration})\n「true」または「false」で入力してください。`, uiSettings.vibration);
        if (newVibeSetting !== null) {
            uiSettings.vibration = newVibeSetting.trim().toLowerCase() === 'true';
        }
        saveSettings();
        alert("設定を保存しました。");
    }
    
    initializeApp();
});
