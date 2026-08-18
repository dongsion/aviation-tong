/**
 * 航空通 - 卫星过境预测模块 (付费功能)
 * 基于观察者位置和卫星 TLE 数据预测可见过境事件
 * 依赖: map.js (escapeHtml, map)、satellites.js (satelliteData, getSatelliteNameCN, calcSatellitePosition)、satellite.js 库
 */

// ============================================================
// 全局状态
// ============================================================
let satPassLayer = null;              // 过境轨迹图层
let satPassObserverMarker = null;     // 观察者位置标记
let satPassPickMode = false;           // 地图选取模式
let satPassMapClickHandler = null;     // 地图点击处理器
let satPassPredictions = [];           // 预测结果列表
let satPassReminders = [];             // 过境提醒定时器列表
let satPassCurrentSatellite = null;    // 当前选择的卫星

// 预测精度配置
const PASS_STEP_SECONDS = 30;          // 基础采样步长(秒)
const PASS_REFINE_SECONDS = 5;          // 精细化步长(秒)
const MIN_PASS_ELEVATION_DEG = 5;      // 最小可见仰角(度)
const EARTH_RADIUS_KM = 6371;

// ============================================================
// 初始化
// ============================================================
function initSatellitePass() {
    // 设置默认观察者位置 (北京)
    const latInput = document.getElementById('sp-observer-lat');
    const lngInput = document.getElementById('sp-observer-lng');
    if (latInput && !latInput.value) latInput.value = '39.9042';
    if (lngInput && !lngInput.value) lngInput.value = '116.4074';

    // 初始化卫星选择下拉
    populateSatelliteSelect();

    // 地图选取按钮
    const pickBtn = document.getElementById('sp-pick-map');
    if (pickBtn) {
        pickBtn.addEventListener('click', function() {
            toggleMapPickMode();
        });
    }
}

/**
 * 填充卫星选择下拉 (从已加载的 satelliteData)
 */
function populateSatelliteSelect() {
    const select = document.getElementById('sp-satellite');
    if (!select) return;

    // 保留第一个选项
    select.innerHTML = '<option value="">请选择卫星</option>';

    if (typeof satelliteData === 'undefined' || satelliteData.length === 0) {
        select.innerHTML += '<option value="" disabled>卫星数据加载中...</option>';
        return;
    }

    // 按类别分组
    const byCategory = {};
    for (const sat of satelliteData) {
        const cat = sat.category || 'other';
        if (!byCategory[cat]) byCategory[cat] = [];
        byCategory[cat].push(sat);
    }

    const categoryNames = {
        'stations': '🛰️ 空间站',
        'visual': '⭐ 最亮卫星',
        'weather': '🌤️ 天气卫星',
        'gps': '📡 GPS导航',
        'beidou': '🧭 北斗导航',
        'starlink': '✨ 星链',
    };

    for (const [cat, sats] of Object.entries(byCategory)) {
        const catName = categoryNames[cat] || '🛰️ 其他';
        const optgroup = document.createElement('optgroup');
        optgroup.label = catName + ' (' + sats.length + ')';

        // 每类最多显示 50 个
        sats.slice(0, 50).forEach(function(sat) {
            const nameCN = (typeof getSatelliteNameCN === 'function') ? getSatelliteNameCN(sat.name) : sat.name;
            const option = document.createElement('option');
            option.value = sat.norad_id;
            option.textContent = nameCN + ' (#' + sat.norad_id + ')';
            optgroup.appendChild(option);
        });

        select.appendChild(optgroup);
    }
}

// ============================================================
// 地图选取观察者位置
// ============================================================
function toggleMapPickMode() {
    if (!map) {
        showToast('地图未初始化', 'error');
        return;
    }

    satPassPickMode = !satPassPickMode;
    const pickBtn = document.getElementById('sp-pick-map');

    if (satPassPickMode) {
        if (pickBtn) {
            pickBtn.classList.add('active');
            pickBtn.textContent = '点击地图选取';
        }

        // 显示提示
        showSatPassHint('请在地图上点击选择观察者位置');

        // 绑定点击事件
        satPassMapClickHandler = function(e) {
            onMapPickObserver(e);
        };
        map.on('click', satPassMapClickHandler);

        // 改变光标
        map.getContainer().style.cursor = 'crosshair';
    } else {
        exitMapPickMode();
    }
}

