function initSite() {
    // Load tooltips
    const tooltipTriggerList = document.querySelectorAll(
        '[data-bs-toggle="tooltip"]'
    );
    const tooltipList = [...tooltipTriggerList].map(
        (tooltipTriggerEl) => new bootstrap.Tooltip(tooltipTriggerEl)
    );

    // Do a timezone check
    const userTimezone = document.getElementById("timezone");
    if (userTimezone) {
        if (userTimezone.innerText !== Intl.DateTimeFormat().resolvedOptions().timeZone) {
            document.getElementById("timezone-alert").classList.remove("d-none");
        }
    }

    // Hook up switch theme
    function switchTheme(event) {
        let html = document.getElementsByTagName("html")[0];
        let theme = html.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
        html.setAttribute("data-bs-theme", theme);
        localStorage.setItem("theme", theme);
        event.preventDefault();
    }

    for (let el of document.getElementsByClassName("theme-switch")) {
        el.addEventListener("click", switchTheme);
    }

};

function initHeartRateCharts() {
    const NS = "http://www.w3.org/2000/svg";
    const W = 600;
    const H = 100;
    const PAD_L = 8;
    const PAD_R = 8;
    const Y_TOP = 16;
    const Y_BOTTOM = 84;
    const PLOT_W = W - PAD_L - PAD_R;

    // Collect every chart with its data series and overlay elements.
    const charts = [...document.querySelectorAll("svg.hr-chart")]
        .map((svg) => {
            let series = [];
            try {
                series = JSON.parse(svg.getAttribute("data-series") || "[]");
            } catch (error) {
                return null;
            }
            if (!Array.isArray(series) || series.length < 2) {
                return null;
            }

            // Optional cumulative-distance dataset used for the tooltips.
            let distanceSeries = [];
            const distanceAttr = svg.getAttribute("data-distance");
            if (distanceAttr) {
                try {
                    distanceSeries = JSON.parse(distanceAttr);
                } catch (error) {
                    distanceSeries = [];
                }
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

            return {
                svg,
                series,
                distanceSeries,
                line,
                tip,
                metric: svg.getAttribute("data-metric") || "hr",
            };
        })
        .filter(Boolean);

    if (charts.length === 0) {
        return;
    }

    const formatTime = (seconds) => {
        seconds = Math.max(0, Math.round(seconds));
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;
        const mm = String(minutes).padStart(2, "0");
        const ss = String(secs).padStart(2, "0");
        return hours > 0 ? `${hours}:${mm}:${ss}` : `${mm}:${ss}`;
    };

    const formatValue = (metric, value) => {
        if (metric === "pace") {
            const paceSeconds = Math.max(0, Math.round(value));
            const minutes = Math.floor(paceSeconds / 60);
            const secs = paceSeconds % 60;
            return `${minutes}:${String(secs).padStart(2, "0")} /km`;
        }
        if (metric === "elevation") {
            return `${Math.round(value)} m`;
        }
        if (metric === "power") {
            return `${Math.round(value)} W`;
        }
        return `${Math.round(value)} bpm`;
    };

    // x position (viewBox units) of a series index within a given chart.
    const xAt = (chart, index) =>
        PAD_L + (PLOT_W * index) / (chart.series.length - 1);

    // Index of the sample closest to the given time (seconds).
    const nearestIndex = (series, target) => {
        let low = 0;
        let high = series.length - 1;
        while (high - low > 1) {
            const mid = (low + high) >> 1;
            if (series[mid][0] <= target) {
                low = mid;
            } else {
                high = mid;
            }
        }
        const lowGap = Math.abs(series[low][0] - target);
        const highGap = Math.abs(series[high][0] - target);
        return lowGap <= highGap ? low : high;
    };

    // Move every chart's crosshair + tooltip to the same moment in time.
    const syncToTime = (targetTime) => {
        charts.forEach((chart) => {
            const index = nearestIndex(chart.series, targetTime);
            const point = chart.series[index];
            const viewBoxX = xAt(chart, index);

            chart.line.setAttribute("x1", String(viewBoxX));
            chart.line.setAttribute("x2", String(viewBoxX));
            chart.line.style.visibility = "visible";

            let distanceText = "";
            if (chart.distanceSeries.length >= 2) {
                const distIndex = nearestIndex(
                    chart.distanceSeries,
                    targetTime
                );
                const km = chart.distanceSeries[distIndex][1];
                distanceText = ` · ${km.toFixed(1)} km`;
            }
            chart.tip.textContent =
                `${formatValue(chart.metric, point[1])} · ${formatTime(targetTime)}${distanceText}`;
            chart.tip.style.display = "block";

            const rect = chart.svg.getBoundingClientRect();
            const pixelX = (viewBoxX / W) * rect.width;
            const tipWidth = chart.tip.offsetWidth;
            const maxLeft = rect.width - tipWidth - 4;
            chart.tip.style.left = `${Math.max(4, Math.min(pixelX + 10, maxLeft))}px`;
            chart.tip.style.top = `${(rect.height / H) * Y_TOP}px`;
        });
    };

    const hideAll = () => {
        charts.forEach((chart) => {
            chart.line.style.visibility = "hidden";
            chart.tip.style.display = "none";
        });
    };

    charts.forEach((chart) => {
        chart.svg.addEventListener("pointermove", (event) => {
            const rect = chart.svg.getBoundingClientRect();
            if (!rect.width || !rect.height) {
                return;
            }
            let viewBoxX = ((event.clientX - rect.left) / rect.width) * W;
            viewBoxX = Math.max(PAD_L, Math.min(W - PAD_R, viewBoxX));

            const index = Math.round(
                ((viewBoxX - PAD_L) / PLOT_W) * (chart.series.length - 1)
            );
            const clamped = Math.max(0, Math.min(chart.series.length - 1, index));
            syncToTime(chart.series[clamped][0]);
        });

        chart.svg.addEventListener("pointerleave", hideAll);
    });
}

function initTheme() {
    let theme = localStorage.getItem("theme");
    if (!theme) {
        theme = window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }
    if (theme) {
        document.getElementsByTagName("html")[0].setAttribute("data-bs-theme", theme);
    }
}

function sundayKey(value) {
    // The week key of a YYYY-MM-DD string, as the Sunday of its Monday-based week.
    const date = new Date(value + "T12:00:00");
    date.setDate(date.getDate() - ((date.getDay() + 6) % 7));
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${date.getFullYear()}-${month}-${day}`;
}

function syncAddBadge(cell) {
    // A day shows an "Add" badge exactly when it has no planned workout card.
    const badge = cell.querySelector(".js-add-badge");
    const hasCards = cell.querySelector(".js-planned-card");
    if (hasCards && badge) {
        badge.remove();
    } else if (!hasCards && !badge) {
        const link = document.createElement("a");
        link.href = cell.dataset.addUrl;
        link.className =
            "js-add-badge badge-add badge text-bg-light link-underline link-underline-opacity-0";
        link.textContent = "Add";
        cell.appendChild(link);
    }
}

function movePlannedWorkout(card, cell) {
    const from = card.closest(".js-planned-drop");
    const token = document.querySelector("[name=csrfmiddlewaretoken]");
    if (!from || from === cell || !token) {
        return;
    }
    // Only one planned workout per day, so the target day has to be free.
    const occupant = cell.querySelector(".js-planned-card");
    if (occupant && occupant !== card) {
        window.alert("There is already a planned workout on that day.");
        return;
    }

    fetch(card.dataset.moveUrl, {
        method: "POST",
        headers: {
            "X-CSRFToken": token.value,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        body: new URLSearchParams({ date: cell.dataset.date }),
    })
        .then((response) => {
            if (!response.ok) {
                throw new Error(`Could not move the workout (${response.status}).`);
            }
            if (sundayKey(from.dataset.date) === sundayKey(cell.dataset.date)) {
                // Same week: move the card, the weekly summary is unchanged.
                cell.appendChild(card);
                syncAddBadge(from);
                syncAddBadge(cell);
            } else {
                // A move between weeks changes the weekly summaries, so re-render.
                window.location.reload();
            }
        })
        .catch((error) => {
            window.alert(error.message);
            window.location.reload();
        });
}

function initCalendarDragAndDrop() {
    const cards = document.querySelectorAll(".js-planned-card");
    const cells = document.querySelectorAll(".js-planned-drop");
    if (!cards.length || !cells.length) {
        return;
    }

    let dragged = null;

    cards.forEach((card) => {
        // Drag the whole card, not the link inside it.
        card.querySelectorAll("a").forEach((link) => {
            link.draggable = false;
        });
        card.addEventListener("dragstart", (event) => {
            dragged = card;
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", card.dataset.plannedId);
            card.classList.add("dragging");
        });
        card.addEventListener("dragend", () => {
            dragged = null;
            card.classList.remove("dragging");
        });
    });

    cells.forEach((cell) => {
        cell.addEventListener("dragover", (event) => {
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
            cell.classList.add("drag-over");
        });
        cell.addEventListener("dragleave", () => cell.classList.remove("drag-over"));
        cell.addEventListener("drop", (event) => {
            event.preventDefault();
            cell.classList.remove("drag-over");
            if (dragged) {
                movePlannedWorkout(dragged, cell);
            }
        });
    });
}

window.addEventListener("DOMContentLoaded", initTheme);
window.addEventListener("DOMContentLoaded", initCalendarDragAndDrop);
window.addEventListener("load", initHeartRateCharts);
window.addEventListener("load", initSite);