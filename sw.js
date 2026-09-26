// 부산 파고 PWA 서비스워커 — 홈화면 설치 + 앱 셸 오프라인 캐시
// 지도 타일·파고 데이터는 항상 네트워크에서(최신), 셸(html/manifest/icon)만 캐시.
const SHELL = 'busan-wave-shell-v2';
const SHELL_FILES = ['./', './index.html', './manifest.json', './icons/icon-192.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(SHELL).then((c) => c.addAll(SHELL_FILES)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== SHELL).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const url = new URL(e.request.url);
  // 지도 타일·API·외부 데이터는 캐시하지 않고 네트워크 우선(최신 파고/위치).
  const isShell = url.origin === location.origin &&
                  (url.pathname.endsWith('/') || url.pathname.endsWith('index.html') ||
                   url.pathname.endsWith('manifest.json') || url.pathname.includes('/icons/'));
  if (isShell) {
    e.respondWith(caches.match(e.request).then((r) => r || fetch(e.request)));
  }
  // 그 외(타일·데이터)는 기본 네트워크 동작에 맡김
});
