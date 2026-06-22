document.addEventListener("DOMContentLoaded", function () {
    const toggle = document.getElementById("sidebarToggle");
    const close = document.getElementById("sidebarClose");
    const backdrop = document.getElementById("sidebarBackdrop");
    if (!toggle) return;

    function setOpen(open) {
        document.body.classList.toggle("sidebar-open", open);
        toggle.setAttribute("aria-expanded", String(open));
    }

    toggle.addEventListener("click", () => setOpen(!document.body.classList.contains("sidebar-open")));
    if (close) close.addEventListener("click", () => setOpen(false));
    if (backdrop) backdrop.addEventListener("click", () => setOpen(false));
    document.addEventListener("keydown", event => { if (event.key === "Escape") setOpen(false); });
});
