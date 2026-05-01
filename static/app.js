const DUMMY_PAGES = [
  { id: "dummy-runtime", labelKey: "tabs.dummy_runtime" },
  { id: "dummy-advanced", labelKey: "tabs.dummy_advanced" },
];

const TAB_DEFINITIONS = [
  { id: "auth-username", labelKey: "tabs.account" },
  { id: "basic", labelKey: "tabs.network" },
  { id: "opcua", labelKey: "tabs.opcua" },
  { id: "modbus", labelKey: "tabs.modbus" },
  ...DUMMY_PAGES,
];

const PASSWORD_REGEX = /^.{3,128}$/;
const DEFAULT_UPLOAD_MAX_BYTES = 1024 * 1024;
const DEFAULT_UPLOAD_MAX_FILES = 5;
const REQUIRED_UPLOAD_EXTENSION = ".der";
const REQUIRED_ADDRESS_SPACE_EXTENSION = ".csv";
const OPCUA_MIN_USERS = 1;
const OPCUA_MAX_USERS = 5;
const OPCUA_MAX_SESSIONS = 16;
const OPCUA_PRODUCT_NAME_REGEX = /^[\x20-\x7E]{1,64}$/;
const MODBUS_MAX_SLAVES = 5;
const MODBUS_DEFAULT_PORT = "502";

let uploadMaxBytes = DEFAULT_UPLOAD_MAX_BYTES;
let uploadMaxFiles = DEFAULT_UPLOAD_MAX_FILES;
let opcuaOverview = null;
let lastBasicPayloadSnapshot = null;
let lastOpcuaConfigSnapshot = null;
let lastFormatGridSnapshot = null;
let lastModbusDraftSnapshot = null;
let opcuaRefreshInterval = null;
let basicInterfaceReloadInProgress = false;
let formatGridRows = [];
let formatGridNamespaces = []; // array of {label: string} (max 5)
let formatGridValidationTimer = null;
let formatGridValidationRequestId = 0;
let modbusOpcuaVariables = [];
const FORMAT_GRID_NS_MAX = 5;
const FORMAT_GRID_VALIDATE_DEBOUNCE_MS = 250;
const RECONNECT_LOCK_STORAGE_KEY = "fieldGatewayReconnectPending";
const THEME_STORAGE_KEY = "fieldGatewayTheme";
const THEME_LIGHT = "light";
const THEME_DARK = "dark";
const i18n = window.FieldGatewayI18n;

function t(key, params = {}) {
  return i18n ? i18n.t(key, params) : key;
}

function applyLanguage() {
  if (i18n) {
    i18n.applyTranslations(document);
  }

  document.title = t("page.title.main");

  const languageButton = document.getElementById("language-toggle-btn");
  if (languageButton && i18n) {
    languageButton.textContent = i18n.getLanguage() === "ja" ? t("actions.language.en") : t("actions.language.ja");
  }
  updateThemeToggleLabel();

  for (const tab of document.querySelectorAll(".tab")) {
    const definition = TAB_DEFINITIONS.find((item) => item.id === tab.dataset.tab);
    if (definition) {
      tab.textContent = t(definition.labelKey);
    }
  }

  for (const page of DUMMY_PAGES) {
    const title = document.querySelector(`[data-page-title="${page.id}"]`);
    if (title) {
      title.textContent = t(page.labelKey);
    }

    const help = document.querySelector(`[data-page-help="${page.id}"]`);
    if (help) {
      help.textContent = t("custom.help");
    }

    const label = document.querySelector(`[data-page-label="${page.id}"]`);
    if (label) {
      label.textContent = t("custom.settings_label");
    }

    const button = document.querySelector(`[data-page-button="${page.id}"]`);
    if (button) {
      button.textContent = t("custom.save_button", { label: t(page.labelKey) });
    }
  }

  for (const row of document.querySelectorAll("[data-role='opcua-user-row']")) {
    const username = row.querySelector(".opcua-user-name");
    const password = row.querySelector(".opcua-user-password");
    const removeButton = row.querySelector(".action.danger");
    if (username) {
      username.placeholder = t("opcua.user_placeholder.username");
    }
    if (password) {
      password.placeholder = t("opcua.user_placeholder.password");
    }
    if (removeButton) {
      removeButton.textContent = t("actions.delete");
    }
  }

  if (opcuaOverview) {
    renderOpcuaOverview(!hasUnsavedOpcuaChanges());
  }

  applyLanguageToGrid();
  applyLanguageToModbus();
}

function applyLanguageToGrid() {
  // Update dynamically created grid row buttons (no data-i18n attribute)
  const tbody = document.getElementById("opcua-grid-body");
  if (tbody) {
    for (const btn of tbody.querySelectorAll(".grid-ins-btn")) {
      btn.textContent = t("opcua.grid.insert_row");
    }
    for (const btn of tbody.querySelectorAll(".grid-del-btn")) {
      btn.textContent = t("opcua.grid.delete_row");
    }
  }

  // Re-render the NameSpace editor to pick up new language
  const container = document.getElementById("opcua-ns-editor-rows");
  if (container && formatGridNamespaces.length > 0) {
    renderNamespaceEditor(formatGridNamespaces.map((n) => n.label));
  }

  // Update toggle button label
  updateToggleButtonLabel();
}

function applyLanguageToModbus() {
  const slaveBody = document.getElementById("modbus-slave-body");
  if (!slaveBody) {
    return;
  }

  renderModbusDraft(collectModbusDraftFromForm(), { preserveMappingVisibility: true });
}

function toggleLanguage() {
  if (!i18n) {
    return;
  }
  i18n.toggleLanguage();
  applyLanguage();
}

function normalizeTheme(value) {
  return value === THEME_DARK ? THEME_DARK : THEME_LIGHT;
}

function getSavedTheme() {
  try {
    return normalizeTheme(window.localStorage.getItem(THEME_STORAGE_KEY));
  } catch (_error) {
    return THEME_LIGHT;
  }
}

function getCurrentTheme() {
  return document.body.classList.contains("theme-dark") ? THEME_DARK : THEME_LIGHT;
}

function applyTheme(theme, persist = true) {
  const normalized = normalizeTheme(theme);
  document.body.classList.toggle("theme-dark", normalized === THEME_DARK);
  if (persist) {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, normalized);
    } catch (_error) {
      // ignore localStorage failures
    }
  }
  updateThemeToggleLabel();
}

function updateThemeToggleLabel() {
  const btn = document.getElementById("theme-toggle-btn");
  if (!btn) return;
  const currentTheme = getCurrentTheme();
  btn.textContent = currentTheme === THEME_DARK ? t("actions.theme.light") : t("actions.theme.dark");
}

function toggleTheme() {
  const nextTheme = getCurrentTheme() === THEME_DARK ? THEME_LIGHT : THEME_DARK;
  applyTheme(nextTheme);
}

function showMessage(msg, isError = false) {
  const activeTab = document.querySelector(".tab.active")?.dataset?.tab || "";
  const local = activeTab ? document.getElementById(`message-${activeTab}`) : null;
  const el = local || document.getElementById("message");
  el.textContent = msg;
  el.classList.toggle("is-error", Boolean(msg) && isError);
  el.classList.toggle("is-ok", Boolean(msg) && !isError);
  delete el.dataset.gridValidation;
}

function showMessageOn(tabId, msg, isError = false) {
  const local = document.getElementById(`message-${tabId}`);
  if (local) {
    local.textContent = msg;
    local.classList.toggle("is-error", Boolean(msg) && isError);
    local.classList.toggle("is-ok", Boolean(msg) && !isError);
    delete local.dataset.gridValidation;
    return;
  }
  showMessage(msg, isError);
}

function setReconnectLock(show, persist = false) {
  const overlay = document.getElementById("reconnect-overlay");
  overlay.classList.toggle("hidden", !show);
  document.body.classList.toggle("ui-locked", show);

  if (persist) {
    if (show) {
      window.localStorage.setItem(RECONNECT_LOCK_STORAGE_KEY, "1");
    } else {
      window.localStorage.removeItem(RECONNECT_LOCK_STORAGE_KEY);
    }
  }
}

function bindReconnectLockEvents() {
  document.getElementById("reconnect-ack").addEventListener("click", () => {
    setReconnectLock(false, true);
    showMessageOn("basic", t("msg.reconnect.verify"));
  });

  if (window.localStorage.getItem(RECONNECT_LOCK_STORAGE_KEY) === "1") {
    setReconnectLock(true, false);
  }
}

async function requestJson(url, options = {}) {
  let requestUrl = url;
  if (typeof url === "string") {
    const baseUrl = `${window.location.protocol}//${window.location.host}`;
    requestUrl = new URL(url, baseUrl).toString();
  }

  const res = await fetch(requestUrl, options);
  let data = {};
  try {
    data = await res.json();
  } catch (_error) {
    data = {};
  }

  if (res.status === 401) {
    throw new Error(t("msg.auth_failed_reload"));
  }
  if (!res.ok) {
    throw new Error(data.error || `request failed: ${res.status}`);
  }
  return data;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function buildTabs() {
  const tabList = document.getElementById("tab-list");
  tabList.innerHTML = "";

  for (const tabDef of TAB_DEFINITIONS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "tab";
    btn.dataset.tab = tabDef.id;
    btn.textContent = t(tabDef.labelKey);
    btn.addEventListener("click", () => requestTabChange(tabDef.id));
    tabList.appendChild(btn);
  }
}

function buildCustomPanels() {
  const host = document.getElementById("custom-panels");
  if (!host) {
    return;
  }

  host.innerHTML = "";
  for (const page of DUMMY_PAGES) {
    const section = document.createElement("section");
    section.id = `panel-${page.id}`;
    section.className = "panel";
    section.setAttribute("role", "tabpanel");

    section.innerHTML = `
      <h2 data-page-title="${page.id}">${t(page.labelKey)}</h2>
      <p class="custom-help" data-page-help="${page.id}">${t("custom.help")}</p>
      <form class="custom-form" data-page-id="${page.id}">
        <label data-page-label="${page.id}">${t("custom.settings_label")}</label>
        <textarea id="custom-json-${page.id}" class="custom-json" spellcheck="false">{}</textarea>
        <button type="button" class="action custom-save-btn" data-page-button="${page.id}">${t("custom.save_button", { label: t(page.labelKey) })}</button>
      </form>
      <p id="message-${page.id}" class="tab-message"></p>
    `;
    host.appendChild(section);
  }
}

function startLocalTimeClock() {
  const target = document.getElementById("local-time");
  if (!target) {
    return;
  }

  const render = () => {
    const now = new Date();
    const parts = [
      String(now.getFullYear()).padStart(4, "0"),
      String(now.getMonth() + 1).padStart(2, "0"),
      String(now.getDate()).padStart(2, "0"),
    ];
    const time = [
      String(now.getHours()).padStart(2, "0"),
      String(now.getMinutes()).padStart(2, "0"),
      String(now.getSeconds()).padStart(2, "0"),
    ];
    target.textContent = `${parts.join("-")} ${time.join(":")}`;
  };

  render();
  window.setInterval(render, 1000);
}

function startOpcuaAutoRefresh() {
  if (opcuaRefreshInterval) {
    return; // Already running
  }
  opcuaRefreshInterval = window.setInterval(async () => {
    try {
      await loadOpcua({ autoRefresh: true });
    } catch (error) {
      console.error("OPCUA auto-refresh error:", error);
      // Continue refreshing even if there's an error
    }
  }, 5000); // 5 seconds
}

function stopOpcuaAutoRefresh() {
  if (opcuaRefreshInterval) {
    window.clearInterval(opcuaRefreshInterval);
    opcuaRefreshInterval = null;
  }
}

function setTab(tabName) {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.classList.toggle("active", tab.dataset.tab === tabName);
  }

  for (const panel of document.querySelectorAll(".panel")) {
    panel.classList.toggle("active", panel.id === `panel-${tabName}`);
  }

  // Start/stop OPCUA auto-refresh based on active tab
  if (tabName === "opcua") {
    startOpcuaAutoRefresh();
  } else {
    stopOpcuaAutoRefresh();
  }
}

