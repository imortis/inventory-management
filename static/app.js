/* Inventory Management System - frontend (vanilla JS SPA talking to the Flask REST API) */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const money = (n) => "$" + Number(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const slug = (s) => String(s).toLowerCase().replace(/\s+/g, "-");
const statePill = (s) => `<span class="pill st-${slug(s)}">${esc(s)}</span>`;
const catPill = (c) => `<span class="pill cat-${esc(c)}">${esc(c)}</span>`;

let me = null;
let currentView = "dashboard";
let productsCache = [];

/* ---------------- API ---------------- */
async function api(path, method = "GET", data) {
  const opts = { method, headers: {} };
  if (data !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(data);
  }
  const res = await fetch(path, opts);
  let json = {};
  try { json = await res.json(); } catch (_) {}
  if (res.status === 401 && path !== "/api/login") { showLogin(); throw new Error("Session expired - please sign in"); }
  if (!res.ok) throw new Error(json.error || `Request failed (${res.status})`);
  return json;
}

function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), kind === "warn" ? 6000 : 3500);
}

async function run(fn) {
  try { return await fn(); } catch (e) { toast(e.message, "error"); }
}

/* ---------------- auth ---------------- */
function showLogin() {
  me = null;
  $("#app-view").classList.add("hidden");
  $("#login-view").classList.remove("hidden");
}

function showApp() {
  $("#login-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  $("#user-name").textContent = me.user;
  $("#user-role").textContent = me.role;
  $$("[data-role]").forEach((el) => el.classList.toggle("hidden", me.role !== el.dataset.role));
  go(me.role !== "manager" && currentView === "sync" ? "dashboard" : currentView);
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  $("#login-error").textContent = "";
  try {
    me = await api("/api/login", "POST", { username: f.get("username"), password: f.get("password") });
    showApp();
  } catch (err) { $("#login-error").textContent = err.message; }
});

$("#logout-btn").addEventListener("click", async () => { await api("/api/logout", "POST"); showLogin(); });

/* ---------------- navigation ---------------- */
$$("#nav a").forEach((a) => a.addEventListener("click", () => go(a.dataset.view)));

function go(view) {
  currentView = view;
  $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
  $$(".view").forEach((v) => v.classList.add("hidden"));
  $(`#view-${view}`).classList.remove("hidden");
  const loaders = { dashboard: loadDashboard, products: loadProducts, stock: loadStock, sync: () => {},
                    valuation: loadValuation, alerts: loadAlerts, audit: loadAudit };
  run(loaders[view]);
  refreshBadge();
}

async function refreshBadge() {
  try {
    const a = await api("/api/alerts");
    const n = a.purchase_orders.filter((p) => p.status === "DRAFT").length;
    const b = $("#po-badge");
    b.textContent = n;
    b.classList.toggle("hidden", n === 0);
  } catch (_) {}
}

/* ---------------- dashboard ---------------- */
async function loadDashboard() {
  const d = await api("/api/dashboard");
  $("#k-products").textContent = d.total_products;
  $("#k-units").textContent = d.total_units.toLocaleString();
  $("#k-low").textContent = d.low_stock.length;
  $("#k-po").textContent = d.open_pos;
  $("#k-val-label").textContent = `Valuation · ${d.valuation.active}`;
  $("#k-val").textContent = money(d.valuation.active_key === "fifo" ? d.valuation.fifo : d.valuation.standard);

  const max = Math.max(1, ...d.products.map((p) => Math.max(p.quantity, p.reorder_level)));
  $("#stock-chart").innerHTML = d.products.length ? d.products.map((p) => `
    <div class="bar-row" title="${esc(p.name)}: ${p.quantity} on hand, reorder at ${p.reorder_level}">
      <span class="lbl"><b>${esc(p.sku)}</b> ${esc(p.name)}</span>
      <div class="bar-track">
        <div class="bar-fill ${p.quantity <= p.reorder_level ? "low" : ""}" style="width:${(p.quantity / max) * 100}%"></div>
        <div class="bar-mark" style="left:${(p.reorder_level / max) * 100}%"></div>
      </div>
      <span class="num">${p.quantity}</span>
    </div>`).join("") + `<div class="legend">Bar = units on hand (orange when at/below reorder) · red line = reorder level</div>`
    : `<div class="empty">No products yet.</div>`;

  $("#low-list").innerHTML = d.low_stock.length ? d.low_stock.map((p) => `
    <div class="list-item"><span><b>${esc(p.sku)}</b> ${esc(p.name)}</span>
      <span>${p.quantity} / ${p.reorder_level} ${statePill(p.state)}</span></div>`).join("")
    : `<div class="empty">All products are above their reorder level 🎉</div>`;

  $("#cat-list").innerHTML = Object.entries(d.by_category).map(([c, v]) => `
    <div class="list-item"><span>${catPill(c)} ${v.count} product(s)</span>
      <span>${v.units} units · ${money(v.value)}</span></div>`).join("") || `<div class="empty">—</div>`;

  $("#recent-tx").innerHTML = txTable(d.recent);
}

