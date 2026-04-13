(function () {
  const loadingShell = document.querySelector("[data-loading-shell]");
  const loadingTitle = document.querySelector("[data-loading-title]");
  const loadingTips = Array.from(document.querySelectorAll("[data-loading-tip]"));

  if (!loadingShell || !loadingTitle) {
    return;
  }

  let loadingVisible = false;
  let tipIndex = 0;
  let tipIntervalId = null;

  document.addEventListener(
    "submit",
    function (event) {
      const form = event.target;
      if (!(form instanceof HTMLFormElement)) {
        return;
      }

      const label =
        form.getAttribute("data-processing-label") || "Working on your request...";

      showLoading(label);
      form.classList.add("form-processing");
      disableForm(form);
    },
    true
  );

  function showLoading(label) {
    if (loadingVisible) {
      return;
    }

    loadingVisible = true;
    loadingTitle.textContent = label;
    startTipRotation();
    loadingShell.hidden = false;
    loadingShell.setAttribute("aria-hidden", "false");
    document.body.classList.add("loading-active");
  }

  function startTipRotation() {
    if (!loadingTips.length) {
      return;
    }

    setActiveTip(tipIndex);
    if (loadingTips.length === 1 || tipIntervalId !== null) {
      return;
    }

    tipIntervalId = window.setInterval(function () {
      tipIndex = (tipIndex + 1) % loadingTips.length;
      setActiveTip(tipIndex);
    }, 20000);
  }

  function setActiveTip(index) {
    loadingTips.forEach(function (tip, currentIndex) {
      tip.classList.toggle("is-active", currentIndex === index);
    });
  }

  function disableForm(form) {
    const buttons = form.querySelectorAll(
      "button, input[type='submit'], input[type='button']"
    );
    buttons.forEach(function (button) {
      if (
        button instanceof HTMLButtonElement ||
        button instanceof HTMLInputElement
      ) {
        button.disabled = true;
      }
    });

    const fields = form.querySelectorAll("input, textarea");
    fields.forEach(function (element) {
      if (
        !(element instanceof HTMLInputElement) &&
        !(element instanceof HTMLTextAreaElement)
      ) {
        return;
      }
      if (
        element instanceof HTMLInputElement &&
        (element.type === "hidden" || element.name === "csrfmiddlewaretoken")
      ) {
        return;
      }
      if (element instanceof HTMLTextAreaElement) {
        element.readOnly = true;
        return;
      }
      if (
        element instanceof HTMLInputElement &&
        (element.type === "checkbox" ||
          element.type === "radio" ||
          element.type === "file")
      ) {
        return;
      }
      element.readOnly = true;
    });
  }
})();