function exitMapPickMode() {
    satPassPickMode = false;
    const pickBtn = document.getElementById('sp-pick-map');
    if (pickBtn) {
        pickBtn.classList.remove('active');
        pickBtn.textContent = '📍 地图选取';
    }

    hideSatPassHint();

    if (map && satPassMapClickHandler) {
        map.off('click', satPassMapClickHandler);
        satPassMapClickHandler = null;
    }
    if (map) {
        map.getContainer().style.cursor = '';
    }
}

/**
 * 地图点击 - 选取观察者位置
 */
function onMapPickObserver(e) {
    const lat = e.latlng.lat;
    const lng = e.latlng.lng;

    const latInput = document.getElementById('sp-observer-lat') || document.getElementById('sp-lat');
    const lngInput = document.getElementById('sp-observer-lng') || document.getElementById('sp-lng');
    if (latInput) latInput.value = lat.toFixed(4);
    if (lngInput) lngInput.value = lng.toFixed(4);

    // 更新地图上的观察者标记
    updateObserverMarker(lat, lng);

    exitMapPickMode();
    showToast('已设置观察者位置: ' + lat.toFixed(2) + ', ' + lng.toFixed(2), 'success');
}

/**
 * 更新观察者位置标记
 */
function updateObserverMarker(lat, lng) {
    if (!map) return;

    if (satPassObserverMarker) {
        map.removeLayer(satPassObserverMarker);
    }

    const icon = L.divIcon({
        className: 'observer-marker',
        html: '<div style="position:relative;">' +
            '<div style="width:16px;height:16px;background:#FFD600;border-radius:50%;border:3px solid #fff;box-shadow:0 0 10px rgba(255,214,0,0.8);"></div>' +
            '<div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:40px;height:40px;border:2px solid #FFD600;border-radius:50%;opacity:0.4;animation:observerPulse 2s ease-in-out infinite;"></div>' +
            '</div>',
        iconSize: [16, 16],
        iconAnchor: [8, 8],
    });

    satPassObserverMarker = L.marker([lat, lng], { icon: icon })
        .bindTooltip('观察者位置 (' + lat.toFixed(2) + ', ' + lng.toFixed(2) + ')', {
            permanent: false,
            direction: 'top',
        })
        .addTo(map);
}

/**
 * 显示/隐藏地图提示
 */
function showSatPassHint(text) {
    let hint = document.querySelector('.map-draw-hint');
    if (!hint) {
        hint = document.createElement('div');
        hint.className = 'map-draw-hint';
        const mapContainer = map.getContainer().parentElement;
        mapContainer.appendChild(hint);
    }
    hint.innerHTML =
        '<span>📍 ' + escapeHtml(text) + '</span>' +
        '<span class="map-draw-hint-close" onclick="exitMapPickMode()">&times;</span>';
    hint.classList.add('visible');
}

function hideSatPassHint() {
    const hint = document.querySelector('.map-draw-hint');
    if (hint) hint.classList.remove('visible');
}

// ============================================================
// 卫星过境预测 (核心算法)
// ============================================================

/**
 * 主入口 - 执行过境预测
 */
