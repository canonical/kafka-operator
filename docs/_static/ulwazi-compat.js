// Mirror Ulwazi's resolved theme for Mermaid and the vendored brand overlay.
// Only observe classes: updating data-theme must not retrigger the observer.
(() => {
  const root = document.documentElement;
  const syncTheme = () => {
    const theme = root.classList.contains("is-dark") ? "dark" : "light";
    root.dataset.theme = theme;
    document.body.dataset.theme = theme;
  };

  syncTheme();
  new MutationObserver(syncTheme).observe(root, {
    attributes: true,
    attributeFilter: ["class"],
  });
})();
