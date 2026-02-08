(() => {
  const DEFAULT_TRIGGER = "click";
  if (!window.htmx) {
    window.htmx = { version: "local" };
  }

  const parseTriggers = (value) => {
    if (!value) {
      return [DEFAULT_TRIGGER];
    }
    return value
      .split(",")
      .map((entry) => entry.trim())
      .filter(Boolean);
  };

  const collectParams = (selector) => {
    if (!selector) {
      return new URLSearchParams();
    }
    const params = new URLSearchParams();
    document.querySelectorAll(selector).forEach((el) => {
      if (!el || el.disabled) {
        return;
      }
      const name = el.getAttribute("name");
      if (!name) {
        return;
      }
      if (el.type === "checkbox" || el.type === "radio") {
        if (!el.checked) {
          return;
        }
      }
      params.append(name, el.value ?? "");
    });
    return params;
  };

  const resolveTarget = (el) => {
    const targetSelector = el.getAttribute("hx-target");
    if (targetSelector) {
      return document.querySelector(targetSelector);
    }
    return el;
  };

  const applySwap = (target, swap, html) => {
    if (!target) {
      return;
    }
    if (swap === "outerHTML") {
      target.outerHTML = html;
      return;
    }
    target.innerHTML = html;
  };

  const resolveIndicator = () => {
    const selector = document.body?.getAttribute("hx-indicator");
    if (!selector) {
      return null;
    }
    return document.querySelector(selector);
  };

  const emitAfterRequest = (verb, path) => {
    const event = new CustomEvent("htmx:afterRequest", {
      detail: { requestConfig: { verb, path } },
    });
    document.body?.dispatchEvent(event);
  };

  const requestFor = async (el) => {
    const url = el.getAttribute("hx-get");
    if (!url) {
      return;
    }
    const params = collectParams(el.getAttribute("hx-include"));
    const target = resolveTarget(el);
    const swap = el.getAttribute("hx-swap") || "innerHTML";
    let finalUrl = url;
    if (params.toString()) {
      const joiner = url.includes("?") ? "&" : "?";
      finalUrl = `${url}${joiner}${params.toString()}`;
    }

    const indicator = resolveIndicator();
    indicator?.classList.add("htmx-request");
    try {
      const response = await fetch(finalUrl, {
        headers: {
          "HX-Request": "true",
        },
      });
      const text = await response.text();
      if (!response.ok) {
        applySwap(
          target,
          swap,
          `<div class=\"warning\">${text || response.statusText}</div>`,
        );
        return;
      }
      applySwap(target, swap, text);
    } catch (error) {
      applySwap(target, swap, `<div class=\"warning\">${error.message}</div>`);
    } finally {
      indicator?.classList.remove("htmx-request");
      emitAfterRequest("get", finalUrl);
    }
  };

  const setupElement = (el) => {
    const triggers = parseTriggers(el.getAttribute("hx-trigger"));
    triggers.forEach((trigger) => {
      if (trigger === "load") {
        if (document.readyState === "loading") {
          document.addEventListener("DOMContentLoaded", () => requestFor(el), {
            once: true,
          });
        } else {
          requestFor(el);
        }
        return;
      }
      if (trigger.startsWith("every ")) {
        const raw = trigger.replace("every ", "").trim();
        const match = raw.match(/^(\d+(?:\.\d+)?)(ms|s)?$/);
        if (!match) {
          return;
        }
        const value = Number(match[1]);
        const unit = match[2] || "ms";
        const interval = unit === "s" ? value * 1000 : value;
        setInterval(() => requestFor(el), interval);
        return;
      }
      el.addEventListener(trigger, (event) => {
        if (trigger === "click" && el.tagName === "A") {
          event.preventDefault();
        }
        requestFor(el);
      });
    });
  };

  const boot = () => {
    document.querySelectorAll("[hx-get]").forEach(setupElement);
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
