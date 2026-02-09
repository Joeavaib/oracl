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

const buildOptions = (listElement, models) => {
  listElement.innerHTML = "";
  const sorted = [...models].sort((left, right) =>
    String(left.id || "").localeCompare(String(right.id || ""))
  );

  sorted.forEach((model) => {
    if (!model.id) {
      return;
    }
    const option = document.createElement("option");
    option.value = model.id;
    option.label = model.id;
    listElement.appendChild(option);
  });
};

const updateRowOptions = (row, modelsIndex) => {
  const roleInput = row.querySelector(".role-input");
  const modelInput = row.querySelector(".model-id-input");
  const dataList = row.querySelector("datalist");
  const missingLabel = row.querySelector(".missing-model-label");
  if (!roleInput || !modelInput || !dataList) {
    return;
  }

  const role = roleInput.value.trim();
  const selectedId = modelInput.dataset.currentModelId || modelInput.value;
  const modelsForRole =
    role && modelsIndex.by_role && modelsIndex.by_role[role]
      ? modelsIndex.by_role[role]
      : modelsIndex.all || [];

  const modelIds = new Set(modelsForRole.map((model) => model.id));
  buildOptions(dataList, modelsForRole);

  let hasMissing = false;
  if (selectedId && !modelIds.has(selectedId)) {
    const missingOption = document.createElement("option");
    missingOption.value = selectedId;
    missingOption.label = `⚠ missing: ${selectedId}`;
    dataList.insertBefore(missingOption, dataList.firstChild);
    modelInput.value = selectedId;
    hasMissing = true;
  }

  row.classList.toggle("model-missing", hasMissing);
  if (missingLabel) {
    if (hasMissing) {
      missingLabel.textContent = `⚠ missing: ${selectedId}`;
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
    const modelInput = row.querySelector(".model-id-input");
    if (roleInput) {
      roleInput.addEventListener("input", () => updateRowOptions(row, modelsIndex));
      roleInput.addEventListener("change", () => updateRowOptions(row, modelsIndex));
    }
    if (modelInput) {
      modelInput.addEventListener("input", () => {
        modelInput.dataset.currentModelId = modelInput.value;
        updateRowOptions(row, modelsIndex);
      });
    }
  });
});
