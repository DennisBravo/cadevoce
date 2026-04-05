/**
 * Dashboard Cadê Você — mapa Leaflet, sidebar, filtros e tabela com ações.
 */

const API_BASE = "";
const REFRESH_MS = 2 * 60 * 1000;

/** Check-in com coordenadas do agente (Windows Location ou USB NMEA). */
function isGpsSource(raw) {
  const s = raw || "ip";
  return s === "gps" || s === "gps_serial";
}

let map;
let layerGroup;
/** Última lista completa da API (antes dos filtros) */
let allDevices = [];
/** Marcadores Leaflet por dispositivo (chave estável hostname + usuário) */
const markersByKey = new Map();

function el(id) {
  return document.getElementById(id);
}

/** Chave única para casar linha da tabela com marcador no mapa */
function deviceKey(r) {
  return `${r.hostname}\n${r.username}`;
}

function initMap() {
  map = L.map("map", { zoomControl: true }).setView([-14.235, -51.9253], 4);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);
  layerGroup = L.layerGroup().addTo(map);
}

/** Lê valores atuais dos filtros do topo do mapa */
function readFilters() {
  const q = (el("filter-search").value || "").trim().toLowerCase();
  const status = el("filter-status").value;
  const source = el("filter-source").value;
  return { q, status, source };
}

/**
 * Filtra dispositivos por texto (hostname/usuário), status e fonte.
 * @param {object[]} rows
 */
