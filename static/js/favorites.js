/**
 * 航空通 - 收藏夹模块
 * 使用 localStorage 持久化收藏的 NOTAM 和发射任务
 */

// ============================================================
// 全局状态
// ============================================================
let favorites = { notams: [], launches: [] };

// ============================================================
// 初始化
// ============================================================
function initFavorites() {
    loadFavorites();
}

/**
 * 从 localStorage 加载收藏
 */
function loadFavorites() {
    try {
        const stored = localStorage.getItem('aviation_favorites');
        if (stored) {
            favorites = JSON.parse(stored);
            if (!favorites.notams) favorites.notams = [];
            if (!favorites.launches) favorites.launches = [];
        }
    } catch (e) {
        console.error('加载收藏失败:', e);
        favorites = { notams: [], launches: [] };
    }
}

/**
 * 保存收藏到 localStorage
 */
function saveFavorites() {
    try {
        localStorage.setItem('aviation_favorites', JSON.stringify(favorites));
    } catch (e) {
        console.error('保存收藏失败:', e);
    }
}

/**
 * 切换 NOTAM 收藏
 */
function toggleNotamFavorite(code) {
    if (!code) return;
    const idx = favorites.notams.indexOf(code);
    if (idx >= 0) {
        favorites.notams.splice(idx, 1);
    } else {
        favorites.notams.push(code);
    }
    saveFavorites();
    renderFavoriteList();
}

/**
 * 切换发射任务收藏
 */
function toggleLaunchFavorite(slug) {
    if (!slug) return;
    const idx = favorites.launches.indexOf(slug);
    if (idx >= 0) {
        favorites.launches.splice(idx, 1);
    } else {
        favorites.launches.push(slug);
    }
    saveFavorites();
    renderFavoriteList();
}

/**
 * 检查是否已收藏
 */
function isNotamFavorited(code) {
    return favorites.notams.includes(code);
}

function isLaunchFavorited(slug) {
    return favorites.launches.includes(slug);
}

/**
 * 渲染收藏列表
 */
function renderFavoriteList() {
    const container = document.getElementById('favorite-list');
    if (!container) return;

    const total = favorites.notams.length + favorites.launches.length;
    if (total === 0) {
        container.innerHTML = '<div class="notam-empty">暂无收藏</div>';
        return;
    }

    const fragment = document.createDocumentFragment();

    // 收藏的 NOTAM
    for (const code of favorites.notams) {
        const feature = allFeatures.find(f =>
            ((f.properties || {}).notam_code || '') === code);
        if (!feature) continue;
        const props = feature.properties || {};
        const type = props.type || 'other';
        const config = TYPE_CONFIG[type] || TYPE_CONFIG.other;

        const card = document.createElement('div');
        card.className = 'notam-card favorite-card';
        card.style.borderLeftColor = config.color;
        card.innerHTML = `
            <div class="notam-code">${escapeHtml(props.notam_code || 'N/A')}</div>
            <div class="notam-type">${escapeHtml(config.name)}</div>
            <span class="notam-fir">${escapeHtml(props.fir || '')}</span>
            <button class="btn-unfavorite" onclick="toggleNotamFavorite('${escapeHtml(props.notam_code)}')" title="取消收藏">✕</button>
        `;
        card.addEventListener('click', (e) => {
            if (e.target.classList.contains('btn-unfavorite')) return;
            const geometry = feature.geometry;
            if (geometry && geometry.type === 'Polygon') {
                const coords = geometry.coordinates[0];
                const latlngs = coords.map(c => [c[1], c[0]]);
                map.fitBounds(L.latLngBounds(latlngs), { padding: [50, 50] });
            }
        });
        fragment.appendChild(card);
    }

    // 收藏的发射任务
    for (const slug of favorites.launches) {
        const feature = allLaunches.find(f =>
            ((f.properties || {}).slug || (f.properties || {}).name || '') === slug);
        if (!feature) continue;
        const props = feature.properties || {};

        const card = document.createElement('div');
        card.className = 'launch-card favorite-card';
        card.style.borderLeftColor = '#FFD700';
        card.innerHTML = `
            <div class="launch-name">${getFlag(props.country_code)} ${escapeHtml(props.rocket_cn || props.rocket || 'N/A')}</div>
            <div class="launch-time">⏰ ${escapeHtml(props.net_display || 'N/A')}</div>
            <button class="btn-unfavorite" onclick="toggleLaunchFavorite('${escapeHtml(slug)}')" title="取消收藏">✕</button>
        `;
        card.addEventListener('click', (e) => {
            if (e.target.classList.contains('btn-unfavorite')) return;
            const geometry = feature.geometry;
            if (geometry && geometry.type === 'Point') {
                const [lon, lat] = geometry.coordinates;
                map.setView([lat, lon], 6, { animate: true });
            }
        });
        fragment.appendChild(card);
    }

    container.innerHTML = '';
    container.appendChild(fragment);
}
