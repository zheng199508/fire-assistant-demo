const CACHE_VERSION = "fire-assistant-v6-install-help";
const SHELL = [
  "./",
  "./index.html",
  "./styles.css",
  "./app.js",
  "./worker.js",
  "./manifest.webmanifest",
  "./icons/icon.svg",
  "./runtime/runtime-manifest.json",
  "./vendor/pyodide/pyodide.js",
  "./vendor/pyodide/pyodide.asm.js",
  "./vendor/pyodide/pyodide.asm.wasm",
  "./vendor/pyodide/python_stdlib.zip",
  "./vendor/pyodide/pyodide-lock.json",
];

function absolute(path) {
  return new URL(path, self.registration.scope).href;
}

self.addEventListener("install", (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE_VERSION);
    await cache.addAll(SHELL.map(absolute));
    try {
      const manifestUrl = absolute("./runtime/runtime-manifest.json");
      const manifest = await (await fetch(manifestUrl, { cache: "no-cache" })).json();
      await Promise.allSettled(
        manifest.files.map((item) => cache.add(absolute(`./runtime/${item.path}`))),
      );
    } catch (error) {
      // The shell remains usable; runtime fetches will be cached on use.
      console.warn("Runtime precache incomplete", error);
    }
    await self.skipWaiting();
  })());
});

self.addEventListener("activate", (event) => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter((key) => key !== CACHE_VERSION).map((key) => caches.delete(key)));
    await self.clients.claim();
  })());
});

async function cacheFirst(request) {
  const cache = await caches.open(CACHE_VERSION);
  const cached = await cache.match(request);
  if (cached) return cached;
  const response = await fetch(request);
  if (response.ok || response.type === "opaque") await cache.put(request, response.clone());
  return response;
}

self.addEventListener("fetch", (event) => {
  if (event.request.method !== "GET") return;
  const url = new URL(event.request.url);
  const sameOrigin = url.origin === self.location.origin;

  if (event.request.mode === "navigate") {
    event.respondWith(
      fetch(event.request)
        .then(async (response) => {
          const cache = await caches.open(CACHE_VERSION);
          await cache.put(event.request, response.clone());
          return response;
        })
        .catch(() => caches.match(absolute("./index.html"))),
    );
    return;
  }
  if (sameOrigin) event.respondWith(cacheFirst(event.request));
});
