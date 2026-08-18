/**
 * 航空通 Pro - 多区域对比视图
 * 并排对比多个情报区的 NOTAM 数据
 */

function openComparisonView() {
    const modal = createModal('comparison-modal', '📊 多区域对比视图');

    const body = modal.querySelector('.modal-body');

    // 收集所有 FIR
    const firs = {};
    for (const f of allFeatures) {
        const fir = (f.properties || {}).fir || '未知';
        if (!firs[fir]) firs[fir] = { count: 0, types: {} };
        firs[fir].count++;
        const type = (f.properties || {}).type || 'other';
        firs[fir].types[type] = (firs[fir].types[type] || 0) + 1;
    }

    const sortedFirs = Object.entries(firs).sort((a, b) => b[1].count - a[1].count);

    body.innerHTML = `
        <div class="comparison-controls">
            <p style="margin-bottom:12px;color:var(--text-secondary);font-size:13px;">选择 2-4 个情报区进行对比：</p>
            <div class="fir-checkbox-list">
                ${sortedFirs.slice(0, 20).map(([fir, data]) => `
                    <label class="fir-checkbox-item">
                        <input type="checkbox" value="${escapeHtml(fir)}" class="fir-checkbox" ${sortedFirs.length <= 2 ? 'checked' : ''}>
                        <span>${escapeHtml(fir)}</span>
                        <span class="fir-count">${data.count}</span>
                    </label>
                `).join('')}
            </div>
            <button class="btn-premium-primary" onclick="generateComparison()" style="margin-top:12px;">📊 生成对比</button>
        </div>
        <div id="comparison-results" style="margin-top:16px;"></div>
    `;
}

/**
 * 生成对比图表
 */
function generateComparison() {
    const checked = [...document.querySelectorAll('.fir-checkbox:checked')].map(c => c.value);

    if (checked.length < 2) {
        document.getElementById('comparison-results').innerHTML = '<div class="premium-error">请至少选择 2 个情报区</div>';
        return;
    }
    if (checked.length > 4) {
        document.getElementById('comparison-results').innerHTML = '<div class="premium-error">最多对比 4 个情报区</div>';
        return;
    }

    // 收集数据
    const data = {};
    for (const fir of checked) {
        data[fir] = { count: 0, types: {} };
    }
    for (const f of allFeatures) {
        const fir = (f.properties || {}).fir || '';
        if (!data[fir]) continue;
        data[fir].count++;
        const type = (f.properties || {}).type || 'other';
        data[fir].types[type] = (data[fir].types[type] || 0) + 1;
    }

    renderComparisonChart(checked, data);
}

/**
 * 渲染对比图表 (纯 CSS 柱状图)
 */
function renderComparisonChart(firs, data) {
    const maxCount = Math.max(...firs.map(f => data[f].count));
    const allTypes = [...new Set(firs.flatMap(f => Object.keys(data[f].types)))];

    const container = document.getElementById('comparison-results');
    container.innerHTML = `
        <div class="comparison-chart">
            <h4 style="margin-bottom:12px;">NOTAM 数量对比</h4>
            <div class="bar-chart">
                ${firs.map(fir => `
                    <div class="bar-chart-row">
                        <div class="bar-chart-label">${escapeHtml(fir.length > 12 ? fir.substring(0, 12) + '...' : fir)}</div>
                        <div class="bar-chart-bar-container">
                            <div class="bar-chart-bar" style="width:${(data[fir].count / maxCount * 100).toFixed(1)}%">
                                <span class="bar-chart-value">${data[fir].count}</span>
                            </div>
                        </div>
                    </div>
                `).join('')}
            </div>

            <h4 style="margin:20px 0 12px;">类型分布对比</h4>
            <div class="comparison-table-container">
                <table class="comparison-table">
                    <thead>
                        <tr>
                            <th>类型</th>
                            ${firs.map(f => `<th>${escapeHtml(f.length > 8 ? f.substring(0, 8) + '...' : f)}</th>`).join('')}
                        </tr>
                    </thead>
                    <tbody>
                        ${allTypes.map(type => {
        const config = TYPE_CONFIG[type] || TYPE_CONFIG.other;
        return `
                            <tr>
                                <td style="color:${config.color}">${config.name}</td>
                                ${firs.map(f => `<td>${data[f].types[type] || 0}</td>`).join('')}
                            </tr>
                        `;
    }).join('')}
                        <tr style="font-weight:700;border-top:2px solid var(--border)">
                            <td>总计</td>
                            ${firs.map(f => `<td>${data[f].count}</td>`).join('')}
                        </tr>
                    </tbody>
                </table>
            </div>
        </div>
    `;
}
