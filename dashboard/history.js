/**
 * Página de histórico — dispositivo + data, mapa Leaflet, tabela e exportação CSV.
 * O parâmetro `date` da API é o dia civil em UTC (YYYY-MM-DD).
 */

const API_BASE = "";

function isGpsSource(raw) {
  const s = raw || "ip";
  return s === "gps" || s === "gps_serial";
}

let map;
let layerGroup;
/** @type {Array<{hostname:string,username:string}>} */
let devicesList = [];
/** @type {Array<object>} */
let lastHistoryRows = [];

function el(id) {
  return document.getElementById(id);
}

/** Menu lateral no mobile (mesmo padrão do dashboard e violações) */
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

/**
 * Se a URL tiver ?hostname=&username=, seleciona o dispositivo e carrega o histórico do dia atual.
 */
function applyFromQueryParams() {
  const params = new URLSearchParams(window.location.search);
  const hn = (params.get("hostname") || "").trim();
  const un = (params.get("username") || "").trim();
  if (!hn || !un) return;
  const idx = devicesList.findIndex(
    (d) => d.hostname === hn && d.username === un
  );
  if (idx < 0) {
    setStatus(
      "Dispositivo indicado na URL não foi encontrado na lista.",
      true
    );
    return;
  }
  el("device-select").value = String(idx);
  loadHistory().catch((e) => {
    console.error(e);
    setStatus("Erro: " + e.message, true);
  });
}

/** Inicializa o mapa Leaflet (tema escuro via tiles OSM). */
function initMap() {
  map = L.map("history-map", { zoomControl: true }).setView([-14.235, -51.9253], 4);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(map);
  layerGroup = L.layerGroup().addTo(map);
}

/** Leaflet após layout flex / sidebar — evita mapa cinza ou altura zero */
function invalidateHistoryMap() {
  if (!map) return;
  requestAnimationFrame(() => {
    map.invalidateSize({ animate: false });
  });
}

function escapeHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

/** Formata instante ISO para exibição em UTC. */
function formatTimeUtc(iso) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString("pt-BR", { timeZone: "UTC" }) + " UTC";
  } catch {
    return iso;
  }
}

