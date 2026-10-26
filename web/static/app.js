"use strict";

const state = { tickets: [], filter: "All" };
const rows = document.querySelector("#ticket-rows");
const dialog = document.querySelector("#ticket-dialog");
const form = document.querySelector("#ticket-form");
const toast = document.querySelector("#toast");

document.querySelector("#current-date").textContent = new Intl.DateTimeFormat(
  undefined, { weekday: "long", month: "long", day: "numeric" },
).format(new Date()).toUpperCase();

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function formatDeadline(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat(undefined, {
    month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  }).format(date);
}

function renderTickets() {
  const tickets = state.filter === "All"
    ? state.tickets
    : state.tickets.filter((ticket) => ticket.ticket_status === state.filter);
  document.querySelector("#nav-count").textContent = state.tickets.length;
  document.querySelector("#open-count").textContent =
    state.tickets.filter((ticket) => ticket.ticket_status === "Open").length;
  document.querySelector("#critical-count").textContent =
    state.tickets.filter((ticket) => ticket.priority_level === "P1" && ticket.ticket_status !== "Resolved").length;
  document.querySelector("#progress-count").textContent =
    state.tickets.filter((ticket) => ticket.ticket_status === "In Progress").length;
  document.querySelector("#resolved-count").textContent =
    state.tickets.filter((ticket) => ticket.ticket_status === "Resolved").length;
  document.querySelector("#result-count").textContent = `${tickets.length} ${tickets.length === 1 ? "ticket" : "tickets"}`;
  document.querySelector("#table-summary").textContent =
    state.filter === "All" ? "Your ticket queue" : `${state.filter} tickets`;

  if (tickets.length === 0) {
    rows.innerHTML = '<tr><td colspan="7" class="empty-state">No tickets here yet. Create a ticket to get started.</td></tr>';
    return;
  }

  rows.innerHTML = tickets.map((ticket) => {
    const statusClass = ticket.ticket_status.replaceAll(" ", "-");
    const action = ticket.ticket_status === "Resolved"
      ? ""
      : `<button class="row-action" data-ticket="${escapeHtml(ticket.ticket_id)}" data-status="${ticket.ticket_status === "Open" ? "In Progress" : "Resolved"}">${ticket.ticket_status === "Open" ? "Start work" : "Resolve"}</button>`;
    return `<tr>
      <td><a class="ticket-ref" href="#ticket-${escapeHtml(ticket.ticket_id)}">#${escapeHtml(ticket.ticket_id.slice(0, 8))}</a><span class="ticket-description">${escapeHtml(ticket.issue_description)}</span></td>
      <td><span class="requester">${escapeHtml(ticket.reporter_name)}</span><span class="requester-dept">${escapeHtml(ticket.department)}</span></td>
      <td>${escapeHtml(ticket.category)}</td>
      <td><span class="priority-badge priority-${escapeHtml(ticket.priority_level)}">${escapeHtml(ticket.priority_level)}</span></td>
      <td><span class="status-badge status-${escapeHtml(statusClass)}">${escapeHtml(ticket.ticket_status)}</span></td>
      <td class="deadline">${escapeHtml(formatDeadline(ticket.sla_deadline))}</td>
      <td>${action}</td>
    </tr>`;
  }).join("");
}

async function loadTickets() {
  rows.innerHTML = '<tr><td colspan="7" class="empty-state">Loading tickets…</td></tr>';
  try {
    const response = await fetch("/api/tickets", { headers: { Accept: "application/json" } });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not load tickets.");
    state.tickets = payload.tickets;
    renderTickets();
  } catch (error) {
    rows.innerHTML = `<tr><td colspan="7" class="empty-state">${escapeHtml(error.message)} Try refreshing.</td></tr>`;
    showToast(error.message);
  }
}

let toastTimer;
function showToast(message) {
  toast.textContent = message;
  toast.classList.add("visible");
  window.clearTimeout(toastTimer);
  toastTimer = window.setTimeout(() => toast.classList.remove("visible"), 3200);
}

document.querySelector("#open-ticket").addEventListener("click", () => {
  document.querySelector("#form-error").textContent = "";
  dialog.showModal();
});
document.querySelector("#close-dialog").addEventListener("click", () => dialog.close());
document.querySelector("#cancel-dialog").addEventListener("click", () => dialog.close());
document.querySelector("#refresh-tickets").addEventListener("click", loadTickets);
document.querySelector("#show-all").addEventListener("click", () => {
  state.filter = "All";
  document.querySelectorAll(".filter-tab").forEach((button) => button.classList.toggle("selected", button.dataset.filter === "All"));
  renderTickets();
});

document.querySelectorAll(".filter-tab").forEach((button) => {
  button.addEventListener("click", () => {
    state.filter = button.dataset.filter;
    document.querySelectorAll(".filter-tab").forEach((tab) => tab.classList.toggle("selected", tab === button));
    renderTickets();
  });
});

rows.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-ticket]");
  if (!button) return;
  const ticket = state.tickets.find((item) => item.ticket_id === button.dataset.ticket);
  const notes = button.dataset.status === "Resolved"
    ? window.prompt("Add resolution notes (optional):") : null;
  if (button.dataset.status === "Resolved" && notes === null) return;
  button.disabled = true;
  try {
    const response = await fetch(`/api/tickets/${encodeURIComponent(button.dataset.ticket)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        ticket_status: button.dataset.status,
        resolution_notes: notes || undefined,
      }),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not update ticket.");
    showToast(`Ticket #${button.dataset.ticket.slice(0, 8)} marked ${button.dataset.status.toLowerCase()}.`);
    await loadTickets();
  } catch (error) {
    button.disabled = false;
    showToast(error.message);
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitButton = document.querySelector("#submit-ticket");
  const formError = document.querySelector("#form-error");
  formError.textContent = "";
  submitButton.disabled = true;
  submitButton.textContent = "Creating…";
  const values = Object.fromEntries(new FormData(form).entries());
  try {
    const response = await fetch("/api/tickets", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify(values),
    });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "Could not create ticket.");
    dialog.close();
    form.reset();
    showToast(`Ticket #${payload.ticket.ticket_id.slice(0, 8)} created · ${payload.ticket.priority_level}`);
    state.filter = "All";
    document.querySelectorAll(".filter-tab").forEach((tab) => tab.classList.toggle("selected", tab.dataset.filter === "All"));
    await loadTickets();
  } catch (error) {
    formError.textContent = error.message;
  } finally {
    submitButton.disabled = false;
    submitButton.innerHTML = 'Create ticket <span>→</span>';
  }
});

loadTickets();
