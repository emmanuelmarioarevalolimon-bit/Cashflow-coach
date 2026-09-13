(() => {
  const STORAGE_KEY = "c1-sidebar-collapsed";
  const toggleButton = document.getElementById("toggleSidebarButton");
  const sidebar = document.getElementById("app-sidebar");
  const menuButton = document.querySelector(".mobile-menu-button");
  const MOBILE_BREAKPOINT = 920;

  const isMobileViewport = () => window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT}px)`).matches;

  const setSidebarState = (collapsed) => {
    document.body.classList.toggle("sidebar-hidden", collapsed);
    if (toggleButton) {
      const text = collapsed ? "Mostrar apartados" : "Ocultar apartados";
      toggleButton.textContent = text;
      toggleButton.setAttribute("aria-expanded", (!collapsed).toString());
    }
    try {
      localStorage.setItem(STORAGE_KEY, collapsed ? "1" : "0");
    } catch {
      // Persistencia opcional.
    }
  };

  const setMenuButtonState = (open) => {
    if (!menuButton) return;
    menuButton.setAttribute("aria-expanded", String(open));
    menuButton.setAttribute("aria-label", open ? "Cerrar navegación" : "Abrir navegación");
  };

  const toggleSidebar = () => {
    const mobile = isMobileViewport();
    if (mobile) {
      const nextOpen = !document.body.classList.contains("sidebar-open");
      document.body.classList.toggle("sidebar-open", nextOpen);
      setMenuButtonState(nextOpen);
      if (nextOpen) {
        document.body.classList.remove("sidebar-hidden");
      }
    } else {
      const collapsed = !document.body.classList.contains("sidebar-hidden");
      setSidebarState(collapsed);
      setMenuButtonState(!collapsed);
    }
  };

  const restoreSidebar = () => {
    if (!sidebar) return;
    const collapsed = localStorage.getItem(STORAGE_KEY) === "1";
    setSidebarState(collapsed);
    if (isMobileViewport()) {
      document.body.classList.remove("sidebar-open");
      setMenuButtonState(false);
      return;
    }
    setMenuButtonState(!collapsed);
  };

  window.addEventListener("resize", () => {
    if (isMobileViewport()) {
      if (!document.body.classList.contains("sidebar-open")) {
        setMenuButtonState(false);
      }
      return;
    }
    document.body.classList.remove("sidebar-open");
    setMenuButtonState(!document.body.classList.contains("sidebar-hidden"));
  });

  document.getElementById("logoutButton").addEventListener("click", () => {
    c1Logout();
  });
  restoreSidebar();

  if (menuButton) {
    menuButton.addEventListener("click", toggleSidebar);
  }

  if (toggleButton) {
    toggleButton.addEventListener("click", () => {
      const collapsed = !document.body.classList.contains("sidebar-hidden");
      setSidebarState(collapsed);
    });
  }

  document.addEventListener("click", (event) => {
    if (
      document.body.classList.contains("sidebar-open") &&
      !event.target.closest(".sidebar") &&
      !event.target.closest(".mobile-menu-button")
    ) {
      document.body.classList.remove("sidebar-open");
      setMenuButtonState(false);
    }
  });
})();
