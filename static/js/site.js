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
            const timezoneElement = document.getElementById("timezone-alert");
            if (timezoneElement) {
                timezoneElement.classList.remove("d-none");
            }
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

    const popoverTriggerList = document.querySelectorAll('[data-bs-toggle="popover"]')
    const popoverList = [...popoverTriggerList].map(popoverTriggerEl => new bootstrap.Popover(popoverTriggerEl))
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

function movePlannedWorkout(card, cell) {
    const from = card.closest(".js-planned-drop");
    const token = document.querySelector("[name=csrfmiddlewaretoken]");
    if (!from || from === cell || !token) {
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
        // Only the drag button starts a drag, so the links inside the card
        // stay clickable.
        card.querySelectorAll("a").forEach((link) => {
            link.draggable = false;
        });
        const handle = card.querySelector(".js-drag-handle");
        if (!handle) {
            return;
        }
        handle.draggable = true;
        handle.addEventListener("dragstart", (event) => {
            dragged = card;
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", card.dataset.plannedId);
            card.classList.add("dragging");
        });
        handle.addEventListener("dragend", () => {
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

function initAddPlannedModal() {
    // The "Add plan" links all open one shared modal; carry the day they were
    // clicked on into the form and title.
    const modal = document.getElementById("add-planned");
    if (!modal) {
        return;
    }
    modal.addEventListener("show.bs.modal", (event) => {
        const trigger = event.relatedTarget;
        const date = trigger && trigger.dataset ? trigger.dataset.date : "";
        const dateInput = modal.querySelector('[name="workout_date"]');
        if (dateInput && date) {
            dateInput.value = date;
        }
        const title = modal.querySelector(".modal-title");
        if (title) {
            title.textContent = date
                ? `Plan a workout for ${date}`
                : "Plan a workout";
        }
    });
}

function pickRandom() {
    const msgs = [
        "Performing stretches...",
        "Lacing shoes...",
        "Fiddling with watch...",
        "Give me a second...",
        "Grabbing electrolytes...",
    ]
    return msgs[Math.floor(Math.random() * msgs.length)];
}

function initBusyForms() {
    // Deleting, editing and duplicating a planned workout all post and then
    // load the next page. Keep a spinner up while that happens.
    const modalElement = document.getElementById("thinking");
    if (!modalElement) {
        return;
    }
    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || !form.matches(".js-busy-form")) {
            return;
        }
        if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
            event.preventDefault();
            return;
        }
        document.getElementById("thinking-message").innerText = pickRandom();
        bootstrap.Modal.getOrCreateInstance(modalElement).show();
    });
}

function initSavedWorkoutPicker() {
    // A saved-workout picker fills in the notes of the form it belongs to.
    // Delegated so it covers every modal on the calendar and the add page.
    document.addEventListener("change", (event) => {
        const picker = event.target;
        if (!(picker instanceof HTMLSelectElement) || picker.name !== "saved_workout") {
            return;
        }
        const form = picker.form;
        const notes = form ? form.querySelector('textarea[name="notes"]') : null;
        const option = picker.selectedOptions[0];
        const text = option ? option.dataset.text : "";
        if (notes && text) {
            notes.value = text;
        }
    });
}

function initCalendarStickyHeader() {
    const header = document.querySelector(".day-header");
    if (!header) {
        return;
    }
    const HIDE_DELAY = 400;
    let timer;
    window.addEventListener(
        "scroll",
        () => {
            header.classList.add("scrolling");
            clearTimeout(timer);
            timer = window.setTimeout(() => {
                header.classList.remove("scrolling");
            }, HIDE_DELAY);
        },
        { passive: true }
    );
}

