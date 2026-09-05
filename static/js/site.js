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

function initHeartRateCharts() {
    const charts = document.querySelectorAll("svg.hr-chart");
    const NS = "http://www.w3.org/2000/svg";
    const W = 600;
    const H = 100;
    const PAD_L = 8;
    const PAD_R = 8;
    const Y_TOP = 16;
    const Y_BOTTOM = 84;
    const PLOT_W = W - PAD_L - PAD_R;

    charts.forEach((svg) => {
        let series = [];
        try {
            series = JSON.parse(svg.getAttribute("data-series") || "[]");
        } catch (error) {
            return;
        }
        if (!Array.isArray(series) || series.length < 2) {
            return;
        }

        const wrap = svg.parentElement;
        wrap.style.position = "relative";

        // Vertical crosshair line, added to the SVG itself.
        const line = document.createElementNS(NS, "line");
        line.setAttribute("stroke", "#6c757d");
        line.setAttribute("stroke-width", "1");
        line.setAttribute("stroke-dasharray", "3 3");
        line.setAttribute("y1", String(Y_TOP));
        line.setAttribute("y2", String(Y_BOTTOM));
        line.style.visibility = "hidden";
        svg.appendChild(line);

        // Tooltip bubble, positioned over the chart.
        const tip = document.createElement("div");
        tip.setAttribute("aria-hidden", "true");
        tip.style.position = "absolute";
        tip.style.pointerEvents = "none";
        tip.style.background = "#212529";
        tip.style.color = "#fff";
        tip.style.padding = "2px 8px";
        tip.style.borderRadius = "4px";
        tip.style.fontSize = "12px";
        tip.style.display = "none";
        tip.style.zIndex = "10";
        tip.style.whiteSpace = "nowrap";
        wrap.appendChild(tip);

        const formatTime = (seconds) => {
            seconds = Math.max(0, Math.round(seconds));
            const hours = Math.floor(seconds / 3600);
            const minutes = Math.floor((seconds % 3600) / 60);
            const secs = seconds % 60;
            const mm = String(minutes).padStart(2, "0");
            const ss = String(secs).padStart(2, "0");
            return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
        };

        svg.addEventListener("pointermove", (event) => {
            const rect = svg.getBoundingClientRect();
            if (!rect.width || !rect.height) {
                return;
            }
            let viewBoxX = ((event.clientX - rect.left) / rect.width) * W;
            viewBoxX = Math.max(PAD_L, Math.min(W - PAD_R, viewBoxX));

            const index = Math.round(
                ((viewBoxX - PAD_L) / PLOT_W) * (series.length - 1)
            );
            const point = series[Math.max(0, Math.min(series.length - 1, index))];
            const value = point[1];
            const seconds = point[0];

            line.setAttribute("x1", String(viewBoxX));
            line.setAttribute("x2", String(viewBoxX));
            line.style.visibility = "visible";

            const metric = svg.getAttribute("data-metric") || "hr";
            let readout;
            if (metric === "pace") {
                const paceSeconds = Math.max(0, Math.round(value));
                const minutes = Math.floor(paceSeconds / 60);
                const secs = paceSeconds % 60;
                readout = `${minutes}:${String(secs).padStart(2, "0")} /km`;
            } else if (metric === "elevation") {
                readout = `${Math.round(value)} m`;
            } else {
                readout = `${Math.round(value)} bpm`;
            }
            tip.textContent = `${readout} · ${formatTime(seconds)}`;
            tip.style.display = "block";

            const pointerX = event.clientX - rect.left;
            const tipWidth = tip.offsetWidth;
            const maxLeft = rect.width - tipWidth - 4;
            tip.style.left = `${Math.max(4, Math.min(pointerX + 10, maxLeft))}px`;
            tip.style.top = `${(rect.height / H) * Y_TOP}px`;
        });

        svg.addEventListener("pointerleave", () => {
            line.style.visibility = "hidden";
            tip.style.display = "none";
        });
    });
}

window.addEventListener("load", initHeartRateCharts);