const DUMMY_PAGES = [
  { id: "dummy-network", labelKey: "tabs.dummy_network" },
  { id: "dummy-runtime", labelKey: "tabs.dummy_runtime" },
  { id: "dummy-advanced", labelKey: "tabs.dummy_advanced" },
];

const TAB_DEFINITIONS = [
  { id: "auth-username", labelKey: "tabs.account" },
  { id: "basic", labelKey: "tabs.network" },
  { id: "opcua", labelKey: "tabs.opcua" },
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

let uploadMaxBytes = DEFAULT_UPLOAD_MAX_BYTES;
let uploadMaxFiles = DEFAULT_UPLOAD_MAX_FILES;
let opcuaOverview = null;
let lastBasicPayloadSnapshot = null;
let lastOpcuaConfigSnapshot = null;
let opcuaRefreshInterval = null;
const RECONNECT_LOCK_STORAGE_KEY = "fieldGatewayReconnectPending";
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
    renderOpcuaOverview();
  }
}

function toggleLanguage() {
  if (!i18n) {
    return;
  }
  i18n.toggleLanguage();
  applyLanguage();
}

function showMessage(msg, isError = false) {
  const activeTab = document.querySelector(".tab.active")?.dataset?.tab || "";
  const local = activeTab ? document.getElementById(`message-${activeTab}`) : null;
  const el = local || document.getElementById("message");
  el.textContent = msg;
  el.style.color = isError ? "#b30000" : "#2f5d50";
}

function showMessageOn(tabId, msg, isError = false) {
  const local = document.getElementById(`message-${tabId}`);
  if (local) {
    local.textContent = msg;
    local.style.color = isError ? "#b30000" : "#2f5d50";
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
  const res = await fetch(url, options);
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
      await loadOpcua();
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

  setTab(targetTabId);
}

async function loadBasic() {
  const data = await requestJson("/api/basic");

  document.getElementById("hostname").value = data.hostname || "";
  document.getElementById("interface").value = data.network?.interface || "";
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

function renderOpcuaOverview() {
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
  renderOpcuaConfig();
}

async function loadOpcua() {
  opcuaOverview = await requestJson("/api/opcua");
  renderOpcuaOverview();
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

  bindClickOnlyAction(document.getElementById("basic-form"), document.getElementById("basic-save-btn"), submitBasicForm);
  bindClickOnlyAction(document.getElementById("auth-username-form"), document.getElementById("auth-username-save-btn"), submitAuthUsernameForm);
  bindClickOnlyAction(document.getElementById("opcua-config-form"), document.getElementById("opcua-config-save-btn"), submitOpcuaConfigForm);
  bindClickOnlyAction(document.getElementById("opcua-format-form"), document.getElementById("opcua-format-upload-btn"), submitOpcuaFormatForm);
  bindClickOnlyAction(document.getElementById("opcua-cert-form"), document.getElementById("opcua-cert-upload-btn"), submitOpcuaCertForm);

  document.getElementById("language-toggle-btn").addEventListener("click", toggleLanguage);
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
}

async function init() {
  buildTabs();
  buildCustomPanels();
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