function initPullToRefresh() {
    // A touch gesture: at the very top of a page, drag down to reload it. This
    // is an enhancement only - reloading the page the usual way still works.
    const DRAG_START = 6; // ignore jitter until the finger has really moved
    const THRESHOLD = 70; // pull this far and releasing reloads
    const DAMPING = 0.5; // the content follows the finger at half speed
    const MAX_PULL = 120; // the furthest the content can be dragged
    const TARGET_CLASS = "pull-to-refresh-target";
    // Things that pan on touch themselves, where a downward drag means
    // something else entirely.
    const IGNORES_PULL = ".leaflet-container";

    const indicator = document.createElement("div");
    indicator.className = "pull-to-refresh";
    indicator.setAttribute("aria-hidden", "true");
    document.body.appendChild(indicator);

    let startX = 0;
    let startY = 0;
    let distance = 0;
    let active = false;
    let reloading = false;

    function content() {
        // Everything the page is made of, minus the indicator. Read fresh each
        // time so anything added to the page since is included.
        return [...document.body.children].filter((el) => el !== indicator);
    }

    function dragged() {
        return document.querySelectorAll(`.${TARGET_CLASS}`);
    }

    function paint() {
        dragged().forEach((el) => {
            el.style.transform = `translateY(${distance}px)`;
        });
        // Half the pull, so the indicator sits in the gap the content leaves.
        indicator.style.opacity = String(Math.min(1, distance / THRESHOLD));
        indicator.style.transform = `translate(-50%, ${distance / 2}px)`;
        indicator.classList.toggle("armed", distance >= THRESHOLD);
    }

    function reset() {
        active = false;
        distance = 0;
        dragged().forEach((el) => {
            // Dropping the inline transition restores the one on the class, so
            // the content eases back instead of snapping.
            el.style.transition = "";
            el.style.transform = "";
        });
        indicator.style.opacity = "";
        indicator.style.transform = "";
        indicator.classList.remove("armed", "loading");
    }

    function onTouchStart(event) {
        if (reloading || window.scrollY > 0 || event.touches.length !== 1) {
            return;
        }
        const target = event.target;
        if (target instanceof Element && target.closest(IGNORES_PULL)) {
            return;
        }
        content().forEach((el) => {
            el.classList.add(TARGET_CLASS);
            // Follow the finger exactly; the class only transitions the release.
            el.style.transition = "none";
        });
        startX = event.touches[0].clientX;
        startY = event.touches[0].clientY;
        active = true;
    }

    function onTouchMove(event) {
        if (!active) {
            return;
        }
        if (event.touches.length !== 1) {
            reset();
            return;
        }
        const delta = event.touches[0].clientY - startY;
        const sideways = Math.abs(event.touches[0].clientX - startX);
        // A sideways gesture, or one that started after scrolling, belongs to
        // the browser.
        if (delta < DRAG_START || sideways > delta || window.scrollY > 0) {
            if (distance > 0) {
                reset();
            }
            return;
        }
        // Ours now: stop the browser's own overscroll fighting the drag.
        event.preventDefault();
        distance = Math.min(MAX_PULL, delta * DAMPING);
        paint();
    }

    function onTouchEnd() {
        if (!active) {
            return;
        }
        if (distance >= THRESHOLD) {
            reloading = true;
            active = false;
            indicator.classList.remove("armed");
            indicator.classList.add("loading");
            indicator.style.opacity = "1";
            // Leave the page pulled down; it is about to be replaced. The
            // delay lets the spinner paint first.
            window.setTimeout(() => window.location.reload(), 80);
            return;
        }
        reset();
    }

    document.addEventListener("touchstart", onTouchStart, { passive: true });
    // Not passive: the whole point is to cancel the browser's own overscroll.
    document.addEventListener("touchmove", onTouchMove, { passive: false });
    document.addEventListener("touchend", onTouchEnd);
    document.addEventListener("touchcancel", reset);
    // A back/forward restore can bring the page back mid-pull.
    window.addEventListener("pageshow", reset);
}

window.addEventListener("DOMContentLoaded", initTheme);
window.addEventListener("DOMContentLoaded", initCalendarDragAndDrop);
window.addEventListener("DOMContentLoaded", initSavedWorkoutPicker);
window.addEventListener("DOMContentLoaded", initBusyForms);
window.addEventListener("DOMContentLoaded", initAddPlannedModal);
window.addEventListener("DOMContentLoaded", initCalendarStickyHeader);
window.addEventListener("DOMContentLoaded", initPullToRefresh);
window.addEventListener("load", initHeartRateCharts);
window.addEventListener("load", initSite);