/**
 * 航空通 - PWA 注册
 */
function initPWA() {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('sw.js?v=19')
            .then(reg => {
                console.log('PWA Service Worker 已注册');
            })
            .catch(err => {
                console.warn('SW 注册失败:', err);
            });
    }
}
