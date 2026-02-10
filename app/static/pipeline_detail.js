const parseModelsIndex = () => {
  const indexNode = document.getElementById("models-index");
  if (!indexNode) {
    return null;
  }
  try {
    return JSON.parse(indexNode.textContent || "{}");
  } catch (error) {
    console.error("Failed to parse models index", error);
    return null;
  }
};

const formatModelLabel = (model) => {
  const id = model.id || "";
  const provider = model.provider || "-";
  const name = model.model_name || "-";
  return `${id} — (${provider}: ${name})`;
};

const buildOptions = (selectElement, models, selectedId) => {
  selectElement.innerHTML = "";
  const emptyOption = document.createElement("option");
  emptyOption.value = "";
  selectElement.appendChild(emptyOption);
  const sorted = [...models].sort((left, right) =>
    String(left.id || "").localeCompare(String(right.id || ""))
  );

  sorted.forEach((model) => {
    if (!model.id) {
      return;
    }
    const option = document.createElement("option");
    option.value = model.id;
    option.textContent = formatModelLabel(model);
    selectElement.appendChild(option);
  });
  if (selectedId) {
    selectElement.value = selectedId;
  }
};

const updateRowOptions = (row, modelsIndex) => {
  const roleInput = row.querySelector(".role-input");
  const modelSelect = row.querySelector(".model-id-select");
  const missingLabel = row.querySelector(".missing-model-label");
  if (!roleInput || !modelSelect) {
    return;
  }
  const rawSuggestions = modelSelect.dataset.missingSuggestions || "";
  const suggestions = rawSuggestions
    .split(",")
    .map((value) => value.trim())
    .filter(Boolean);

  const role = roleInput.value.trim();
  const normalizedRole = role.toLowerCase();
  const selectedId = modelSelect.dataset.currentModelId || modelSelect.value;
  let modelsForRole = modelsIndex.all || [];
  if (normalizedRole) {
    const entries = Object.entries(modelsIndex.by_role || {});
    const matchingEntry = entries.find(
      ([roleKey]) => String(roleKey || "").toLowerCase() === normalizedRole
    );
    modelsForRole = matchingEntry ? matchingEntry[1] || [] : [];
  }

  const modelIds = new Set(modelsForRole.map((model) => model.id));
  buildOptions(modelSelect, modelsForRole, selectedId);

  let hasMissing = false;
  if (selectedId && !modelIds.has(selectedId)) {
    const missingOption = document.createElement("option");
    missingOption.value = selectedId;
    missingOption.textContent = `⚠ missing: ${selectedId}`;
    modelSelect.insertBefore(missingOption, modelSelect.firstChild);
    modelSelect.value = selectedId;
    hasMissing = true;
  }

  row.classList.toggle("model-missing", hasMissing);
  if (missingLabel) {
    if (hasMissing) {
      const suggestionText = suggestions.length
        ? ` (Vorschläge: ${suggestions.join(", ")})`
        : "";
      missingLabel.textContent = `⚠ missing: ${selectedId}${suggestionText}`;
      missingLabel.hidden = false;
    } else {
      missingLabel.textContent = "";
      missingLabel.hidden = true;
    }
  }
};

document.addEventListener("DOMContentLoaded", () => {
  const modelsIndex = parseModelsIndex();
  if (!modelsIndex) {
    return;
  }

  const rows = document.querySelectorAll("[data-step-row]");
  rows.forEach((row) => updateRowOptions(row, modelsIndex));

  rows.forEach((row) => {
    const roleInput = row.querySelector(".role-input");
    const modelSelect = row.querySelector(".model-id-select");
    if (roleInput) {
      roleInput.addEventListener("input", () => updateRowOptions(row, modelsIndex));
      roleInput.addEventListener("change", () => updateRowOptions(row, modelsIndex));
    }
    if (modelSelect) {
      modelSelect.addEventListener("change", () => {
        modelSelect.dataset.currentModelId = modelSelect.value;
        if (modelSelect.value) {
          modelSelect.dataset.missingSuggestions = "";
        }
        updateRowOptions(row, modelsIndex);
      });
    }
  });
});
