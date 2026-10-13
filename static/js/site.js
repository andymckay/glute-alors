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

function initExerciseFormset() {
    const container = document.getElementById("exercise-rows");
    const addButton = document.getElementById("add-exercise-row");
    const template = document.getElementById("empty-exercise-row");
    const totalForms = document.querySelector('input[name="exercises-TOTAL_FORMS"]');
    const headerTemplate = document.getElementById("empty-superset-header");
    if (!container || !addButton || !template || !totalForms) {
        return;
    }

    // Exercises the server considers timed: those ask for a time, not reps.
    const timedIdsElement = document.getElementById("timed-exercise-ids");
    const timedIds = new Set(
        timedIdsElement ? JSON.parse(timedIdsElement.textContent).map(Number) : []
    );
    // Supersets are labelled with these, in the order they appear.
    const LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

    // Where the description and picture of a chosen exercise come from.
    const detailUrlElement = document.getElementById("exercise-detail-url");
    const detailUrlTemplate = detailUrlElement ? JSON.parse(detailUrlElement.textContent) : null;

    const rows = () => Array.from(container.querySelectorAll(".exercise-row"));
    // Removed rows are left in place, hidden, so the formset still sees them.
    const liveRows = () => rows().filter((row) => !row.classList.contains("d-none"));
    const letterOf = (row) => row.querySelector('input[name$="-superset"]');

    const toggleFields = (root, selector, hidden) => {
        root.querySelectorAll(selector).forEach((field) => {
            field.classList.toggle("d-none", hidden);
        });
    };

    // Drill into a row's set template, which querySelectorAll skips.
    const setTemplateOf = (row) => row.querySelector(".set-template");

    // The values a set repeats from one set to the next.
    const SET_FIELDS = ["reps", "duration", "weight", "rest"];

    // A row's sets, leaving out any that have been removed.
    const liveSetRows = (row) =>
        Array.from(row.querySelectorAll(".set-row")).filter(
            (setRow) => !setRow.classList.contains("d-none")
        );

    /** Give every field of a new set the value the previous set has. */
    const repeatPreviousSet = (setRow, previous) => {
        if (!previous) {
            return;
        }
        SET_FIELDS.forEach((field) => {
            const source = previous.querySelector(`input[name$="-${field}"]`);
            const target = setRow.querySelector(`input[name$="-${field}"]`);
            if (source && target) {
                target.value = source.value;
            }
        });
    };

    /** Fill in the exercise's description and picture. */
    const fillDetail = (block, details) => {
        const description = block.querySelector('[data-detail-panel="description"]');
        const text = description.querySelector(".exercise-instructions");
        const imagePanel = block.querySelector('[data-detail-panel="image"]');
        const image = imagePanel.querySelector("img");

        const hasText = Boolean(details.description);
        text.textContent = details.description || "";
        text.classList.toggle("d-none", !hasText);
        description
            .querySelector("[data-detail-missing]")
            .classList.toggle("d-none", hasText);

        const hasImage = Boolean(details.image);
        if (hasImage) {
            image.src = details.image;
            image.alt = details.name || "";
        } else {
            image.removeAttribute("src");
        }
        image.classList.toggle("d-none", !hasImage);
        imagePanel.querySelector("[data-detail-missing]").classList.toggle("d-none", hasImage);
    };

    const clearDetail = (row) => {
        const block = row.querySelector("[data-exercise-detail]");
        if (!block) {
            return;
        }
        delete block.dataset.exerciseId;
        block.querySelectorAll("[data-detail-panel]").forEach((panel) => {
            panel.classList.add("d-none");
        });
        block.querySelectorAll(".js-toggle-detail").forEach((button) => {
            button.setAttribute("aria-expanded", "false");
        });
        block.querySelectorAll(".exercise-instructions").forEach((text) => {
            text.textContent = "";
        });
        const image = block.querySelector("img");
        if (image) {
            image.removeAttribute("src");
        }
    };

    /** Fetch an exercise's details, once per exercise chosen in a row. */
    const loadDetail = (row) => {
        const block = row.querySelector("[data-exercise-detail]");
        const select = row.querySelector('select[name$="-exercise_id"]');
        const exerciseId = select.value;
        if (!block || !exerciseId || !detailUrlTemplate) {
            return Promise.resolve();
        }
        if (block.dataset.exerciseId === exerciseId) {
            return Promise.resolve();
        }
        const url = detailUrlTemplate.replace("__id__", exerciseId);
        return fetch(url)
            .then((response) => (response.ok ? response.json() : null))
            .then((details) => {
                if (!details) {
                    throw new Error("no details");
                }
                fillDetail(block, details);
                block.dataset.exerciseId = exerciseId;
            })
            .catch(() => {
                fillDetail(block, {
                    name: "",
                    description: "Could not load the details for this exercise.",
                    image: null,
                });
            });
    };

    /** Show a set as done when its checkbox is ticked. */
    const syncSetRow = (setRow) => {
        const done = setRow.querySelector('input[name$="-completed"]');
        setRow.classList.toggle("completed", Boolean(done && done.checked));
    };

    /** Bring one row's fields in line with its exercise and its superset. */
    const syncRow = (row) => {
        const select = row.querySelector('select[name$="-exercise_id"]');
        const timed = Boolean(select) && timedIds.has(Number(select.value));
        row.dataset.timed = String(timed);
        row.querySelectorAll(".set-row").forEach((setRow) =>
            toggleFields(setRow, ".reps-fields", timed)
        );
        row.querySelectorAll(".set-row").forEach((setRow) =>
            toggleFields(setRow, ".timed-fields", !timed)
        );

        // A superset rests at the end of each round, so its exercises do not
        // rest after their own sets.
        const letter = letterOf(row).value;
        row.dataset.superset = letter;
        row.classList.toggle("superset-member", Boolean(letter));
        toggleFields(row, ".rest-fields", Boolean(letter));

        const setTemplate = setTemplateOf(row);
        if (setTemplate) {
            toggleFields(setTemplate.content, ".reps-fields", timed);
            toggleFields(setTemplate.content, ".timed-fields", !timed);
            toggleFields(setTemplate.content, ".rest-fields", Boolean(letter));
        }

        const detail = row.querySelector("[data-exercise-detail]");
        if (detail) {
            detail.classList.toggle("d-none", !select || !select.value);
        }
    };

    // Row i owns the "exercises-<i>-…" fields and the "sets<i>-…" ones, so
    // moving a row means rewriting both.
    const renumber = (root, index) =>
        root.querySelectorAll("input, select, label").forEach((element) => {
            ["name", "id", "for"].forEach((attribute) => {
                const value = element.getAttribute(attribute);
                if (!value) {
                    return;
                }
                element.setAttribute(
                    attribute,
                    value
                        .replace(/(^|_)exercises-\d+-/g, `$1exercises-${index}-`)
                        .replace(/(^|_)sets\d+-/g, `$1sets${index}-`)
                );
            });
        });

    /** Renumber every prefix so the formset order matches the order on screen. */
    const renumberAll = () =>
        rows().forEach((row, index) => {
            renumber(row, index);
            const setTemplate = setTemplateOf(row);
            if (setTemplate) {
                renumber(setTemplate.content, index);
            }
        });

    const makeHeader = () =>
        headerTemplate
            ? document
                  .createRange()
                  .createContextualFragment(headerTemplate.innerHTML)
                  .firstElementChild
            : null;

    const renameHeader = (header, letter) => {
        header.dataset.superset = letter;
        header.querySelector(".js-superset-letter").textContent = letter;
        header.querySelectorAll("input").forEach((input) => {
            input.name = `superset-${letter}-${input.name.split("-").pop()}`;
        });
    };

    /**
     * Label the runs of grouped rows A, B, C… and put a header on each one.
     *
     * The header moves with its group, so a rest already entered stays with
     * the exercises it was entered for.
     */
    const syncGroups = () => {
        const headers = new Map(
            Array.from(container.querySelectorAll(".superset-header")).map(
                (header) => [header.dataset.superset, header]
            )
        );
        let labels = 0;
        let seen = "";
        let run = [];

        const close = () => {
            if (!run.length) {
                return;
            }
            // One exercise on its own is not a superset, and only so many
            // letters are available to label them with.
            const letter =
                run.length > 1 && labels < LETTERS.length ? LETTERS[labels++] : "";
            const header = headers.get(seen);
            headers.delete(seen);
            run.forEach((row) => {
                letterOf(row).value = letter;
                row.dataset.superset = letter;
                row.classList.toggle("superset-member", Boolean(letter));
            });
            if (letter && headerTemplate) {
                const element = header || makeHeader();
                renameHeader(element, letter);
                run[0].parentElement.insertBefore(element, run[0]);
            } else if (header) {
                header.remove();
            }
            run = [];
        };

        liveRows().forEach((row) => {
            const letter = letterOf(row).value;
            if (letter && letter === seen) {
                run.push(row);
                return;
            }
            close();
            seen = letter;
            if (letter) {
                run.push(row);
            }
        });
        close();
        headers.forEach((header) => header.remove());
    };

    /** Everything that has to follow a row being added, moved or regrouped. */
    const sync = () => {
        renumberAll();
        syncGroups();
        rows().forEach(syncRow);
        container.querySelectorAll(".set-row").forEach(syncSetRow);
    };

    const freeLetter = () => {
        const used = new Set(liveRows().map((row) => letterOf(row).value));
        return LETTERS.split("").find((letter) => !used.has(letter)) || LETTERS[0];
    };

    /** Drop ``row`` onto ``target``, so the two are done as a superset. */
    const groupWith = (row, target) => {
        const letter = letterOf(target).value;
        if (letter && letter === letterOf(row).value) {
            return;
        }
        // Land at the end of the target's group, to keep a group a run of rows.
        let last = target;
        liveRows().forEach((other) => {
            if (other === target || (letter && letterOf(other).value === letter)) {
                last = other;
            }
        });
        last.after(row);
        const grouped = letter || freeLetter();
        letterOf(target).value = grouped;
        letterOf(row).value = grouped;
        sync();
    };

    const dropTargetAt = (x, y, dragged) => {
        const element = document.elementFromPoint(x, y);
        if (!element || !element.closest) {
            return null;
        }
        const row = element.closest(".exercise-row");
        return row && row !== dragged && !row.classList.contains("d-none") ? row : null;
    };

    const startDrag = (event, row) => {
        if (event.pointerType === "mouse" && event.button !== 0) {
            return;
        }
        event.preventDefault();
        row.classList.add("dragging");
        document.body.classList.add("dragging-superset");

        let target = null;
        const highlight = (found) => {
            if (found === target) {
                return;
            }
            if (target) {
                target.classList.remove("drop-target");
            }
            target = found;
            if (target) {
                target.classList.add("drop-target");
            }
        };

        // Follow the pointer anywhere on the page, not just over the handle.
        const onMove = (moveEvent) =>
            highlight(dropTargetAt(moveEvent.clientX, moveEvent.clientY, row));

        const onEnd = (endEvent) => {
            document.removeEventListener("pointermove", onMove);
            document.removeEventListener("pointerup", onEnd);
            document.removeEventListener("pointercancel", onEnd);
            row.classList.remove("dragging");
            document.body.classList.remove("dragging-superset");
            highlight(target || dropTargetAt(endEvent.clientX, endEvent.clientY, row));
            const found = target;
            if (target) {
                target.classList.remove("drop-target");
                target = null;
            }
            if (found) {
                groupWith(row, found);
            }
        };

        document.addEventListener("pointermove", onMove);
        document.addEventListener("pointerup", onEnd);
        document.addEventListener("pointercancel", onEnd);
    };

    sync();

    // Switching exercise swaps the reps field for a time (or back).
    container.addEventListener("change", (event) => {
        const select = event.target.closest('select[name$="-exercise_id"]');
        if (select) {
            const row = select.closest(".exercise-row");
            clearDetail(row);
            syncRow(row);
            return;
        }
        const completed = event.target.closest('input[name$="-completed"]');
        if (completed) {
            syncSetRow(completed.closest(".set-row"));
        }
    });

    // Sets of an exercise tend to repeat each other, so a field that is set on
    // one set is carried into the sets that follow it.
    container.addEventListener("input", (event) => {
        const input = event.target.closest(".set-row input");
        const setRow = input && input.closest(".set-row");
        const field = input && SET_FIELDS.find((name) => input.name.endsWith(`-${name}`));
        if (!setRow || !field) {
            return;
        }
        const sets = liveSetRows(setRow.closest(".exercise-row"));
        const from = sets.indexOf(setRow);
        if (from < 0) {
            return;
        }
        sets.slice(from + 1).forEach((later) => {
            const sameField = later.querySelector(`input[name$="-${field}"]`);
            if (sameField) {
                sameField.value = input.value;
            }
        });
    });

    container.addEventListener("pointerdown", (event) => {
        const handle = event.target.closest(".js-superset-handle");
        if (handle) {
            startDrag(event, handle.closest(".exercise-row"));
        }
    });

    addButton.addEventListener("click", () => {
        const index = parseInt(totalForms.value, 10);
        // Django's placeholder names the new row's own fields; the sets inside
        // it keep theirs, for the "+ Add set" button to fill in later.
        const html = template.innerHTML
            .replace(/__exercise__/g, index)
            .replace(/exercises-__prefix__-/g, `exercises-${index}-`);
        const row = document.createRange().createContextualFragment(html).firstElementChild;
        container.appendChild(row);
        totalForms.value = index + 1;
        sync();
    });

    container.addEventListener("click", (event) => {
        const toggle = event.target.closest(".js-toggle-detail");
        if (toggle) {
            const row = toggle.closest(".exercise-row");
            const block = toggle.closest("[data-exercise-detail]");
            const panel = block.querySelector(
                `[data-detail-panel="${toggle.dataset.detail}"]`
            );
            const opening = panel.classList.contains("d-none");
            toggle.setAttribute("aria-expanded", String(opening));
            if (opening) {
                loadDetail(row).then(() => panel.classList.remove("d-none"));
            } else {
                panel.classList.add("d-none");
            }
            return;
        }
        const ungroup = event.target.closest(".js-ungroup");
        if (ungroup) {
            const header = ungroup.closest(".superset-header");
            liveRows().forEach((row) => {
                if (letterOf(row).value === header.dataset.superset) {
                    letterOf(row).value = "";
                }
            });
            sync();
            return;
        }
        const addSet = event.target.closest(".js-add-set");
        if (addSet) {
            const row = addSet.closest(".exercise-row");
            const setTotal = row.querySelector('input[name$="-TOTAL_FORMS"]');
            const setTemplate = setTemplateOf(row);
            const previous = liveSetRows(row).pop();
            const index = parseInt(setTotal.value, 10);
            // The set row on screen and the one the JS clones are the same
            // partial; the clone is named with Django's placeholder.
            const html = setTemplate.innerHTML.replace(/__prefix__/g, index);
            const setRow = document.createRange().createContextualFragment(html).firstElementChild;
            repeatPreviousSet(setRow, previous);
            setTemplate.parentElement.insertBefore(setRow, setTemplate);
            setTotal.value = index + 1;
            syncRow(row);
            syncSetRow(setRow);
            return;
        }
        const removeExercise = event.target.closest(".js-remove-exercise");
        if (removeExercise) {
            const row = removeExercise.closest(".exercise-row");
            const deleted = row.querySelector('input[name$="-DELETE"]');
            if (deleted) {
                deleted.checked = true;
            }
            row.classList.add("d-none");
            sync();
            return;
        }
        const removeSet = event.target.closest(".js-remove-set");
        if (removeSet) {
            const setRow = removeSet.closest(".set-row");
            const deleted = setRow.querySelector('input[name$="-DELETE"]');
            if (deleted) {
                deleted.checked = true;
            }
            setRow.classList.add("d-none");
        }
    });
}