$("#reset-btn").addEventListener("click", () => run(async () => {
  if (!confirm("Reset all inventory data to the demo dataset?")) return;
  await api("/api/reset", "POST");
  toast("Demo data restored", "ok");
  go("dashboard");
}));

function txTable(rows) {
  if (!rows.length) return `<div class="empty">No transactions.</div>`;
  return `<table><thead><tr><th>#</th><th>Time</th><th>Type</th><th>SKU</th><th class="num">Qty</th>
    <th class="num">Unit cost</th><th>User</th></tr></thead><tbody>${rows.map((t) => `
    <tr><td>${t.id}</td><td>${esc(t.timestamp)}</td><td><span class="pill tx-${t.type}">${t.type}</span></td>
    <td><b>${esc(t.sku)}</b></td><td class="num">${t.qty}</td><td class="num">${money(t.unit_cost)}</td>
    <td>${esc(t.user)}</td></tr>`).join("")}</tbody></table>`;
}

/* ---------------- products ---------------- */
async function loadProducts() {
  productsCache = await api("/api/products");
  renderProducts();
}

function renderProducts() {
  const q = $("#prod-search").value.trim().toLowerCase();
  const cat = $("#prod-cat").value, st = $("#prod-state").value;
  const rows = productsCache.filter((p) =>
    (!q || p.sku.toLowerCase().includes(q) || p.name.toLowerCase().includes(q)) &&
    (!cat || p.category === cat) && (!st || p.state === st));
  const isMgr = me.role === "manager";
  $("#prod-table").innerHTML = `<thead><tr><th>SKU</th><th>Name</th><th>Category</th><th class="num">Qty</th>
    <th class="num">Reorder</th><th class="num">Unit price</th><th class="num">Value</th><th>State</th><th></th></tr></thead>
    <tbody>${rows.map((p) => `
      <tr class="clickable" data-sku="${esc(p.sku)}">
        <td><b>${esc(p.sku)}</b></td><td>${esc(p.name)}<div class="muted small">${esc(p.details)}</div></td><td>${catPill(p.category)}</td>
        <td class="num">${p.quantity}</td><td class="num">${p.reorder_level}</td>
        <td class="num">${money(p.unit_price)}</td><td class="num">${money(p.stock_value)}</td>
        <td>${statePill(p.state)}</td>
        <td><div class="actions">
          ${p.state !== "Discontinued" ? `<button class="btn small" data-act="receive">Receive</button>
          <button class="btn small" data-act="issue">Issue</button>` : ""}
          ${isMgr && p.state !== "Discontinued" ? `<button class="btn small danger" data-act="discontinue">Discontinue</button>` : ""}
        </div></td>
      </tr>`).join("") || `<tr><td colspan="9" class="empty">No matching products.</td></tr>`}</tbody>`;
}

["#prod-search", "#prod-cat", "#prod-state"].forEach((s) => $(s).addEventListener("input", renderProducts));

$("#prod-table").addEventListener("click", (e) => {
  const tr = e.target.closest("tr[data-sku]");
  if (!tr) return;
  const sku = tr.dataset.sku;
  const act = e.target.dataset.act;
  if (act === "receive" || act === "issue") quickMove(sku, act);
  else if (act === "discontinue") run(async () => {
    if (!confirm(`Discontinue ${sku}? It can no longer receive stock.`)) return;
    await api(`/api/products/${encodeURIComponent(sku)}/discontinue`, "POST");
    toast(`${sku} discontinued`, "ok");
    loadProducts();
  });
  else showProduct(sku);
});

function quickMove(sku, act) {
  const p = productsCache.find((x) => x.sku === sku);
  openModal(`<h2>${act === "receive" ? "📥 Receive" : "📤 Issue"} — ${esc(sku)}</h2>
    <p class="muted">${esc(p.name)} · on hand <b>${p.quantity}</b> · reorder level ${p.reorder_level}</p>
    <form id="quick-form" class="form">
      <label>Quantity<input name="qty" type="number" min="1" required autofocus></label>
      ${act === "receive" ? `<label>Unit cost (blank = ${money(p.unit_price)})<input name="unit_cost" type="number" step="0.01" min="0"></label>` : ""}
      <button class="btn primary full">${act === "receive" ? "Receive" : "Issue"}</button>
    </form>`);
  $("#quick-form").addEventListener("submit", (e) => {
    e.preventDefault();
    run(async () => {
      await doMove(sku, act, Object.fromEntries(new FormData(e.target)));
      closeModal();
      loadProducts();
    });
  });
}

