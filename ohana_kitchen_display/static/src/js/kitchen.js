const app = document.getElementById("ohana-kitchen-app");

if (app && Number(app.dataset.displayId)) {
    const displayId = Number(app.dataset.displayId);
    const board = document.getElementById("kitchen-board");
    const connectionState = document.getElementById("connection-state");
    const activeCount = document.getElementById("active-ticket-count");
    const lateCount = document.getElementById("late-ticket-count");
    const voidCount = document.getElementById("void-alert-count");
    const lastSync = document.getElementById("last-sync");
    let refreshTimer = null;
    let knownTicketIds = new Set();
    let knownAlertIds = new Set();
    let latestPayload = null;

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
        const parsed = new Date(value.replace(" ", "T") + "Z");
        return Math.max(Math.floor((Date.now() - parsed.getTime()) / 60000), 0);
    }

    function ageLabel(value) {
        const minutes = ageMinutes(value);
        if (minutes < 1) return "Now";
        if (minutes < 60) return `${minutes}m`;
        return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
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
            oscillator.start();
            oscillator.stop(context.currentTime + 0.34);
        } catch (_error) {
            // Browsers can block audio until a user interacts with the page.
        }
    }

    function ticketCard(ticket, payload) {
        const minutes = ageMinutes(ticket.opened_at);
        const late = minutes >= payload.display.alert_minutes;
        const card = element("article", `ticket-card${late ? " late" : ""}${ticket.alerts.length ? " has-alert" : ""}`);
        card.dataset.ticketId = ticket.id;

        const header = element("div", "ticket-card-header");
        const identity = element("div", "ticket-identity");
        identity.append(element("span", "ticket-type", ticket.order_type));
        identity.append(element("h3", "", ticket.table_name));
        identity.append(element("p", "", ticket.name));
        const timer = element("div", `ticket-timer${late ? " urgent" : ""}`, ageLabel(ticket.opened_at));
        timer.dataset.openedAt = ticket.opened_at;
        header.append(identity, timer);
        card.append(header);

        const meta = element("div", "ticket-meta");
        if (ticket.waiter_name) meta.append(element("span", "", `Waiter: ${ticket.waiter_name}`));
        if (ticket.guest_count) meta.append(element("span", "", `${ticket.guest_count} guest${ticket.guest_count === 1 ? "" : "s"}`));
        if (ticket.customer_name) meta.append(element("span", "", ticket.customer_name));
        card.append(meta);

        if (ticket.alerts.length) {
            const alerts = element("div", "void-alerts");
            ticket.alerts.forEach((alert) => {
                const alertBox = element("div", "void-alert");
                const title = element("strong", "", `VOID ${alert.quantity} × ${alert.product_name}`);
                const reason = element("span", "", alert.reason || "Manager-approved cancellation");
                alertBox.append(title, reason);
                if (alert.notes) alertBox.append(element("small", "", alert.notes));
                const ack = element("button", "ack-alert", "Acknowledge");
                ack.type = "button";
                ack.dataset.action = "ack_alert";
                ack.dataset.alertId = alert.id;
                alertBox.append(ack);
                alerts.append(alertBox);
            });
            card.append(alerts);
        }

        const items = element("div", "ticket-items");
        ticket.lines.forEach((line) => {
            const row = element("div", "ticket-item");
            row.append(element("strong", "qty", `${line.quantity}×`));
            const itemText = element("div", "item-text");
            itemText.append(element("span", "name", line.product_name));
            if (line.course_name) itemText.append(element("small", "course", line.course_name));
            if (line.notes) itemText.append(element("small", "note", line.notes));
            row.append(itemText);
            items.append(row);
        });
        card.append(items);

        if (ticket.notes) {
            card.append(element("div", "order-note", `Note: ${ticket.notes}`));
        }

        const actions = element("div", "ticket-actions");
        const currentIndex = payload.stages.findIndex((stage) => stage.id === ticket.stage_id);
        const nextStage = payload.stages[currentIndex + 1];
        if (nextStage) {
            const next = element("button", "primary-action", nextStage.is_done ? "Complete" : `Move to ${nextStage.name}`);
            next.type = "button";
            next.dataset.action = "next";
            actions.append(next);
        }
        const cancelStage = payload.stages.find((stage) => stage.is_cancelled);
        if (cancelStage) {
            const cancel = element("button", "secondary-action", "Cancel Ticket");
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
        let voidAlerts = 0;
        const newTicketIds = new Set();
        const newAlertIds = new Set();

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
                    if (ageMinutes(ticket.opened_at) >= payload.display.alert_minutes) lateTickets += 1;
                    voidAlerts += ticket.alerts.length;
                    ticket.alerts.forEach((alert) => newAlertIds.add(alert.id));
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
        const hasNewAlert = [...newAlertIds].some((id) => !knownAlertIds.has(id));
        if ((hasNewTicket || hasNewAlert) && payload.display.sound_enabled && knownTicketIds.size) {
            playAttentionTone();
        }
        knownTicketIds = newTicketIds;
        knownAlertIds = newAlertIds;
        activeCount.textContent = payload.tickets.length;
        lateCount.textContent = lateTickets;
        voidCount.textContent = voidAlerts;
        lastSync.textContent = `Updated ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    }

    async function refresh() {
        try {
            const payload = await jsonRpc("/ohana/kitchen/data", { display_id: displayId });
            if (!payload?.ok) throw new Error(payload?.error || "Kitchen data unavailable");
            render(payload);
            connectionState.className = "connection online";
            connectionState.innerHTML = "<span></span> Live";
            const interval = Math.max(payload.display.refresh_seconds, 1) * 1000;
            clearTimeout(refreshTimer);
            refreshTimer = setTimeout(refresh, interval);
        } catch (error) {
            connectionState.className = "connection offline";
            connectionState.innerHTML = "<span></span> Reconnecting";
            lastSync.textContent = error.message;
            clearTimeout(refreshTimer);
            refreshTimer = setTimeout(refresh, 5000);
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
                alert_id: Number(button.dataset.alertId || 0),
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

