const CACHE_NAME = 'fussball-mathe-v14';

const CORE_FILES = [
  './',
  './index.html',
  './players.json',
  './manifest.webmanifest',
  './apple-touch-icon.png'
];

self.addEventListener('install', event => {
  self.skipWaiting();

  event.waitUntil(
    caches.open(CACHE_NAME).then(async cache => {
      // Einzelnes Cachen, damit eine fehlende optionale Datei
      // nicht die komplette Installation des Service Workers stoppt.
      await Promise.allSettled(
        CORE_FILES.map(file => cache.add(file))
      );
    })
  );
});

self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(key => key !== CACHE_NAME)
          .map(key => caches.delete(key))
      )
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;

  // Für Seitenaufrufe zuerst im Internet nach der neuesten Version suchen.
  // Falls das nicht klappt, wird die gespeicherte Offline-Version genommen.
  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then(response => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put('./index.html', copy));
          return response;
        })
        .catch(() =>
          caches.match(event.request).then(r => r || caches.match('./index.html'))
        )
    );
    return;
  }

  const url = new URL(event.request.url);

  // players.json immer zuerst aus dem Internet laden.
  // So werden neue Cartoon-Links sofort übernommen.
  if (url.origin === self.location.origin && url.pathname.endsWith('/players.json')) {
    event.respondWith(
      fetch(event.request, { cache: 'no-store' })
        .then(response => {
          if (response && response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
          }
          return response;
        })
        .catch(() => caches.match(event.request))
    );
    return;
  }

  // Für andere lokale Dateien: Cache benutzen und parallel aktualisieren.
  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(event.request).then(cached => {
        const network = fetch(event.request)
          .then(response => {
            if (response && response.ok) {
              const copy = response.clone();
              caches.open(CACHE_NAME).then(cache => cache.put(event.request, copy));
            }
            return response;
          })
          .catch(() => cached);

        return cached || network;
      })
    );
  }
});
