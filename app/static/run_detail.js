(() => {
  const onReady = (fn) => {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
      return;
    }
    fn();
  };

  onReady(() => {
    document.addEventListener("click", (event) => {
      const target = event.target.closest(".tmp-s-path");
      if (!target) return;
      const path = target.dataset.path;
      if (!path) return;
      const scopeItems = document.querySelectorAll(".scope-item");
      scopeItems.forEach((item) => {
        item.classList.toggle("highlight", item.dataset.path === path);
      });
    });
  });
})();
