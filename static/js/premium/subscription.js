/**
 * 航空通 - NOTAM 订阅管理面板 (付费功能)
 * 提供订阅创建、地理围栏框选、通知渠道配置、导入导出等功能
 * 依赖: map.js (escapeHtml, map, allFeatures)、Leaflet
 */

// ============================================================
// 全局状态
// ============================================================
let subscriptions = [];              // 订阅列表
let subscriptionLayer = null;        // 订阅区域图层
let drawRectHandler = null;          // 地图框选绘制处理器
let drawRectTemp = null;             // 绘制中的临时矩形
let drawStartLatLng = null;          // 框选起点
let drawMode = 'none';               // 当前绘制模式: 'none' | 'rectangle'

// 中国 FIR (飞行情报区) 代码列表
const FIR_CODES = [
    { code: 'ZBPE', name: '北京情报区' },
    { code: 'ZGZU', name: '广州情报区' },
    { code: 'ZSSS', name: '上海情报区' },
    { code: 'ZWWW', name: '乌鲁木齐情报区' },
    { code: 'ZLHW', name: '兰州情报区' },
    { code: 'ZYSH', name: '沈阳情报区' },
    { code: 'ZPKM', name: '昆明情报区' },
    { code: 'ZHKG', name: '香港情报区' },
    { code: 'ZSHA', name: '上海沿海' },
    { code: 'ZHAY', name: '郑州高空' },
    { code: 'ZJSA', name: '济南高空' },
    { code: 'ZGZG', name: '广州高空' },
];

// 订阅类型配置
const SUBSCRIPTION_TYPE_CONFIG = {
    keyword:   { color: '#FF6D00', icon: '🔍', name: '关键词订阅' },
    fir:       { color: '#2962FF', icon: '📡', name: '情报区订阅' },
    geo_fences: { color: '#00E5FF', icon: '🗺️', name: '地理围栏订阅' },
};

