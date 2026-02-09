(() => {
  const providerGroup = (provider) => {
    if (provider === "ollama") return "ollama";
    if (provider === "llamacpp") return "llamacpp";
    if (provider === "openai-compatible" || provider === "vllm") return "openai";
    return "other";
  };

  const onReady = (fn) => {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
      return;
    }
    fn();
  };

  onReady(() => {
    const tabButtons = document.querySelectorAll(".tab-button[data-provider]");
    const roleFilter = document.getElementById("models-role-filter");
    const rows = document.querySelectorAll("tbody tr[data-provider]");

    if (!tabButtons.length || !rows.length) {
      return;
    }

    const applyFilters = () => {
      const activeButton = document.querySelector(".tab-button.is-active");
      const activeProvider = activeButton?.dataset.provider || "all";
      const roleValue = roleFilter?.value || "";

      rows.forEach((row) => {
        const rowRole = row.dataset.role || "";
        const rowProvider = row.dataset.provider || "";
        const matchesRole = !roleValue || rowRole === roleValue;
        const matchesProvider =
          activeProvider === "all" ||
          providerGroup(rowProvider) === activeProvider;
        row.hidden = !(matchesRole && matchesProvider);
      });
    };

    tabButtons.forEach((button) => {
      button.addEventListener("click", () => {
        tabButtons.forEach((btn) =>
          btn.classList.toggle("is-active", btn === button),
        );
        applyFilters();
      });
    });

    roleFilter?.addEventListener("change", applyFilters);

    applyFilters();
  });
})();
