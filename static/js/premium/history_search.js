/**
 * 航空通 Pro - 历史 NOTAM 检索
 * 按时间/区域/关键词搜索历史 NOTAM 归档数据
 */

let historySearchResults = [];
let historySearchLayer = null;

function openHistorySearch() {
    const modal = createModal('history-search-modal', '📜 历史 NOTAM 检索');

    const body = modal.querySelector('.modal-body');
    body.innerHTML = `
        <div class="route-planner-form">
            <div class="form-group">
                <label class="form-label">关键词</label>
                <input type="text" id="hs-keyword" class="form-input" placeholder="NOTAM 编号或内容关键词">
            </div>
            <div class="form-row">
                <div class="form-group" style="flex:1;">
                    <label class="form-label">开始日期</label>
                    <input type="date" id="hs-date-from" class="form-input">
                </div>
                <div class="form-group" style="flex:1;">
                    <label class="form-label">结束日期</label>
                    <input type="date" id="hs-date-to" class="form-input">
                </div>
            </div>
            <div class="form-group">
                <label class="form-label">NOTAM 类型</label>
                <select id="hs-type" class="form-select" style="width:100%;">
                    <option value="">全部类型</option>
                    <option value="danger">临时危险区</option>
                    <option value="restricted">限制区</option>
                    <option value="warning">警告区</option>
                    <option value="prohibited">禁航区</option>
                    <option value="tfr">临时飞行限制</option>
                    <option value="airway">航路变更</option>
                    <option value="other">其他</option>
                </select>
            </div>
            <div class="form-group">
                <label class="form-label">情报区 (FIR)</label>
                <input type="text" id="hs-fir" class="form-input" placeholder="如 ZBAA">
            </div>
            <button class="btn-premium-primary" onclick="searchHistoryNotams()">🔍 检索历史 NOTAM</button>
        </div>
        <div id="hs-results" style="margin-top:16px;"></div>
    `;
}

/**
 * 搜索历史 NOTAM
 * 注: 此功能在实际部署时需要后端历史数据库支持
 * 当前版本在客户端模拟检索当前数据集
 */
function searchHistoryNotams() {
    const keyword = (document.getElementById('hs-keyword') || {}).value || '';
    const dateFrom = (document.getElementById('hs-date-from') || {}).value || '';
    const dateTo = (document.getElementById('hs-date-to') || {}).value || '';
    const type = (document.getElementById('hs-type') || {}).value || '';
    const fir = (document.getElementById('hs-fir') || {}).value || '';

    // 在当前数据集上模拟历史搜索
    let results = allFeatures.filter(f => {
        const p = f.properties || {};

        // 关键词匹配
        if (keyword) {
            const k = keyword.toLowerCase();
            const match = (p.notam_code || '').toLowerCase().includes(k) ||
                         (p.raw_message || '').toLowerCase().includes(k);
            if (!match) return false;
        }

        // 类型匹配
        if (type && p.type !== type) return false;

        // 情报区匹配
        if (fir && !(p.fir || '').toUpperCase().includes(fir.toUpperCase())) return false;

        // 日期匹配
        if (dateFrom) {
            const start = p.start || '';
            if (start && start < dateFrom) return false;
        }
        if (dateTo) {
            const end = p.end || '';
            if (end && end > dateTo + 'T23:59:59Z') return false;
        }

        return true;
    });

    historySearchResults = results;
    renderHistoryResults(results, { keyword, dateFrom, dateTo, type, fir });
}

/**
 * 渲染历史搜索结果
 */
function renderHistoryResults(results, filters) {
    const container = document.getElementById('hs-results');

    if (results.length === 0) {
        container.innerHTML = '<div class="notam-empty">未找到匹配的历史 NOTAM</div>';
        return;
    }

    // 按类型统计
    const typeStats = {};
    results.forEach(f => {
        const t = (f.properties || {}).type || 'other';
        typeStats[t] = (typeStats[t] || 0) + 1;
    });

    container.innerHTML = `
        <div class="history-summary">
            <span>找到 <strong>${results.length}</strong> 条记录</span>
            ${Object.entries(typeStats).map(([t, c]) => {
        const config = TYPE_CONFIG[t] || TYPE_CONFIG.other;
        return `<span class="history-type-tag" style="border-color:${config.color};color:${config.color}">${config.name} ${c}</span>`;
    }).join('')}
        </div>
        <div class="history-results-list" style="max-height:400px;overflow-y:auto;">
            ${results.slice(0, 100).map(f => {
        const p = f.properties || {};
        const config = TYPE_CONFIG[p.type] || TYPE_CONFIG.other;
        return `
                <div class="history-result-item" style="border-left-color:${config.color}" data-code="${escapeHtml(p.notam_code || '')}">
                    <div class="notam-code">${escapeHtml(p.notam_code || 'N/A')}</div>
                    <div class="notam-type">${escapeHtml(config.name)}</div>
                    <div class="notam-time">${escapeHtml(p.start || '')} ~ ${escapeHtml(p.end || '')}</div>
                    <span class="notam-fir">${escapeHtml(p.fir || '')}</span>
                </div>
            `;
    }).join('')}
        </div>
        ${results.length > 100 ? `<div style="text-align:center;padding:8px;color:var(--text-muted);">仅显示前 100 条（共 ${results.length} 条）</div>` : ''}
        <button class="btn-premium-secondary" onclick="exportHistoryResults()" style="margin-top:12px;">📤 导出结果</button>
    `;

    // 点击定位
    container.querySelectorAll('.history-result-item').forEach((el, idx) => {
        el.addEventListener('click', () => {
            const feature = results[idx];
            const geometry = feature.geometry;
            if (geometry && geometry.type === 'Polygon') {
                const coords = geometry.coordinates[0];
                const latlngs = coords.map(c => [c[1], c[0]]);
                map.fitBounds(L.latLngBounds(latlngs), { padding: [50, 50] });
            }
        });
    });
}

/**
 * 导出历史搜索结果
 */
function exportHistoryResults() {
    if (historySearchResults.length === 0) {
        showStatus('error', '暂无结果可导出');
        return;
    }

    const headers = ['NOTAM编号', '类型', '情报区', '生效时间', '失效时间'];
    const rows = historySearchResults.map(f => {
        const p = f.properties || {};
        return [p.notam_code || '', p.type || '', p.fir || '', p.start || '', p.end || ''];
    });

    const csv = [headers, ...rows].map(r =>
        r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(',')
    ).join('\n');

    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `history_notams_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    showStatus('success', `已导出 ${historySearchResults.length} 条历史记录`);
}
