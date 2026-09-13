(() => {
  const STORAGE_KEY = "c1-sidebar-collapsed";
  const toggleButton = document.getElementById("toggleSidebarButton");
  const sidebar = document.getElementById("app-sidebar");

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

  const restoreSidebar = () => {
    if (!sidebar) return;
    const collapsed = localStorage.getItem(STORAGE_KEY) === "1";
    setSidebarState(collapsed);
  };

  document.getElementById("logoutButton").addEventListener("click", () => {
    c1Logout();
  });
  restoreSidebar();

  const menuButton = document.querySelector(".mobile-menu-button");
  if (menuButton) {
    menuButton.addEventListener("click", () => document.body.classList.toggle("sidebar-open"));
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
    }
  });
})();
