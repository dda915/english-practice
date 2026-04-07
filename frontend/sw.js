// 最低限のService Worker（PWA要件を満たすためのもの。キャッシュは行わず常にネットワーク優先）
self.addEventListener('install', (e) => { self.skipWaiting(); });
self.addEventListener('activate', (e) => { e.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', (e) => { /* pass-through */ });
