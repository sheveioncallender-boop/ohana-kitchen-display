const app = document.getElementById("ohana-kitchen-app");

if (app && Number(app.dataset.displayId)) {
    const displayId = Number(app.dataset.displayId);
    const board = document.getElementById("kitchen-board");
    const connectionState = document.getElementById("connection-state");
    const activeCount = document.getElementById("active-ticket-count");
    const lateCount = document.getElementById("late-ticket-count");
    const updatedCount = document.getElementById("updated-ticket-count");
    const lastSync = document.getElementById("last-sync");
    let refreshTimer = null;
    let knownTicketIds = new Set();
    let hasRendered = false;
    let latestPayload = null;
    let refreshInFlight = false;

    async function jsonRpc(url, params = {}) {
        const response = await fetch(url, {
            method: "POST",
            credentials: "same-origin",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                jsonrpc: "2.0",
                method: "call",
                params,
                id: Date.now(),
            }),
        });
        if (!response.ok) {
            throw new Error(`Server returned ${response.status}`);
        }
        const body = await response.json();
        if (body.error) {
            throw new Error(body.error.data?.message || body.error.message || "Kitchen request failed");
        }
        return body.result;
    }

    function element(tag, className, text) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined && text !== null) node.textContent = text;
        return node;
    }

    function ageMinutes(value) {
        if (!value) return 0;
        const normalized = value.includes("T") ? value : `${value.replace(" ", "T")}Z`;
        const parsed = new Date(normalized);
        if (Number.isNaN(parsed.getTime())) return 0;
        return Math.max(Math.floor((Date.now() - parsed.getTime()) / 60000), 0);
    }

    function ageLabel(value) {
        const minutes = ageMinutes(value);
        if (minutes < 1) return "Now";
        if (minutes < 60) return `${minutes}m`;
        return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
    }

    function ticketTimerStart(ticket) {
        return ticket.has_changes && ticket.last_change_at
            ? ticket.last_change_at
            : ticket.opened_at;
    }

    function playAttentionTone() {
        try {
            const AudioContext = window.AudioContext || window.webkitAudioContext;
            const context = new AudioContext();
            const oscillator = context.createOscillator();
            const gain = context.createGain();
            oscillator.type = "sine";
            oscillator.frequency.value = 720;
            gain.gain.setValueAtTime(0.0001, context.currentTime);
            gain.gain.exponentialRampToValueAtTime(0.16, context.currentTime + 0.02);
            gain.gain.exponentialRampToValueAtTime(0.0001, context.currentTime + 0.32);
            oscillator.connect(gain);
            gain.connect(context.destination);
            oscillator.addEventListener("ended", () => context.close());
            oscillator.start();
            oscillator.stop(context.currentTime + 0.34);
        } catch (_error) {
            // Browsers can block audio until a user interacts with the page.
        }
    }

    function ticketCard(ticket, payload) {
        const timerStart = ticketTimerStart(ticket);
        const minutes = ageMinutes(timerStart);
        const late = minutes >= payload.display.alert_minutes;
        const card = element("article", `ticket-card${late ? " late" : ""}${ticket.has_changes ? " has-update" : ""}`);
        card.dataset.ticketId = ticket.id;

        const header = element("div", "ticket-card-header");
        const identity = element("div", "ticket-identity");
        identity.append(element("span", "ticket-type", ticket.order_type));
        identity.append(element("h3", "", ticket.table_name));
        identity.append(element("p", "", ticket.name));
        if (ticket.has_changes) {
            identity.append(element("span", "update-badge", `Updated · Rev ${ticket.revision_count}`));
        }
        const timer = element("div", `ticket-timer${late ? " urgent" : ""}`, ageLabel(timerStart));
        timer.dataset.openedAt = timerStart;
        header.append(identity, timer);
        card.append(header);

        const meta = element("div", "ticket-meta");
        if (ticket.waiter_name) meta.append(element("span", "", `Waiter: ${ticket.waiter_name}`));
        if (ticket.guest_count) meta.append(element("span", "", `${ticket.guest_count} guest${ticket.guest_count === 1 ? "" : "s"}`));
        if (ticket.customer_name) meta.append(element("span", "", ticket.customer_name));
        card.append(meta);

        const items = element("div", "ticket-items");
        ticket.lines.forEach((line) => {
            const row = element("div", `ticket-item${line.is_changed ? " changed" : ""}`);
            row.append(element("strong", "qty", `${line.quantity}×`));
            if (payload.display.show_product_images && line.product_image_url) {
                const photo = element("img", "product-photo");
                photo.src = line.product_image_url;
                photo.alt = line.product_name;
                photo.loading = "lazy";
                photo.addEventListener("error", () => photo.remove());
                row.append(photo);
            }
            const itemText = element("div", "item-text");
            itemText.append(element("span", "name", line.product_name));
            if (line.course_name) itemText.append(element("small", "course", line.course_name));
            if (line.notes) itemText.append(element("small", "note", line.notes));
            if (line.is_changed) itemText.append(element("small", "changed-label", "Order update"));
            row.append(itemText);
            items.append(row);
        });
        card.append(items);

        if (ticket.customer_note) {
            card.append(element("div", "order-note", `Customer: ${ticket.customer_note}`));
        }
        if (ticket.internal_note) {
            card.append(element("div", "order-note internal", `Kitchen: ${ticket.internal_note}`));
        }

        const actions = element("div", "ticket-actions");
        const workflowStages = payload.stages.filter((stage) => !stage.is_cancelled);
        const currentIndex = workflowStages.findIndex((stage) => stage.id === ticket.stage_id);
        const nextStage = currentIndex >= 0 ? workflowStages[currentIndex + 1] : null;
        if (nextStage) {
            const next = element("button", "primary-action", nextStage.is_done ? "Complete" : `Move to ${nextStage.name}`);
            next.type = "button";
            next.dataset.action = "next";
            actions.append(next);
        }
        const cancelStage = payload.stages.find((stage) => stage.is_cancelled);
        if (cancelStage) {
            const cancel = element("button", "secondary-action", "Dismiss");
            cancel.type = "button";
            cancel.dataset.action = "set_stage";
            cancel.dataset.stageId = cancelStage.id;
            actions.append(cancel);
        }
        card.append(actions);
        return card;
    }

    function render(payload) {
        latestPayload = payload;
        board.replaceChildren();
        let lateTickets = 0;
        let updatedTickets = 0;
        const newTicketIds = new Set();

        payload.stages
            .filter((stage) => !stage.is_done && !stage.is_cancelled)
            .forEach((stage) => {
                const column = element("section", "stage-column");
                const tickets = payload.tickets.filter((ticket) => ticket.stage_id === stage.id);
                const heading = element("header", "stage-heading");
                const dot = element("span", "stage-dot");
                dot.style.backgroundColor = stage.color;
                heading.append(dot, element("h2", "", stage.name), element("strong", "stage-count", tickets.length));
                column.append(heading);
                const stack = element("div", "ticket-stack");
                tickets.forEach((ticket) => {
                    newTicketIds.add(ticket.id);
                    if (ageMinutes(ticketTimerStart(ticket)) >= payload.display.alert_minutes) lateTickets += 1;
                    if (ticket.has_changes) updatedTickets += 1;
                    stack.append(ticketCard(ticket, payload));
                });
                if (!tickets.length) {
                    const empty = element("div", "stage-empty", "No active orders");
                    stack.append(empty);
                }
                column.append(stack);
                board.append(column);
            });

        const hasNewTicket = [...newTicketIds].some((id) => !knownTicketIds.has(id));
        if (hasRendered && hasNewTicket && payload.display.sound_enabled) {
            playAttentionTone();
        }
        knownTicketIds = newTicketIds;
        hasRendered = true;
        activeCount.textContent = payload.tickets.length;
        lateCount.textContent = lateTickets;
        updatedCount.textContent = updatedTickets;
        lastSync.textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    }

    async function refresh() {
        if (refreshInFlight) return;
        refreshInFlight = true;
        clearTimeout(refreshTimer);
        try {
            const payload = await jsonRpc("/ohana/kitchen/data", { display_id: displayId });
            if (!payload?.ok) throw new Error(payload?.error || "Kitchen data unavailable");
            render(payload);
            connectionState.className = "connection online";
            connectionState.innerHTML = "<span></span> Live";
            const interval = Math.max(payload.display.refresh_seconds, 1) * 1000;
            refreshTimer = setTimeout(refresh, interval);
        } catch (error) {
            connectionState.className = "connection offline";
            connectionState.innerHTML = "<span></span> Reconnecting";
            lastSync.textContent = error.message;
            refreshTimer = setTimeout(refresh, 5000);
        } finally {
            refreshInFlight = false;
        }
    }

    board.addEventListener("click", async (event) => {
        const button = event.target.closest("button[data-action]");
        if (!button) return;
        const ticket = button.closest(".ticket-card");
        button.disabled = true;
        try {
            const result = await jsonRpc("/ohana/kitchen/action", {
                display_id: displayId,
                ticket_id: Number(ticket.dataset.ticketId),
                action: button.dataset.action,
                stage_id: Number(button.dataset.stageId || 0),
            });
            if (!result?.ok) throw new Error(result?.error || "Kitchen action failed");
            await refresh();
        } catch (error) {
            window.alert(error.message);
        } finally {
            button.disabled = false;
        }
    });

    document.getElementById("fullscreen-button")?.addEventListener("click", () => {
        if (!document.fullscreenElement) document.documentElement.requestFullscreen?.();
        else document.exitFullscreen?.();
    });

    document.getElementById("display-switcher")?.addEventListener("change", (event) => {
        window.location.href = `/ohana/kitchen?display_id=${Number(event.target.value)}`;
    });

    setInterval(() => {
        document.getElementById("kitchen-clock").textContent = new Date().toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
        });
        document.querySelectorAll(".ticket-timer").forEach((timer) => {
            timer.textContent = ageLabel(timer.dataset.openedAt);
            if (latestPayload && ageMinutes(timer.dataset.openedAt) >= latestPayload.display.alert_minutes) {
                timer.classList.add("urgent");
            }
        });
    }, 1000);

    refresh();
}
