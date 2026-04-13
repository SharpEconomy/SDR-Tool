(function () {
  const workflowGrid = document.querySelector("[data-workflow-grid]");
  const flowChoiceButtons = Array.from(
    document.querySelectorAll("[data-flow-choice]")
  );
  const workflowPanels = Array.from(
    document.querySelectorAll("[data-workflow-panel]")
  );
  const loadingShell = document.querySelector("[data-loading-shell]");
  const loadingTitle = document.querySelector("[data-loading-title]");
  const loadingTips = Array.from(document.querySelectorAll("[data-loading-tip]"));

  if (workflowGrid && flowChoiceButtons.length && workflowPanels.length) {
    let selectedFlow = "";

    flowChoiceButtons.forEach(function (button) {
      button.addEventListener("click", function () {
        const flow = button.getAttribute("data-flow-choice") || "";
        setSelectedFlow(flow);
      });
    });

    setSelectedFlow(workflowGrid.getAttribute("data-default-flow") || "");

    function setSelectedFlow(flow) {
      selectedFlow = flow;
      flowChoiceButtons.forEach(function (button) {
        const isActive = button.getAttribute("data-flow-choice") === selectedFlow;
        button.classList.toggle("is-active", isActive);
        button.setAttribute("aria-pressed", isActive ? "true" : "false");
      });
      workflowPanels.forEach(function (panel) {
        const isActive = panel.getAttribute("data-workflow-panel") === selectedFlow;
        panel.hidden = !isActive;
      });
      workflowGrid.classList.toggle(
        "workflow-grid-single",
        Boolean(selectedFlow)
      );
    }
  }

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