/**
 * Doing a workout: one set at a time, with the rest counted down.
 *
 * Each step is a plain form that works on its own; this only takes over the
 * ticking, the moving between sets and the countdown.
 */
function initWorkoutRunner() {
    const runner = document.querySelector("[data-perform]");
    if (!runner) {
        return;
    }

    // The sets in the order they are done in, which is not the order the page
    // holds them in: a superset's sets sit under their own exercises, while it
    // is done a round at a time. The server numbers them as it goes.
    const steps = Array.from(runner.querySelectorAll(".perform-step")).sort(
        (one, other) => Number(one.dataset.step) - Number(other.dataset.step)
    );
    const restPanel = runner.querySelector("[data-rest-panel]");
    // The rest is a modal: it takes the screen until the countdown is done,
    // and only the buttons on it get you out of it.
    const restModal = restPanel
        ? new bootstrap.Modal(restPanel, {
              backdrop: "static",
              keyboard: false,
          })
        : null;
    const restTime = runner.querySelector("[data-rest-time]");
    const restNext = runner.querySelector("[data-rest-next]");
    const doneCount = runner.querySelector("[data-done-count]");
    const elapsed = runner.querySelector("[data-elapsed]");
    const showAll = runner.querySelector("[data-show-all]");
    const pickedInput = runner.querySelector("[name='entry']");
    const doneSummary = runner.querySelector("[data-done-summary]");
    const exerciseGroups = Array.from(
        runner.querySelectorAll("[data-exercise-group]")
    );
    const finishForm = runner.querySelector("[data-finish-workout]");
    const finishLabel = finishForm && finishForm.querySelector("[data-finish-label]");
    const finishButton = finishForm && finishForm.querySelector("button");
    const total = steps.length;
    const csrf = runner.querySelector("[name=csrfmiddlewaretoken]");
    const stepsUrl = window.location.href;
    let finished = runner.dataset.finished === "true";
    let restTimer = null;
    let restLeft = 0;
    // How long the workout had been going when the page was drawn, turned into
    // a start time on the browser's own clock so the timer keeps up from here.
    // A finished workout's clock is left where it stopped.
    const startedAt = elapsed
        ? Date.now() - (Number(elapsed.dataset.elapsed) || 0) * 1000
        : null;
    let stoppedAt =
        elapsed && elapsed.dataset.finished === "true" ? Date.now() : null;

    const isDone = (step) => step.dataset.done === "true";

    /**
     * The round a set belongs to: a superset is done one round at a time, while
     * an exercise on its own has no round to speak of.
     */
    const roundOf = (step) => step.dataset.round || "";

    const groupOf = (step) => (step ? step.closest("[data-exercise-group]") : null);

    // Which exercise is being logged: the one picked from the full list, or the
    // one holding the first set still to do. `showEveryGroup` opens the lot,
    // which is where the page starts when it is linked to as #all.
    let pickedGroup = null;
    let showEveryGroup = window.location.hash === "#all";

    /** The link says what pressing it will do. */
    const paintShowAll = () => {
        if (showAll) {
            showAll.textContent = showEveryGroup
                ? "Show one exercise"
                : "Show all exercises";
        }
    };

    /**
     * The group to put in front of the user: the exercise they picked, which
     * stays put until the workout's own order has reason to move on, or the one
     * holding the first set still to do.
     */
    const groupToShow = () => {
        if (pickedGroup) {
            return pickedGroup;
        }
        const next = steps.find((step) => !isDone(step));
        return next ? groupOf(next) : groupOf(steps[steps.length - 1]);
    };

    /**
     * Whether a picked exercise is still the one to be doing: it keeps its place
     * while it has a set to do in the round being worked through, and once it
     * has nothing left to log at all — the page then offers the way back to the
     * calendar in place of another set. An exercise on its own has no round to
     * give way on, so only its last set moves the page on.
     */
    const holdsItsPlace = (next) => {
        const left = Array.from(
            pickedGroup.querySelectorAll(".perform-step")
        ).filter((step) => !isDone(step));
        return (
            !left.length ||
            left.some(
                (step) => !roundOf(step) || roundOf(step) === roundOf(next)
            )
        );
    };

    /**
     * Let the workout's own order back in once a set is logged: an exercise that
     * has done its set for the round hands the page to the next one in the
     * superset, which brings the first back round for the next round.
     */
    const releasePick = () => {
        const next = steps.find((step) => !isDone(step));
        if (!next || !pickedGroup || holdsItsPlace(next)) {
            return;
        }
        pickedGroup = null;
    };

    const formatTime = (seconds) => {
        const minutes = Math.floor(Math.max(0, seconds) / 60);
        const secs = Math.max(0, seconds) % 60;
        return `${minutes}:${String(secs).padStart(2, "0")}`;
    };

    /** How long the workout has been going, which stops when it is finished. */
    const paintElapsed = () => {
        if (!elapsed || startedAt === null) {
            return;
        }
        const until = stoppedAt === null ? Date.now() : stoppedAt;
        elapsed.textContent = formatTime(Math.floor((until - startedAt) / 1000));
    };

    /** The set being done: the next one of the exercise on show. */
    const currentIndex = () => {
        const shown = steps.filter((step) => groupOf(step) === groupToShow());
        const found = shown.findIndex((step) => !isDone(step));
        // Nothing left in it: the last set of the exercise is the one it ends
        // on.
        const step = shown[found === -1 ? shown.length - 1 : found];
        return step ? steps.indexOf(step) : 0;
    };

    const showCurrent = () => {
        const current = currentIndex();
        steps.forEach((step, index) => {
            step.classList.toggle("current", index === current);
        });
        // The exercise goes on show before the scroll, or the row it scrolls
        // to would still be hidden.
        updateProgress();
        if (steps[current]) {
            steps[current].scrollIntoView({ block: "center" });
        }
    };

    /**
     * Show one exercise at a time: the group holding the first set still to do,
     * so finishing an exercise brings the next one on.
     */
    const showCurrentGroup = () => {
        const shown = showEveryGroup ? null : groupToShow();
        exerciseGroups.forEach((group) => {
            group.classList.toggle("d-none", shown !== null && group !== shown);
        });
        // The whole workout on show: a summary per exercise instead of its
        // sets, and the workout's own button rather than the log.
        runner.classList.toggle("showing-all", showEveryGroup);
        // An exercise with nothing left to log is done with: the page offers
        // the way back to the calendar instead of another set to log.
        const left = shown
            ? Array.from(shown.querySelectorAll(".perform-step")).some(
                  (step) => !isDone(step)
              )
            : true;
        runner.classList.toggle("exercise-done", !showEveryGroup && !left);
        // Logging follows the exercise on show, so tell the form which it is.
        // An exercise with nothing left to log hands the log to whichever one
        // is next, so the form and the page never disagree.
        if (pickedInput) {
            const aim = shown && left ? shown : groupOf(steps.find((step) => !isDone(step)));
            pickedInput.value = aim ? aim.dataset.exerciseGroup : "";
        }
    };

    /** How far along each exercise is, on its card and in the full list. */
    const paintSummaries = () => {
        exerciseGroups.forEach((group) => {
            const rows = Array.from(group.querySelectorAll(".perform-step"));
            const done = rows.filter(isDone).length;
            const summary = group.querySelector("[data-summary]");
            if (summary) {
                summary.textContent = `${done} of ${rows.length} sets done`;
            }
            // Every set logged: the exercise is done with.
            const badge = group.querySelector("[data-done-badge]");
            if (badge) {
                badge.classList.toggle("d-none", done < rows.length);
            }
        });
    };

    const updateProgress = () => {
        const done = steps.filter(isDone).length;
        if (doneCount) {
            doneCount.textContent = String(done);
        }
        if (doneSummary) {
            doneSummary.textContent = `${done} of ${total} sets done.`;
        }
        showCurrentGroup();
        paintSummaries();
    };

    /** Tick a set off; its row carries the state the rest of the page reads. */
    const setDone = (step) => {
        step.dataset.done = "true";
        step.classList.add("done");
        updateProgress();
    };

    /**
     * Show whether the workout itself has been finished. Ticking the last set
     * off finishes it on the server, so the button has to follow along.
     */
    const setFinished = (completed) => {
        finished = completed;
        // The clock stops with the workout, and picks up again if it is
        // reopened.
        stoppedAt = completed ? Date.now() : null;
        if (finishLabel) {
            finishLabel.textContent = completed ? "Reopen workout" : "Complete workout";
        }
        if (finishButton) {
            finishButton.classList.toggle("btn-success", !completed);
            finishButton.classList.toggle("btn-outline-secondary", completed);
        }
        updateProgress();
        paintElapsed();
    };

    const hideRest = () => {
        window.clearInterval(restTimer);
        restTimer = null;
        if (restModal) {
            restModal.hide();
        }
    };

    const tickRest = () => {
        restLeft -= 1;
        if (restLeft > 0) {
            restTime.textContent = formatTime(restLeft);
            return;
        }
        restPanel.classList.add("finished");
        restTime.textContent = "Go";
        if (navigator.vibrate) {
            navigator.vibrate(300);
        }
        window.setTimeout(() => {
            hideRest();
            showCurrent();
        }, 800);
    };

    /** Count the rest down, then move on to the next set. */
    const startRest = (seconds, message) => {
        if (!restModal || seconds <= 0) {
            showCurrent();
            return;
        }
        restLeft = seconds;
        restTime.textContent = formatTime(restLeft);
        restNext.textContent = message || "";
        restPanel.classList.remove("finished");
        restModal.show();
        window.clearInterval(restTimer);
        restTimer = window.setInterval(tickRest, 1000);
    };

    /** What the server refused, said the same way wherever it is refused. */
    const showErrors = (errors) => {
        window.alert(Object.values(errors || {}).flat().join(" "));
    };

    /** Send one change to the server; a plain post if the fetch does not land. */
    const send = (form, extra = {}) => {
        const body = new URLSearchParams(new FormData(form));
        Object.entries(extra).forEach(([name, value]) => {
            body.set(name, value);
        });
        return fetch(stepsUrl.toString(), {
            method: "POST",
            headers: {
                "X-CSRFToken": csrf ? csrf.value : "",
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            body,
        }).then((response) => {
            if (!response.ok) {
                throw new Error(`Could not save that (${response.status}).`);
            }
            return response.json();
        });
    };

    runner.addEventListener("submit", (event) => {
        const form = event.target.closest(".perform-log");
        if (!form) {
            return;
        }
        event.preventDefault();
        send(form)
            .then((data) => {
                if (!data.ok) {
                    showErrors(data.errors);
                    return;
                }
                // The server logs the first set still to do, not the row the
                // button was tapped on, so tick off whichever set came back.
                const logged = steps.find(
                    (step) => step.dataset.set === String(data.set)
                );
                if (logged) {
                    setDone(logged);
                }
                setFinished(data.finished);
                // The set is logged: an exercise that has done its set for the
                // round hands the page on to the next one in the superset.
                releasePick();
                updateProgress();
                const next = steps.find((other) => !isDone(other));
                const rest = logged ? Number(logged.dataset.stepRest) || 0 : 0;
                if (next) {
                    startRest(rest, "Next set");
                } else {
                    showCurrent();
                }
            })
            .catch((error) => {
                window.alert(error.message);
            });
    });

    /** The link that opens every exercise, and the names that pick one. */
    if (showAll) {
        showAll.addEventListener("click", (event) => {
            event.preventDefault();
            showEveryGroup = !showEveryGroup;
            paintShowAll();
            showCurrentGroup();
        });
    }

    runner.addEventListener("click", (event) => {
        const pick = event.target.closest("[data-pick]");
        if (!pick) {
            return;
        }
        event.preventDefault();
        pickedGroup = pick.closest("[data-exercise-group]");
        showEveryGroup = false;
        paintShowAll();
        showCurrent();
    });

    /**
     * A set's own menu: delete it, put it back to do, or add another like it.
     * Each one changes the table's shape, so the page comes back from the
     * server showing the change rather than being patched up here.
     */
    runner.addEventListener("click", (event) => {
        const action = event.target.closest("[name='action'][value]");
        const form = action && action.closest("form");
        if (!form) {
            return;
        }
        event.preventDefault();
        send(form, { action: action.getAttribute("value") })
            .then((data) => {
                if (!data.ok) {
                    showErrors(data.errors);
                    return;
                }
                window.location.reload();
            })
            .catch((error) => {
                window.alert(error.message);
            });
    });

    runner.addEventListener("click", (event) => {
        const step = event.target.closest(".perform-step");
        const prev = event.target.closest(".js-perform-prev");
        const next = event.target.closest(".js-perform-next");
        if (prev || next) {
            const index = Math.min(Math.max(currentIndex() + (next ? 1 : -1), 0), steps.length - 1);
            const target = steps[index];
            steps.forEach((other) => other.classList.remove("current"));
            target.classList.add("current");
            target.scrollIntoView({ block: "center" });
            return;
        }
        if (event.target.closest(".js-rest-skip")) {
            hideRest();
            showCurrent();
            return;
        }
        if (event.target.closest(".js-rest-more")) {
            restLeft += 15;
            restPanel.classList.remove("finished");
            restTime.textContent = formatTime(restLeft);
        }
    });

    // Tapping a closed row opens it; the tick button still does its own thing.
    runner.addEventListener("click", (event) => {
        const step = event.target.closest(".perform-step");
        if (
            !step ||
            event.target.closest("button, form, a, input, label, summary")
        ) {
            return;
        }
        steps.forEach((other) => other.classList.remove("current"));
        step.classList.add("current");
        updateProgress();
    });

    steps.forEach((step) => {
        const nav = step.querySelector(".perform-nav");
        if (nav) {
            nav.classList.remove("d-none");
        }
    });
    hideRest();
    showCurrent();
    paintShowAll();

    // The workout's clock, ticking while it is going on.
    if (elapsed && startedAt !== null) {
        paintElapsed();
        window.setInterval(paintElapsed, 1000);
    }

    // Keep the screen on while a workout is being done.
    if (navigator.wakeLock) {
        navigator.wakeLock.request("screen").catch(() => {});
    }
}

window.addEventListener("DOMContentLoaded", initTheme);
window.addEventListener("DOMContentLoaded", initCalendarDragAndDrop);
window.addEventListener("DOMContentLoaded", initSavedWorkoutPicker);
window.addEventListener("DOMContentLoaded", initBusyForms);
window.addEventListener("DOMContentLoaded", initAddPlannedModal);
window.addEventListener("DOMContentLoaded", initCalendarStickyHeader);
window.addEventListener("DOMContentLoaded", initExerciseFormset);
window.addEventListener("DOMContentLoaded", initWorkoutRunner);
window.addEventListener("load", initHeartRateCharts);
window.addEventListener("load", initSite);