async function predictSatellitePasses() {
    const latInput = document.getElementById('sp-observer-lat') || document.getElementById('sp-lat');
    const lngInput = document.getElementById('sp-observer-lng') || document.getElementById('sp-lng');
    const satSelect = document.getElementById('sp-satellite');
    const noradInput = document.getElementById('sp-norad-id');
    const daysSelect = document.getElementById('sp-days');

    if (!latInput || !lngInput) {
        showToast('缺少观察者位置输入', 'error');
        return;
    }

    const observerLat = parseFloat(latInput.value);
    const observerLng = parseFloat(lngInput.value);
    if (isNaN(observerLat) || isNaN(observerLng)) {
        showToast('请输入有效的经纬度', 'error');
        return;
    }
    if (observerLat < -90 || observerLat > 90) {
        showToast('纬度范围应在 -90 到 90 之间', 'error');
        return;
    }
    if (observerLng < -180 || observerLng > 180) {
        showToast('经度范围应在 -180 到 180 之间', 'error');
        return;
    }

    const days = daysSelect ? parseInt(daysSelect.value, 10) : 1;

    // 获取选择的卫星
    let sat = null;
    const noradId = noradInput ? noradInput.value.trim() : '';
    const selectValue = satSelect ? satSelect.value : '';

    if (selectValue) {
        sat = satelliteData.find(function(s) { return s.norad_id === selectValue; });
    } else if (noradId) {
        sat = satelliteData.find(function(s) { return String(s.norad_id) === noradId; });
    }

    if (!sat) {
        showToast('请选择一颗卫星或输入有效的 NORAD ID', 'error');
        return;
    }

    satPassCurrentSatellite = sat;

    // 显示加载状态
    showPassLoading();

    // 先尝试后端 API
    let result = null;
    try {
        result = await predictViaAPI(sat, observerLat, observerLng, days);
    } catch (e) {
        console.log('后端 API 不可用，使用本地计算', e);
    }

    // 本地计算回退
    if (!result) {
        result = predictPassesLocal(sat, observerLat, observerLng, days);
    }

    if (!result || result.length === 0) {
        renderPassEmpty();
        showToast('预测期间内无可见过境', 'info');
        return;
    }

    satPassPredictions = result;
    renderPassTable(result, sat);
    drawPassTrajectory(sat, observerLat, observerLng, result[0]);

    showToast('预测完成: 发现 ' + result.length + ' 次过境', 'success');
}

/**
 * 通过后端 API 预测
 */
async function predictViaAPI(sat, observerLat, observerLng, days) {
    const resp = await fetch('/api/v1/satellite-pass', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            norad_id: sat.norad_id,
            tle1: sat.tle1,
            tle2: sat.tle2,
            observer_lat: observerLat,
            observer_lng: observerLng,
            observer_alt: 0,
            days: days,
        }),
    });

    if (!resp.ok) throw new Error('API 返回 ' + resp.status);
    const data = await resp.json();
    if (data.passes) return data.passes;
    return null;
}

/**
 * 本地计算过境预测
 * 使用 satellite.js 库计算仰角，遍历时间找过境事件
 */
function predictPassesLocal(sat, observerLat, observerLng, days) {
    if (typeof satellite === 'undefined') {
        console.error('satellite.js 未加载');
        showToast('satellite.js 库未加载，无法计算', 'error');
        return null;
    }

    // 解析 TLE
    let satrec;
    try {
        satrec = satellite.twoline2satrec(sat.tle1, sat.tle2);
    } catch (e) {
        console.error('TLE 解析失败:', e);
        showToast('TLE 数据解析失败', 'error');
        return null;
    }

    // 观察者地心坐标 (弧度)
    const observerGd = {
        longitude: satellite.radiansLong(observerLng),
        latitude: satellite.radiansLat(observerLat),
        height: 0,
    };

    const startTime = new Date();
    const endTime = new Date(startTime.getTime() + days * 24 * 3600 * 1000);

    const stepMs = PASS_STEP_SECONDS * 1000;
    const totalSteps = Math.ceil((endTime - startTime) / stepMs);

    // 采样仰角序列
    const samples = [];
    for (let i = 0; i <= totalSteps; i++) {
        const time = new Date(startTime.getTime() + i * stepMs);
        const elevation = calcElevation(satrec, time, observerGd);
        if (elevation !== null) {
            samples.push({ time: time, elevation: elevation });
        }
    }

    // 从仰角序列中提取过境事件
    const passes = extractPassesFromSamples(samples, satrec, observerGd);

    return passes;
}

/**
 * 计算某时刻卫星相对观察者的仰角
 * @returns 仰角(度) 或 null
 */
function calcElevation(satrec, date, observerGd) {
    try {
        // 传播卫星位置
        const pv = satellite.propagate(satrec, date);
        if (!pv.position || typeof pv.position === 'boolean') return null;

        const positionEci = pv.position;

        // 计算格林尼治恒星时
        const gmst = satellite.gstime(date);

        // ECI -> ECF
        const positionEcf = satellite.eciToEcf(positionEci, gmst);

        // 计算观察方向 (方位角、仰角、距离)
        const lookAngles = satellite.ecfToLookAngles(observerGd, positionEcf);

        // 仰角(弧度)转角度
        const elevationDeg = satellite.radiansToDegrees(lookAngles.elevation);
        const azimuthDeg = satellite.radiansToDegrees(lookAngles.azimuth);

        return { elevation: elevationDeg, azimuth: azimuthDeg };
    } catch (e) {
        return null;
    }
}

