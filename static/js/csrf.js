document.addEventListener("DOMContentLoaded", function () {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (!meta) return;

    document.querySelectorAll("form").forEach(function (form) {
        if ((form.method || "get").toLowerCase() !== "post") return;
        if (form.querySelector('input[name="_csrf_token"]')) return;

        const input = document.createElement("input");
        input.type = "hidden";
        input.name = "_csrf_token";
        input.value = meta.content;
        form.prepend(input);
    });
});