async function doMove(sku, act, data) {
  const r = await api(`/api/products/${encodeURIComponent(sku)}/${act}`, "POST", data);
  toast(`${act === "receive" ? "Received" : "Issued"} ${data.qty} × ${sku} → ${r.product.quantity} on hand`, "ok");
  (r.alerts || []).forEach((a) => toast(a, "warn"));
  refreshBadge();
  return r;
}

async function showProduct(sku) {
  const { product: p, transactions } = await api(`/api/products/${encodeURIComponent(sku)}`);
  const extra = Object.entries(p.extra).map(([k, v]) => `<dt>${esc(k.replace(/_/g, " "))}</dt><dd>${esc(v)}</dd>`).join("");
  openModal(`<h2>${esc(p.sku)} · ${esc(p.name)}</h2>
    <dl class="detail-grid">
      <dt>Class</dt><dd><code>${esc(p.type)}</code> ${catPill(p.category)}</dd>
      <dt>State</dt><dd>${statePill(p.state)}</dd>
      <dt>On hand</dt><dd>${p.quantity} (reorder at ${p.reorder_level})</dd>
      <dt>Unit price</dt><dd>${money(p.unit_price)}</dd>
      ${extra}
      <dt>Handling policy</dt><dd>${esc(p.handling_policy)}</dd>
      <dt>Open batches</dt><dd>${p.batches.length ? p.batches.map((b) => `${b.qty} @ ${money(b.unit_cost)}`).join(" → ") : "none"}</dd>
    </dl>
    <h3>Transaction history</h3>${txTable(transactions.slice().reverse())}`);
}

/* add product */
$("#add-product-btn").addEventListener("click", () => {
  openModal($("#tpl-add-product").innerHTML);
  const form = $("#add-product-form");
  const syncCat = () => $$(".cat-field", form).forEach((el) => el.classList.toggle("hidden", el.dataset.cat !== form.category.value));
  form.category.addEventListener("change", syncCat);
  syncCat();
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    run(async () => {
      const p = await api("/api/products", "POST", Object.fromEntries(new FormData(form)));
      toast(`Registered ${p.type} ${p.sku}`, "ok");
      closeModal();
      loadProducts();
    });
  });
});

/* ---------------- stock movement ---------------- */
async function loadStock() {
  productsCache = await api("/api/products");
  const active = productsCache.filter((p) => p.state !== "Discontinued");
  $$(".sku-select").forEach((sel) => {
    const prev = sel.value;
    sel.innerHTML = active.map((p) => `<option value="${esc(p.sku)}">${esc(p.sku)} — ${esc(p.name)} (${p.quantity})</option>`).join("");
    if (active.some((p) => p.sku === prev)) sel.value = prev;
  });
  updateAvail();
}

function updateAvail() {
  const sku = $("#issue-form [name=sku]").value;
  const p = productsCache.find((x) => x.sku === sku);
  $("#issue-avail").textContent = p ? `Available: ${p.quantity} · reorder level ${p.reorder_level}` : "";
}
$("#issue-form [name=sku]").addEventListener("change", updateAvail);

["receive", "issue"].forEach((act) => {
  $(`#${act}-form`).addEventListener("submit", (e) => {
    e.preventDefault();
    run(async () => {
      const data = Object.fromEntries(new FormData(e.target));
      const r = await doMove(data.sku, act, data);
      const box = $("#stock-result");
      box.classList.remove("hidden");
      box.innerHTML = `<h3>Last movement</h3>
        <p><b>${act === "receive" ? "INBOUND" : "OUTBOUND"}</b> ${data.qty} × <b>${esc(data.sku)}</b> →
          ${r.product.quantity} on hand ${statePill(r.product.state)}</p>
        ${(r.alerts || []).map((a) => `<div class="email">${esc(a)}</div>`).join("")}`;
      e.target.qty.value = "";
      if (e.target.unit_cost) e.target.unit_cost.value = "";
      loadStock();
    });
  });
});

/* ---------------- supplier sync ---------------- */
$("#sync-sample").addEventListener("click", () => {
  $("#sync-csv").value = "sku,name,category,price,qty\nSKU-501,USB Cable,electronic,3.50,40\nSKU-102,Greek Yogurt,perishable,1.20,24\nSKU-301,Portland Cement,bulk,9.10,5";
});