/**
 * 从仰角采样序列中提取过境事件
 */
function extractPassesFromSamples(samples, satrec, observerGd) {
    const passes = [];
    let inPass = false;
    let currentPass = null;

    const minElev = MIN_PASS_ELEVATION_DEG;

    for (let i = 0; i < samples.length; i++) {
        const sample = samples[i];
        const visible = sample.elevation.elevation > minElev;

        if (visible && !inPass) {
            // 过境开始
            inPass = true;
            currentPass = {
                startTime: sample.time,
                startAzimuth: sample.elevation.azimuth,
                startElevation: sample.elevation.elevation,
                maxElevation: sample.elevation.elevation,
                maxAzimuth: sample.elevation.azimuth,
                maxTime: sample.time,
                samples: [sample],
            };
        } else if (visible && inPass) {
            // 过境中 - 更新最大仰角
            currentPass.samples.push(sample);
            if (sample.elevation.elevation > currentPass.maxElevation) {
                currentPass.maxElevation = sample.elevation.elevation;
                currentPass.maxAzimuth = sample.elevation.azimuth;
                currentPass.maxTime = sample.time;
            }
        } else if (!visible && inPass) {
            // 过境结束
            inPass = false;
            currentPass.endTime = samples[i].time;
            currentPass.endAzimuth = samples[i].elevation.azimuth;
            currentPass.endElevation = samples[i].elevation.elevation;

            // 精细化起止时间和峰值
            refinePass(currentPass, satrec, observerGd);

            // 计算持续时间和方向
            currentPass.duration = Math.round((currentPass.endTime - currentPass.startTime) / 1000);
            currentPass.direction = calcPassDirection(
                currentPass.startAzimuth,
                currentPass.endAzimuth
            );

            passes.push(currentPass);
            currentPass = null;
        }
    }

    // 处理未结束的过境 (采样结束仍在过境中)
    if (inPass && currentPass) {
        currentPass.endTime = samples[samples.length - 1].time;
        currentPass.endAzimuth = samples[samples.length - 1].elevation.azimuth;
        currentPass.endElevation = samples[samples.length - 1].elevation.elevation;
        currentPass.duration = Math.round((currentPass.endTime - currentPass.startTime) / 1000);
        currentPass.direction = calcPassDirection(
            currentPass.startAzimuth,
            currentPass.endAzimuth
        );
        passes.push(currentPass);
    }

    return passes;
}

/**
 * 精细化过境的起止时间和峰值时间
 */
function refinePass(pass, satrec, observerGd) {
    const refineMs = PASS_REFINE_SECONDS * 1000;
    const searchRange = PASS_STEP_SECONDS * 1000;

    // 精细化开始时间 (在 pass.startTime 前后搜索)
    pass.startTime = refineTime(pass.startTime, -searchRange, 0, refineMs, satrec, observerGd, true);

    // 精细化结束时间
    pass.endTime = refineTime(pass.endTime, 0, searchRange, refineMs, satrec, observerGd, true);

    // 精细化峰值时间
    if (pass.maxTime) {
        pass.maxTime = refineTime(pass.maxTime, -searchRange, searchRange, refineMs, satrec, observerGd, false);
        const refined = calcElevation(satrec, pass.maxTime, observerGd);
        if (refined) {
            pass.maxElevation = refined.elevation;
            pass.maxAzimuth = refined.azimuth;
        }
    }

    // 更新起止仰角/方位角
    const startLook = calcElevation(satrec, pass.startTime, observerGd);
    if (startLook) {
        pass.startAzimuth = startLook.azimuth;
        pass.startElevation = startLook.elevation;
    }
    const endLook = calcElevation(satrec, pass.endTime, observerGd);
    if (endLook) {
        pass.endAzimuth = endLook.azimuth;
        pass.endElevation = endLook.elevation;
    }
}

/**
 * 在时间范围内精细化查找 (仰角过零或峰值)
 * @param findZero - true: 查找仰角过零点(起止), false: 查找峰值
 */
