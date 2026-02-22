document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-toggle='password']");
  if (!button) {
    return;
  }

  const targetId = button.getAttribute("data-target");
  const input = document.getElementById(targetId);
  if (!input) {
    return;
  }

  const isHidden = input.type === "password";
  input.type = isHidden ? "text" : "password";
  button.textContent = isHidden ? "Скрыть" : "Показать";
});

document.addEventListener("input", (event) => {
  const input = event.target;
  if (!input || input.getAttribute("data-no-spaces") !== "true") {
    return;
  }

  const cleaned = input.value.replace(/\s+/g, "");
  if (cleaned !== input.value) {
    input.value = cleaned;
  }
});
