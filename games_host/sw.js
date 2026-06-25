/* PlayStudy games service worker — offline play on the web target.
 *
 * Caches the SDK and versioned game bundles cache-first. Bundle paths are
 * immutable (/games/<slug>/<version>/…), so a cached response is always valid
 * for that URL — a new version is a new path. After a game has been opened
 * once online, it plays offline.
 *
 * Served from the games-host root so its scope covers /games/* and the SDK.
 * Registered by playstudy-sdk.js on the web origin (skipped on the native
 * local server, which caches via the app instead).
 */
const CACHE = "playstudy-games-v1";

self.addEventListener("activate", (event) => {
  // Drop old caches if the SW itself is bumped.
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
});

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  const cacheable =
    url.pathname === "/playstudy-sdk.js" || url.pathname.startsWith("/games/");
  if (!cacheable) return;

  event.respondWith(
    (async () => {
      const cache = await caches.open(CACHE);
      const cached = await cache.match(event.request);
      if (cached) return cached;
      try {
        const resp = await fetch(event.request);
        if (resp.ok) cache.put(event.request, resp.clone());
        return resp;
      } catch (e) {
        const fallback = await cache.match(event.request);
        if (fallback) return fallback;
        throw e;
      }
    })()
  );
});