function refineTime(baseTime, rangeStart, rangeEnd, stepMs, satrec, observerGd, findZero) {
    let bestTime = baseTime;
    let bestVal = findZero ? -999 : -999;
    let prevElev = null;

    for (let offset = rangeStart; offset <= rangeEnd; offset += stepMs) {
        const time = new Date(baseTime.getTime() + offset);
        const look = calcElevation(satrec, time, observerGd);
        if (!look) continue;

        const elev = look.elevation;

        if (findZero) {
            // 查找最接近 0 度(MIN_PASS_ELEVATION_DEG)的时刻
            const target = MIN_PASS_ELEVATION_DEG;
            const diff = Math.abs(elev - target);
            if (prevElev !== null) {
                // 检测过零
                if ((prevElev < target && elev >= target) || (prevElev > target && elev <= target)) {
                    bestTime = time;
                    break;
                }
            }
            if (diff < Math.abs(bestVal)) {
                bestVal = diff;
                bestTime = time;
            }
            prevElev = elev;
        } else {
            // 查找最大仰角
            if (elev > bestVal) {
                bestVal = elev;
                bestTime = time;
            }
        }
    }

    return bestTime;
}

/**
 * 计算过境方向描述
 * @param startAz - 开始方位角
 * @param endAz - 结束方位角
 */
function calcPassDirection(startAz, endAz) {
    const azToCompass = function(az) {
        // 将方位角归一化到 0-360
        let a = az % 360;
        if (a < 0) a += 360;
        const dirs = ['北', '东北', '东', '东南', '南', '西南', '西', '西北', '北'];
        return dirs[Math.round(a / 45)];
    };

    const startCompass = azToCompass(startAz);
    const endCompass = azToCompass(endAz);

    return startCompass + ' → ' + endCompass;
}

// ============================================================
// 结果渲染
// ============================================================

function showPassLoading() {
    const resultEl = document.getElementById('sp-result');
    if (!resultEl) return;
    resultEl.innerHTML =
        '<div class="analysis-loading">' +
            '<div style="margin-bottom:8px;">🛰️ 正在计算卫星过境...</div>' +
        '</div>';
}

function renderPassEmpty() {
    const resultEl = document.getElementById('sp-result');
    if (!resultEl) return;
    resultEl.innerHTML =
        '<div class="analysis-empty">' +
            '<div style="font-size:32px;margin-bottom:8px;opacity:0.5;">🌌</div>' +
            '<div>预测期间内无可见过境</div>' +
            '<div style="font-size:11px;margin-top:4px;">可尝试选择其他卫星或延长预测天数</div>' +
        '</div>';
}

/**
 * 渲染过境预测表格
 */
function renderPassTable(passes, sat) {
    const resultEl = document.getElementById('sp-result');
    if (!resultEl) return;

    const satName = (typeof getSatelliteNameCN === 'function') ? getSatelliteNameCN(sat.name) : sat.name;

    let html =
        '<div class="analysis-result">' +
            '<div style="font-size:13px;font-weight:700;color:var(--text-primary);margin-bottom:10px;">' +
                '🛰️ ' + escapeHtml(satName) + ' 过境预测 (' + passes.length + ' 次)' +
            '</div>' +
            '<div class="satellite-pass-table-wrapper" style="overflow-x:auto;">' +
                '<table class="satellite-pass-table">' +
                    '<thead><tr>' +
                        '<th>开始时间</th>' +
                        '<th>最高点</th>' +
                        '<th>结束时间</th>' +
                        '<th>最大仰角</th>' +
                        '<th>持续</th>' +
                        '<th>方向</th>' +
                        '<th>提醒</th>' +
                    '</tr></thead>' +
                    '<tbody>';

    passes.forEach(function(pass, idx) {
        const maxElev = pass.maxElevation.toFixed(1);
        const durationMin = Math.floor(pass.duration / 60);
        const durationSec = pass.duration % 60;
        const durationStr = durationMin + '分' + (durationSec > 0 ? durationSec + '秒' : '');

        html +=
            '<tr onclick="selectPass(' + idx + ')" data-idx="' + idx + '">' +
                '<td>' + formatPassTime(pass.startTime) + '</td>' +
                '<td>' + formatPassTime(pass.maxTime) + '</td>' +
                '<td>' + formatPassTime(pass.endTime) + '</td>' +
                '<td class="pass-max-elevation">' + maxElev + '°</td>' +
                '<td>' + durationStr + '</td>' +
                '<td class="pass-direction">' + escapeHtml(pass.direction || 'N/A') + '</td>' +
                '<td><button class="pass-reminder-btn" onclick="event.stopPropagation();setPassReminder(' + idx + ', this)">⏰ 提醒</button></td>' +
            '</tr>';
    });

    html +=
                    '</tbody>' +
                '</table>' +
            '</div>' +
            '<div class="premium-divider"></div>' +
            '<div class="premium-btn-group">' +
                '<button class="premium-btn" onclick="clearSatPassLayers()">清除轨迹</button>' +
            '</div>' +
        '</div>';

    resultEl.innerHTML = html;
}