function formatUptimeSeconds(sec) {
  if (sec == null || !Number.isFinite(Number(sec)) || Number(sec) < 0) return "—";
  let s = Math.floor(Number(sec));
  const days = Math.floor(s / 86400);
  s %= 86400;
  const hours = Math.floor(s / 3600);
  s %= 3600;
  const mins = Math.floor(s / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${mins}min`;
  if (mins > 0) return `${mins}min`;
  return `${Math.max(0, s)}s`;
}

/** Precisão em metros ou traço se não for GPS. */
function formatAccuracy(row) {
  if (!isGpsSource(row.source) || row.accuracy == null) return "—";
  return "±" + Math.round(Number(row.accuracy)) + " m";
}

/** HTML do badge de fonte (GPS / IP). */
function sourceBadge(row) {
  const s = row.source || "ip";
  if (s === "gps_serial") {
    return '<span class="badge badge--source-gps-serial">GPS USB</span>';
  }
  if (s === "gps") {
    return '<span class="badge badge--source-gps">GPS Windows</span>';
  }
  return '<span class="badge badge--source-ip">IP</span>';
}

/**
 * Ícone Leaflet para um check-in no mapa.
 * @param {"first"|"last"|"both"|"mid"} role — primeiro / último / único / intermediário
 * @param {"ok"|"violation"} status
 */
function makeHistoryIcon(role, status) {
  const violation = status === "violation";
  const fill = violation ? "#e74c3c" : "#2ecc71";
  const size = 32;
  let inner = "";
  if (role === "both") {
    inner =
      '<span style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:8px;font-weight:800;color:#fff;text-shadow:0 0 2px #000;line-height:1;text-align:center;">1º<br/>Últ</span>';
  } else if (role === "first") {
    inner =
      '<span style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:10px;font-weight:800;color:#fff;text-shadow:0 0 2px #000;">1º</span>';
  } else if (role === "last") {
    inner =
      '<span style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;font-size:9px;font-weight:800;color:#fff;text-shadow:0 0 2px #000;">Últ</span>';
  }
  let border = "3px solid " + fill;
  let bg = fill;
  if (role === "first") {
    border = "3px solid #3498db";
  } else if (role === "last") {
    border = "3px solid #9b59b6";
  } else if (role === "both") {
    // Único ponto com coordenadas: destaque primeiro/último; cor de fundo segue o status
    border = "3px solid #3498db";
    bg = violation
      ? fill
      : "linear-gradient(135deg,#3498db 50%,#9b59b6 50%)";
  }
  const html = `
    <div style="position:relative;width:26px;height:26px;border-radius:50%;
      background:${bg};border:${border};
      box-shadow:0 1px 4px rgba(0,0,0,.5);">
      ${inner}
    </div>`;
  return L.divIcon({
    className: "cv-history-marker",
    html,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2],
    popupAnchor: [0, -16],
  });
}

/** Carrega /devices e preenche o dropdown (valor = índice na lista). */
async function loadDeviceOptions() {
  const sel = el("device-select");
  const res = await fetch(`${API_BASE}/devices`);
  if (!res.ok) throw new Error(`Dispositivos: HTTP ${res.status}`);
  const rows = await res.json();
  devicesList = rows.map((r) => ({
    hostname: r.hostname,
    username: r.username,
  }));
  sel.innerHTML = "";
  if (!devicesList.length) {
    sel.innerHTML = '<option value="">Nenhum dispositivo cadastrado</option>';
    return;
  }
  devicesList.forEach((d, i) => {
    const opt = document.createElement("option");
    opt.value = String(i);
    opt.textContent = `${d.hostname} — ${d.username}`;
    sel.appendChild(opt);
  });
}

/** Data padrão no seletor: hoje no fuso local (YYYY-MM-DD). */
function setDefaultDate() {
  const input = el("history-date");
  const t = new Date();
  const y = t.getFullYear();
  const m = String(t.getMonth() + 1).padStart(2, "0");
  const day = String(t.getDate()).padStart(2, "0");
  input.value = `${y}-${m}-${day}`;
}

/**
 * Converte YYYY-MM-DD (dia civil no fuso do navegador) em intervalo UTC [start, end)
 * para a API — alinha com o que o usuário vê no calendário (antes usávamos só “dia UTC”).
 */
function localYmdToUtcRangeIso(ymd) {
  const parts = ymd.split("-").map(Number);
  const y = parts[0];
  const mo = parts[1];
  const d = parts[2];
  const startLocal = new Date(y, mo - 1, d, 0, 0, 0, 0);
  const endExclusiveLocal = new Date(y, mo - 1, d + 1, 0, 0, 0, 0);
  return {
    start: startLocal.toISOString(),
    end: endExclusiveLocal.toISOString(),
  };
}

function setStatus(msg, isError) {
  const p = el("history-status");
  p.textContent = msg || "";
  p.classList.toggle("history-status--err", !!isError);
}

/**
 * Determina papéis “primeiro” e “último” entre pontos com coordenadas válidas
 * (ordem já é a do dia).
 */
function coordRoles(rows) {
  const withIdx = [];
  rows.forEach((r, i) => {
    if (r.lat != null && r.lon != null && !Number.isNaN(+r.lat) && !Number.isNaN(+r.lon)) {
      withIdx.push(i);
    }
  });
  const firstIdx = withIdx.length ? withIdx[0] : -1;
  const lastIdx = withIdx.length ? withIdx[withIdx.length - 1] : -1;
  return { firstIdx, lastIdx, singlePoint: firstIdx === lastIdx && firstIdx >= 0 };
}

/** Desenha polyline, marcadores e popups a partir dos check-ins. */
function renderMap(rows) {
  layerGroup.clearLayers();
  const { firstIdx, lastIdx, singlePoint } = coordRoles(rows);

  // Só liga pontos **GPS** na ordem do dia. Misturar IP (centro aproximado do provedor)
  // com GPS desenha uma reta falsa de vários km — parece “rota” mas é dois tipos de medida.
  const gpsLatLngs = [];
  rows.forEach((r) => {
    if (!isGpsSource(r.source) || r.lat == null || r.lon == null) return;
    const la = Number(r.lat);
    const lo = Number(r.lon);
    if (Number.isNaN(la) || Number.isNaN(lo)) return;
    gpsLatLngs.push([la, lo]);
  });
  if (gpsLatLngs.length >= 2) {
    layerGroup.addLayer(
      L.polyline(gpsLatLngs, {
        color: "#3498db",
        weight: 3,
        opacity: 0.85,
      })
    );
  }

  const fitBoundsPoints = [];

  rows.forEach((r, i) => {
    if (r.lat == null || r.lon == null) return;
    const lat = Number(r.lat);
    const lon = Number(r.lon);

    let role = "mid";
    if (singlePoint && i === firstIdx) role = "both";
    else if (i === firstIdx) role = "first";
    else if (i === lastIdx) role = "last";

    const icon = makeHistoryIcon(role, r.status);
    const m = L.marker([lat, lon], { icon });
    const fonte =
      r.source === "gps_serial"
        ? "GPS USB (NMEA)"
        : isGpsSource(r.source)
          ? "GPS Windows"
          : "IP";
    const bootLine =
      r.last_boot_utc != null
        ? `<br/><strong>Boot:</strong> ${escapeHtml(formatTimeUtc(r.last_boot_utc))}`
        : "";
    const upLine =
      r.uptime_seconds != null
        ? `<br/><strong>Ligado há:</strong> ${escapeHtml(formatUptimeSeconds(r.uptime_seconds))}`
        : "";
    m.bindPopup(
      `<strong>${escapeHtml(formatTimeUtc(r.timestamp))}</strong><br/>` +
        `<strong>Fonte:</strong> ${escapeHtml(fonte)}<br/>` +
        `<strong>Precisão:</strong> ${escapeHtml(formatAccuracy(r))}<br/>` +
        `<strong>Região:</strong> ${escapeHtml(r.region ?? "—")}<br/>` +
        `<strong>Cidade:</strong> ${escapeHtml(r.city ?? "—")}<br/>` +
        `<strong>Status:</strong> ${escapeHtml(r.status)}` +
        bootLine +
        upLine
    );
    layerGroup.addLayer(m);
    fitBoundsPoints.push([lat, lon]);

    if (
      isGpsSource(r.source) &&
      r.accuracy != null &&
      r.accuracy > 0 &&
      r.accuracy < 1e6
    ) {
      const acc = Number(r.accuracy);
      const circle = L.circle([lat, lon], {
        radius: acc,
        color: r.status === "violation" ? "#e74c3c" : "#3498db",
        fillColor: r.status === "violation" ? "#e74c3c" : "#3498db",
        fillOpacity: 0.1,
        weight: 1,
      });
      layerGroup.addLayer(circle);
      const dLat = acc / 111320;
      fitBoundsPoints.push([lat + dLat, lon], [lat - dLat, lon]);
    }
  });

  if (fitBoundsPoints.length) {
    map.fitBounds(fitBoundsPoints, { padding: [40, 40], maxZoom: 15 });
  }
  invalidateHistoryMap();
}

/** Tabela de check-ins do dia. */
function renderTable(rows) {
  const tbody = el("history-rows");
  if (!rows.length) {
    tbody.innerHTML =
      '<tr><td colspan="10" class="muted">Nenhum check-in neste dia.</td></tr>';
    return;
  }
  tbody.innerHTML = rows
    .map((r) => {
      let badgeClass = "badge--ok";
      let badgeText = "OK";
      if (r.status === "violation") {
        badgeClass = "badge--violation";
        badgeText = "Violação";
      }
      const latStr = r.lat != null ? String(r.lat) : "—";
      const lonStr = r.lon != null ? String(r.lon) : "—";
      const bootStr =
        r.last_boot_utc != null ? formatTimeUtc(r.last_boot_utc) : "—";
      const upStr = formatUptimeSeconds(r.uptime_seconds);
      return `<tr>
        <td class="muted">${escapeHtml(formatTimeUtc(r.timestamp))}</td>
        <td>${escapeHtml(latStr)}</td>
        <td>${escapeHtml(lonStr)}</td>
        <td>${sourceBadge(r)}</td>
        <td class="muted">${escapeHtml(formatAccuracy(r))}</td>
        <td>${escapeHtml(r.region ?? "—")}</td>
        <td>${escapeHtml(r.city ?? "—")}</td>
        <td class="muted">${escapeHtml(bootStr)}</td>
        <td class="muted">${escapeHtml(upStr)}</td>
        <td><span class="badge ${badgeClass}">${badgeText}</span></td>
      </tr>`;
    })
    .join("");
}

/** Gera CSV com BOM para Excel e faz download. */
function exportCsv(rows, hostname, username, dateStr) {
  const header = [
    "timestamp_utc",
    "lat",
    "lon",
    "source",
    "accuracy_m",
    "region",
    "city",
    "last_boot_utc",
    "uptime_seconds",
    "status",
  ];
  const lines = [header.join(",")];
  for (const r of rows) {
    const acc =
      isGpsSource(r.source) && r.accuracy != null
        ? String(Math.round(Number(r.accuracy)))
        : "";
    const cells = [
      r.timestamp,
      r.lat ?? "",
      r.lon ?? "",
      r.source || "ip",
      acc,
      csvEscape(r.region),
      csvEscape(r.city),
      r.last_boot_utc ?? "",
      r.uptime_seconds != null ? String(r.uptime_seconds) : "",
      r.status,
    ];
    lines.push(cells.join(","));
  }
  const blob = new Blob(["\ufeff" + lines.join("\n")], {
    type: "text/csv;charset=utf-8",
  });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `cadevoce-historico_${hostname}_${username}_${dateStr}.csv`.replace(
    /[^a-zA-Z0-9._-]+/g,
    "_"
  );
  a.click();
  URL.revokeObjectURL(a.href);
}

function csvEscape(val) {
  if (val == null || val === "") return "";
  const s = String(val);
  if (/[",\n\r]/.test(s)) return '"' + s.replace(/"/g, '""') + '"';
  return s;
}

/** Busca GET /history e atualiza mapa e tabela. */
async function loadHistory() {
  const sel = el("device-select");
  const idx = parseInt(sel.value, 10);
  const dateVal = el("history-date").value;
  el("btn-csv").disabled = true;
  lastHistoryRows = [];

  if (sel.value === "" || Number.isNaN(idx) || !devicesList[idx]) {
    setStatus("Selecione um dispositivo.", true);
    renderTable([]);
    layerGroup.clearLayers();
    invalidateHistoryMap();
    return;
  }
  if (!dateVal) {
    setStatus("Selecione uma data.", true);
    invalidateHistoryMap();
    return;
  }

  const { hostname, username } = devicesList[idx];
  const { start, end } = localYmdToUtcRangeIso(dateVal);
  const params = new URLSearchParams({
    hostname,
    username,
    start,
    end,
  });

  setStatus("Carregando…", false);
  const res = await fetch(`${API_BASE}/history?${params}`);
  if (!res.ok) {
    const errText = await res.text();
    setStatus(`Erro ${res.status}: ${errText.slice(0, 200)}`, true);
    renderTable([]);
    layerGroup.clearLayers();
    invalidateHistoryMap();
    return;
  }
  const rows = await res.json();
  lastHistoryRows = rows;
  renderMap(rows);
  renderTable(rows);
  el("btn-csv").disabled = rows.length === 0;
  setStatus(
    `${rows.length} check-in(s) no dia ${dateVal} (seu fuso horário).`,
    false
  );
}

document.addEventListener("DOMContentLoaded", () => {
  initMap();
  initSidebarToggle();
  setDefaultDate();

  let resizeTimer;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(invalidateHistoryMap, 120);
  });
  setTimeout(invalidateHistoryMap, 150);

  loadDeviceOptions()
    .then(() => {
      const params = new URLSearchParams(window.location.search);
      if (params.get("hostname") && params.get("username")) {
        applyFromQueryParams();
      } else {
        setStatus("Selecione o dispositivo e a data, depois Carregar.", false);
      }
    })
    .catch((e) => {
      console.error(e);
      setStatus("Erro ao carregar dispositivos: " + e.message, true);
      el("device-select").innerHTML = '<option value="">Erro</option>';
    });

  el("btn-load").addEventListener("click", () => {
    loadHistory().catch((e) => {
      console.error(e);
      setStatus("Erro: " + e.message, true);
    });
  });

  el("btn-csv").addEventListener("click", () => {
    if (!lastHistoryRows.length) return;
    const sel = el("device-select");
    const idx = parseInt(sel.value, 10);
    const d = devicesList[idx];
    if (!d) return;
    exportCsv(lastHistoryRows, d.hostname, d.username, el("history-date").value);
  });
});
