(function () {
  const sidebar = document.getElementById("terminalSidebar");
  const pin = document.getElementById("sidebarPin");
  if (!sidebar || !pin) return;

  const stored = localStorage.getItem("quantSidebarPinned");
  const initial = stored === null ? document.body.dataset.sidebarPinned === "1" : stored === "1";
  sidebar.classList.toggle("pinned", initial);
  pin.classList.toggle("active", initial);
  document.body.classList.toggle("sidebar-pinned", initial);

  function updateState() {
    const pinned = sidebar.classList.contains("pinned");
    localStorage.setItem("quantSidebarPinned", pinned ? "1" : "0");
    pin.classList.toggle("active", pinned);
    document.body.classList.toggle("sidebar-pinned", pinned);
    const state = sidebar.querySelector(".sidebar-state");
    if (state) state.textContent = pinned ? "PINNED" : "AUTO HIDE";
  }

  pin.addEventListener("click", () => {
    sidebar.classList.toggle("pinned");
    updateState();
  });
  updateState();
})();