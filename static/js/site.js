window.addEventListener("load", (event) => {
    // Load tooltips
    const tooltipTriggerList = document.querySelectorAll(
        '[data-bs-toggle="tooltip"]'
    );
    const tooltipList = [...tooltipTriggerList].map(
        (tooltipTriggerEl) => new bootstrap.Tooltip(tooltipTriggerEl)
    );

    // Load copy to clipboard
    document.querySelectorAll(".copy").forEach((element) => {
        element.addEventListener("click", (element) => {
            navigator.clipboard.writeText(element.target.getAttribute("data-copy"))
        });
    });
});