/**
 * 格式化过境时间显示
 */
function formatPassTime(date) {
    if (!date) return 'N/A';
    return date.toLocaleString('zh-CN', {
        month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        hour12: false,
    });
}

/**
 * 选中某次过境 - 在地图上绘制轨迹
 */
function selectPass(idx) {
    if (idx < 0 || idx >= satPassPredictions.length) return;
    if (!satPassCurrentSatellite) return;

    // 高亮选中行
    document.querySelectorAll('.satellite-pass-table tbody tr').forEach(function(tr) {
        tr.classList.toggle('highlighted', parseInt(tr.dataset.idx, 10) === idx);
    });

    const pass = satPassPredictions[idx];
    const lat = parseFloat((document.getElementById('sp-observer-lat') || {}).value);
    const lng = parseFloat((document.getElementById('sp-observer-lng') || {}).value);
    drawPassTrajectory(satPassCurrentSatellite, lat, lng, pass);
}

// ============================================================
// 地图绘制 - 过境轨迹
// ============================================================

/**
 * 绘制卫星过境轨迹
 * 包括: 卫星地面轨迹、起止点标记、最高点标记
 */
function drawPassTrajectory(sat, observerLat, observerLng, pass) {
    if (!map || !pass) return;

    if (!satPassLayer) {
        satPassLayer = L.layerGroup().addTo(map);
    }
    satPassLayer.clearLayers();

    // 计算过境期间卫星地面轨迹
    if (typeof satellite === 'undefined') return;

    let satrec;
    try {
        satrec = satellite.twoline2satrec(sat.tle1, sat.tle2);
    } catch (e) {
        console.error('TLE 解析失败:', e);
        return;
    }

    // 过境前后各扩展 2 分钟
    const margin = 2 * 60 * 1000;
    const startMs = pass.startTime.getTime() - margin;
    const endMs = pass.endTime.getTime() + margin;
    const stepSec = 10; // 10秒一步

    const trackPoints = [];
    const visiblePoints = [];

    const observerGd = {
        longitude: satellite.radiansLong(observerLng),
        latitude: satellite.radiansLat(observerLat),
        height: 0,
    };

    for (let t = startMs; t <= endMs; t += stepSec * 1000) {
        const time = new Date(t);
        const pv = satellite.propagate(satrec, time);
        if (!pv.position || typeof pv.position === 'boolean') continue;

        const gmst = satellite.gstime(time);
        const pgd = satellite.eciToGeodetic(pv.position, gmst);
        const lng = satellite.degreesLong(pgd.longitude);
        const lat = satellite.degreesLat(pgd.latitude);

        trackPoints.push([lat, lng]);

        // 判断是否可见
        const positionEcf = satellite.eciToEcf(pv.position, gmst);
        const lookAngles = satellite.ecfToLookAngles(observerGd, positionEcf);
        const elevDeg = satellite.radiansToDegrees(lookAngles.elevation);

        if (elevDeg > MIN_PASS_ELEVATION_DEG) {
            visiblePoints.push({ lat: lat, lng: lng, elev: elevDeg, time: time });
        }
    }

    // 绘制完整地面轨迹 (虚线)
    if (trackPoints.length > 1) {
        const trackLine = L.polyline(trackPoints, {
            color: '#546E7A',
            weight: 1.5,
            opacity: 0.5,
            dashArray: '4, 4',
        });
        satPassLayer.addLayer(trackLine);
    }

    // 绘制可见段轨迹 (高亮实线)
    if (visiblePoints.length > 1) {
        const visibleLatLngs = visiblePoints.map(function(p) { return [p.lat, p.lng]; });
        const visibleLine = L.polyline(visibleLatLngs, {
            color: '#00E5FF',
            weight: 3,
            opacity: 0.9,
            dashArray: '',
        });
        satPassLayer.addLayer(visibleLine);
    }

    // 起始点标记
    if (visiblePoints.length > 0) {
        const startPt = visiblePoints[0];
        const startMarker = L.circleMarker([startPt.lat, startPt.lng], {
            radius: 6,
            color: '#00e676',
            fillColor: '#00e676',
            fillOpacity: 0.8,
            weight: 2,
        }).bindTooltip('过境开始 (' + formatPassTime(pass.startTime) + ')\n仰角: ' + pass.startElevation.toFixed(1) + '°', { sticky: true });
        satPassLayer.addLayer(startMarker);

        // 结束点标记
        const endPt = visiblePoints[visiblePoints.length - 1];
        const endMarker = L.circleMarker([endPt.lat, endPt.lng], {
            radius: 6,
            color: '#ff5252',
            fillColor: '#ff5252',
            fillOpacity: 0.8,
            weight: 2,
        }).bindTooltip('过境结束 (' + formatPassTime(pass.endTime) + ')\n仰角: ' + pass.endElevation.toFixed(1) + '°', { sticky: true });
        satPassLayer.addLayer(endMarker);
    }

    // 最高点标记 (卫星在最高点时刻的位置)
    if (pass.maxTime) {
        const maxPv = satellite.propagate(satrec, pass.maxTime);
        if (maxPv.position && typeof maxPv.position !== 'boolean') {
            const maxGmst = satellite.gstime(pass.maxTime);
            const maxGd = satellite.eciToGeodetic(maxPv.position, maxGmst);
            const maxLng = satellite.degreesLong(maxGd.longitude);
            const maxLat = satellite.degreesLat(maxGd.latitude);

            const maxMarker = L.circleMarker([maxLat, maxLng], {
                radius: 9,
                color: '#FFD600',
                fillColor: '#FFD600',
                fillOpacity: 0.9,
                weight: 3,
            }).bindTooltip('最高点 (' + formatPassTime(pass.maxTime) + ')\n最大仰角: ' + pass.maxElevation.toFixed(1) + '°', { sticky: true });
            satPassLayer.addLayer(maxMarker);
        }
    }

    // 更新观察者标记
    updateObserverMarker(observerLat, observerLng);

    // 飞到轨迹区域
    if (trackPoints.length > 0) {
        const bounds = L.latLngBounds(trackPoints);
        bounds.extend([observerLat, observerLng]);
        map.fitBounds(bounds, { padding: [50, 50] });
    }
}

