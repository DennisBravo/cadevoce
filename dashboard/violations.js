/**
 * Página de violações — lista GET /violations e menu lateral (mobile).
 */

const API_BASE = "";

function el(id) {
  return document.getElementById(id);
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatTime(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", { timeZone: "UTC" }) + " UTC";
  } catch {
    return iso;
  }
}

/** Abre/fecha sidebar no mobile e sincroniza ARIA. */
function initSidebarToggle() {
  const sidebar = el("sidebar");
  const toggle = el("sidebar-toggle");
  const backdrop = el("sidebar-backdrop");
  if (!sidebar || !toggle || !backdrop) return;

  function close() {
    sidebar.classList.remove("sidebar--open");
    backdrop.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
  }

  function open() {
    sidebar.classList.add("sidebar--open");
    backdrop.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
  }

  toggle.addEventListener("click", () => {
    if (sidebar.classList.contains("sidebar--open")) close();
    else open();
  });
  backdrop.addEventListener("click", close);
  const closeBtn = document.getElementById("sidebar-close");
  if (closeBtn) closeBtn.addEventListener("click", close);
  sidebar.querySelectorAll("a.sidebar__item").forEach((a) => {
    a.addEventListener("click", () => {
      if (window.matchMedia("(max-width: 900px)").matches) close();
    });
  });
  window.addEventListener(
    "resize",
    () => {
      if (window.matchMedia("(min-width: 901px)").matches) close();
    },
    { passive: true }
  );
}

async function loadViolations() {
  const tbody = el("violations-rows");
  const statusEl = el("violations-status");
  statusEl.textContent = "Carregando…";
  try {
    const res = await fetch(`${API_BASE}/violations`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const rows = await res.json();
    if (!rows.length) {
      tbody.innerHTML =
        '<tr><td colspan="7" class="muted">Nenhuma violação registrada.</td></tr>';
    } else {
      tbody.innerHTML = rows
        .map(
          (r) => `<tr>
        <td class="muted">${escapeHtml(formatTime(r.timestamp))}</td>
        <td>${escapeHtml(r.hostname)}</td>
        <td>${escapeHtml(r.username)}</td>
        <td>${escapeHtml(r.ip)}</td>
        <td>${escapeHtml(r.region ?? "—")}</td>
        <td>${escapeHtml(r.city ?? "—")}</td>
        <td>${escapeHtml(r.estado_permitido)}</td>
      </tr>`
        )
        .join("");
    }
    statusEl.textContent =
      rows.length + " registro(s) — " + new Date().toLocaleString("pt-BR");
  } catch (e) {
    console.error(e);
    tbody.innerHTML =
      '<tr><td colspan="7" class="muted">Erro ao carregar.</td></tr>';
    statusEl.textContent = "Erro: " + e.message;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initSidebarToggle();
  loadViolations();
});
