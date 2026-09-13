(() => {

  document.getElementById("logoutButton").addEventListener("click", () => {
    c1Logout();
  });

  const menuButton = document.querySelector(".mobile-menu-button");
  if (menuButton) {
    menuButton.addEventListener("click", () => document.body.classList.toggle("sidebar-open"));
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
