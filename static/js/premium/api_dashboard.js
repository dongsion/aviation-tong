/**
 * 航空通 Pro - API 用量仪表盘
 * 可视化 API 调用量、配额使用率、告警阈值
 */

function openApiDashboard() {
    const modal = createModal('api-dashboard-modal', '🔌 API 用量仪表盘');

    const body = modal.querySelector('.modal-body');

    // 模拟 API 用量数据（实际部署时从后端获取）
    const apiStats = {
        totalCalls: 15482,
        todayCalls: 342,
        quota: 50000,
        quotaUsed: 15482,
        quotaRemaining: 34518,
        endpoints: [
            { path: '/api/v1/notams', calls: 8420, color: '#FF1744' },
            { path: '/api/v1/launches', calls: 4210, color: '#FFAB00' },
            { path: '/api/v1/satellites', calls: 1850, color: '#00E5FF' },
            { path: '/api/v1/flight-plan', calls: 620, color: '#2962FF' },
            { path: '/api/v1/route-planner', calls: 382, color: '#AA00FF' },
        ],
        recentErrors: [
            { time: '2025-08-18 14:32', code: 429, message: 'Rate limit exceeded' },
            { time: '2025-08-18 09:15', code: 500, message: 'Internal server error' },
        ],
        responseTime: {
            avg: 245,
            p50: 180,
            p95: 620,
            p99: 1240,
        },
    };

    const quotaPct = (apiStats.quotaUsed / apiStats.quota * 100).toFixed(1);
    const quotaColor = quotaPct > 80 ? '#FF1744' : quotaPct > 60 ? '#FFAB00' : '#00E676';

    const maxEndpointCalls = Math.max(...apiStats.endpoints.map(e => e.calls));

    body.innerHTML = `
        <div class="dashboard-container">
            <!-- 配额概览 -->
            <div class="dashboard-section">
                <h4>📊 配额概览</h4>
                <div class="quota-display">
                    <div class="quota-ring" style="background:conic-gradient(${quotaColor} 0% ${quotaPct}%, #1e3a5f ${quotaPct}% 100%);">
                        <div class="quota-ring-inner">
                            <div class="quota-pct" style="color:${quotaColor}">${quotaPct}%</div>
                            <div class="quota-label">已使用</div>
                        </div>
                    </div>
                    <div class="quota-details">
                        <div class="quota-row"><span>月度配额</span><strong>${apiStats.quota.toLocaleString()}</strong></div>
                        <div class="quota-row"><span>已使用</span><strong style="color:${quotaColor}">${apiStats.quotaUsed.toLocaleString()}</strong></div>
                        <div class="quota-row"><span>剩余</span><strong style="color:#00E676">${apiStats.quotaRemaining.toLocaleString()}</strong></div>
                        <div class="quota-row"><span>今日调用</span><strong>${apiStats.todayCalls}</strong></div>
                        <div class="quota-row"><span>累计调用</span><strong>${apiStats.totalCalls.toLocaleString()}</strong></div>
                    </div>
                </div>
            </div>

            <!-- 接口调用分布 -->
            <div class="dashboard-section">
                <h4>🔗 接口调用分布</h4>
                <div class="endpoint-chart">
                    ${apiStats.endpoints.map(e => `
                        <div class="endpoint-bar-row">
                            <div class="endpoint-label">${escapeHtml(e.path)}</div>
                            <div class="endpoint-bar-container">
                                <div class="endpoint-bar" style="width:${(e.calls / maxEndpointCalls * 100).toFixed(1)}%;background:${e.color};">
                                    <span class="endpoint-value">${e.calls.toLocaleString()}</span>
                                </div>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>

            <!-- 响应时间 -->
            <div class="dashboard-section">
                <h4>⚡ 响应时间 (ms)</h4>
                <div class="response-time-grid">
                    <div class="rt-cell"><span>平均</span><strong>${apiStats.responseTime.avg}</strong></div>
                    <div class="rt-cell"><span>P50</span><strong>${apiStats.responseTime.p50}</strong></div>
                    <div class="rt-cell"><span>P95</span><strong style="color:#FFAB00">${apiStats.responseTime.p95}</strong></div>
                    <div class="rt-cell"><span>P99</span><strong style="color:#FF1744">${apiStats.responseTime.p99}</strong></div>
                </div>
            </div>

            <!-- 最近错误 -->
            <div class="dashboard-section">
                <h4>❌ 最近错误</h4>
                <div class="error-list">
                    ${apiStats.recentErrors.length > 0 ? apiStats.recentErrors.map(e => `
                        <div class="error-item">
                            <span class="error-code">${e.code}</span>
                            <span class="error-msg">${escapeHtml(e.message)}</span>
                            <span class="error-time">${escapeHtml(e.time)}</span>
                        </div>
                    `).join('') : '<div style="color:#00e676;padding:8px;">✅ 无近期错误</div>'}
                </div>
            </div>

            <!-- 告警设置 -->
            <div class="dashboard-section">
                <h4>🔔 告警阈值</h4>
                <div class="alert-config">
                    <label class="alert-row">
                        <span>配额使用超过</span>
                        <input type="number" value="80" class="alert-input" style="width:60px;">%
                    </label>
                    <label class="alert-row">
                        <span>响应时间超过</span>
                        <input type="number" value="1000" class="alert-input" style="width:80px;">ms
                    </label>
                    <button class="btn-premium-secondary" onclick="showStatus('success','告警设置已保存')">保存设置</button>
                </div>
            </div>
        </div>
    `;
}
