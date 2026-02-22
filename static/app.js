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