function createEmptyModbusSlave() {
  return { name: "", ip: "", port: MODBUS_DEFAULT_PORT, type: "holding", unitId: 1 };
}

function sanitizeModbusDraft(raw) {
  const source = raw && typeof raw === "object" ? raw : {};
  const slaves = Array.isArray(source.slaves)
    ? source.slaves.slice(0, MODBUS_MAX_SLAVES).map((item) => ({
        name: String(item?.name || "").trim(),
        ip: String(item?.ip || "").trim(),
        port: String(item?.port || MODBUS_DEFAULT_PORT).trim(),
        type: String(item?.type || "holding").trim() || "holding",
        unitId: Math.min(255, Math.max(0, parseInt(item?.unitId ?? 1, 10) || 1)),
      }))
    : [];
  const mappings = Array.isArray(source.mappings)
    ? source.mappings.map((item) => ({
        nodeId: String(item?.nodeId || "").trim(),
        browsePath: String(item?.browsePath || "").trim(),
        browseName: String(item?.browseName || "").trim(),
        dataType: String(item?.dataType || "").trim(),
        slaveName: String(item?.slaveName || "").trim(),
        address: String(item?.address || "").trim(),
      }))
    : [];
  return { slaves, mappings };
}

function isValidIPv4Address(ip) {
  const parts = ip.split(".");
  if (parts.length !== 4) {
    return false;
  }

  return parts.every((part) => {
    if (!/^\d{1,3}$/.test(part)) {
      return false;
    }
    const number = Number(part);
    return Number.isInteger(number) && number >= 0 && number <= 255;
  });
}

function isModbusMappingCardVisible() {
  const card = document.getElementById("modbus-mapping-card");
  return Boolean(card) && card.style.display !== "none";
}

function setModbusMappingCardVisible(visible) {
  const card = document.getElementById("modbus-mapping-card");
  if (card) {
    card.style.display = visible ? "block" : "none";
  }
}

function normalizeModbusMappingKey(mapping) {
  const nodeId = String(mapping?.nodeId || "").trim();
  if (nodeId) {
    return `nid::${nodeId}`;
  }
  const browseName = String(mapping?.browseName || "").trim();
  if (browseName) {
    return `bn::${browseName}`;
  }
  return `bp::${String(mapping?.browsePath || "").trim()}`;
}

function getModbusMappingSourceRows(savedMappings = []) {
  const savedMap = new Map(savedMappings.map((item) => [normalizeModbusMappingKey(item), item]));
  if (modbusOpcuaVariables.length > 0) {
    return modbusOpcuaVariables.map((item) => ({
      ...item,
      ...(savedMap.get(normalizeModbusMappingKey(item)) || {}),
    }));
  }
  return savedMappings;
}

function updateModbusSlaveCount(count) {
  const target = document.getElementById("modbus-slave-count");
  if (target) {
    target.textContent = t("modbus.count.slaves", { count, max: MODBUS_MAX_SLAVES });
  }
}

function updateModbusMappingStatus(message = "", count = 0) {
  const target = document.getElementById("modbus-mapping-status");
  if (!target) {
    return;
  }
  const countLabel = t("modbus.count.mappings", { count });
  target.textContent = message ? `${message} | ${countLabel}` : countLabel;
}

function clearModbusConnectionResult() {
  const card = document.getElementById("modbus-connect-result-card");
  const summary = document.getElementById("modbus-connect-result-summary");
  const body = document.getElementById("modbus-connect-result-body");
  const tableWrap = card?.querySelector(".modbus-grid-wrap");
  if (summary) {
    summary.textContent = "";
    summary.classList.remove("modbus-result-summary", "is-error");
  }
  if (body) {
    body.innerHTML = "";
  }
  if (tableWrap) {
    tableWrap.hidden = false;
  }
  if (card) {
    card.hidden = true;
  }
}