function applyFilters(rows) {
  const { q, status, source } = readFilters();
  return rows.filter((r) => {
    if (q) {
      const hay = `${r.hostname} ${r.username}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    if (status === "ok" && r.status !== "ok") return false;
    if (status === "violation" && r.status !== "violation") return false;
    if (status === "none" && r.status != null) return false;
    const src = r.source || "ip";
    if (source === "gps_all" && !isGpsSource(src)) return false;
    if (source === "gps" && src !== "gps") return false;
    if (source === "gps_serial" && src !== "gps_serial") return false;
    if (source === "ip" && src !== "ip") return false;
    return true;
  });
}

/** Abre/fecha sidebar no mobile */
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
  const closeBtn = el("sidebar-close");
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

/** HTML do marcador: GPS = losango, IP = círculo; cor por status / VPN */
function markerHtml(status, vpn, isGps) {
  const violation = status === "violation";
  const color = violation ? "#e74c3c" : "#2ecc71";
  const border = vpn && !violation ? "#f39c12" : color;
  const inner = vpn && !violation ? "&#128274;" : "";
  if (isGps) {
    return `
    <div style="
      width:20px;height:20px;background:${color};border:3px solid ${border};
      transform:rotate(45deg);border-radius:3px;
      box-shadow:0 1px 4px rgba(0,0,0,.45);
      display:flex;align-items:center;justify-content:center;
      font-size:9px;line-height:1;">${inner}</div>`;
  }
  return `
    <div style="
      width:22px;height:22px;border-radius:50%;
      background:${color};border:3px solid ${border};
      box-shadow:0 1px 4px rgba(0,0,0,.45);
      display:flex;align-items:center;justify-content:center;
      font-size:11px;line-height:1;">${inner}</div>`;
}

function makeIcon(status, vpn, isGps) {
  const size = isGps ? 26 : 28;
  return L.divIcon({
    className: "cv-marker",
    html: markerHtml(status, vpn, isGps),
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -14],
  });
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

function formatAccuracy(r) {
  if (!isGpsSource(r.source) || r.accuracy == null) return "—";
  return "±" + Math.round(r.accuracy) + " m";
}

function sourceBadge(r) {
  const s = r.source || "ip";
  if (s === "gps_serial") {
    return '<span class="badge badge--source-gps-serial" title="Receptor GNSS USB (NMEA)">GPS USB</span>';
  }
  if (s === "gps") {
    return '<span class="badge badge--source-gps" title="Serviço de localização do Windows">GPS Windows</span>';
  }
  return '<span class="badge badge--source-ip" title="Geolocalização por IP">IP</span>';
}

/** Resumo calculado sobre a lista filtrada (coerente com mapa e tabela) */
function renderStats(rows) {
  const total = rows.length;
  const withStatus = rows.filter((r) => r.status);
  const ok = withStatus.filter((r) => r.status === "ok").length;
  const violation = withStatus.filter((r) => r.status === "violation").length;
  const vpn = withStatus.filter((r) => r.vpn_detected).length;

  el("stat-total").textContent = String(total);
  el("stat-ok").textContent = String(ok);
  el("stat-violation").textContent = String(violation);
  el("stat-vpn").textContent = String(vpn);
}

/** Link para histórico com dispositivo pré-selecionado */
function historyPageUrl(hostname, username) {
  const p = new URLSearchParams({
    hostname,
    username,
  });
  return `/static/history.html?${p.toString()}`;
}

function renderTable(rows) {
  const tbody = el("device-rows");
  tbody.innerHTML = rows
    .map((r) => {
      let badgeClass = "badge--pending";
      let badgeText = "Sem check-in";
      if (r.status === "ok") {
        badgeClass = "badge--ok";
        badgeText = "OK";
      } else if (r.status === "violation") {
        badgeClass = "badge--violation";
        badgeText = "Violação";
      }
      const vpnCell =
        r.vpn_detected === true
          ? '<span class="vpn-icon vpn-yes" title="Proxy/hosting (ip-api)">&#128274;</span>'
          : r.vpn_detected === false
            ? '<span class="vpn-icon vpn-no" title="Sem indicação">—</span>'
            : '<span class="muted">—</span>';
      const hEsc = escapeHtml(r.hostname);
      const uEsc = escapeHtml(r.username);
      const histUrl = historyPageUrl(r.hostname, r.username);
      const hAttr = escapeAttr(r.hostname);
      const uAttr = escapeAttr(r.username);
      const canCenter =
        r.lat != null && r.lon != null && r.status != null ? "" : " disabled";
      return `<tr>
        <td>${hEsc}</td>
        <td>${uEsc}</td>
        <td>${sourceBadge(r)}</td>
        <td class="muted">${escapeHtml(formatAccuracy(r))}</td>
        <td>${escapeHtml(r.ip ?? "—")}</td>
        <td>${escapeHtml(r.region ?? "—")}</td>
        <td>${escapeHtml(r.city ?? "—")}</td>
        <td class="col-hide-sm">${escapeHtml(r.estado_permitido)}</td>
        <td><span class="badge ${badgeClass}">${badgeText}</span></td>
        <td>${vpnCell}</td>
        <td class="muted">${formatTime(r.last_seen)}</td>
        <td class="table-actions">
          <a class="btn-action" href="${escapeHtml(histUrl)}" title="Ver histórico">📅 Histórico</a>
          <button type="button" class="btn-action"${canCenter} data-action="center" data-hostname="${hAttr}" data-username="${uAttr}" title="Centralizar no mapa">📍 Mapa</button>
        </td>
      </tr>`;
    })
    .join("");
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Aspas duplas em atributo HTML */
function escapeAttr(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/"/g, "&quot;");
}

/** Desenha apenas os pontos da lista filtrada; guarda referências aos marcadores */
function renderMap(rows) {
  layerGroup.clearLayers();
  markersByKey.clear();
  const bounds = [];
  rows.forEach((r) => {
    if (r.lat == null || r.lon == null || !r.status) return;
    const isGps = isGpsSource(r.source);
    const icon = makeIcon(r.status, !!r.vpn_detected, isGps);
    const m = L.marker([r.lat, r.lon], { icon });
    const key = deviceKey(r);
    markersByKey.set(key, m);
    const accLabel = formatAccuracy(r);
    const fonte =
      r.source === "gps_serial"
        ? "GPS USB (NMEA)"
        : isGps
          ? "GPS Windows (Location)"
          : "IP (ip-api)";
    const vpnNote = r.vpn_detected
      ? "<br/><strong>VPN/proxy:</strong> indicado (ip-api)"
      : "";
    m.bindPopup(
      `<strong>${escapeHtml(r.hostname)}</strong><br/>` +
        `${escapeHtml(r.username)}<br/>` +
        `<strong>Fonte:</strong> ${fonte}<br/>` +
        `<strong>Precisão:</strong> ${escapeHtml(accLabel)}<br/>` +
        `<strong>IP:</strong> ${escapeHtml(r.ip ?? "—")}<br/>` +
        `<strong>Status:</strong> ${escapeHtml(r.status)}` +
        vpnNote +
        `<br/><strong>Último check-in:</strong> ${escapeHtml(formatTime(r.last_seen))}`
    );
    layerGroup.addLayer(m);
    bounds.push([r.lat, r.lon]);

    if (isGps && r.accuracy != null && r.accuracy > 0 && r.accuracy < 1e6) {
      const circle = L.circle([r.lat, r.lon], {
        radius: r.accuracy,
        color: r.status === "violation" ? "#e74c3c" : "#3498db",
        fillColor: r.status === "violation" ? "#e74c3c" : "#3498db",
        fillOpacity: 0.12,
        weight: 1,
      });
      layerGroup.addLayer(circle);
      bounds.push([r.lat + r.accuracy / 111320, r.lon]);
      bounds.push([r.lat - r.accuracy / 111320, r.lon]);
    }
  });
  if (bounds.length) {
    map.fitBounds(bounds, { padding: [48, 48], maxZoom: 14 });
  }
}

/**
 * Centraliza o mapa no dispositivo e abre o popup se houver marcador.
 * Usa coordenadas da lista completa se o filtro ocultar o ponto.
 */
function centerOnDevice(hostname, username) {
  const key = `${hostname}\n${username}`;
  const marker = markersByKey.get(key);
  if (marker) {
    const ll = marker.getLatLng();
    map.flyTo(ll, Math.max(map.getZoom(), 13), { duration: 0.45 });
    marker.openPopup();
    return;
  }
  const r = allDevices.find(
    (d) => d.hostname === hostname && d.username === username
  );
  if (r && r.lat != null && r.lon != null) {
    map.flyTo([r.lat, r.lon], 14, { duration: 0.45 });
    L.popup()
      .setLatLng([r.lat, r.lon])
      .setContent(
        `<strong>${escapeHtml(hostname)}</strong><br/>${escapeHtml(username)}<br/><span class="muted">Fora dos filtros atuais — sem marcador na camada.</span>`
      )
      .openOn(map);
  }
}

/** Reaplica filtros sobre allDevices sem nova requisição */
function refreshView() {
  const filtered = applyFilters(allDevices);
  renderStats(filtered);
  renderTable(filtered);
  renderMap(filtered);
  invalidateMapSize();
}

/** Leaflet precisa recalcular o tamanho após mudanças de layout (sidebar fixa, flex). */
function invalidateMapSize() {
  if (!map) return;
  requestAnimationFrame(() => {
    map.invalidateSize({ animate: false });
  });
}

async function loadDevices() {
  const res = await fetch(`${API_BASE}/devices`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  allDevices = await res.json();
  refreshView();
  el("last-refresh").textContent =
    "Atualizado: " + new Date().toLocaleString("pt-BR");
}

async function tick() {
  try {
    await loadDevices();
  } catch (e) {
    console.error(e);
    el("last-refresh").textContent =
      "Erro ao carregar dados — " + String(e.message);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  initMap();
  initSidebarToggle();

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(invalidateMapSize, 120);
  });

  el("btn-refresh").addEventListener("click", () => tick());

  ["filter-search", "filter-status", "filter-source"].forEach((id) => {
    el(id).addEventListener("input", refreshView);
    el(id).addEventListener("change", refreshView);
  });

  el("device-rows").addEventListener("click", (ev) => {
    const btn = ev.target.closest("button[data-action='center']");
    if (!btn || btn.disabled) return;
    const hostname = btn.getAttribute("data-hostname");
    const username = btn.getAttribute("data-username");
    if (hostname != null && username != null) centerOnDevice(hostname, username);
  });

  tick();
  setInterval(tick, REFRESH_MS);
});
