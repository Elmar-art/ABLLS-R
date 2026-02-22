document.addEventListener("DOMContentLoaded", () => {
  const navToggle = document.getElementById("navToggle");
  const mainNav = document.getElementById("mainNav");

  if (navToggle && mainNav) {
    navToggle.addEventListener("click", () => {
      const isOpen = mainNav.classList.toggle("open");
      navToggle.setAttribute("aria-expanded", isOpen ? "true" : "false");
      navToggle.textContent = isOpen ? "Закрыть" : "Меню";
    });
  }

  const currentPath = window.location.pathname.replace(/\/$/, "") || "/";
  const navLinks = document.querySelectorAll(".nav a[href]");
  navLinks.forEach((link) => {
    const href = link.getAttribute("href");
    if (!href) {
      return;
    }

    const normalizedHref = href.replace(/\/$/, "") || "/";
    const isRoot = normalizedHref === "/";
    const isActive = isRoot ? currentPath === "/" : currentPath.startsWith(normalizedHref);
    if (isActive) {
      link.classList.add("active");
    }
  });

  const revealTargets = document.querySelectorAll(
    ".hero, .page-head, .auth-panel, .flash, .site-footer"
  );

  revealTargets.forEach((el, index) => {
    el.classList.add("reveal");
    el.style.transitionDelay = `${Math.min(index * 34, 260)}ms`;
  });

  if ("IntersectionObserver" in window) {
    const isInViewport = (el) => {
      const rect = el.getBoundingClientRect();
      const viewportHeight = window.innerHeight || document.documentElement.clientHeight;
      return rect.top < viewportHeight * 0.95 && rect.bottom > viewportHeight * 0.05;
    };

    const observer = new IntersectionObserver(
      (entries, obs) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) {
            return;
          }
          entry.target.classList.add("visible");
          obs.unobserve(entry.target);
        });
      },
      { threshold: 0.01, rootMargin: "0px 0px -8% 0px" }
    );

    revealTargets.forEach((el) => {
      if (isInViewport(el)) {
        el.classList.add("visible");
      } else {
        observer.observe(el);
      }
    });

    // Safety fallback: avoid hidden content if observer is throttled by browser.
    setTimeout(() => {
      revealTargets.forEach((el) => el.classList.add("visible"));
    }, 700);
  } else {
    revealTargets.forEach((el) => el.classList.add("visible"));
  }

  const flash = document.querySelector(".flash[data-autohide='true']");
  if (flash) {
    setTimeout(() => {
      flash.style.opacity = "0";
      flash.style.transform = "translateY(-6px)";
      flash.style.transition = "opacity 0.35s ease, transform 0.35s ease";
      setTimeout(() => flash.remove(), 350);
    }, 5200);
  }

  const accordionGroups = document.querySelectorAll("[data-accordion='skills']");
  accordionGroups.forEach((group) => {
    const items = group.querySelectorAll("details.skill-item");
    items.forEach((item) => {
      item.addEventListener("toggle", () => {
        if (!item.open) {
          return;
        }
        items.forEach((other) => {
          if (other !== item) {
            other.open = false;
          }
        });
      });
    });
  });

  const chartCanvases = document.querySelectorAll(".daily-line-chart[data-daily-chart]");
  const formatDateLabel = (value) => {
    if (typeof value !== "string") {
      return String(value ?? "");
    }
    const parts = value.split("-");
    if (parts.length === 3) {
      return `${parts[2]}.${parts[1]}`;
    }
    return value;
  };

  const drawDailyChart = (canvas) => {
    let points = [];
    try {
      points = JSON.parse(canvas.dataset.dailyChart || "[]");
    } catch {
      points = [];
    }

    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    const cssWidth = Math.max(canvas.clientWidth || 600, 280);
    const cssHeight = Math.max(canvas.clientHeight || 300, 220);
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(cssWidth * dpr);
    canvas.height = Math.round(cssHeight * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, cssWidth, cssHeight);

    if (!points.length) {
      ctx.fillStyle = "#5f6f7f";
      ctx.font = "600 14px Nunito, sans-serif";
      ctx.fillText("Недостаточно данных для графика", 16, 28);
      return;
    }

    const margin = { top: 22, right: 16, bottom: 40, left: 42 };
    const plotW = cssWidth - margin.left - margin.right;
    const plotH = cssHeight - margin.top - margin.bottom;

    const maxValue = Math.max(
      ...points.flatMap((point) => [Number(point.independent || 0), Number(point.prompted || 0)]),
      1
    );
    const gridLines = 5;
    const yStep = Math.max(1, Math.ceil(maxValue / gridLines));
    const yMax = yStep * gridLines;

    const xAt = (index) =>
      points.length === 1
        ? margin.left + plotW / 2
        : margin.left + (index / (points.length - 1)) * plotW;
    const yAt = (value) => margin.top + plotH - (value / yMax) * plotH;

    ctx.strokeStyle = "rgba(142, 168, 154, 0.5)";
    ctx.lineWidth = 1;
    ctx.font = "600 11px Nunito, sans-serif";
    ctx.fillStyle = "#5f6f7f";

    for (let i = 0; i <= gridLines; i += 1) {
      const yValue = i * yStep;
      const y = yAt(yValue);
      ctx.beginPath();
      ctx.moveTo(margin.left, y);
      ctx.lineTo(margin.left + plotW, y);
      ctx.stroke();
      ctx.fillText(String(yValue), 8, y + 4);
    }

    ctx.strokeStyle = "#597487";
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(margin.left, margin.top);
    ctx.lineTo(margin.left, margin.top + plotH);
    ctx.lineTo(margin.left + plotW, margin.top + plotH);
    ctx.stroke();

    const drawSeries = (key, color) => {
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 2;
      ctx.beginPath();
      points.forEach((point, index) => {
        const x = xAt(index);
        const y = yAt(Number(point[key] || 0));
        if (index === 0) {
          ctx.moveTo(x, y);
        } else {
          ctx.lineTo(x, y);
        }
      });
      ctx.stroke();

      points.forEach((point, index) => {
        const value = Number(point[key] || 0);
        const x = xAt(index);
        const y = yAt(value);
        ctx.beginPath();
        ctx.arc(x, y, 3.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.font = "700 11px Nunito, sans-serif";
        ctx.fillText(String(value), x - 4, y - 8);
      });
    };

    drawSeries("independent", "#4f91bd");
    drawSeries("prompted", "#de945c");

    ctx.fillStyle = "#516b7d";
    ctx.font = "700 11px Nunito, sans-serif";
    const xLabelStep = Math.max(1, Math.ceil(points.length / 9));
    points.forEach((point, index) => {
      if (index % xLabelStep !== 0 && index !== points.length - 1) {
        return;
      }
      const x = xAt(index);
      const label = formatDateLabel(point.date);
      ctx.fillText(label, x - 14, margin.top + plotH + 18);
    });
  };

  const drawAllDailyCharts = () => {
    chartCanvases.forEach((canvas) => drawDailyChart(canvas));
  };
  drawAllDailyCharts();

  let chartResizeTimer = null;
  window.addEventListener("resize", () => {
    if (chartResizeTimer) {
      clearTimeout(chartResizeTimer);
    }
    chartResizeTimer = setTimeout(drawAllDailyCharts, 150);
  });
});

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