function renderModbusConnectionResult({ ip = "", port = "", unitId = "", hexValues = [], errorMessage = "" } = {}) {
  const card = document.getElementById("modbus-connect-result-card");
  const summary = document.getElementById("modbus-connect-result-summary");
  const body = document.getElementById("modbus-connect-result-body");
  const tableWrap = card?.querySelector(".modbus-grid-wrap");
  if (!card || !summary || !body) {
    return;
  }

  const isError = Boolean(errorMessage);
  summary.textContent = isError
    ? (errorMessage || t("modbus.result.summary.error", { ip, port }))
    : t("modbus.result.summary.success", { ip, port, unitId });
  summary.classList.add("modbus-result-summary");
  summary.classList.toggle("is-error", isError);

  body.innerHTML = "";
  if (tableWrap) {
    tableWrap.hidden = isError;
  }

  if (!isError && Array.isArray(hexValues) && hexValues.length > 0) {
    hexValues.slice(0, 9).forEach((value, index) => {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td>ADDR${index}</td>
        <td>${escapeHtml(value)}</td>
      `;
      body.appendChild(row);
    });
  } else if (!isError) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="2" class="modbus-result-empty">${escapeHtml(t("modbus.result.empty"))}</td>`;
    body.appendChild(row);
  }

  card.hidden = false;
}

function renderModbusSlaveRows(slaves) {
  const tbody = document.getElementById("modbus-slave-body");
  if (!tbody) {
    return;
  }

  tbody.innerHTML = "";
  for (const [index, slave] of slaves.entries()) {
    const row = document.createElement("tr");
    row.dataset.rowIndex = String(index);
    row.innerHTML = `
      <td><input class="modbus-slave-name" type="text" value="${escapeHtml(slave.name)}" /></td>
      <td><input class="modbus-slave-ip" type="text" inputmode="decimal" value="${escapeHtml(slave.ip)}" /></td>
      <td><input class="modbus-slave-port" type="number" min="1" max="65535" inputmode="numeric" value="${escapeHtml(slave.port)}" /></td>
      <td><input class="modbus-slave-unit-id" type="number" min="0" max="255" inputmode="numeric" value="${escapeHtml(String(slave.unitId ?? 1))}" /></td>
      <td>
        <select class="modbus-slave-type">
          <option value="holding" ${slave.type === "holding" ? "selected" : ""}>${escapeHtml(t("modbus.type.holding"))}</option>
        </select>
      </td>
      <td>
        <div class="action-row">
          <button type="button" class="action secondary modbus-connect-btn">${escapeHtml(t("modbus.actions.connect"))}</button>
          <button type="button" class="action danger modbus-delete-btn">${escapeHtml(t("modbus.actions.delete"))}</button>
        </div>
      </td>
    `;
    tbody.appendChild(row);
  }

  updateModbusSlaveCount(slaves.length);
  const addButton = document.getElementById("modbus-add-slave-btn");
  if (addButton) {
    addButton.disabled = slaves.length >= MODBUS_MAX_SLAVES;
  }
}

function renderModbusMappingRows(draft) {
  const tbody = document.getElementById("modbus-mapping-body");
  if (!tbody) {
    return;
  }

  const sourceRows = getModbusMappingSourceRows(draft.mappings || []);
  if (sourceRows.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="modbus-empty-cell">${escapeHtml(t("modbus.empty.mapping"))}</td></tr>`;
    updateModbusMappingStatus("", 0);
    return;
  }

  const slaveOptions = draft.slaves.map((slave) => slave.name).filter(Boolean);
  tbody.innerHTML = "";
  for (const item of sourceRows) {
    const row = document.createElement("tr");
    row.dataset.nodeId = item.nodeId || "";
    row.dataset.browsePath = item.browsePath || "";
    row.dataset.browseName = item.browseName || "";
    row.dataset.dataType = item.dataType || "";

    const optionsHtml = ['<option value=""></option>']
      .concat(
        slaveOptions.map((name) => (
          `<option value="${escapeHtml(name)}" ${item.slaveName === name ? "selected" : ""}>${escapeHtml(name)}</option>`
        )),
      )
      .join("");

    row.innerHTML = `
      <td>${escapeHtml(item.browsePath || "")}</td>
      <td>${escapeHtml(item.browseName || item.nodeId || "")}</td>
      <td>${escapeHtml(item.dataType || "")}</td>
      <td><select class="modbus-mapping-slave">${optionsHtml}</select></td>
      <td><input class="modbus-mapping-address" type="text" value="${escapeHtml(item.address || "")}" /></td>
      <td><button type="button" class="action secondary modbus-clear-mapping-btn">${escapeHtml(t("modbus.actions.clear"))}</button></td>
    `;
    tbody.appendChild(row);
  }

  updateModbusMappingStatus("", sourceRows.length);
}

function renderModbusDraft(draft, options = {}) {
  const sanitized = sanitizeModbusDraft(draft);
  const preserveVisibility = Boolean(options.preserveMappingVisibility);
  const showMapping = preserveVisibility
    ? isModbusMappingCardVisible()
    : sanitized.mappings.length > 0 || modbusOpcuaVariables.length > 0 || isModbusMappingCardVisible();

  renderModbusSlaveRows(sanitized.slaves);
  renderModbusMappingRows(sanitized);
  setModbusMappingCardVisible(showMapping);

  const help = document.querySelector('[data-i18n="modbus.slaves.help"]');
  if (help) {
    help.textContent = t("modbus.slaves.help", { max: MODBUS_MAX_SLAVES });
  }
}

function collectModbusDraftFromForm() {
  const slaves = Array.from(document.querySelectorAll("#modbus-slave-body tr[data-row-index]"))
    .map((row) => ({
      name: row.querySelector(".modbus-slave-name")?.value.trim() || "",
      ip: row.querySelector(".modbus-slave-ip")?.value.trim() || "",
      port: row.querySelector(".modbus-slave-port")?.value.trim() || "",
      type: row.querySelector(".modbus-slave-type")?.value.trim() || "holding",
      unitId: parseInt(row.querySelector(".modbus-slave-unit-id")?.value ?? "1", 10) || 1,
    }))
    .filter((item) => item.name || item.ip || item.port || item.type !== "holding");

  const mappings = Array.from(document.querySelectorAll("#modbus-mapping-body tr[data-browse-name], #modbus-mapping-body tr[data-browse-path], #modbus-mapping-body tr[data-node-id]"))
    .map((row) => ({
      nodeId: row.dataset.nodeId || "",
      browsePath: row.dataset.browsePath || "",
      browseName: row.dataset.browseName || "",
      dataType: row.dataset.dataType || "",
      slaveName: row.querySelector(".modbus-mapping-slave")?.value.trim() || "",
      address: row.querySelector(".modbus-mapping-address")?.value.trim() || "",
    }))
    .filter((item) => item.slaveName || item.address);

  return { slaves, mappings };
}

function hasUnsavedModbusChanges() {
  if (!lastModbusDraftSnapshot) {
    return false;
  }
  return JSON.stringify(collectModbusDraftFromForm()) !== JSON.stringify(lastModbusDraftSnapshot);
}

function validateModbusDraft(draft) {
  const names = new Set();
  for (const slave of draft.slaves) {
    if (!slave.name) {
      throw new Error(t("msg.modbus_name_required"));
    }
    const normalizedName = slave.name.toLowerCase();
    if (names.has(normalizedName)) {
      throw new Error(t("msg.modbus_name_duplicate"));
    }
    if (!isValidIPv4Address(slave.ip)) {
      throw new Error(t("msg.modbus_ip_invalid", { name: slave.name }));
    }
    const port = Number(slave.port);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      throw new Error(t("msg.modbus_port_invalid"));
    }
    const unitId = Number(slave.unitId);
    if (!Number.isInteger(unitId) || unitId < 0 || unitId > 255) {
      throw new Error(t("msg.modbus_unit_id_invalid"));
    }
    names.add(normalizedName);
  }

  for (const mapping of draft.mappings) {
    if (!mapping.slaveName || !mapping.address) {
      throw new Error(t("msg.modbus_mapping_invalid"));
    }
    if (!names.has(mapping.slaveName.toLowerCase())) {
      throw new Error(t("msg.modbus_mapping_unknown_slave", { name: mapping.slaveName }));
    }
  }
}

function parseCidr(ipv4Cidr) {
  if (!ipv4Cidr || !ipv4Cidr.includes("/")) {
    return { ip: "", prefix: "" };
  }
  const [ip, prefix] = ipv4Cidr.split("/");
  return { ip, prefix };
}

function splitIPv4(ip) {
  if (!ip || !ip.includes(".")) {
    return ["", "", "", ""];
  }
  const parts = ip.split(".");
  if (parts.length !== 4) {
    return ["", "", "", ""];
  }
  return parts;
}

function setSegment(group, ip) {
  const parts = splitIPv4(ip);
  for (let i = 1; i <= 4; i += 1) {
    document.getElementById(`${group}_${i}`).value = parts[i - 1] || "";
  }
}

function readSegment(group, required = false) {
  const values = [];
  for (let i = 1; i <= 4; i += 1) {
    values.push(document.getElementById(`${group}_${i}`).value.trim());
  }

  const allEmpty = values.every((v) => v === "");
  const anyEmpty = values.some((v) => v === "");

  if (allEmpty) {
    if (required) {
      throw new Error(t("msg.invalid_group", { group }));
    }
    return "";
  }

  if (anyEmpty) {
    throw new Error(t("msg.fill_all_fields", { group }));
  }

  const normalized = values.map((v) => {
    const n = Number(v);
    if (!Number.isInteger(n) || n < 0 || n > 255) {
      throw new Error(t("msg.range_0_255", { group }));
    }
    return String(n);
  });

  return normalized.join(".");
}

function prefixToMask(prefixStr) {
  const prefix = Number(prefixStr);
  if (!Number.isInteger(prefix) || prefix < 1 || prefix > 32) {
    return "";
  }

  const parts = [];
  let bits = prefix;
  for (let i = 0; i < 4; i += 1) {
    const use = Math.max(0, Math.min(8, bits));
    const octet = use === 0 ? 0 : 256 - 2 ** (8 - use);
    parts.push(String(octet));
    bits -= use;
  }
  return parts.join(".");
}

function maskToPrefix(mask) {
  const parts = splitIPv4(mask).map((value) => Number(value));
  if (parts.length !== 4 || parts.some((value) => !Number.isInteger(value) || value < 0 || value > 255)) {
    return "";
  }

  let prefix = 0;
  let seenZeroBit = false;
  for (const octet of parts) {
    for (let bit = 7; bit >= 0; bit -= 1) {
      const isOneBit = (octet & (1 << bit)) !== 0;
      if (seenZeroBit && isOneBit) {
        return "";
      }
      if (isOneBit) {
        prefix += 1;
      } else {
        seenZeroBit = true;
      }
    }
  }

  return String(prefix);
}

function toggleStaticFields() {
  const mode = document.getElementById("mode").value;
  const staticFields = document.getElementById("static-fields");
  staticFields.style.display = mode === "static" ? "grid" : "none";
}

function toggleWifiFields() {
  const wifiEnabled = document.getElementById("wifi-enabled").checked;
  const wifiApFields = document.getElementById("wifi-ap-fields");
  wifiApFields.style.display = wifiEnabled ? "block" : "none";
  if (wifiEnabled) {
    fetchWifiSsids();
  }
}

async function fetchWifiSsids() {
  const btn = document.getElementById("wifi-scan-btn");
  if (btn) {
    btn.disabled = true;
    btn.textContent = t("basic.wifi_scan");
  }
  try {
    const data = await requestJson("/api/wifi/scan");
    const datalist = document.getElementById("wifi-ssid-list");
    if (!datalist) return;
    datalist.innerHTML = "";
    for (const ssid of data.ssids || []) {
      const option = document.createElement("option");
      option.value = ssid;
      datalist.appendChild(option);
    }
  } catch (_error) {
    // Scan failure is non-fatal
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = t("basic.wifi_scan");
    }
  }
}

function collectBasicPayloadFromForm() {
  const payload = {
    hostname: document.getElementById("hostname").value.trim(),
    interface: document.getElementById("interface").value.trim(),
    mode: document.getElementById("mode").value,
    ipv4: "",
    gateway4: "",
    dns: "",
    sntp: document.getElementById("sntp").value.trim(),
  };

  if (payload.mode === "static") {
    const ip = readSegment("ipv4", true);
    const subnetMask = readSegment("subnet_mask", true);
    const derivedPrefix = maskToPrefix(subnetMask);
    if (!derivedPrefix) {
      throw new Error(t("msg.subnet_contiguous"));
    }

    const prefixNum = Number(derivedPrefix);
    if (!Number.isInteger(prefixNum) || prefixNum < 1 || prefixNum > 32) {
      throw new Error(t("msg.subnet_invalid"));
    }

    payload.ipv4 = `${ip}/${prefixNum}`;
    payload.gateway4 = readSegment("gateway4", true);

    const dns1 = readSegment("dns1", false);
    const dns2 = readSegment("dns2", false);
    payload.dns = [dns1, dns2].filter(Boolean).join(",");
  }

  return payload;
}

function setBasicInterfaceOptions(interfaces, selectedInterface) {
  const select = document.getElementById("interface");
  const previousValue = select.value;
  select.innerHTML = "";

  for (const item of Array.isArray(interfaces) ? interfaces : []) {
    const option = document.createElement("option");
    option.value = item.value || "";
    option.textContent = item.label || item.value || "";
    select.appendChild(option);
  }

  const nextValue = selectedInterface || previousValue;
  if (nextValue) {
    select.value = nextValue;
  }
}

function applyBasicPayloadToForm(payload) {
  document.getElementById("hostname").value = payload.hostname || "";
  document.getElementById("interface").value = payload.interface || "";
  document.getElementById("mode").value = payload.mode || "dhcp";

  const cidr = parseCidr(payload.ipv4 || "");
  setSegment("ipv4", cidr.ip || "");
  setSegment("subnet_mask", prefixToMask(cidr.prefix || ""));

  setSegment("gateway4", payload.gateway4 || "");

  const dnsList = (payload.dns || "")
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
  setSegment("dns1", dnsList[0] || "");
  setSegment("dns2", dnsList[1] || "");

  document.getElementById("sntp").value = payload.sntp || "";
  toggleStaticFields();
}

function hasUnsavedBasicChanges() {
  if (!lastBasicPayloadSnapshot) {
    return false;
  }
  try {
    const currentPayload = collectBasicPayloadFromForm();
    return JSON.stringify(currentPayload) !== JSON.stringify(lastBasicPayloadSnapshot);
  } catch (_error) {
    return true;
  }
}

function collectOpcuaConfigDraft() {
  const rows = document.querySelectorAll("[data-role='opcua-user-row']");
  const users = [];
  for (const row of rows) {
    const username = row.querySelector(".opcua-user-name")?.value?.trim() || "";
    const password = row.querySelector(".opcua-user-password")?.value?.trim() || "";
    users.push({ username, password });
  }

  return {
    product_name: document.getElementById("opcua-product-name")?.value?.trim() || "",
    software_version: document.getElementById("opcua-software-version")?.value?.trim() || "",
    port: document.getElementById("opcua-port-number")?.value?.trim() || "",
    max_sessions: document.getElementById("opcua-max-sessions")?.value?.trim() || "",
    allow_anonymous: document.getElementById("opcua-allow-anonymous")?.checked ? "1" : "0",
    users,
  };
}

function applyOpcuaConfigDraftToForm(draft) {
  document.getElementById("opcua-product-name").value = draft?.product_name || "";
  document.getElementById("opcua-software-version").value = draft?.software_version || "";
  document.getElementById("opcua-port-number").value = draft?.port || "";
  document.getElementById("opcua-max-sessions").value = draft?.max_sessions || "";
  document.getElementById("opcua-allow-anonymous").checked = String(draft?.allow_anonymous || "") === "1";

  const userList = document.getElementById("opcua-user-list");
  userList.innerHTML = "";
  const users = Array.isArray(draft?.users) && draft.users.length > 0 ? draft.users : [{ username: "", password: "" }];
  for (const user of users) {
    userList.appendChild(createOpcuaUserRow(user));
  }
}

function hasUnsavedOpcuaChanges() {
  if (!lastOpcuaConfigSnapshot) {
    return false;
  }

  const currentDraft = collectOpcuaConfigDraft();
  return JSON.stringify(currentDraft) !== JSON.stringify(lastOpcuaConfigSnapshot);
}

function collectFormatGridDraft() {
  return {
    rows: collectGridRows(),
    ns_labels: formatGridNamespaces.map((n) => n.label),
  };
}

function hasUnsavedFormatGridChanges() {
  if (!lastFormatGridSnapshot) {
    return false;
  }
  try {
    const current = JSON.stringify(collectFormatGridDraft());
    return current !== lastFormatGridSnapshot;
  } catch (_error) {
    return false;
  }
}

function requestTabChange(targetTabId) {
  const activeTabId = document.querySelector(".tab.active")?.dataset?.tab || "";
  if (!targetTabId || targetTabId === activeTabId) {
    return;
  }

  if (activeTabId === "basic" && hasUnsavedBasicChanges()) {
    const shouldMove = window.confirm(
      t("msg.unsaved_basic"),
    );
    if (!shouldMove) {
      return;
    }
    if (lastBasicPayloadSnapshot) {
      applyBasicPayloadToForm(lastBasicPayloadSnapshot);
    }
  }

  if (activeTabId === "opcua" && hasUnsavedOpcuaChanges()) {
    const shouldMove = window.confirm(
      t("msg.unsaved_opcua"),
    );
    if (!shouldMove) {
      return;
    }
    if (lastOpcuaConfigSnapshot) {
      applyOpcuaConfigDraftToForm(lastOpcuaConfigSnapshot);
    }
  }

  if (activeTabId === "modbus" && hasUnsavedModbusChanges()) {
    const shouldMove = window.confirm(t("msg.modbus_unsaved"));
    if (!shouldMove) {
      return;
    }
    if (lastModbusDraftSnapshot) {
      renderModbusDraft(lastModbusDraftSnapshot, { preserveMappingVisibility: true });
    }
  }

  setTab(targetTabId);
}

async function loadBasic(interfaceName = "") {
  const query = interfaceName ? `?interface=${encodeURIComponent(interfaceName)}` : "";
  const data = await requestJson(`/api/basic${query}`);

  setBasicInterfaceOptions(data.interfaces || [], data.selected_interface || data.network?.interface || "");

  document.getElementById("hostname").value = data.hostname || "";
  document.getElementById("interface").value = data.selected_interface || data.network?.interface || "";
  document.getElementById("mode").value = data.network?.mode || "dhcp";

  const cidr = parseCidr(data.network?.ipv4 || "");
  setSegment("ipv4", cidr.ip || "");
  setSegment("subnet_mask", prefixToMask(cidr.prefix || ""));

  setSegment("gateway4", data.network?.gateway4 || "");

  const dnsList = (data.network?.dns || "")
    .split(",")
    .map((v) => v.trim())
    .filter(Boolean);
  setSegment("dns1", dnsList[0] || "");
  setSegment("dns2", dnsList[1] || "");

  document.getElementById("sntp").value = data.sntp || "";

  toggleStaticFields();

  try {
    lastBasicPayloadSnapshot = collectBasicPayloadFromForm();
  } catch (_error) {
    lastBasicPayloadSnapshot = null;
  }
}

async function handleInterfaceChange() {
  if (basicInterfaceReloadInProgress) {
    return;
  }

  const select = document.getElementById("interface");
  const nextInterface = select.value;
  const previousInterface = lastBasicPayloadSnapshot?.interface || "";

  if (lastBasicPayloadSnapshot && hasUnsavedBasicChanges()) {
    const shouldMove = window.confirm(t("msg.unsaved_basic"));
    if (!shouldMove) {
      select.value = previousInterface;
      return;
    }
  }

  basicInterfaceReloadInProgress = true;
  try {
    await loadBasic(nextInterface);
  } catch (error) {
    select.value = previousInterface;
    showMessageOn("basic", error.message || t("msg.basic_update_failed"), true);
  } finally {
    basicInterfaceReloadInProgress = false;
  }
}

async function loadAppSettings() {
  const data = await requestJson("/api/app");
  uploadMaxBytes = Number(data.upload_max_bytes) || DEFAULT_UPLOAD_MAX_BYTES;
  uploadMaxFiles = Number(data.upload_max_files) || DEFAULT_UPLOAD_MAX_FILES;
}

function setOpcuaServiceActionEnabled(service) {
  const installed = Boolean(opcuaOverview?.installed);
  const manageable = installed && Boolean(service?.systemctl_available) && service?.unit_file_state !== "not-found";
  document.getElementById("opcua-start-btn").disabled = !manageable || Boolean(service?.active);
  document.getElementById("opcua-stop-btn").disabled = !manageable || !Boolean(service?.active);
}

function getOpcuaServiceStateKey(service) {
  if (!service) {
    return "unknown/unknown";
  }
  return `${service.active_state || "unknown"}/${service.sub_state || "unknown"}/${service.active ? "1" : "0"}`;
}

function formatOpcuaServiceState(service) {
  const systemctlAvailable = Boolean(service?.systemctl_available);
  if (!systemctlAvailable) {
    return t("opcua.status.systemctl_unavailable");
  }
  if (service?.unit_file_state === "not-found") {
    return t("opcua.status.unit_not_found");
  }

  const activeState = service?.active_state || "unknown";
  const subState = service?.sub_state || "unknown";
  if ((activeState === "failed" && subState === "failed") || (activeState === "inactive" && subState === "dead")) {
    return t("opcua.status.not_started");
  }

  return `${activeState} / ${subState}`;
}

function sleepMs(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

async function waitForOpcuaServiceStateChange(previousStateKey, timeoutMs = 15000, intervalMs = 1000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    await loadOpcua();
    const currentKey = getOpcuaServiceStateKey(opcuaOverview?.service);
    if (currentKey !== previousStateKey) {
      return true;
    }
    await sleepMs(intervalMs);
  }

  return false;
}

function renderOpcuaFormatStatus() {
  const status = document.getElementById("opcua-format-status");
  const downloadButton = document.getElementById("opcua-format-download-btn");
  const formatFile = opcuaOverview?.format_file || null;

  if (!formatFile) {
    status.textContent = t("opcua.address_space_missing");
    downloadButton.disabled = true;
    return;
  }

  status.textContent = t("opcua.current_file", {
    name: formatFile.name,
    size: formatFile.size,
    mtime: formatFile.mtime,
  });
  downloadButton.disabled = false;
}

function renderOpcuaClientCerts() {
  const list = document.getElementById("opcua-cert-list");
  const certs = Array.isArray(opcuaOverview?.client_certs) ? opcuaOverview.client_certs : [];
  list.innerHTML = "";

  if (certs.length === 0) {
    const li = document.createElement("li");
    li.textContent = t("opcua.no_client_certificates");
    list.appendChild(li);
    return;
  }

  for (const file of certs) {
    const li = document.createElement("li");
    li.className = "file-item";

    const meta = document.createElement("span");
    meta.className = "file-meta";
    meta.textContent = t("opcua.file_meta", { name: file.name, size: file.size, mtime: file.mtime });

    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "action danger";
    removeButton.textContent = t("actions.delete");
    removeButton.addEventListener("click", () => deleteOpcuaClientCert(file.name));

    li.appendChild(meta);
    li.appendChild(removeButton);
    list.appendChild(li);
  }
}

function createOpcuaUserRow(user = { username: "", password: "" }) {
  const row = document.createElement("div");
  row.className = "file-item";
  row.dataset.role = "opcua-user-row";

  const username = document.createElement("input");
  username.type = "text";
  username.placeholder = t("opcua.user_placeholder.username");
  username.value = user.username || "";
  username.className = "opcua-user-name";

  const password = document.createElement("input");
  password.type = "text";
  password.placeholder = t("opcua.user_placeholder.password");
  password.value = user.password || "";
  password.className = "opcua-user-password";

  const removeButton = document.createElement("button");
  removeButton.type = "button";
  removeButton.className = "action danger";
  removeButton.textContent = t("actions.delete");
  removeButton.addEventListener("click", () => {
    const count = document.querySelectorAll("[data-role='opcua-user-row']").length;
    if (count <= OPCUA_MIN_USERS) {
      showMessageOn("opcua", t("msg.user_min", { min: OPCUA_MIN_USERS }), true);
      return;
    }
    row.remove();
    showMessageOn("opcua", t("msg.user_removed"));
  });

  row.appendChild(username);
  row.appendChild(password);
  row.appendChild(removeButton);
  return row;
}

function renderOpcuaConfig() {
  const config = opcuaOverview?.config || null;
  const productNameInput = document.getElementById("opcua-product-name");
  const softwareVersionInput = document.getElementById("opcua-software-version");
  const portInput = document.getElementById("opcua-port-number");
  const maxSessionsInput = document.getElementById("opcua-max-sessions");
  const allowAnonymousInput = document.getElementById("opcua-allow-anonymous");
  const userList = document.getElementById("opcua-user-list");

  productNameInput.value = config?.product_name || "";
  softwareVersionInput.value = config?.software_version || "";
  portInput.value = config?.port || "";
  maxSessionsInput.value = config?.max_sessions || "";
  allowAnonymousInput.checked = ["1", "true", "on", "yes"].includes(
    String(config?.allow_anonymous || "").toLowerCase(),
  );
  userList.innerHTML = "";

  const users = Array.isArray(config?.users) && config.users.length > 0
    ? config.users
    : [{ username: "", password: "" }];

  for (const user of users) {
    userList.appendChild(createOpcuaUserRow(user));
  }

  lastOpcuaConfigSnapshot = collectOpcuaConfigDraft();
}

function collectOpcuaConfigPayload() {
  const productName = document.getElementById("opcua-product-name").value.trim();
  if (!OPCUA_PRODUCT_NAME_REGEX.test(productName)) {
    throw new Error(t("msg.product_name_ascii"));
  }
  if (productName.includes(",")) {
    throw new Error(t("msg.product_name_comma"));
  }

  const softwareVersion = document.getElementById("opcua-software-version").value.trim();
  if (!softwareVersion) {
    throw new Error(t("msg.software_version_required"));
  }
  if (softwareVersion.length > 64) {
    throw new Error(t("msg.software_version_length"));
  }
  if (softwareVersion.includes(",")) {
    throw new Error(t("msg.software_version_comma"));
  }

  const rawPort = document.getElementById("opcua-port-number").value.trim();
  const port = Number(rawPort);
  if (!Number.isInteger(port)) {
    throw new Error(t("msg.port_number"));
  }
  if (port <= 1023 || port >= 65536) {
    throw new Error(t("msg.port_range"));
  }

  const rawMaxSessions = document.getElementById("opcua-max-sessions").value.trim();
  const maxSessions = Number(rawMaxSessions);
  if (!Number.isInteger(maxSessions)) {
    throw new Error(t("msg.max_sessions_number"));
  }
  if (maxSessions <= 0 || maxSessions > OPCUA_MAX_SESSIONS) {
    throw new Error(t("msg.max_sessions_range", { max: OPCUA_MAX_SESSIONS }));
  }

  const allowAnonymous = document.getElementById("opcua-allow-anonymous").checked;

  const rows = document.querySelectorAll("[data-role='opcua-user-row']");
  const users = [];
  for (const row of rows) {
    const username = row.querySelector(".opcua-user-name")?.value?.trim() || "";
    const password = row.querySelector(".opcua-user-password")?.value?.trim() || "";
    if (!username || !password) {
      throw new Error(t("msg.user_entry_required"));
    }
    users.push({ username, password });
  }

  if (users.length < OPCUA_MIN_USERS) {
    throw new Error(t("msg.user_min", { min: OPCUA_MIN_USERS }));
  }
  if (users.length > OPCUA_MAX_USERS) {
    throw new Error(t("msg.user_max", { max: OPCUA_MAX_USERS }));
  }

  return {
    product_name: productName,
    software_version: softwareVersion,
    port,
    max_sessions: maxSessions,
    allow_anonymous: allowAnonymous,
    users,
  };
}

function renderOpcuaOverview(refreshConfig = true) {
  const installed = Boolean(opcuaOverview?.installed);
  const service = opcuaOverview?.service || {};
  const serviceText = formatOpcuaServiceState(service);
  document.getElementById("opcua-service-state").textContent = serviceText;

  document.getElementById("opcua-reload-btn").disabled = false;
  document.getElementById("opcua-cert-upload-btn").disabled = !installed;
  document.getElementById("opcua-cert-reload-btn").disabled = !installed;
  document.getElementById("opcua-format-upload-btn").disabled = !installed;
  document.getElementById("opcua-format-download-btn").disabled = !installed;
  document.getElementById("opcua-user-add-btn").disabled = !installed;
  document.getElementById("opcua-config-save-btn").disabled = !installed;
  document.getElementById("opcua-product-name").disabled = !installed;
  document.getElementById("opcua-software-version").disabled = !installed;
  document.getElementById("opcua-port-number").disabled = !installed;
  document.getElementById("opcua-max-sessions").disabled = !installed;
  document.getElementById("opcua-allow-anonymous").disabled = !installed;

  setOpcuaServiceActionEnabled(service);
  renderOpcuaFormatStatus();
  renderOpcuaClientCerts();
  if (refreshConfig) {
    renderOpcuaConfig();
  }
}

// ---------------------------------------------------------------------------
// format.csv Grid Editor
// ---------------------------------------------------------------------------

const GRID_DATA_TYPES = [
  { value: "", label: "" },
  { value: "Boolean", label: "Boolean" },
  { value: "INT16", label: "INT16" },
  { value: "UINT16", label: "UINT16" },
  { value: "INT32", label: "INT32" },
  { value: "UINT32", label: "UINT32" },
  { value: "FLOAT", label: "FLOAT" },
  { value: "INT64", label: "INT64" },
  { value: "UINT64", label: "UINT64" },
  { value: "DOUBLE", label: "DOUBLE" },
  { value: "String", label: "String" },
];

const GRID_ACCESS_LEVELS = [
  { value: "", label: "" },
  { value: "1", label: "Read" },
  { value: "2", label: "Write" },
  { value: "3", label: "Read/Write" },
];

function createGridSelect(options, currentValue, className) {
  const sel = document.createElement("select");
  if (className) sel.className = className;
  for (const opt of options) {
    const el = document.createElement("option");
    if (typeof opt === "string") {
      el.value = opt;
      el.textContent = opt || "—";
    } else {
      el.value = opt.value;
      el.textContent = opt.label || "—";
    }
    if ((typeof opt === "string" ? opt : opt.value) === currentValue) el.selected = true;
    sel.appendChild(el);
  }
  return sel;
}

function createGridCell(content) {
  const td = document.createElement("td");
  td.appendChild(content);
  return td;
}

function getFormatGridValidationStatusElement() {
  return document.getElementById("opcua-grid-validation-status");
}

function setFormatGridValidationStatus(message = "", isError = false) {
  const el = getFormatGridValidationStatusElement();
  if (!el) return;
  el.textContent = message;
  el.classList.toggle("is-error", Boolean(message) && isError);
  el.classList.toggle("is-ok", Boolean(message) && !isError);
}

function clearFormatGridValidationStatus() {
  setFormatGridValidationStatus("");
}

function bindFormatGridValidationTrigger(element, eventName = "change") {
  if (!element) return;
  element.addEventListener(eventName, () => {
    scheduleFormatGridValidation();
  });
}

function gridNodeClassChangeWillClearValues(tr, nextNodeClass) {
  if (nextNodeClass === "Variable") {
    return Boolean(tr.querySelector(".grid-event-notifier")?.checked);
  }

  if (nextNodeClass === "Object") {
    return Boolean(
      tr.querySelector(".grid-data-type")?.value
      || tr.querySelector(".grid-access")?.value
      || tr.querySelector(".grid-historizing")?.checked
      || tr.querySelector(".grid-param1")?.checked
    );
  }

  return false;
}

function applyGridNodeClassTransition(tr, nextNodeClass) {
  const dataTypeSel = tr.querySelector(".grid-data-type");
  const accessSel = tr.querySelector(".grid-access");
  const histCheck = tr.querySelector(".grid-historizing");
  const evtCheck = tr.querySelector(".grid-event-notifier");
  const param1Check = tr.querySelector(".grid-param1");

  if (nextNodeClass === "Variable") {
    if (evtCheck) evtCheck.checked = false;
    return;
  }

  if (nextNodeClass === "Object") {
    if (dataTypeSel) dataTypeSel.value = "";
    if (accessSel) accessSel.value = "";
    if (histCheck) histCheck.checked = false;
    if (param1Check) param1Check.checked = false;
    const cyclicInput = tr.querySelector(".grid-cyclic");
    if (cyclicInput) cyclicInput.value = "";
  }
}

function handleGridNodeClassChange(tr, nodeClassSel) {
  const prevNodeClass = nodeClassSel.dataset.previousValue || nodeClassSel.value;
  const nextNodeClass = nodeClassSel.value;

  if (prevNodeClass === nextNodeClass) {
    updateGridRowForNodeClass(tr, nextNodeClass);
    scheduleFormatGridValidation();
    return;
  }

  if (gridNodeClassChangeWillClearValues(tr, nextNodeClass)) {
    const confirmed = window.confirm(
      t("opcua.grid.node_class_change_confirm", { nodeClass: nextNodeClass }),
    );
    if (!confirmed) {
      nodeClassSel.value = prevNodeClass;
      return;
    }
  }

  applyGridNodeClassTransition(tr, nextNodeClass);
  updateGridRowForNodeClass(tr, nextNodeClass);
  nodeClassSel.dataset.previousValue = nextNodeClass;
  scheduleFormatGridValidation();
}

function enforceSingleObjectEventNotifier(activeTr) {
  const tbody = document.getElementById("opcua-grid-body");
  if (!tbody) return;
  for (const tr of tbody.querySelectorAll("tr")) {
    if (tr === activeTr) continue;
    const nodeClassSel = tr.querySelector(".grid-node-class");
    const evtCheck = tr.querySelector(".grid-event-notifier");
    if (!nodeClassSel || !evtCheck) continue;
    if (nodeClassSel.value === "Object") {
      evtCheck.checked = false;
    }
  }
}

function buildNamespaceOptions(selectedIndex) {
  // Build options array for namespace select from formatGridNamespaces
  const opts = formatGridNamespaces.map((ns, i) => ({
    value: String(i),
    label: ns.label || t("opcua.grid.ns_unnamed_label", { n: i + 1 }),
  }));
  if (opts.length === 0) {
    opts.push({ value: "0", label: t("opcua.grid.ns_unnamed_label", { n: 1 }) });
  }
  return opts;
}

function adjustGridNsIndexAfterDelete(delIdx) {
  // Reset rows using the deleted namespace to index 0.
  // Decrement rows using a higher index so they still point to the same namespace.
  const tbody = document.getElementById("opcua-grid-body");
  if (!tbody) return;
  for (const tr of tbody.querySelectorAll("tr")) {
    const sel = tr.querySelector(".grid-ns-index");
    if (!sel) continue;
    const current = parseInt(sel.value, 10);
    if (current === delIdx) {
      sel.value = "0";
    } else if (current > delIdx) {
      sel.value = String(current - 1);
    }
  }
}

function createGridRow(rowData, rowIndex) {
  const tr = document.createElement("tr");
  tr.dataset.rowIndex = rowIndex;
  tr.dataset.originalRow = rowData._row !== undefined ? String(rowData._row) : "-1";

  // NodeClass
  const nodeClassSel = createGridSelect(["Object", "Variable"], rowData.NodeClass, "grid-node-class");
  nodeClassSel.dataset.previousValue = rowData.NodeClass || "Variable";
  nodeClassSel.addEventListener("change", () => {
    handleGridNodeClassChange(tr, nodeClassSel);
  });
  tr.appendChild(createGridCell(nodeClassSel));

  // BrowsePath
  const bpInput = document.createElement("input");
  bpInput.type = "text";
  bpInput.value = rowData.BrowsePath || "";
  bpInput.className = "grid-browse-path";
  bindFormatGridValidationTrigger(bpInput, "input");
  tr.appendChild(createGridCell(bpInput));

  // BrowseName
  const bnInput = document.createElement("input");
  bnInput.type = "text";
  bnInput.value = rowData.BrowseName || "";
  bnInput.className = "grid-browse-name";
  bindFormatGridValidationTrigger(bnInput, "input");
  tr.appendChild(createGridCell(bnInput));

  // NamespaceIndex (select) - separate column
  const nsSel = createGridSelect(buildNamespaceOptions(), String(rowData.NamespaceIndex || "0"), "grid-ns-index");
  bindFormatGridValidationTrigger(nsSel);
  tr.appendChild(createGridCell(nsSel));

  // NodeIdNumber (text input) - separate column
  const idNumInput = document.createElement("input");
  idNumInput.type = "text";
  idNumInput.value = rowData.NodeIdNumber || "";
  idNumInput.className = "grid-node-id-num";
  idNumInput.placeholder = "e.g. 10001";
  bindFormatGridValidationTrigger(idNumInput, "input");
  tr.appendChild(createGridCell(idNumInput));

  // DataType
  const dtSel = createGridSelect(GRID_DATA_TYPES, rowData.DataType || "", "grid-data-type");
  bindFormatGridValidationTrigger(dtSel);
  tr.appendChild(createGridCell(dtSel));

  // Access
  const accessSel = createGridSelect(GRID_ACCESS_LEVELS, rowData.Access || "", "grid-access");
  bindFormatGridValidationTrigger(accessSel);
  tr.appendChild(createGridCell(accessSel));

  // Historizing
  const histCheck = document.createElement("input");
  histCheck.type = "checkbox";
  histCheck.className = "grid-historizing";
  histCheck.checked = rowData.Historizing === "1";
  histCheck.title = t("opcua.grid.hint.historizing_variable_only");
  bindFormatGridValidationTrigger(histCheck);
  tr.appendChild(createGridCell(histCheck));

  // EventNotifier (Object only)
  const evtCheck = document.createElement("input");
  evtCheck.type = "checkbox";
  evtCheck.className = "grid-event-notifier";
  evtCheck.checked = rowData.EventNotifier === "1";
  evtCheck.title = t("opcua.grid.hint.event_object_only");
  evtCheck.addEventListener("change", () => {
    if (evtCheck.checked) {
      enforceSingleObjectEventNotifier(tr);
    }
    scheduleFormatGridValidation();
  });
  tr.appendChild(createGridCell(evtCheck));

  // Event detection flag for Variable nodes (stored in Param1: "1" or "0")
  const param1Check = document.createElement("input");
  param1Check.type = "checkbox";
  param1Check.className = "grid-param1";
  param1Check.checked = rowData.Param1 === "1";
  param1Check.title = t("opcua.grid.hint.param1_detect");
  bindFormatGridValidationTrigger(param1Check);
  tr.appendChild(createGridCell(param1Check));

  // Cyclic interval (Variable only)
  const cyclicInput = document.createElement("input");
  cyclicInput.type = "number";
  cyclicInput.className = "grid-cyclic";
  cyclicInput.value = rowData.Cyclic || "1000";
  cyclicInput.min = "250";
  cyclicInput.max = "300000";
  cyclicInput.placeholder = "1000";
  cyclicInput.title = t("opcua.grid.hint.cyclic");
  bindFormatGridValidationTrigger(cyclicInput, "input");
  tr.appendChild(createGridCell(cyclicInput));

  // Insert button (add row after this row)
  const insBtn = document.createElement("button");
  insBtn.type = "button";
  insBtn.className = "action grid-ins-btn";
  insBtn.textContent = t("opcua.grid.insert_row");
  insBtn.addEventListener("click", () => {
    insertFormatGridRowAfter(tr);
  });

  // Delete button
  const delBtn = document.createElement("button");
  delBtn.type = "button";
  delBtn.className = "action danger grid-del-btn";
  delBtn.textContent = t("opcua.grid.delete_row");
  delBtn.addEventListener("click", () => {
    if (!window.confirm(t("opcua.grid.delete_confirm"))) return;
    tr.remove();
    updateGridRowIndices();
    updateGridRowCount();
    scheduleFormatGridValidation();
  });
  const actionTd = document.createElement("td");
  actionTd.className = "grid-action-cell";
  actionTd.appendChild(insBtn);
  actionTd.appendChild(delBtn);
  tr.appendChild(actionTd);

  updateGridRowForNodeClass(tr, rowData.NodeClass);
  return tr;
}

function updateGridRowForNodeClass(tr, nodeClass) {
  const isVariable = nodeClass === "Variable";
  const isObject = nodeClass === "Object";
  const dataTypeSel = tr.querySelector(".grid-data-type");
  const accessSel = tr.querySelector(".grid-access");
  const histCheck = tr.querySelector(".grid-historizing");
  const evtCheck = tr.querySelector(".grid-event-notifier");
  const param1Check = tr.querySelector(".grid-param1");
  const cyclicInput = tr.querySelector(".grid-cyclic");

  if (dataTypeSel) dataTypeSel.disabled = !isVariable;
  if (accessSel) accessSel.disabled = !isVariable;
  if (histCheck) histCheck.disabled = !isVariable;
  if (evtCheck) evtCheck.disabled = !isObject;
  if (param1Check) param1Check.disabled = !isVariable;
  if (cyclicInput) cyclicInput.disabled = !isVariable;

  // Reduce confusion: hide controls that are not applicable for the current NodeClass.
  if (histCheck) histCheck.style.visibility = isVariable ? "visible" : "hidden";
  if (evtCheck) evtCheck.style.visibility = isObject ? "visible" : "hidden";
  if (param1Check) param1Check.style.visibility = isVariable ? "visible" : "hidden";
  if (cyclicInput) cyclicInput.style.visibility = isVariable ? "visible" : "hidden";

  // Keep UI state consistent when switching NodeClass.
  if (isVariable && evtCheck) {
    evtCheck.checked = false;
  }
  if (isObject) {
    if (histCheck) histCheck.checked = false;
    if (param1Check) param1Check.checked = false;
    if (cyclicInput) cyclicInput.value = "";
  }
}

function updateGridRowIndices() {
  const tbody = document.getElementById("opcua-grid-body");
  let idx = 0;
  for (const tr of tbody.querySelectorAll("tr")) {
    tr.dataset.rowIndex = idx++;
  }
}

function updateGridRowCount() {
  const tbody = document.getElementById("opcua-grid-body");
  const count = tbody.querySelectorAll("tr").length;
  const el = document.getElementById("opcua-grid-row-count");
  if (el) el.textContent = t("opcua.grid.row_count", { count });
}

function collectGridRows() {
  const tbody = document.getElementById("opcua-grid-body");
  const rows = [];
  for (const tr of tbody.querySelectorAll("tr")) {
    const nodeClass = tr.querySelector(".grid-node-class").value;
    const histCheck = tr.querySelector(".grid-historizing");
    const evtCheck = tr.querySelector(".grid-event-notifier");
    rows.push({
      _row: parseInt(tr.dataset.originalRow ?? "-1"),
      NodeClass: nodeClass,
      BrowsePath: tr.querySelector(".grid-browse-path").value.trim(),
      BrowseName: tr.querySelector(".grid-browse-name").value.trim(),
      NamespaceIndex: tr.querySelector(".grid-ns-index").value,
      NodeIdNumber: tr.querySelector(".grid-node-id-num").value.trim(),
      DataType: nodeClass === "Variable" ? tr.querySelector(".grid-data-type").value : "",
      Access: nodeClass === "Variable" ? tr.querySelector(".grid-access").value : "",
      Historizing: (nodeClass === "Variable" && histCheck.checked) ? "1" : "",
      EventNotifier: (nodeClass === "Object" && evtCheck.checked) ? "1" : "",
      Cyclic: nodeClass === "Variable" ? (tr.querySelector(".grid-cyclic").value.trim() || "1000") : "",
      Param1: nodeClass === "Variable" ? (tr.querySelector(".grid-param1").checked ? "1" : "0") : "",
    });
  }
  return rows;
}

function renderFormatGrid(rows) {
  formatGridRows = rows;
  const tbody = document.getElementById("opcua-grid-body");
  tbody.innerHTML = "";
  rows.forEach((row, idx) => {
    tbody.appendChild(createGridRow(row, idx));
  });
  updateGridRowCount();
}

function renderNamespaceEditor(nsLabels) {
  formatGridNamespaces = (nsLabels || []).map((lbl) => ({ label: lbl }));
  const container = document.getElementById("opcua-ns-editor-rows");
  if (!container) return;
  container.innerHTML = "";
  formatGridNamespaces.forEach((ns, idx) => {
    container.appendChild(createNamespaceRow(ns.label, idx));
  });
  updateNamespaceAddBtn();
}

function createNamespaceRow(label, idx) {
  const div = document.createElement("div");
  div.className = "ns-editor-row";
  div.dataset.nsIndex = idx;

  const input = document.createElement("input");
  input.type = "text";
  input.className = "ns-label-input";
  input.value = label || "";
  input.placeholder = t("opcua.grid.ns_label_placeholder");
  input.addEventListener("input", () => {
    formatGridNamespaces[idx] = { label: input.value };
    rebuildNsSelects();
  });
  div.appendChild(input);

  const delBtn = document.createElement("button");
  delBtn.type = "button";
  delBtn.className = "action danger ns-del-btn";
  delBtn.textContent = t("opcua.grid.delete_row");
  if (idx === 0) {
    delBtn.disabled = true;
    delBtn.title = t("opcua.grid.ns_first_row_protected");
  } else {
    delBtn.addEventListener("click", () => {
      if (!window.confirm(t("opcua.grid.ns_delete_confirm"))) return;
      adjustGridNsIndexAfterDelete(idx);
      formatGridNamespaces.splice(idx, 1);
      renderNamespaceEditor(formatGridNamespaces.map((n) => n.label));
      rebuildNsSelects();
      scheduleFormatGridValidation();
    });
  }
  div.appendChild(delBtn);

  return div;
}

function updateNamespaceAddBtn() {
  const btn = document.getElementById("opcua-ns-add-btn");
  if (btn) {
    btn.disabled = formatGridNamespaces.length >= FORMAT_GRID_NS_MAX;
  }
}

function addNamespaceRow() {
  if (formatGridNamespaces.length >= FORMAT_GRID_NS_MAX) return;
  formatGridNamespaces.push({ label: "" });
  renderNamespaceEditor(formatGridNamespaces.map((n) => n.label));
  rebuildNsSelects();
}

function insertNamespaceRowAfter(idx) {
  if (formatGridNamespaces.length >= FORMAT_GRID_NS_MAX) return;
  formatGridNamespaces.splice(idx + 1, 0, { label: "" });
  renderNamespaceEditor(formatGridNamespaces.map((n) => n.label));
  rebuildNsSelects();
}

function rebuildNsSelects() {
  // Update all namespace select elements in grid rows
  const tbody = document.getElementById("opcua-grid-body");
  if (!tbody) return;
  const opts = buildNamespaceOptions();
  for (const tr of tbody.querySelectorAll("tr")) {
    const sel = tr.querySelector(".grid-ns-index");
    if (!sel) continue;
    const currentVal = sel.value;
    sel.innerHTML = "";
    for (const opt of opts) {
      const el = document.createElement("option");
      el.value = opt.value;
      el.textContent = opt.label;
      if (opt.value === currentVal) el.selected = true;
      sel.appendChild(el);
    }
  }
}

function clearGridErrorHighlights() {
  const tbody = document.getElementById("opcua-grid-body");
  if (!tbody) return;
  for (const tr of tbody.querySelectorAll("tr.grid-row-error")) {
    tr.classList.remove("grid-row-error");
    for (const el of tr.querySelectorAll(".grid-cell-error")) {
      el.classList.remove("grid-cell-error");
    }
  }
}

function applyGridErrors(errors) {
  clearGridErrorHighlights();
  const tbody = document.getElementById("opcua-grid-body");
  const rows = [...tbody.querySelectorAll("tr")];
  const fieldClassMap = {
    NodeClass: ".grid-node-class",
    BrowsePath: ".grid-browse-path",
    BrowseName: ".grid-browse-name",
    NodeIdNumber: ".grid-node-id-num",
    DataType: ".grid-data-type",
    Access: ".grid-access",
    Historizing: ".grid-historizing",
    EventNotifier: ".grid-event-notifier",
    Cyclic: ".grid-cyclic",
    Param1: ".grid-param1",
  };
  for (const err of errors) {
    const tr = rows[err.row];
    if (!tr) continue;
    tr.classList.add("grid-row-error");
    const cls = fieldClassMap[err.field];
    if (cls) {
      const el = tr.querySelector(cls);
      if (el) el.classList.add("grid-cell-error");
    }
  }
}

async function validateFormatGridInline() {
  const requestId = ++formatGridValidationRequestId;
  let data;

  try {
    data = await requestJson("/api/opcua/format-grid/validate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(collectFormatGridDraft()),
    });
  } catch (error) {
    if (requestId !== formatGridValidationRequestId) return;
    setFormatGridValidationStatus(error.message || t("opcua.grid.inline_validation_unavailable"), true);
    return;
  }

  if (requestId !== formatGridValidationRequestId) return;

  const errors = Array.isArray(data?.errors) ? data.errors : [];
  if (errors.length > 0) {
    applyGridErrors(errors);
    const first = errors[0];
    const detail = first && first.message ? `: ${first.message}` : "";
    setFormatGridValidationStatus(`${t("opcua.grid.validation_failed")}${detail}`, true);
    return;
  }

  clearGridErrorHighlights();
  clearFormatGridValidationStatus();
  const msgEl = document.getElementById("message-opcua");
  if (msgEl && msgEl.dataset.gridValidation) {
    msgEl.textContent = "";
    msgEl.classList.remove("is-error", "is-ok");
    delete msgEl.dataset.gridValidation;
  }
}

function scheduleFormatGridValidation(delay = FORMAT_GRID_VALIDATE_DEBOUNCE_MS) {
  if (formatGridValidationTimer) {
    window.clearTimeout(formatGridValidationTimer);
  }
  formatGridValidationTimer = window.setTimeout(() => {
    formatGridValidationTimer = null;
    validateFormatGridInline();
  }, delay);
}

function setFormatGridToggleButtonVisible(visible) {
  const btn = document.getElementById("opcua-grid-toggle-btn");
  if (btn) btn.style.display = visible ? "" : "none";
}

function isFormatGridOpen() {
  const gridCard = document.getElementById("opcua-grid-card");
  return gridCard && gridCard.style.display !== "none";
}

function updateToggleButtonLabel() {
  const btn = document.getElementById("opcua-grid-toggle-btn");
  if (!btn) return;
  const open = isFormatGridOpen();
  btn.textContent = t(open ? "opcua.grid.edit_close" : "opcua.grid.edit_open");
  btn.setAttribute("aria-expanded", String(open));
}

function toggleFormatGridEditor() {
  const gridCard = document.getElementById("opcua-grid-card");
  if (!gridCard) return;
  const opening = gridCard.style.display === "none";
  gridCard.style.display = opening ? "" : "none";
  updateToggleButtonLabel();
}

async function loadFormatGrid() {
  const gridCard = document.getElementById("opcua-grid-card");
  try {
    const data = await requestJson("/api/opcua/format-grid");
    renderNamespaceEditor(data.ns_labels || []);
    renderFormatGrid(data.rows || []);
    lastFormatGridSnapshot = JSON.stringify({ rows: data.rows || [], ns_labels: data.ns_labels || [] });
    formatGridValidationRequestId += 1;
    if (formatGridValidationTimer) {
      window.clearTimeout(formatGridValidationTimer);
      formatGridValidationTimer = null;
    }
    clearGridErrorHighlights();
    clearFormatGridValidationStatus();
    // Show toggle button but keep grid panel in its current open/closed state
    setFormatGridToggleButtonVisible(true);
    updateToggleButtonLabel();
  } catch (_err) {
    // No format.csv or not installed – hide both toggle and grid panel
    setFormatGridToggleButtonVisible(false);
    if (gridCard) gridCard.style.display = "none";
  }
}

async function saveFormatGrid() {
  const rows = collectGridRows();
  const ns_labels = formatGridNamespaces.map((n) => n.label);
  clearGridErrorHighlights();
  let data;
  try {
    data = await requestJson("/api/opcua/format-grid", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows, ns_labels }),
    });
  } catch (error) {
    showMessageOn("opcua", error.message || t("opcua.grid.save_failed"), true);
    return;
  }

  if (data && data.errors) {
    applyGridErrors(data.errors);
    const first = data.errors[0];
    const detail = first && first.message ? `: ${first.message}` : "";
    showMessageOn("opcua", `${t("opcua.grid.validation_failed")}${detail}`, true);
    const msgEl = document.getElementById("message-opcua");
    if (msgEl) msgEl.dataset.gridValidation = "1";
    return;
  }

  lastFormatGridSnapshot = JSON.stringify({ rows, ns_labels });
  showMessageOn("opcua", t("opcua.grid.saved", { count: data.row_count }));
}

async function assignGridNodeIds() {
  const rows = collectGridRows();
  let data;
  try {
    data = await requestJson("/api/opcua/format-grid/assign-node-ids", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows }),
    });
  } catch (error) {
    showMessageOn("opcua", error.message || t("opcua.grid.assign_failed"), true);
    return;
  }
  renderFormatGrid(data.rows || []);
  showMessageOn("opcua", t("opcua.grid.assigned"));
}

function insertFormatGridRowAfter(afterTr) {
  const tbody = document.getElementById("opcua-grid-body");
  const defaultNs = formatGridNamespaces.length > 0 ? "0" : "0";
  const emptyRow = {
    NodeClass: "Variable", BrowsePath: "", BrowseName: "",
    NamespaceIndex: defaultNs, NodeIdNumber: "",
    DataType: "", Access: "", Historizing: "", EventNotifier: "", Cyclic: "1000", Param1: "",
  };
  const newTr = createGridRow(emptyRow, 0);
  if (afterTr && afterTr.parentNode === tbody) {
    afterTr.insertAdjacentElement("afterend", newTr);
  } else {
    tbody.appendChild(newTr);
  }
  updateGridRowIndices();
  updateGridRowCount();
  scheduleFormatGridValidation();
}

function addFormatGridRow() {
  const tbody = document.getElementById("opcua-grid-body");
  const defaultNs = formatGridNamespaces.length > 0 ? "0" : "0";
  const emptyRow = {
    NodeClass: "Variable", BrowsePath: "", BrowseName: "",
    NamespaceIndex: defaultNs, NodeIdNumber: "",
    DataType: "", Access: "", Historizing: "", EventNotifier: "", Cyclic: "1000", Param1: "",
  };
  tbody.appendChild(createGridRow(emptyRow, tbody.querySelectorAll("tr").length));
  updateGridRowCount();
  scheduleFormatGridValidation();
}

async function loadOpcua(options = {}) {
  const autoRefresh = Boolean(options.autoRefresh);
  opcuaOverview = await requestJson("/api/opcua");
  const skipConfigRefresh = autoRefresh && hasUnsavedOpcuaChanges();
  const skipGridRefresh = autoRefresh && hasUnsavedFormatGridChanges();
  renderOpcuaOverview(!skipConfigRefresh);
  if (!skipGridRefresh) {
    await loadFormatGrid();
  }
}

async function loadAuthSettings() {
  const data = await requestJson("/api/auth/settings");
  document.getElementById("auth_username").value = data.username || "";
}

async function loadCustomSettings() {
  for (const page of DUMMY_PAGES) {
    const data = await requestJson(`/api/app/custom/${page.id}`);
    const target = document.getElementById(`custom-json-${page.id}`);
    if (target) {
      target.value = JSON.stringify(data.settings || {}, null, 2);
    }
  }
}

async function loadModbusMappingSource(showStatus = false) {
  try {
    const data = await requestJson("/api/opcua/format-grid");
    modbusOpcuaVariables = Array.isArray(data.rows)
      ? data.rows
          .filter((row) => row.NodeClass === "Variable" && row.DataType !== "String")
          .map((row) => ({
            nodeId: row.NodeIdNumber ? `ns=${row.NamespaceIndex};i=${row.NodeIdNumber}` : "",
            browsePath: row.BrowsePath || "",
            browseName: row.BrowseName || "",
            dataType: row.DataType || "",
            slaveName: "",
            address: "",
          }))
      : [];
    if (showStatus) {
      showMessageOn("modbus", t("msg.modbus_mapping_source_loaded"));
    }
  } catch (_error) {
    modbusOpcuaVariables = [];
    if (showStatus) {
      showMessageOn("modbus", t("msg.modbus_mapping_source_unavailable"), true);
    }
  }
}

async function loadModbusDraft() {
  await loadModbusMappingSource();
  try {
    const data = await requestJson("/api/modbus");
    const draft = sanitizeModbusDraft(data.settings || {});
    renderModbusDraft(draft);
    lastModbusDraftSnapshot = draft;
    clearModbusConnectionResult();
  } catch (_error) {
    const draft = sanitizeModbusDraft({});
    renderModbusDraft(draft);
    lastModbusDraftSnapshot = draft;
    clearModbusConnectionResult();
  }
}

async function addModbusSlave() {
  const draft = collectModbusDraftFromForm();
  if (draft.slaves.length >= MODBUS_MAX_SLAVES) {
    showMessageOn("modbus", t("msg.modbus_max_slaves", { max: MODBUS_MAX_SLAVES }), true);
    return;
  }
  draft.slaves.push(createEmptyModbusSlave());
  renderModbusDraft(draft, { preserveMappingVisibility: true });
  showMessageOn("modbus", t("msg.modbus_slave_added"));
}

function deleteModbusSlave(rowIndex) {
  const draft = collectModbusDraftFromForm();
  const deleted = draft.slaves[rowIndex];
  draft.slaves.splice(rowIndex, 1);
  if (deleted?.name) {
    draft.mappings = draft.mappings.filter((item) => item.slaveName !== deleted.name);
  }
  renderModbusDraft(draft, { preserveMappingVisibility: true });
  showMessageOn("modbus", t("msg.modbus_slave_deleted"));
}

function getValidatedModbusSlave(row) {
  const slave = {
    name: row.querySelector(".modbus-slave-name")?.value.trim() || "",
    ip: row.querySelector(".modbus-slave-ip")?.value.trim() || "",
    port: row.querySelector(".modbus-slave-port")?.value.trim() || "",
    type: row.querySelector(".modbus-slave-type")?.value.trim() || "holding",
    unitId: parseInt(row.querySelector(".modbus-slave-unit-id")?.value ?? "1", 10) || 1,
  };
  validateModbusDraft({ slaves: [slave], mappings: [] });
  return slave;
}

async function testModbusSlaveConnection(row) {
  let slave;
  try {
    slave = getValidatedModbusSlave(row);
  } catch (error) {
    clearModbusConnectionResult();
    showMessageOn("modbus", error.message || t("msg.modbus_connect_failed", { ip: "", port: "" }), true);
    return;
  }

  try {
    const data = await requestJson("/api/modbus/test-connection", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip: slave.ip, port: slave.port, unit_id: slave.unitId ?? 1, timeout_ms: 1500 }),
    });
    renderModbusConnectionResult({
      ip: slave.ip,
      port: slave.port,
      unitId: data?.unit_id ?? 1,
      hexValues: data?.hex_values,
    });
    showMessageOn("modbus", t("msg.modbus_connect_success", { ip: slave.ip, port: slave.port }));
  } catch (error) {
    renderModbusConnectionResult({
      ip: slave.ip,
      port: slave.port,
      errorMessage: error.message || t("msg.modbus_connect_failed", { ip: slave.ip, port: slave.port }),
    });
    showMessageOn("modbus", error.message || t("msg.modbus_connect_failed", { ip: slave.ip, port: slave.port }), true);
    return;
  }
}

async function openModbusMapping() {
  await loadModbusMappingSource(true);
  setModbusMappingCardVisible(true);
  renderModbusDraft(collectModbusDraftFromForm(), { preserveMappingVisibility: true });
  showMessageOn("modbus", t("msg.modbus_mapping_opened"));
}

async function saveModbusDraft() {
  const draft = collectModbusDraftFromForm();
  try {
    validateModbusDraft(draft);
  } catch (error) {
    showMessageOn("modbus", error.message || t("msg.modbus_save_failed"), true);
    return;
  }

  if (lastModbusDraftSnapshot && JSON.stringify(draft) === JSON.stringify(lastModbusDraftSnapshot)) {
    window.alert(t("msg.no_changes"));
    return;
  }

  if (!window.confirm(t("msg.modbus_confirm"))) {
    showMessageOn("modbus", t("msg.save_canceled"));
    return;
  }

  let data;
  try {
    data = await requestJson("/api/modbus", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    });
  } catch (error) {
    showMessageOn("modbus", error.message || t("msg.modbus_save_failed"), true);
    return;
  }

  lastModbusDraftSnapshot = sanitizeModbusDraft(data.settings || draft);
  renderModbusDraft(lastModbusDraftSnapshot, { preserveMappingVisibility: true });
  showMessageOn("modbus", t("msg.modbus_saved"));
}

async function handleModbusSlaveTableClick(event) {
  const row = event.target.closest("tr[data-row-index]");
  if (!row) {
    return;
  }
  if (event.target.closest(".modbus-delete-btn")) {
    deleteModbusSlave(Number(row.dataset.rowIndex || "-1"));
    return;
  }
  if (event.target.closest(".modbus-connect-btn")) {
    await testModbusSlaveConnection(row);
  }
}

function handleModbusSlaveTableInput(event) {
  if (!event.target.closest("#modbus-slave-body")) {
    return;
  }
  renderModbusMappingRows(collectModbusDraftFromForm());
}

function handleModbusMappingTableClick(event) {
  const row = event.target.closest("tr[data-browse-path], tr[data-node-id]");
  if (!row || !event.target.closest(".modbus-clear-mapping-btn")) {
    return;
  }
  const slave = row.querySelector(".modbus-mapping-slave");
  const address = row.querySelector(".modbus-mapping-address");
  if (slave) {
    slave.value = "";
  }
  if (address) {
    address.value = "";
  }
  showMessageOn("modbus", t("msg.modbus_mapping_cleared"));
}

async function submitBasicForm(event) {
  if (event && typeof event.preventDefault === "function") {
    event.preventDefault();
  }

  let payload;
  try {
    payload = collectBasicPayloadFromForm();
  } catch (error) {
    showMessageOn("basic", error.message || t("msg.invalid_ipv4"), true);
    return;
  }

  if (lastBasicPayloadSnapshot && JSON.stringify(payload) === JSON.stringify(lastBasicPayloadSnapshot)) {
    window.alert(t("msg.no_changes"));
    return;
  }

  const confirmMessage =
    payload.mode === "static"
      ? t("msg.basic_confirm_static", {
          hostname: payload.hostname || t("common.not_set"),
          ip: payload.ipv4 || t("common.not_set"),
          gateway: payload.gateway4 || t("common.not_set"),
          dns: payload.dns || t("common.not_set"),
        }) 
      : t("msg.basic_confirm_dhcp");

  if (!window.confirm(confirmMessage)) {
    showMessageOn("basic", t("msg.basic_save_canceled"));
    return;
  }

  let data;
  try {
    data = await requestJson("/api/basic", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    showMessageOn("basic", error.message || t("msg.basic_update_failed"), true);
    return;
  }

  if (!data.ok) {
    showMessageOn("basic", data.error || t("msg.basic_update_failed"), true);
    return;
  }

  showMessageOn("basic", t("msg.basic_updated"));
  lastBasicPayloadSnapshot = payload;
  setReconnectLock(true, true);
}

async function submitAuthUsernameForm(event) {
  event.preventDefault();

  const username = document.getElementById("auth_username").value.trim();
  const newPassword = document.getElementById("auth_account_new_password").value;
  const newPasswordConfirm = document.getElementById("auth_account_new_password_confirm").value;

  if (newPassword || newPasswordConfirm) {
    if (newPassword !== newPasswordConfirm) {
      showMessageOn("auth-username", t("msg.password_mismatch"), true);
      return;
    }

    if (!PASSWORD_REGEX.test(newPassword)) {
      showMessageOn("auth-username", t("msg.password_length"), true);
      return;
    }
  }

  const payload = { username };
  if (newPassword) {
    payload.new_password = newPassword;
  }

  if (!window.confirm(t("msg.account_confirm"))) {
    showMessageOn("auth-username", t("msg.account_save_canceled"));
    return;
  }

  try {
    await requestJson("/api/auth/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    showMessageOn("auth-username", error.message || t("msg.account_update_failed"), true);
    return;
  }

  document.getElementById("auth_account_new_password").value = "";
  document.getElementById("auth_account_new_password_confirm").value = "";
  showMessageOn("auth-username", t("msg.account_updated"));
}

async function logout() {
  const shouldProceed = window.confirm(t("msg.logout_confirm"));
  if (!shouldProceed) {
    showMessage(t("msg.logout_canceled"));
    return;
  }

  try {
    await requestJson("/api/auth/logout", { method: "POST" });
  } catch (_error) {
    // ignore
  }
  window.location.replace("/logout");
}

function getDownloadFilenameFromHeader(contentDisposition, fallbackName) {
  if (!contentDisposition) {
    return fallbackName;
  }

  const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8Match && utf8Match[1]) {
    return decodeURIComponent(utf8Match[1]);
  }

  const asciiMatch = contentDisposition.match(/filename="?([^";]+)"?/i);
  if (asciiMatch && asciiMatch[1]) {
    return asciiMatch[1];
  }

  return fallbackName;
}

async function controlOpcuaService(action) {
  const actionLabel = t(`opcua.action.${action}`);
  const ok = window.confirm(t("msg.service_confirm", { action: actionLabel }));
  if (!ok) {
    showMessageOn("opcua", t("msg.service_canceled", { action: actionLabel }));
    return;
  }

  const beforeStateKey = getOpcuaServiceStateKey(opcuaOverview?.service);
  showMessageOn("opcua", t("msg.service_waiting", { action: actionLabel }));

  try {
    await requestJson("/api/opcua/service", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
  } catch (error) {
    showMessageOn("opcua", error.message || t("msg.service_failed", { action: actionLabel }), true);
    return;
  }

  const changed = await waitForOpcuaServiceStateChange(beforeStateKey);
  if (!changed) {
    await loadOpcua();
    showMessageOn("opcua", t("msg.service_no_change", { action: actionLabel }), true);
    return;
  }

  showMessageOn("opcua", t("msg.service_completed", { action: actionLabel }));
}

async function submitOpcuaConfigForm(event) {
  event.preventDefault();

  if (!opcuaOverview?.installed) {
    showMessageOn("opcua", t("msg.opcua_not_found"), true);
    return;
  }

  let payload;
  try {
    payload = collectOpcuaConfigPayload();
  } catch (error) {
    showMessageOn("opcua", error.message || t("msg.opcua_save_failed"), true);
    return;
  }

  if (!window.confirm(t("msg.opcua_confirm"))) {
    showMessageOn("opcua", t("msg.save_canceled"));
    return;
  }

  try {
    await requestJson("/api/opcua/config", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    showMessageOn("opcua", error.message || t("msg.opcua_save_failed"), true);
    return;
  }

  await loadOpcua();
  showMessageOn("opcua", t("msg.opcua_saved"));
}

async function addOpcuaUser() {
  const list = document.getElementById("opcua-user-list");
  const count = list.querySelectorAll("[data-role='opcua-user-row']").length;
  if (count >= OPCUA_MAX_USERS) {
    showMessageOn("opcua", t("msg.user_max", { max: OPCUA_MAX_USERS }), true);
    return;
  }

  list.appendChild(createOpcuaUserRow({ username: "", password: "" }));
  showMessageOn("opcua", t("msg.user_added"));
}

async function submitOpcuaFormatForm(event) {
  event.preventDefault();

  if (!opcuaOverview?.installed) {
    showMessageOn("opcua", t("msg.opcua_not_found"), true);
    return;
  }

  const fileInput = document.getElementById("opcua_format_file");
  if (!fileInput.files || fileInput.files.length === 0) {
    showMessageOn("opcua", t("msg.select_address_space"), true);
    return;
  }

  const selectedFile = fileInput.files[0];
  if (!selectedFile.name.toLowerCase().endsWith(REQUIRED_ADDRESS_SPACE_EXTENSION)) {
    showMessageOn("opcua", t("msg.select_csv"), true);
    return;
  }

  if (selectedFile.size > uploadMaxBytes) {
    showMessageOn("opcua", t("msg.max_file_size", { size: uploadMaxBytes }), true);
    return;
  }

  if (!window.confirm(t("msg.upload_format_confirm", { name: selectedFile.name }))) {
    showMessageOn("opcua", t("msg.upload_canceled"));
    return;
  }

  const formData = new FormData();
  formData.append("file", selectedFile);
  if (opcuaOverview?.format_file) {
    const overwrite = window.confirm(t("msg.overwrite_format_confirm"));
    if (!overwrite) {
      showMessageOn("opcua", t("msg.save_canceled"));
      return;
    }
    formData.append("overwrite", "true");
  }

  const res = await fetch("/api/opcua/format-file", { method: "POST", body: formData });
  let data = {};
  try {
    data = await res.json();
  } catch (_error) {
    data = {};
  }

  if (res.status === 401) {
    showMessageOn("opcua", t("msg.auth_failed_reload"), true);
    return;
  }
  if (!res.ok) {
    showMessageOn("opcua", data.error || t("msg.upload_failed_format"), true);
    return;
  }

  fileInput.value = "";
  await loadOpcua();
  showMessageOn("opcua", t("msg.address_space_uploaded"));
}

async function downloadOpcuaFormatFile() {
  if (!opcuaOverview?.format_file) {
    return;
  }

  if (!window.confirm(t("msg.download_format_confirm"))) {
    showMessageOn("opcua", t("msg.download_canceled"));
    return;
  }

  const res = await fetch("/api/opcua/format-file/download");
  if (res.status === 401) {
    showMessageOn("opcua", t("msg.auth_failed_reload"), true);
    return;
  }

  if (!res.ok) {
    let data = {};
    try {
      data = await res.json();
    } catch (_error) {
      data = {};
    }
    showMessageOn("opcua", data.error || t("msg.download_failed"), true);
    return;
  }

  const blob = await res.blob();
  const downloadName = getDownloadFilenameFromHeader(
    res.headers.get("Content-Disposition"),
    opcuaOverview.format_file.name,
  );
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = downloadName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);

  showMessageOn("opcua", t("msg.address_space_downloaded"));
}

async function submitOpcuaCertForm(event) {
  event.preventDefault();

  if (!opcuaOverview?.installed) {
    showMessageOn("opcua", t("msg.opcua_not_found"), true);
    return;
  }

  const fileInput = document.getElementById("opcua_cert_file");
  if (!fileInput.files || fileInput.files.length === 0) {
    showMessageOn("opcua", t("msg.select_client_cert"), true);
    return;
  }

  const selectedFile = fileInput.files[0];
  if (!selectedFile.name.toLowerCase().endsWith(REQUIRED_UPLOAD_EXTENSION)) {
    showMessageOn("opcua", t("msg.select_der"), true);
    return;
  }

  if (selectedFile.size > uploadMaxBytes) {
    showMessageOn("opcua", t("msg.max_file_size", { size: uploadMaxBytes }), true);
    return;
  }

  if (!window.confirm(t("msg.upload_client_cert_confirm", { name: selectedFile.name }))) {
    showMessageOn("opcua", t("msg.upload_canceled"));
    return;
  }

  const overwriteNeeded = Array.isArray(opcuaOverview?.client_certs)
    && opcuaOverview.client_certs.some((file) => file.name === selectedFile.name);

  const formData = new FormData();
  formData.append("file", selectedFile);
  if (overwriteNeeded) {
    const overwrite = window.confirm(t("msg.overwrite_cert_confirm", { name: selectedFile.name }));
    if (!overwrite) {
      showMessageOn("opcua", t("msg.save_canceled"));
      return;
    }
    formData.append("overwrite", "true");
  }

  const res = await fetch("/api/opcua/client-certs", { method: "POST", body: formData });
  let data = {};
  try {
    data = await res.json();
  } catch (_error) {
    data = {};
  }

  if (res.status === 401) {
    showMessageOn("opcua", t("msg.auth_failed_reload"), true);
    return;
  }
  if (!res.ok) {
    showMessageOn("opcua", data.error || t("msg.upload_failed_cert"), true);
    return;
  }

  fileInput.value = "";
  await loadOpcua();
  showMessageOn("opcua", overwriteNeeded ? t("msg.cert_overwritten") : t("msg.cert_uploaded"));
}

async function deleteOpcuaClientCert(filename) {
  if (!window.confirm(t("msg.delete_cert_confirm", { name: filename }))) {
    return;
  }

  try {
    await requestJson(`/api/opcua/client-certs/${encodeURIComponent(filename)}`, {
      method: "DELETE",
    });
  } catch (error) {
    showMessageOn("opcua", error.message || t("msg.delete_cert_failed"), true);
    return;
  }

  await loadOpcua();
  showMessageOn("opcua", t("msg.deleted_name", { name: filename }));
}

async function submitCustomForm(event) {
  if (event && typeof event.preventDefault === "function") {
    event.preventDefault();
  }

  const pageId = event.currentTarget.dataset.pageId;
  const textarea = document.getElementById(`custom-json-${pageId}`);
  if (!textarea) {
    return;
  }

  let payload;
  try {
    payload = JSON.parse(textarea.value.trim() || "{}");
  } catch (_error) {
    showMessageOn(pageId, t("msg.invalid_json", { pageId }), true);
    return;
  }

  if (payload === null || Array.isArray(payload) || typeof payload !== "object") {
    showMessageOn(pageId, t("msg.json_object_required", { pageId }), true);
    return;
  }

  if (!window.confirm(t("msg.custom_confirm", { pageId }))) {
    showMessageOn(pageId, t("msg.custom_canceled", { pageId }));
    return;
  }

  let data;
  try {
    data = await requestJson(`/api/app/custom/${pageId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch (error) {
    showMessageOn(pageId, error.message || t("msg.custom_failed", { pageId }), true);
    return;
  }

  textarea.value = JSON.stringify(data.settings || {}, null, 2);
  showMessageOn(pageId, t("msg.custom_saved", { pageId }));
}

function bindClickOnlyAction(formElement, actionButtonElement, handler) {
  if (!formElement || !actionButtonElement) {
    return;
  }

  formElement.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
    }
  });

  actionButtonElement.addEventListener("click", (event) => {
    handler({
      preventDefault: () => event.preventDefault(),
      currentTarget: formElement,
      originalEvent: event,
    });
  });
}

function bindEvents() {
  document.getElementById("mode").addEventListener("change", toggleStaticFields);
  document.getElementById("interface").addEventListener("change", handleInterfaceChange);

  bindClickOnlyAction(document.getElementById("basic-form"), document.getElementById("basic-save-btn"), submitBasicForm);
  bindClickOnlyAction(document.getElementById("auth-username-form"), document.getElementById("auth-username-save-btn"), submitAuthUsernameForm);
  bindClickOnlyAction(document.getElementById("opcua-config-form"), document.getElementById("opcua-config-save-btn"), submitOpcuaConfigForm);
  bindClickOnlyAction(document.getElementById("opcua-format-form"), document.getElementById("opcua-format-upload-btn"), submitOpcuaFormatForm);
  bindClickOnlyAction(document.getElementById("opcua-cert-form"), document.getElementById("opcua-cert-upload-btn"), submitOpcuaCertForm);

  document.getElementById("language-toggle-btn").addEventListener("click", toggleLanguage);
  document.getElementById("theme-toggle-btn").addEventListener("click", toggleTheme);
  document.getElementById("logout-btn").addEventListener("click", logout);
  document.getElementById("opcua-reload-btn").addEventListener("click", async () => {
    await loadOpcua();
    showMessageOn("opcua", t("msg.opcua_status_reloaded"));
  });
  document.getElementById("opcua-start-btn").addEventListener("click", () => controlOpcuaService("start"));
  document.getElementById("opcua-stop-btn").addEventListener("click", () => controlOpcuaService("stop"));
  document.getElementById("opcua-user-add-btn").addEventListener("click", addOpcuaUser);
  document.getElementById("opcua-format-download-btn").addEventListener("click", downloadOpcuaFormatFile);
  document.getElementById("opcua-cert-reload-btn").addEventListener("click", async () => {
    await loadOpcua();
    showMessageOn("opcua", t("msg.cert_list_reloaded"));
  });

  document.getElementById("opcua-grid-toggle-btn").addEventListener("click", toggleFormatGridEditor);
  document.getElementById("opcua-grid-add-btn").addEventListener("click", addFormatGridRow);
  document.getElementById("opcua-ns-add-btn").addEventListener("click", addNamespaceRow);
  document.getElementById("opcua-grid-assign-btn").addEventListener("click", assignGridNodeIds);
  document.getElementById("opcua-grid-save-btn").addEventListener("click", saveFormatGrid);
  document.getElementById("opcua-grid-reload-btn").addEventListener("click", async () => {
    await loadFormatGrid();
    showMessageOn("opcua", t("opcua.grid.reloaded"));
  });

  document.getElementById("modbus-add-slave-btn").addEventListener("click", addModbusSlave);
  document.getElementById("modbus-open-mapping-btn").addEventListener("click", openModbusMapping);
  document.getElementById("modbus-save-btn").addEventListener("click", saveModbusDraft);
  document.getElementById("modbus-slave-body").addEventListener("click", handleModbusSlaveTableClick);
  document.getElementById("modbus-slave-body").addEventListener("input", handleModbusSlaveTableInput);
  document.getElementById("modbus-mapping-body").addEventListener("click", handleModbusMappingTableClick);

  for (const form of document.querySelectorAll(".custom-form")) {
    bindClickOnlyAction(form, form.querySelector(".custom-save-btn"), submitCustomForm);
  }
}

async function loadProtectedData() {
  await loadBasic();
  await loadOpcua();
  await loadAppSettings();
  await loadAuthSettings();
  await loadCustomSettings();
  await loadModbusDraft();
}

async function init() {
  buildTabs();
  buildCustomPanels();
  applyTheme(getSavedTheme(), false);
  applyLanguage();
  bindReconnectLockEvents();
  bindEvents();
  startLocalTimeClock();
  setTab("auth-username");
  await loadProtectedData();
}

init().catch((error) => {
  showMessage(t("msg.initialization_failed", { message: error.message }), true);
});
