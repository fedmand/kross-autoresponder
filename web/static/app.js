// Instant blue highlight on chip selection (before "Applica filtri" is pressed).
document.querySelectorAll(".chip input").forEach(function (input) {
    input.addEventListener("change", function () {
        if (input.type === "radio") {
            // Radios: only the checked one in the group stays highlighted.
            document
                .querySelectorAll('input[name="' + input.name + '"]')
                .forEach(function (r) {
                    r.closest(".chip").classList.toggle("chip-on", r.checked);
                });
        } else {
            input.closest(".chip").classList.toggle("chip-on", input.checked);
        }
    });
});

// Slide-in filters drawer (open/close like a sidebar).
(function () {
    var body = document.body;
    var openBtn = document.getElementById("openFilters");
    var closeBtn = document.getElementById("closeFilters");
    var overlay = document.getElementById("drawerOverlay");

    function open() { body.classList.add("drawer-open"); }
    function close() { body.classList.remove("drawer-open"); }

    if (openBtn) openBtn.addEventListener("click", open);
    if (closeBtn) closeBtn.addEventListener("click", close);
    if (overlay) overlay.addEventListener("click", close);

    document.addEventListener("keydown", function (e) {
        if (e.key === "Escape") close();
    });
})();
