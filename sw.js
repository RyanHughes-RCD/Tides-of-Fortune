// Service worker: keeps Tides of Fortune on the phone so it plays offline.
// The version below changes with every build, which is how phones learn an update exists.
const CACHE = 'tof-1.8.0-b0888653';
const CORE = ['./', './index.html', './manifest.webmanifest', './icon-180.png', './icon-192.png', './icon-512.png', './icon-maskable-512.png'];

self.addEventListener('install', e => {
  // cache: 'reload' skips the browser's HTTP cache, so an update never stores yesterday's files
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(CORE.map(u => new Request(u, { cache: 'reload' })))));
});

self.addEventListener('activate', e => {
  e.waitUntil(caches.keys()
    .then(keys => Promise.all(keys.filter(k => k.startsWith('tof-') && k !== CACHE && k !== 'tof-fonts').map(k => caches.delete(k))))
    .then(() => self.clients.claim()));
});

// The page asks the waiting version to take over when the player taps "restart".
self.addEventListener('message', e => { if (e.data === 'skipWaiting') self.skipWaiting(); });

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.hostname.endsWith('open-meteo.com')) return; // live weather always goes to the network
  if (url.origin === self.location.origin) {
    // the game itself: from the phone first, so it opens instantly and offline
    e.respondWith(
      caches.match(req, { ignoreSearch: true }).then(hit => hit || fetch(req).then(res => {
        if (res.ok) { const copy = res.clone(); caches.open(CACHE).then(c => c.put(req, copy)); }
        return res;
      }).catch(() => (req.mode === 'navigate' ? caches.match('./index.html') : Response.error())))
    );
    return;
  }
  if (url.hostname === 'fonts.googleapis.com' || url.hostname === 'fonts.gstatic.com') {
    // the pixel font: saved after the first online visit
    e.respondWith(caches.open('tof-fonts').then(c => c.match(req).then(hit => hit || fetch(req).then(res => { c.put(req, res.clone()); return res; }).catch(() => Response.error()))));
  }
});
