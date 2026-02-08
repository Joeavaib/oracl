(() => {
  const onReady = (fn) => {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
      return;
    }
    fn();
  };

  onReady(() => {
    const providerInput = document.getElementById("provider");
    const tabButtons = document.querySelectorAll(".tab-button");
    const tabPanels = document.querySelectorAll(".tab-panel");
    const openaiProviderSelect = document.getElementById(
      "openai-provider-select",
    );
    const ollamaBaseUrlInput = document.querySelector(
      "[data-provider='ollama'] [name='base_url']",
    );

    if (!providerInput || tabButtons.length === 0 || tabPanels.length === 0) {
      return;
    }

    const providerToTab = (provider) => {
      if (provider === "llamacpp") return "llamacpp";
      if (provider === "ollama") return "ollama";
      if (provider === "openai-compatible" || provider === "vllm")
        return "openai";
      return "ollama";
    };

    const setTab = (tab) => {
      tabButtons.forEach((button) => {
        button.classList.toggle("is-active", button.dataset.provider === tab);
      });
      tabPanels.forEach((panel) => {
        const isActive = panel.dataset.provider === tab;
        panel.classList.toggle("is-active", isActive);
        panel
          .querySelectorAll("input, select, textarea, button")
          .forEach((el) => {
            if (el.type === "button") {
              return;
            }
            el.disabled = !isActive;
          });
      });
      if (tab === "openai") {
        providerInput.value =
          openaiProviderSelect?.value || "openai-compatible";
      } else if (tab === "ollama") {
        providerInput.value = tab;
        if (ollamaBaseUrlInput && !ollamaBaseUrlInput.value) {
          ollamaBaseUrlInput.value = "http://127.0.0.1:11434";
        }
      } else {
        providerInput.value = tab;
      }
    };

    tabButtons.forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        setTab(button.dataset.provider);
      });
    });

    openaiProviderSelect?.addEventListener("change", () => {
      providerInput.value = openaiProviderSelect.value;
    });

    setTab(providerToTab(providerInput.value));
  });
})();