// ============================================================
// Toast 通知 (全局共享，供所有 premium 模块使用)
// ============================================================
function showToast(message, type = 'info') {
    let container = document.querySelector('.premium-toast-container');
    if (!container) {
        container = document.createElement('div');
        container.className = 'premium-toast-container';
        document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = 'premium-toast ' + type;

    const icon = type === 'success' ? '✅' : (type === 'error' ? '❌' : 'ℹ️');
    toast.innerHTML = '<span>' + icon + '</span><span>' + escapeHtml(message) + '</span>';

    container.appendChild(toast);

    setTimeout(function() {
        toast.classList.add('removing');
        setTimeout(function() {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 300);
    }, 3500);
}

// ============================================================
// 模态框辅助函数 (全局共享，供所有 premium 模块使用)
// ============================================================

// 功能路由: index.html 中 onclick="openPremiumModal('subscription')" 调用此函数
function openPremiumFeature(featureName) {
    switch(featureName) {
        case 'subscription':
            openSubscriptionPanel();
            break;
        case 'flight-plan':
            openFlightPlanPanel();
            break;
        case 'satellite-pass':
            openSatellitePassPanel();
            break;
        case 'api-docs':
            openApiDocsPanel();
            break;
        default:
            openPremiumModal('提示', '<p style="color:var(--text-muted);text-align:center;padding:20px 0;">功能开发中，敬请期待...</p>');
    }
}

// NOTAM 订阅面板
function openSubscriptionPanel() {
    const subs = loadSubscriptions();
    let listHtml = '';
    if (subs.length === 0) {
        listHtml = '<div class="notam-empty" style="padding:30px 0;">暂无订阅，点击下方按钮创建</div>';
    } else {
        subs.forEach(function(sub) {
            var statusBadge = sub.enabled !== false
                ? '<span style="color:#00e676">● 启用</span>'
                : '<span style="color:#546E7A">● 暂停</span>';
            listHtml +=
                '<div class="subscription-card" style="border-left:3px solid ' + (sub.area_polygon ? '#00E5FF' : '#FFAB00') + ';">' +
                    '<div style="display:flex;justify-content:space-between;align-items:center;">' +
                        '<div style="font-weight:600;">' + escapeHtml(sub.name || '未命名') + '</div>' +
                        statusBadge +
                    '</div>' +
                    '<div style="font-size:11px;color:var(--text-muted);margin-top:4px;">' +
                        (sub.fir_codes && sub.fir_codes.length ? 'FIR: ' + escapeHtml(sub.fir_codes.join(', ')) : 'FIR: 全部') +
                        (sub.keywords ? ' | 关键词: ' + escapeHtml(sub.keywords) : '') +
                    '</div>' +
                    '<div style="display:flex;gap:8px;margin-top:8px;">' +
                        '<button class="btn-action" style="font-size:10px;padding:3px 8px;" onclick="toggleSubscription(\'' + escapeHtml(sub.id) + '\')">' + (sub.enabled !== false ? '暂停' : '启用') + '</button>' +
                        '<button class="btn-action" style="font-size:10px;padding:3px 8px;" onclick="deleteSubscription(\'' + escapeHtml(sub.id) + '\')">删除</button>' +
                    '</div>' +
                '</div>';
        });
    }

    var bodyHtml =
        '<div id="subscription-panel">' +
            listHtml +
        '</div>' +
        '<div style="display:flex;gap:8px;margin-top:12px;">' +
            '<button class="btn-action" style="flex:1;" onclick="openSubscriptionForm()">+ 新建订阅</button>' +
            '<button class="btn-action" style="flex:1;" onclick="startMapBoxSubscription()">🗺️ 地图框选</button>' +
        '</div>' +
        '<div style="font-size:10px;color:var(--text-muted);margin-top:8px;text-align:center;">订阅的 NOTAM 更新后自动推送通知</div>';

    openPremiumModal('📡 NOTAM 订阅', bodyHtml);
}

// 飞行计划分析面板
function openFlightPlanPanel() {
    var airportOptions = '';
    if (typeof CHINA_AIRPORTS !== 'undefined') {
        CHINA_AIRPORTS.forEach(function(a) {
            airportOptions += '<option value="' + escapeHtml(a.icao) + '">' + escapeHtml(a.icao) + ' - ' + escapeHtml(a.name) + '</option>';
        });
    }

    var bodyHtml =
        '<div class="flight-plan-form">' +
            '<div class="form-row">' +
                '<div class="form-field">' +
                    '<label class="form-field-label">起飞机场 (ICAO)</label>' +
                    '<input type="text" class="form-input" id="fp-departure" placeholder="如 ZBAA" list="airport-list" autocomplete="off">' +
                '</div>' +
                '<div class="form-field">' +
                    '<label class="form-field-label">降落机场 (ICAO)</label>' +
                    '<input type="text" class="form-input" id="fp-arrival" placeholder="如 ZSSS" list="airport-list" autocomplete="off">' +
                '</div>' +
            '</div>' +
            '<datalist id="airport-list">' + airportOptions + '</datalist>' +
            '<div class="form-row">' +
                '<div class="form-field">' +
                    '<label class="form-field-label">起飞时间</label>' +
                    '<input type="datetime-local" class="form-input" id="fp-time">' +
                '</div>' +
                '<div class="form-field">' +
                    '<label class="form-field-label">巡航高度 (英尺)</label>' +
                    '<input type="number" class="form-input" id="fp-altitude" placeholder="35000" value="35000">' +
                '</div>' +
            '</div>' +
            '<button class="btn-action" style="width:100%;margin-top:8px;" onclick="analyzeFlightPlan()">✈️ 分析 NOTAM 影响</button>' +
        '</div>' +
        '<div id="fp-result" style="margin-top:12px;"></div>';

    openPremiumModal('✈️ 飞行计划分析', bodyHtml);

    // 设置默认时间
    setTimeout(function() {
        var timeInput = document.getElementById('fp-time');
        if (timeInput && !timeInput.value) {
            var now = new Date();
            now.setMinutes(now.getMinutes() - now.getTimezoneOffset());
            timeInput.value = now.toISOString().slice(0, 16);
        }
        // 初始化自动补全
        if (typeof initAirportAutocomplete === 'function') {
            initAirportAutocomplete();
        }
    }, 100);
}

// 卫星过境预测面板
function openSatellitePassPanel() {
    var satOptions = '';
    if (typeof satelliteData !== 'undefined' && satelliteData.length > 0) {
        var categories = {};
        satelliteData.forEach(function(s) {
            var cat = s.category || 'other';
            if (!categories[cat]) categories[cat] = [];
            categories[cat].push(s);
        });
        for (var cat in categories) {
            satOptions += '<optgroup label="' + escapeHtml(cat) + '">';
            categories[cat].slice(0, 20).forEach(function(s) {
                satOptions += '<option value="' + escapeHtml(String(s.norad_id)) + '">' + escapeHtml(s.name) + '</option>';
            });
            satOptions += '</optgroup>';
        }
    } else {
        satOptions = '<option value="">请先加载卫星数据</option>';
    }

    var bodyHtml =
        '<div class="flight-plan-form">' +
            '<div class="form-row">' +
                '<div class="form-field">' +
                    '<label class="form-field-label">观察者纬度</label>' +
                    '<input type="number" class="form-input" id="sp-lat" placeholder="39.9" step="0.0001">' +
                '</div>' +
                '<div class="form-field">' +
                    '<label class="form-field-label">观察者经度</label>' +
                    '<input type="number" class="form-input" id="sp-lng" placeholder="116.4" step="0.0001">' +
                '</div>' +
            '</div>' +
            '<div class="form-field">' +
                '<label class="form-field-label">选择卫星</label>' +
                '<select class="form-select" id="sp-satellite">' + satOptions + '</select>' +
            '</div>' +
            '<div class="form-row">' +
                '<div class="form-field">' +
                    '<label class="form-field-label">预测天数</label>' +
                    '<select class="form-select" id="sp-days">' +
                        '<option value="1">1 天</option>' +
                        '<option value="3" selected>3 天</option>' +
                        '<option value="7">7 天</option>' +
                    '</select>' +
                '</div>' +
                '<div class="form-field" style="display:flex;align-items:flex-end;">' +
                    '<button class="btn-action" style="width:100%;" onclick="toggleMapPickMode()">🗺️ 地图选取</button>' +
                '</div>' +
            '</div>' +
            '<button class="btn-action" style="width:100%;margin-top:8px;" onclick="predictSatellitePasses()">🛰️ 预测过境</button>' +
        '</div>' +
        '<div id="sp-result" style="margin-top:12px;"></div>';

    openPremiumModal('🛰️ 卫星过境预测', bodyHtml);
}

// API 接口文档面板
function openApiDocsPanel() {
    var bodyHtml =
        '<div style="font-size:12px;line-height:1.8;color:var(--text-secondary);">' +
            '<div style="margin-bottom:12px;color:var(--text-primary);font-weight:600;">RESTful API 端点</div>' +
            '<div style="margin-bottom:8px;padding:8px;background:rgba(0,0,0,0.2);border-radius:6px;">' +
                '<div style="color:#00e676;font-weight:600;">GET /api/v1/health</div>' +
                '<div style="color:var(--text-muted);">健康检查 (无需认证)</div>' +
            '</div>' +
            '<div style="margin-bottom:8px;padding:8px;background:rgba(0,0,0,0.2);border-radius:6px;">' +
                '<div style="color:#00e676;font-weight:600;">GET /api/v1/notams</div>' +
                '<div style="color:var(--text-muted);">NOTAM 列表 (支持 ?type=&active=&bbox= 过滤)</div>' +
            '</div>' +
            '<div style="margin-bottom:8px;padding:8px;background:rgba(0,0,0,0.2);border-radius:6px;">' +
                '<div style="color:#00e676;font-weight:600;">GET /api/v1/launches</div>' +
                '<div style="color:var(--text-muted);">火箭发射计划</div>' +
            '</div>' +
            '<div style="margin-bottom:8px;padding:8px;background:rgba(0,0,0,0.2);border-radius:6px;">' +
                '<div style="color:#00e676;font-weight:600;">GET /api/v1/satellites</div>' +
                '<div style="color:var(--text-muted);">卫星数据</div>' +
            '</div>' +
            '<div style="margin-bottom:8px;padding:8px;background:rgba(0,0,0,0.2);border-radius:6px;">' +
                '<div style="color:#FFAB00;font-weight:600;">POST /api/v1/flight-plan/analyze</div>' +
                '<div style="color:var(--text-muted);">飞行计划 NOTAM 影响分析 (PRO+)</div>' +
            '</div>' +
            '<div style="margin-bottom:8px;padding:8px;background:rgba(0,0,0,0.2);border-radius:6px;">' +
                '<div style="color:#FFAB00;font-weight:600;">GET/POST /api/v1/subscriptions</div>' +
                '<div style="color:var(--text-muted);">订阅管理 (PRO+)</div>' +
            '</div>' +
            '<div style="margin-top:12px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.1);">' +
                '<div style="font-weight:600;color:var(--text-primary);margin-bottom:4px;">认证方式</div>' +
                '<div style="color:var(--text-muted);">请求头添加: <code style="background:rgba(0,0,0,0.3);padding:2px 6px;border-radius:3px;">X-API-Key: your_api_key</code></div>' +
            '</div>' +
            '<div style="margin-top:12px;">' +
                '<div style="font-weight:600;color:var(--text-primary);margin-bottom:4px;">权限等级</div>' +
                '<div style="color:var(--text-muted);">FREE: 基础查询 | PRO: 1000次/月 | TEAM: 10万次/月</div>' +
            '</div>' +
        '</div>';

    openPremiumModal('🔌 API 接口文档', bodyHtml);
}

function openPremiumModal(title, bodyHtml, footerHtml) {
    closeModal();

    const overlay = document.createElement('div');
    overlay.className = 'premium-modal-overlay visible';
    overlay.id = 'premium-modal-overlay';
    overlay.innerHTML =
        '<div class="premium-modal">' +
            '<div class="premium-modal-header">' +
                '<div class="premium-modal-title">' + escapeHtml(title) + '</div>' +
                '<button class="premium-modal-close" onclick="closeModal()" title="关闭">&times;</button>' +
            '</div>' +
            '<div class="premium-modal-body">' + bodyHtml + '</div>' +
            (footerHtml ? '<div class="premium-modal-footer">' + footerHtml + '</div>' : '') +
        '</div>';

    document.body.appendChild(overlay);

    // 点击遮罩关闭
    overlay.addEventListener('click', function(e) {
        if (e.target === overlay) closeModal();
    });

    // ESC 键关闭
    document.addEventListener('keydown', onModalEsc);

    return overlay;
}

function closeModal() {
    const overlay = document.getElementById('premium-modal-overlay');
    if (overlay) {
        overlay.classList.remove('visible');
        if (overlay.parentNode) overlay.parentNode.removeChild(overlay);
    }
    document.removeEventListener('keydown', onModalEsc);
}

function onModalEsc(e) {
    if (e.key === 'Escape') closeModal();
}

// ============================================================
// 订阅数据持久化 (localStorage)
// ============================================================
const SUBSCRIPTIONS_STORAGE_KEY = 'aviation_tong_subscriptions';

function loadSubscriptions() {
    try {
        const raw = localStorage.getItem(SUBSCRIPTIONS_STORAGE_KEY);
        if (raw) {
            subscriptions = JSON.parse(raw);
        } else {
            subscriptions = [];
        }
    } catch (e) {
        console.error('订阅数据加载失败:', e);
        subscriptions = [];
    }
    return subscriptions;
}

function saveSubscriptions() {
    try {
        localStorage.setItem(SUBSCRIPTIONS_STORAGE_KEY, JSON.stringify(subscriptions));
    } catch (e) {
        console.error('订阅数据保存失败:', e);
        showToast('订阅保存失败，请检查浏览器存储空间', 'error');
    }
}

/**
 * 生成唯一订阅 ID
 */
function generateSubscriptionId() {
    return 'sub_' + Date.now() + '_' + Math.random().toString(36).substring(2, 8);
}

/**
 * 更新订阅触发统计
 * @param {string} subId - 订阅 ID
 */
function recordSubscriptionTrigger(subId) {
    const sub = subscriptions.find(function(s) { return s.id === subId; });
    if (sub) {
        sub.triggerCount = (sub.triggerCount || 0) + 1;
        sub.lastTriggeredAt = new Date().toISOString();
        saveSubscriptions();
    }
}

// ============================================================
// 渲染订阅列表
// ============================================================
function renderSubscriptionList() {
    const container = document.getElementById('subscription-list');
    if (!container) return;

    if (subscriptions.length === 0) {
        container.innerHTML =
            '<div class="subscription-empty">' +
                '<div class="subscription-empty-icon">📡</div>' +
                '<div>暂无订阅，点击「新建订阅」创建</div>' +
            '</div>';
        return;
    }

    let html = '';
    subscriptions.forEach(function(sub) {
        const typeConfig = SUBSCRIPTION_TYPE_CONFIG[sub.type] || SUBSCRIPTION_TYPE_CONFIG.keyword;
        const isActive = sub.enabled !== false;
        const triggerCount = sub.triggerCount || 0;
        const lastTriggered = sub.lastTriggeredAt ? formatDate(sub.lastTriggeredAt) : '未触发';

        // 通知渠道标签
        let channelsHtml = '';
        if (sub.channels && sub.channels.length > 0) {
            channelsHtml = sub.channels.map(function(ch) {
                const icon = ch.type === 'email' ? '📧' : '🔗';
                return '<span class="notify-channel-tag ' + escapeHtml(ch.type) + '">' + icon + ' ' + escapeHtml(ch.type === 'email' ? '邮件' : 'Webhook') + '</span>';
            }).join('');
        } else {
            channelsHtml = '<span style="font-size:10px;color:var(--text-muted);">未配置通知</span>';
        }

        // 订阅条件描述
        let conditionHtml = '';
        if (sub.type === 'geo_fences' && sub.bounds) {
            conditionHtml =
                '<div class="subscription-card-meta-row">' +
                    '<div class="subscription-card-meta-item">' +
                        '<span class="subscription-card-meta-label">区域:</span>' +
                        '<span class="subscription-card-meta-value">' +
                            escapeHtml(sub.bounds.south.toFixed(2)) + '°, ' +
                            escapeHtml(sub.bounds.west.toFixed(2)) + '° ~ ' +
                            escapeHtml(sub.bounds.north.toFixed(2)) + '°, ' +
                            escapeHtml(sub.bounds.east.toFixed(2)) + '°' +
                        '</span>' +
                    '</div>' +
                '</div>';
        } else {
            const firText = sub.firCode ? escapeHtml(sub.firCode) : '全部';
            const kwText = sub.keywords ? escapeHtml(sub.keywords) : '无';
            conditionHtml =
                '<div class="subscription-card-meta-row">' +
                    '<div class="subscription-card-meta-item">' +
                        '<span class="subscription-card-meta-label">情报区:</span>' +
                        '<span class="subscription-card-meta-value">' + firText + '</span>' +
                    '</div>' +
                    '<div class="subscription-card-meta-item">' +
                        '<span class="subscription-card-meta-label">关键词:</span>' +
                        '<span class="subscription-card-meta-value">' + kwText + '</span>' +
                    '</div>' +
                '</div>';
        }

        html +=
            '<div class="subscription-card ' + escapeHtml(sub.type) + '" data-id="' + escapeHtml(sub.id) + '">' +
                '<div class="subscription-card-header">' +
                    '<div class="subscription-card-name">' +
                        '<span>' + typeConfig.icon + '</span>' +
                        '<span>' + escapeHtml(sub.name) + '</span>' +
                    '</div>' +
                    '<span class="subscription-card-status ' + (triggerCount > 0 ? 'triggered' : (isActive ? 'active' : '')) + '">' +
                        (isActive ? '● 已启用' : '○ 已暂停') +
                    '</span>' +
                '</div>' +
                '<div class="subscription-card-meta">' +
                    '<div class="subscription-card-meta-row">' +
                        '<div class="subscription-card-meta-item">' +
                            '<span class="subscription-card-meta-label">触发次数:</span>' +
                            '<span class="subscription-card-meta-value">' + triggerCount + '</span>' +
                        '</div>' +
                        '<div class="subscription-card-meta-item">' +
                            '<span class="subscription-card-meta-label">最后触发:</span>' +
                            '<span class="subscription-card-meta-value">' + lastTriggered + '</span>' +
                        '</div>' +
                    '</div>' +
                    conditionHtml +
                    '<div class="subscription-card-meta-row">' + channelsHtml + '</div>' +
                '</div>' +
                '<div class="subscription-card-actions">' +
                    '<button class="subscription-card-btn" onclick="toggleSubscription(\'' + escapeHtml(sub.id) + '\')">' +
                        (isActive ? '暂停' : '启用') +
                    '</button>' +
                    '<button class="subscription-card-btn" onclick="editSubscriptionChannels(\'' + escapeHtml(sub.id) + '\')">通知渠道</button>' +
                    (sub.type === 'geo_fences' ? '<button class="subscription-card-btn" onclick="locateSubscription(\'' + escapeHtml(sub.id) + '\')">定位</button>' : '') +
                    '<button class="subscription-card-btn danger" onclick="deleteSubscription(\'' + escapeHtml(sub.id) + '\')">删除</button>' +
                '</div>' +
            '</div>';
    });

    container.innerHTML = html;
}

/**
 * 格式化日期显示
 */
function formatDate(dateStr) {
    try {
        const d = new Date(dateStr);
        return d.toLocaleString('zh-CN', {
            month: '2-digit', day: '2-digit',
            hour: '2-digit', minute: '2-digit',
        });
    } catch (e) {
        return dateStr;
    }
}

// ============================================================
// 订阅图层渲染 (在地图上显示地理围栏)
// ============================================================
function renderSubscriptionLayer() {
    if (!map) return;

    if (!subscriptionLayer) {
        subscriptionLayer = L.layerGroup().addTo(map);
    }
    subscriptionLayer.clearLayers();

    subscriptions.forEach(function(sub) {
        if (sub.type === 'geo_fences' && sub.bounds && sub.enabled !== false) {
            const bounds = [
                [sub.bounds.south, sub.bounds.west],
                [sub.bounds.north, sub.bounds.east],
            ];
            const rect = L.rectangle(bounds, {
                color: '#00E5FF',
                weight: 2,
                opacity: 0.8,
                fillColor: '#00E5FF',
                fillOpacity: 0.08,
                dashArray: '6, 4',
            });

            rect.bindTooltip(escapeHtml(sub.name) + ' (地理围栏订阅)', {
                sticky: true,
                className: 'subscription-tooltip',
            });

            rect.addTo(subscriptionLayer);
        }
    });
}

/**
 * 定位到订阅区域
 */
function locateSubscription(subId) {
    const sub = subscriptions.find(function(s) { return s.id === subId; });
    if (!sub || !sub.bounds || !map) {
        showToast('该订阅无地理区域信息', 'info');
        return;
    }
    const bounds = [
        [sub.bounds.south, sub.bounds.west],
        [sub.bounds.north, sub.bounds.east],
    ];
    map.fitBounds(bounds, { padding: [50, 50] });
}

// ============================================================
// 新建订阅 (表单弹窗)
// ============================================================
function openSubscriptionForm() {
    const firOptions = FIR_CODES.map(function(f) {
        return '<option value="' + escapeHtml(f.code) + '">' + escapeHtml(f.code) + ' - ' + escapeHtml(f.name) + '</option>';
    }).join('');

    const bodyHtml =
        '<div class="flight-plan-form">' +
            '<div class="form-field">' +
                '<label class="form-field-label">订阅名称 <span class="required">*</span></label>' +
                '<input type="text" class="form-input" id="sub-name" placeholder="例如: 华北地区危险区监控" maxlength="40">' +
            '</div>' +
            '<div class="form-row">' +
                '<div class="form-field">' +
                    '<label class="form-field-label">FIR 情报区</label>' +
                    '<select class="form-select" id="sub-fir">' +
                        '<option value="">全部情报区</option>' +
                        firOptions +
                    '</select>' +
                '</div>' +
                '<div class="form-field">' +
                    '<label class="form-field-label">关键词</label>' +
                    '<input type="text" class="form-input" id="sub-keywords" placeholder="如: 火箭发射, 导弹">' +
                '</div>' +
            '</div>' +
            '<div class="premium-divider"></div>' +
            '<div style="font-size:12px;color:var(--text-muted);line-height:1.6;">' +
                '<strong style="color:var(--text-secondary);">提示:</strong> ' +
                '可填写情报区代码和关键词筛选 NOTAM。如需按地理区域订阅，请关闭此窗口后点击「地图框选订阅」按钮在地图上绘制矩形区域。' +
            '</div>' +
        '</div>';

    const footerHtml =
        '<button class="premium-btn" onclick="closeModal()">取消</button>' +
        '<button class="premium-btn primary" onclick="createSubscriptionFromForm()">创建订阅</button>';

    openPremiumModal('🔍 新建 NOTAM 订阅', bodyHtml, footerHtml);

    // 自动聚焦
    setTimeout(function() {
        const nameInput = document.getElementById('sub-name');
        if (nameInput) nameInput.focus();
    }, 100);
}

/**
 * 从表单创建订阅
 */
function createSubscriptionFromForm() {
    const nameInput = document.getElementById('sub-name');
    const firInput = document.getElementById('sub-fir');
    const kwInput = document.getElementById('sub-keywords');

    if (!nameInput) return;
    const name = nameInput.value.trim();
    if (!name) {
        showToast('请输入订阅名称', 'error');
        nameInput.focus();
        return;
    }

    const firCode = firInput ? firInput.value.trim() : '';
    const keywords = kwInput ? kwInput.value.trim() : '';

    if (!firCode && !keywords) {
        showToast('请至少填写情报区或关键词', 'error');
        return;
    }

    // 判断订阅类型
    let subType = 'keyword';
    if (firCode && !keywords) {
        subType = 'fir';
    }

    const newSub = {
        id: generateSubscriptionId(),
        name: name,
        type: subType,
        firCode: firCode,
        keywords: keywords,
        channels: [],
        enabled: true,
        triggerCount: 0,
        lastTriggeredAt: null,
        createdAt: new Date().toISOString(),
    };

    subscriptions.push(newSub);
    saveSubscriptions();
    renderSubscriptionList();
    renderSubscriptionLayer();
    closeModal();
    showToast('订阅创建成功', 'success');
}

// ============================================================
// 地图框选订阅 (地理围栏)
// ============================================================
function startMapBoxSubscription() {
    if (!map) {
        showToast('地图未初始化', 'error');
        return;
    }

    closeModal();
    drawMode = 'rectangle';

    // 显示绘制提示
    showDrawHint('请在地图上拖拽绘制矩形区域');

    // 禁用地图拖拽以避免冲突 (绘制时仍可缩放)
    map.getContainer().style.cursor = 'crosshair';

    // 绑定鼠标事件
    drawRectHandler = function(e) {
        onDrawRectMouseDown(e);
    };
    map.on('mousedown', drawRectHandler);
}

/**
 * 显示地图绘制提示横幅
 */
function showDrawHint(text) {
    let hint = document.querySelector('.map-draw-hint');
    if (!hint) {
        hint = document.createElement('div');
        hint.className = 'map-draw-hint';
        const mapContainer = map.getContainer().parentElement;
        mapContainer.appendChild(hint);
    }
    hint.innerHTML =
        '<span>✏️ ' + escapeHtml(text) + '</span>' +
        '<span class="map-draw-hint-close" onclick="cancelMapDraw()">&times;</span>';
    hint.classList.add('visible');
}

function hideDrawHint() {
    const hint = document.querySelector('.map-draw-hint');
    if (hint) hint.classList.remove('visible');
}

/**
 * 取消地图绘制
 */
function cancelMapDraw() {
    drawMode = 'none';
    hideDrawHint();
    if (map) {
        map.getContainer().style.cursor = '';
        map.off('mousedown', drawRectHandler);
        map.dragging.enable();
    }
    if (drawRectTemp) {
        map.removeLayer(drawRectTemp);
        drawRectTemp = null;
    }
    drawStartLatLng = null;
}

/**
 * 鼠标按下 - 开始绘制矩形
 */
function onDrawRectMouseDown(e) {
    if (drawMode !== 'rectangle') return;

    drawStartLatLng = e.latlng;
    map.dragging.disable();

    // 清除上一次的临时矩形
    if (drawRectTemp) {
        map.removeLayer(drawRectTemp);
    }

    // 创建临时矩形 (随鼠标移动更新)
    drawRectTemp = L.rectangle([e.latlng, e.latlng], {
        className: 'draw-rect-temp',
        color: '#00E5FF',
        weight: 2,
        opacity: 0.9,
        fillColor: '#00E5FF',
        fillOpacity: 0.1,
        dashArray: '6, 4',
    }).addTo(map);

    map.on('mousemove', onDrawRectMouseMove);
    map.on('mouseup', onDrawRectMouseUp);

    // 触摸支持
    map.on('touchmove', onDrawRectTouchMove);
    map.on('touchend', onDrawRectTouchEnd);
}

/**
 * 鼠标移动 - 更新矩形大小
 */
function onDrawRectMouseMove(e) {
    if (!drawStartLatLng || !drawRectTemp) return;
    drawRectTemp.setBounds([drawStartLatLng, e.latlng]);
}

/**
 * 鼠标松开 - 完成绘制
 */
function onDrawRectMouseUp(e) {
    if (!drawStartLatLng || !drawRectTemp) return;

    map.off('mousemove', onDrawRectMouseMove);
    map.off('mouseup', onDrawRectMouseUp);
    map.off('touchmove', onDrawRectTouchMove);
    map.off('touchend', onDrawRectTouchEnd);
    map.dragging.enable();

    const start = drawStartLatLng;
    const end = e.latlng;

    // 最小面积校验
    const latDiff = Math.abs(end.lat - start.lat);
    const lngDiff = Math.abs(end.lng - start.lng);
    if (latDiff < 0.1 || lngDiff < 0.1) {
        showToast('绘制区域太小，请重新绘制', 'error');
        if (drawRectTemp) {
            map.removeLayer(drawRectTemp);
            drawRectTemp = null;
        }
        drawStartLatLng = null;
        return;
    }

    // 计算边界 (经纬度极值)
    const bounds = {
        north: Math.max(start.lat, end.lat),
        south: Math.min(start.lat, end.lat),
        east: Math.max(start.lng, end.lng),
        west: Math.min(start.lng, end.lng),
    };

    // 清理临时矩形
    if (drawRectTemp) {
        map.removeLayer(drawRectTemp);
        drawRectTemp = null;
    }

    cancelMapDraw();
    openGeoFenceSubscriptionForm(bounds);
}

/**
 * 触摸移动 - 更新矩形
 */
function onDrawRectTouchMove(e) {
    if (e.touches && e.touches.length > 0) {
        onDrawRectMouseMove({ latlng: map.containerPointToLatLng([e.touches[0].clientX - map.getContainer().getBoundingClientRect().left, e.touches[0].clientY - map.getContainer().getBoundingClientRect().top]) });
    }
}

/**
 * 触摸结束
 */
function onDrawRectTouchEnd(e) {
    if (e.latlng) {
        onDrawRectMouseUp(e);
    }
}

/**
 * 地理围栏订阅表单 (框选完成后)
 */
function openGeoFenceSubscriptionForm(bounds) {
    const bodyHtml =
        '<div class="flight-plan-form">' +
            '<div class="form-field">' +
                '<label class="form-field-label">订阅名称 <span class="required">*</span></label>' +
                '<input type="text" class="form-input" id="geofence-name" placeholder="例如: 华南空域监控" maxlength="40">' +
            '</div>' +
            '<div class="form-field">' +
                '<label class="form-field-label">地理围栏范围</label>' +
                '<div style="padding:10px 12px;background:var(--bg-primary);border-radius:8px;font-size:12px;color:var(--text-secondary);line-height:1.8;">' +
                    '<div>北界: <strong style="color:#00E5FF;">' + bounds.north.toFixed(4) + '°</strong> &nbsp; 南界: <strong style="color:#00E5FF;">' + bounds.south.toFixed(4) + '°</strong></div>' +
                    '<div>东界: <strong style="color:#00E5FF;">' + bounds.east.toFixed(4) + '°</strong> &nbsp; 西界: <strong style="color:#00E5FF;">' + bounds.west.toFixed(4) + '°</strong></div>' +
                '</div>' +
            '</div>' +
            '<div class="form-field">' +
                '<label class="form-field-label">关键词 (可选)</label>' +
                '<input type="text" class="form-input" id="geofence-keywords" placeholder="用于在该区域内进一步筛选">' +
            '</div>' +
        '</div>';

    const footerHtml =
        '<button class="premium-btn" onclick="closeModal()">取消</button>' +
        '<button class="premium-btn primary" onclick="createGeoFenceSubscription()">创建围栏订阅</button>';

    // 将 bounds 存到全局临时变量
    window._pendingGeoFenceBounds = bounds;

    openPremiumModal('🗺️ 地理围栏订阅', bodyHtml, footerHtml);

    setTimeout(function() {
        const nameInput = document.getElementById('geofence-name');
        if (nameInput) nameInput.focus();
    }, 100);
}

/**
 * 创建地理围栏订阅
 */
function createGeoFenceSubscription() {
    const nameInput = document.getElementById('geofence-name');
    const kwInput = document.getElementById('geofence-keywords');
    const bounds = window._pendingGeoFenceBounds;

    if (!nameInput || !bounds) return;
    const name = nameInput.value.trim();
    if (!name) {
        showToast('请输入订阅名称', 'error');
        nameInput.focus();
        return;
    }

    const keywords = kwInput ? kwInput.value.trim() : '';

    const newSub = {
        id: generateSubscriptionId(),
        name: name,
        type: 'geo_fences',
        bounds: bounds,
        keywords: keywords,
        channels: [],
        enabled: true,
        triggerCount: 0,
        lastTriggeredAt: null,
        createdAt: new Date().toISOString(),
    };

    subscriptions.push(newSub);
    saveSubscriptions();
    renderSubscriptionList();
    renderSubscriptionLayer();
    closeModal();
    delete window._pendingGeoFenceBounds;
    showToast('地理围栏订阅创建成功', 'success');
}

// ============================================================
// 通知渠道配置
// ============================================================
function editSubscriptionChannels(subId) {
    const sub = subscriptions.find(function(s) { return s.id === subId; });
    if (!sub) return;

    const channels = sub.channels || [];

    let channelsHtml = '';
    channels.forEach(function(ch, idx) {
        channelsHtml +=
            '<div class="form-row" style="align-items:flex-end;margin-bottom:8px;" data-ch-idx="' + idx + '">' +
                '<div class="form-field">' +
                    '<label class="form-field-label">通知类型</label>' +
                    '<select class="form-select ch-type">' +
                        '<option value="email"' + (ch.type === 'email' ? ' selected' : '') + '>邮件</option>' +
                        '<option value="webhook"' + (ch.type === 'webhook' ? ' selected' : '') + '>Webhook</option>' +
                    '</select>' +
                '</div>' +
                '<div class="form-field">' +
                    '<label class="form-field-label">目标地址</label>' +
                    '<input type="text" class="form-input ch-target" value="' + escapeHtml(ch.target || '') + '" placeholder="' + (ch.type === 'email' ? 'user@example.com' : 'https://hook.example.com/notify') + '">' +
                '</div>' +
                '<button class="premium-btn danger" style="flex-shrink:0;" onclick="removeChannelRow(this,' + "'" + escapeHtml(subId) + "'" + ')">删除</button>' +
            '</div>';
    });

    const bodyHtml =
        '<div>' +
            '<div style="font-size:12px;color:var(--text-muted);margin-bottom:12px;line-height:1.6;">' +
                '为订阅「<strong style="color:var(--text-secondary);">' + escapeHtml(sub.name) + '</strong>」配置通知渠道。触发时将通过以下方式发送提醒。' +
            '</div>' +
            '<div id="channels-list">' + channelsHtml + '</div>' +
            '<button class="premium-btn" style="margin-top:8px;" onclick="addChannelRow()">+ 添加通知渠道</button>' +
        '</div>';

    const footerHtml =
        '<button class="premium-btn" onclick="closeModal()">取消</button>' +
        '<button class="premium-btn primary" onclick="saveSubscriptionChannels(\'' + escapeHtml(subId) + '\')">保存</button>';

    openPremiumModal('🔔 通知渠道配置', bodyHtml, footerHtml);
}

/**
 * 添加通知渠道行
 */
function addChannelRow() {
    const list = document.getElementById('channels-list');
    if (!list) return;

    const row = document.createElement('div');
    row.className = 'form-row';
    row.style.alignItems = 'flex-end';
    row.style.marginBottom = '8px';
    row.innerHTML =
        '<div class="form-field">' +
            '<label class="form-field-label">通知类型</label>' +
            '<select class="form-select ch-type">' +
                '<option value="email">邮件</option>' +
                '<option value="webhook">Webhook</option>' +
            '</select>' +
        '</div>' +
        '<div class="form-field">' +
            '<label class="form-field-label">目标地址</label>' +
            '<input type="text" class="form-input ch-target" placeholder="user@example.com">' +
        '</div>' +
        '<button class="premium-btn danger" style="flex-shrink:0;" onclick="this.parentElement.remove()">删除</button>';
    list.appendChild(row);
}

/**
 * 删除通知渠道行
 */
function removeChannelRow(btn, subId) {
    btn.closest('.form-row').remove();
}

/**
 * 保存通知渠道配置
 */
function saveSubscriptionChannels(subId) {
    const sub = subscriptions.find(function(s) { return s.id === subId; });
    if (!sub) return;

    const rows = document.querySelectorAll('#channels-list .form-row');
    const newChannels = [];

    rows.forEach(function(row) {
        const typeSelect = row.querySelector('.ch-type');
        const targetInput = row.querySelector('.ch-target');
        if (!typeSelect || !targetInput) return;

        const type = typeSelect.value;
        const target = targetInput.value.trim();
        if (!target) return;

        // 基本校验
        if (type === 'email' && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(target)) {
            showToast('邮箱地址格式不正确: ' + target, 'error');
            return;
        }
        if (type === 'webhook' && !target.startsWith('http')) {
            showToast('Webhook 地址必须以 http 开头', 'error');
            return;
        }

        newChannels.push({ type: type, target: target });
    });

    sub.channels = newChannels;
    saveSubscriptions();
    renderSubscriptionList();
    closeModal();
    showToast('通知渠道已保存', 'success');
}

// ============================================================
// 订阅操作 (启用/暂停、删除)
// ============================================================
function toggleSubscription(subId) {
    const sub = subscriptions.find(function(s) { return s.id === subId; });
    if (!sub) return;

    sub.enabled = sub.enabled === false ? true : false;
    saveSubscriptions();
    renderSubscriptionList();
    renderSubscriptionLayer();
    showToast(sub.enabled ? '订阅已启用' : '订阅已暂停', 'info');
}

function deleteSubscription(subId) {
    const sub = subscriptions.find(function(s) { return s.id === subId; });
    if (!sub) return;

    const bodyHtml =
        '<div style="font-size:13px;color:var(--text-secondary);line-height:1.6;">' +
            '确定要删除订阅「<strong style="color:var(--text-primary);">' + escapeHtml(sub.name) + '</strong>」吗？此操作不可撤销。' +
        '</div>';

    const footerHtml =
        '<button class="premium-btn" onclick="closeModal()">取消</button>' +
        '<button class="premium-btn danger" onclick="confirmDeleteSubscription(\'' + escapeHtml(subId) + '\')">确认删除</button>';

    openPremiumModal('删除订阅确认', bodyHtml, footerHtml);
}

function confirmDeleteSubscription(subId) {
    subscriptions = subscriptions.filter(function(s) { return s.id !== subId; });
    saveSubscriptions();
    renderSubscriptionList();
    renderSubscriptionLayer();
    closeModal();
    showToast('订阅已删除', 'success');
}

// ============================================================
// 导出 / 导入订阅配置
// ============================================================
function exportSubscriptions() {
    if (subscriptions.length === 0) {
        showToast('暂无订阅可导出', 'info');
        return;
    }

    const data = {
        exportTime: new Date().toISOString(),
        version: '1.0',
        count: subscriptions.length,
        subscriptions: subscriptions,
    };

    const jsonStr = JSON.stringify(data, null, 2);
    const blob = new Blob([jsonStr], { type: 'application/json' });
    const url = URL.createObjectURL(blob);

    const a = document.createElement('a');
    a.href = url;
    a.download = 'aviation-tong-subscriptions-' + new Date().toISOString().slice(0, 10) + '.json';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    showToast('已导出 ' + subscriptions.length + ' 条订阅', 'success');
}

function importSubscriptions() {
    const input = document.createElement('input');
    input.type = 'file';
    input.accept = '.json,application/json';
    input.style.display = 'none';

    input.addEventListener('change', function(e) {
        const file = e.target.files[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = function(ev) {
            try {
                const data = JSON.parse(ev.target.result);
                if (!data.subscriptions || !Array.isArray(data.subscriptions)) {
                    showToast('文件格式不正确，未找到订阅数据', 'error');
                    return;
                }

                // 合并导入 (去重)
                let importCount = 0;
                data.subscriptions.forEach(function(sub) {
                    if (!sub.id) sub.id = generateSubscriptionId();
                    // 检查是否已存在
                    const exists = subscriptions.find(function(s) { return s.id === sub.id; });
                    if (!exists) {
                        subscriptions.push(sub);
                        importCount++;
                    }
                });

                saveSubscriptions();
                renderSubscriptionList();
                renderSubscriptionLayer();
                showToast('成功导入 ' + importCount + ' 条订阅', 'success');
            } catch (err) {
                console.error('导入失败:', err);
                showToast('导入失败: 文件解析错误', 'error');
            }
        };
        reader.readAsText(file);
    });

    document.body.appendChild(input);
    input.click();
    document.body.removeChild(input);
}

// ============================================================
// 订阅匹配检测 (供外部调用)
// 检查某条 NOTAM 是否匹配订阅规则
// ============================================================
function matchNotamToSubscriptions(feature) {
    const props = feature.properties || {};
    const geometry = feature.geometry;
    const matchedSubs = [];

    subscriptions.forEach(function(sub) {
        if (sub.enabled === false) return;

        let matched = true;

        // 关键词匹配
        if (sub.keywords) {
            const keywords = sub.keywords.split(/[,，]/).map(function(k) { return k.trim(); }).filter(Boolean);
            const searchText = (
                (props.notam_code || '') + ' ' +
                (props.raw_message || '') + ' ' +
                (props.type_name || '') + ' ' +
                (props.fir || '')
            ).toLowerCase();
            matched = keywords.some(function(kw) {
                return searchText.includes(kw.toLowerCase());
            });
            if (!matched) return;
        }

        // FIR 匹配
        if (sub.firCode) {
            if ((props.fir || '') !== sub.firCode) {
                return;
            }
        }

        // 地理围栏匹配
        if (sub.type === 'geo_fences' && sub.bounds && geometry) {
            matched = isNotamInBounds(feature, sub.bounds);
            if (!matched) return;
        }

        if (matched) {
            matchedSubs.push(sub);
        }
    });

    return matchedSubs;
}

/**
 * 判断 NOTAM 多边形是否与边界框相交
 */
function isNotamInBounds(feature, bounds) {
    const geometry = feature.geometry;
    if (!geometry || geometry.type !== 'Polygon') return false;

    const coords = geometry.coordinates[0];
    for (let i = 0; i < coords.length; i++) {
        const lng = coords[i][0];
        const lat = coords[i][1];
        if (lat >= bounds.south && lat <= bounds.north &&
            lng >= bounds.west && lng <= bounds.east) {
            return true;
        }
    }

    // 也检查边界框中心是否在 NOTAM 内 (简单射线法)
    const centerLng = (bounds.east + bounds.west) / 2;
    const centerLat = (bounds.north + bounds.south) / 2;
    if (pointInPolygon([centerLng, centerLat], coords)) {
        return true;
    }

    return false;
}

/**
 * 射线法判断点是否在多边形内
 */
function pointInPolygon(point, polygon) {
    let inside = false;
    const x = point[0], y = point[1];
    for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
        const xi = polygon[i][0], yi = polygon[i][1];
        const xj = polygon[j][0], yj = polygon[j][1];
        const intersect = ((yi > y) !== (yj > y)) &&
            (x < (xj - xi) * (y - yi) / (yj - yi) + xi);
        if (intersect) inside = !inside;
    }
    return inside;
}

// ============================================================
// 初始化订阅模块
// ============================================================
function initSubscriptions() {
    loadSubscriptions();

    // 确保地图已初始化后再创建图层
    if (map) {
        subscriptionLayer = L.layerGroup().addTo(map);
    }

    renderSubscriptionList();
    renderSubscriptionLayer();
}

// DOM 加载完成后自动初始化 (确保在 map.js 之后)
document.addEventListener('DOMContentLoaded', function() {
    // 延迟初始化以确保 map 已就绪
    setTimeout(initSubscriptions, 500);
});