/**
 * 清除过境图层
 */
function clearSatPassLayers() {
    if (satPassLayer) {
        map.removeLayer(satPassLayer);
        satPassLayer = null;
    }
    if (satPassObserverMarker) {
        map.removeLayer(satPassObserverMarker);
        satPassObserverMarker = null;
    }
    const resultEl = document.getElementById('sp-result');
    if (resultEl) resultEl.innerHTML = '';

    // 清除提醒
    satPassReminders.forEach(function(r) { clearTimeout(r.timer); });
    satPassReminders = [];
}

// ============================================================
// 过境提醒
// ============================================================

/**
 * 设置过境提醒 (提前 X 分钟通知)
 */
function setPassReminder(idx, btn) {
    if (idx < 0 || idx >= satPassPredictions.length) {
        showToast('无效的过境记录', 'error');
        return;
    }

    const pass = satPassPredictions[idx];

    // 检查是否已设置
    const existing = satPassReminders.find(function(r) { return r.passIdx === idx; });
    if (existing) {
        clearTimeout(existing.timer);
        satPassReminders = satPassReminders.filter(function(r) { return r.passIdx !== idx; });
        if (btn) {
            btn.classList.remove('set');
            btn.textContent = '⏰ 提醒';
        }
        showToast('已取消该过境提醒', 'info');
        return;
    }

    // 弹出选择提前分钟数的表单
    const bodyHtml =
        '<div class="flight-plan-form">' +
            '<div class="form-field">' +
                '<label class="form-field-label">提前提醒时间</label>' +
                '<select class="form-select" id="reminder-minutes">' +
                    '<option value="1">提前 1 分钟</option>' +
                    '<option value="5" selected>提前 5 分钟</option>' +
                    '<option value="10">提前 10 分钟</option>' +
                    '<option value="15">提前 15 分钟</option>' +
                    '<option value="30">提前 30 分钟</option>' +
                '</select>' +
            '</div>' +
            '<div style="font-size:12px;color:var(--text-muted);line-height:1.6;">' +
                '过境开始时间: <strong style="color:var(--text-secondary);">' + formatPassTime(pass.startTime) + '</strong><br>' +
                '最大仰角: <strong style="color:#00E5FF;">' + pass.maxElevation.toFixed(1) + '°</strong><br>' +
                '<span style="color:var(--text-muted);">注意: 请保持页面打开以接收提醒</span>' +
            '</div>' +
        '</div>';

    const footerHtml =
        '<button class="premium-btn" onclick="closeModal()">取消</button>' +
        '<button class="premium-btn primary" onclick="confirmPassReminder(' + idx + ')">设置提醒</button>';

    openPremiumModal('⏰ 过境提醒设置', bodyHtml, footerHtml);
}

