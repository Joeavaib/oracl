(() => {
  const onReady = (fn) => {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fn, { once: true });
      return;
    }
    fn();
  };

  onReady(() => {
    const startButton = document.getElementById("llamacpp-start");
    const stopButton = document.getElementById("llamacpp-stop");
    const useButton = document.getElementById("llamacpp-use-endpoint");
    const statusEl = document.getElementById("llamacpp-runtime-status");
    const healthEl = document.getElementById("llamacpp-health-status");
    const runningListEl = document.getElementById("llamacpp-running-list");
    const instanceInput = document.getElementById("llamacpp-instance-id");
    const modelPathInput = document.querySelector(
      "[data-provider='llamacpp'] [name='model_path']",
    );
    const binaryPathInput = document.querySelector(
      "[data-provider='llamacpp'] [name='llamacpp_binary_path']",
    );
    const ctxSizeInput = document.querySelector(
      "[data-provider='llamacpp'] [name='ctx_size']",
    );
    const threadsInput = document.querySelector(
      "[data-provider='llamacpp'] [name='threads']",
    );
    const roleInput = document.querySelector("[name='role']");
    const baseUrlInput = document.querySelector(
      "[data-provider='llamacpp'] [name='base_url']",
    );

    if (!statusEl) {
      return;
    }

    const setStatus = (text, isError = false) => {
      statusEl.textContent = text;
      statusEl.classList.toggle("warning", isError);
      statusEl.classList.toggle("hint", !isError);
    };

    const setHealth = (text, isError = false) => {
      if (!healthEl) {
        return;
      }
      healthEl.textContent = text;
      healthEl.classList.toggle("warning", isError);
      healthEl.classList.toggle("hint", !isError);
    };

    const renderRunningList = (instances = []) => {
      if (!runningListEl) {
        return;
      }
      if (!instances.length) {
        runningListEl.textContent = "Keine laufenden Instanzen.";
        return;
      }
      const items = instances
        .map(
          (entry) => `${entry.role || "role"} @ ${entry.base_url || "unknown"}`,
        )
        .join(" · ");
      runningListEl.textContent = `Running: ${items}`;
    };

    const fetchJson = async (url, options = {}) => {
      const response = await fetch(url, options);
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const detail = payload.detail || response.statusText;
        throw new Error(detail);
      }
      return payload;
    };

    const getRunningInstance = (instances) => {
      const role = roleInput?.value;
      return (
        instances.find(
          (entry) => entry.status === "running" && entry.role === role,
        ) || instances.find((entry) => entry.status === "running")
      );
    };

    const refreshRunning = async () => {
      try {
        const list = await fetchJson("/api/runtimes/llamacpp/list");
        const instances = (list.instances || []).filter(
          (entry) => entry.status === "running",
        );
        renderRunningList(instances);
        return instances;
      } catch (error) {
        renderRunningList([]);
        return [];
      }
    };

    const refreshHealth = async (targetBaseUrl) => {
      if (!targetBaseUrl) {
        setHealth("Healthcheck: keine base_url.", true);
        return;
      }
      try {
        const params = new URLSearchParams({ base_url: targetBaseUrl });
        const result = await fetchJson(
          `/api/runtimes/llamacpp/health?${params.toString()}`,
        );
        if (result.ok) {
          setHealth("Healthcheck: OK");
        } else {
          setHealth(`Healthcheck: ${result.error || "FAIL"}`, true);
        }
      } catch (error) {
        setHealth(`Healthcheck: ${error.message}`, true);
      }
    };

    startButton?.addEventListener("click", async () => {
      if (!modelPathInput?.value) {
        setStatus("Bitte zuerst einen Model Path angeben.", true);
        return;
      }
      try {
        const payload = {
          model_path: modelPathInput.value,
          role: roleInput?.value,
        };
        if (binaryPathInput?.value) {
          payload.binary_path = binaryPathInput.value;
        }
        if (ctxSizeInput?.value) {
          payload.ctx_size = Number(ctxSizeInput.value);
        }
        if (threadsInput?.value) {
          payload.threads = Number(threadsInput.value);
        }
        const data = await fetchJson("/api/runtimes/llamacpp/start", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        instanceInput.value = data.id || "";
        statusEl.dataset.baseUrl = data.base_url || "";
        setStatus(`Gestartet auf ${data.base_url || "unknown"}.`);
        await refreshRunning();
        await refreshHealth(data.base_url);
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    stopButton?.addEventListener("click", async () => {
      try {
        let instanceId = instanceInput.value;
        if (!instanceId) {
          const list = await fetchJson("/api/runtimes/llamacpp/list");
          const running = getRunningInstance(list.instances || []);
          instanceId = running?.id || "";
        }
        if (!instanceId) {
          setStatus("Keine laufende Instanz gefunden.", true);
          return;
        }
        await fetchJson("/api/runtimes/llamacpp/stop", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ instance_id: instanceId }),
        });
        instanceInput.value = "";
        statusEl.dataset.baseUrl = "";
        setStatus("Instanz gestoppt.");
        await refreshRunning();
        setHealth("Healthcheck: keine base_url.");
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    useButton?.addEventListener("click", async () => {
      try {
        let baseUrl = statusEl.dataset.baseUrl || "";
        if (!baseUrl) {
          const list = await fetchJson("/api/runtimes/llamacpp/list");
          const running = getRunningInstance(list.instances || []);
          baseUrl = running?.base_url || "";
          statusEl.dataset.baseUrl = baseUrl;
        }
        if (!baseUrl) {
          setStatus("Keine laufende Instanz gefunden.", true);
          return;
        }
        if (baseUrlInput) {
          baseUrlInput.value = baseUrl;
        }
        setStatus(`base_url gesetzt: ${baseUrl}`);
        await refreshHealth(baseUrl);
      } catch (error) {
        setStatus(error.message, true);
      }
    });

    refreshRunning();
  });
})();
