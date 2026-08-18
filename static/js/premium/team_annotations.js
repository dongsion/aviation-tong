/**
 * 航空通 Pro - 团队共享标注
 * 团队成员在地图上标注、评论、共享视图
 */

let annotationLayer = null;
let annotations = [];

function openTeamAnnotations() {
    const modal = createModal('annotations-modal', '👥 团队共享标注');

    const body = modal.querySelector('.modal-body');
    body.innerHTML = `
        <div style="margin-bottom:12px;color:var(--text-secondary);font-size:13px;">
            在地图上点击添加标注，与团队成员实时共享。标注保存到本地，可导出分享。
        </div>
        <div style="display:flex;gap:8px;margin-bottom:16px;">
            <button class="btn-premium-primary" onclick="enableAnnotationMode()" style="flex:1;">📍 添加标注</button>
            <button class="btn-premium-secondary" onclick="exportAnnotations()" style="flex:1;">📤 导出</button>
            <button class="btn-premium-secondary" onclick="clearAnnotations()" style="flex:0;">🗑️ 清除</button>
        </div>
        <div id="annotations-list" style="max-height:300px;overflow-y:auto;"></div>
    `;

    loadAnnotations();
    renderAnnotationsList();
}

/**
 * 启用标注模式
 */
let annotationMode = false;

function enableAnnotationMode() {
    annotationMode = !annotationMode;
    if (annotationMode) {
        if (!annotationLayer) {
            annotationLayer = L.layerGroup().addTo(map);
        }
        map.getContainer().style.cursor = 'crosshair';
        map.on('click', onMapClickForAnnotation);
        showStatus('success', '标注模式已开启，点击地图添加标注');
    } else {
        map.getContainer().style.cursor = '';
        map.off('click', onMapClickForAnnotation);
        showStatus('success', '标注模式已关闭');
    }
    document.getElementById('annotations-modal').remove();
}

/**
 * 地图点击添加标注
 */
function onMapClickForAnnotation(e) {
    const text = prompt('输入标注内容:', '');
    if (!text) return;

    const annotation = {
        id: Date.now(),
        lat: e.latlng.lat,
        lng: e.latlng.lng,
        text: text,
        author: '我',
        time: new Date().toISOString(),
    };

    annotations.push(annotation);
    saveAnnotationsToStorage();
    renderAnnotationOnMap(annotation);
    showStatus('success', '标注已添加');
}

/**
 * 渲染标注到地图
 */
function renderAnnotationOnMap(annotation) {
    const marker = L.marker([annotation.lat, annotation.lng], {
        icon: L.divIcon({
            html: `<div style="font-size:20px">📍</div>`,
            iconSize: [20, 20],
            iconAnchor: [10, 10],
        }),
    }).addTo(annotationLayer);

    marker.bindPopup(`
        <div style="min-width:180px;">
            <div style="font-weight:700;margin-bottom:4px;">📍 ${escapeHtml(annotation.text)}</div>
            <div style="font-size:11px;color:#90caf9;">标注者: ${escapeHtml(annotation.author)}</div>
            <div style="font-size:11px;color:#607d8b;">${new Date(annotation.time).toLocaleString('zh-CN')}</div>
            <button onclick="deleteAnnotation(${annotation.id})" style="margin-top:6px;padding:2px 8px;border:1px solid #ff1744;color:#ff1744;border-radius:4px;cursor:pointer;background:transparent;">删除</button>
        </div>
    `);
}

/**
 * 加载标注
 */
function loadAnnotations() {
    try {
        const stored = localStorage.getItem('aviation_annotations');
        if (stored) {
            annotations = JSON.parse(stored);
        }
    } catch (e) {
        annotations = [];
    }
}

/**
 * 保存标注
 */
function saveAnnotationsToStorage() {
    try {
        localStorage.setItem('aviation_annotations', JSON.stringify(annotations));
    } catch (e) {
        console.error('保存标注失败:', e);
    }
}

/**
 * 渲染标注列表
 */
function renderAnnotationsList() {
    const listEl = document.getElementById('annotations-list');
    if (!listEl) return;

    if (annotations.length === 0) {
        listEl.innerHTML = '<div class="notam-empty">暂无标注</div>';
        return;
    }

    listEl.innerHTML = annotations.map(a => `
        <div class="annotation-item">
            <div class="annotation-text">📍 ${escapeHtml(a.text)}</div>
            <div class="annotation-meta">${escapeHtml(a.author)} · ${new Date(a.time).toLocaleString('zh-CN')}</div>
            <button class="btn-delete-annotation" onclick="deleteAnnotation(${a.id})">✕</button>
        </div>
    `).join('');
}

/**
 * 删除标注
 */
function deleteAnnotation(id) {
    annotations = annotations.filter(a => a.id !== id);
    saveAnnotationsToStorage();
    // 重渲染地图上的标注
    if (annotationLayer) {
        map.removeLayer(annotationLayer);
        annotationLayer = L.layerGroup().addTo(map);
        for (const a of annotations) {
            renderAnnotationOnMap(a);
        }
    }
    renderAnnotationsList();
}

/**
 * 清除所有标注
 */
function clearAnnotations() {
    if (!confirm('确定清除所有标注？')) return;
    annotations = [];
    saveAnnotationsToStorage();
    if (annotationLayer) {
        map.removeLayer(annotationLayer);
        annotationLayer = null;
    }
    renderAnnotationsList();
    showStatus('success', '所有标注已清除');
}

/**
 * 导出标注
 */
function exportAnnotations() {
    if (annotations.length === 0) {
        showStatus('error', '暂无标注可导出');
        return;
    }
    const data = JSON.stringify({
        export_time: new Date().toISOString(),
        count: annotations.length,
        annotations,
    }, null, 2);
    const blob = new Blob([data], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `annotations_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showStatus('success', `已导出 ${annotations.length} 个标注`);
}