/**
 * 确认设置过境提醒
 */
function confirmPassReminder(idx) {
    if (idx < 0 || idx >= satPassPredictions.length) return;

    const pass = satPassPredictions[idx];
    const minutesSelect = document.getElementById('reminder-minutes');
    const minutes = minutesSelect ? parseInt(minutesSelect.value, 10) : 5;

    const reminderTime = new Date(pass.startTime.getTime() - minutes * 60 * 1000);
    const now = new Date();

    if (reminderTime <= now) {
        showToast('该过境即将开始或已过，无法设置提醒', 'error');
        closeModal();
        return;
    }

    const delay = reminderTime.getTime() - now.getTime();

    const timer = setTimeout(function() {
        const satName = satPassCurrentSatellite ?
            ((typeof getSatelliteNameCN === 'function') ? getSatelliteNameCN(satPassCurrentSatellite.name) : satPassCurrentSatellite.name) : '卫星';
        showToast('🛰️ ' + satName + ' 即将在 ' + minutes + ' 分钟后过境！最大仰角: ' + pass.maxElevation.toFixed(1) + '°', 'info');

        // 浏览器通知 (如果已授权)
        if ('Notification' in window && Notification.permission === 'granted') {
            new Notification('🛰️ 卫星过境提醒', {
                body: satName + ' 即将在 ' + minutes + ' 分钟后过境！\n最大仰角: ' + pass.maxElevation.toFixed(1) + '°\n方向: ' + (pass.direction || 'N/A'),
            });
        }

        // 清除已触发的提醒
        satPassReminders = satPassReminders.filter(function(r) { return r.passIdx !== idx; });
    }, delay);

    satPassReminders.push({
        passIdx: idx,
        timer: timer,
        minutes: minutes,
        passStartTime: pass.startTime,
    });

    closeModal();

    // 更新按钮状态
    const btn = document.querySelector('.pass-reminder-btn');
    // 通过 idx 找到对应按钮
    const rows = document.querySelectorAll('.satellite-pass-table tbody tr');
    rows.forEach(function(row) {
        if (parseInt(row.dataset.idx, 10) === idx) {
            const btnEl = row.querySelector('.pass-reminder-btn');
            if (btnEl) {
                btnEl.classList.add('set');
                btnEl.textContent = '✓ 已设';
            }
        }
    });

    showToast('已设置提醒: 提前 ' + minutes + ' 分钟', 'success');

    // 请求浏览器通知权限
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission();
    }
}

// ============================================================
// 初始化
// ============================================================

// 在 CSS 中定义 observerPulse 动画 (通过 style 注入)
(function injectObserverPulseStyle() {
    const style = document.createElement('style');
    style.textContent =
        '@keyframes observerPulse {' +
            '0%, 100% { transform: translate(-50%,-50%) scale(1); opacity: 0.4; }' +
            '50% { transform: translate(-50%,-50%) scale(1.5); opacity: 0; }' +
        '}';
    document.head.appendChild(style);
})();

document.addEventListener('DOMContentLoaded', function() {
    setTimeout(initSatellitePass, 700);
});