$("#sync-btn").addEventListener("click", () => run(async () => {
  const r = await api("/api/sync", "POST", { csv: $("#sync-csv").value });
  const box = $("#sync-result");
  box.classList.remove("hidden");
  box.innerHTML = `<h3>Sync result · ${r.records} record(s)</h3>${r.log.map((l) => `<div class="list-item mono">${esc(l)}</div>`).join("")}`;
  toast(`Synced ${r.records} supplier record(s)`, "ok");
}));

/* ---------------- valuation ---------------- */
async function loadValuation() {
  const v = await api("/api/valuation");
  $("#v-std").textContent = money(v.standard);
  $("#v-fifo").textContent = money(v.fifo);
  $$(".kpi.selectable").forEach((k) => k.classList.toggle("active", k.dataset.strategy === v.active_key));
  $("#v-note").textContent = me.role === "manager"
    ? `Active strategy: ${v.active}. Click a card to switch the ValuationStrategy at runtime.`
    : `Active strategy: ${v.active}. Only managers can switch strategies.`;
  $("#val-table").innerHTML = `<thead><tr><th>SKU</th><th>Name</th><th class="num">Qty</th>
    <th class="num">Standard cost</th><th class="num">FIFO batch</th><th class="num">Difference</th></tr></thead>
    <tbody>${v.rows.map((r) => `<tr><td><b>${esc(r.sku)}</b></td><td>${esc(r.name)}</td><td class="num">${r.quantity}</td>
      <td class="num">${money(r.standard)}</td><td class="num">${money(r.fifo)}</td>
      <td class="num">${money(r.fifo - r.standard)}</td></tr>`).join("")}</tbody>
    <tfoot><tr><td colspan="3">Total</td><td class="num">${money(v.standard)}</td><td class="num">${money(v.fifo)}</td>
      <td class="num">${money(v.fifo - v.standard)}</td></tr></tfoot>`;
}

$$(".kpi.selectable").forEach((k) => k.addEventListener("click", () => run(async () => {
  if (me.role !== "manager") return toast("Only managers can switch valuation strategy", "error");
  const r = await api("/api/valuation", "POST", { strategy: k.dataset.strategy });
  toast(`Switched to ${r.active}: ${money(r.total)}`, "ok");
  loadValuation();
})));

/* ---------------- alerts ---------------- */
async function loadAlerts() {
  const a = await api("/api/alerts");
  const isMgr = me.role === "manager";
  $("#po-list").innerHTML = a.purchase_orders.length ? a.purchase_orders.map((po) => `
    <div class="list-item"><span><b>${po.po_id}</b> · ${esc(po.sku)} · ${po.qty} units
      <span class="pill po-${po.status}">${po.status}</span></span>
      ${isMgr && po.status === "DRAFT" ? `<span class="actions">
        <button class="btn small primary" data-po="${po.po_id}" data-act="receive">Receive</button>
        <button class="btn small ghost" data-po="${po.po_id}" data-act="cancel">Cancel</button></span>` : ""}
    </div>`).join("") : `<div class="empty">No purchase orders.</div>`;
  $("#email-list").innerHTML = a.emails.length ? a.emails.map((m) => `<div class="email">${esc(m)}</div>`).join("")
    : `<div class="empty">No alerts sent.</div>`;
}

$("#po-list").addEventListener("click", (e) => {
  const b = e.target.closest("[data-po]");
  if (!b) return;
  run(async () => {
    const r = await api(`/api/purchase-orders/${b.dataset.po}/${b.dataset.act}`, "POST", {});
    toast(`${r.po_id} ${r.status.toLowerCase()}`, "ok");
    loadAlerts();
    refreshBadge();
  });
});

/* ---------------- audit ---------------- */
async function loadAudit() {
  const [txs, products] = await Promise.all([api("/api/transactions"), api("/api/products")]);
  const sel = $("#audit-sku"), prev = sel.value;
  sel.innerHTML = `<option value="">All SKUs</option>` + products.map((p) => `<option>${esc(p.sku)}</option>`).join("");
  sel.value = prev;
  const type = $("#audit-type").value;
  const rows = txs.filter((t) => (!sel.value || t.sku === sel.value) && (!type || t.type === type));
  $("#audit-table").innerHTML = txTable(rows).replace(/^<table>|<\/table>$/g, "");
}
["#audit-sku", "#audit-type"].forEach((s) => $(s).addEventListener("change", () => run(loadAudit)));

/* ---------------- modal ---------------- */
function openModal(html) {
  $("#modal-body").innerHTML = html;
  $("#modal").classList.remove("hidden");
  const f = $("#modal-body input");
  if (f) f.focus();
}
function closeModal() { $("#modal").classList.add("hidden"); }
$("#modal-close").addEventListener("click", closeModal);
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

/* ---------------- boot ---------------- */
(async () => {
  try { me = await api("/api/me"); showApp(); } catch (_) { showLogin(); }
})();
