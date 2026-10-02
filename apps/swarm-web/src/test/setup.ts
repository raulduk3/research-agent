// jsdom draws nothing: a canvas without a 2d context leaves the globe unpainted, as the page allows.
HTMLCanvasElement.prototype.getContext = (() => null) as typeof HTMLCanvasElement.prototype.getContext;

// Newer Node runtimes define a `localStorage` of their own that is unset without a backing file,
// and it hides jsdom's. The tests get a plain in-memory one in that case.
if (typeof globalThis.localStorage === "undefined") {
  const items = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return items.size;
    },
    clear: () => items.clear(),
    getItem: (key) => items.get(key) ?? null,
    key: (index) => [...items.keys()][index] ?? null,
    removeItem: (key) => void items.delete(key),
    setItem: (key, value) => void items.set(key, String(value)),
  };
  Object.defineProperty(globalThis, "localStorage", { value: storage, configurable: true });
}
