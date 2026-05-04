const apiBase = document.body.dataset.apiBase || "";
const api = (path) => `${apiBase}${path}`;

let previousOrderIds = new Set();
let orderCatalog = { products: [], deals: [] };
let draftItems = [];
let currentOrderId = null;
let orderViewMode = "tabular";
let orderDetailMode = "detailed";
let priorityEnabled = true;
let priorityOrderState = { received: [], "in progress": [] };

const orderModal = document.getElementById("orderModal");
const orderModalTitle = document.getElementById("orderModalTitle");
const orderModalCopy = document.getElementById("orderModalCopy");
const orderSearch = document.getElementById("orderSearch");
const orderSearchResults = document.getElementById("orderSearchResults");
const orderSummaryList = document.getElementById("orderSummaryList");
const orderSummaryTotal = document.getElementById("orderSummaryTotal");
const allowDiscounts = document.getElementById("allowDiscounts");
const saveOrderBtn = document.getElementById("saveOrderBtn");
const statusSections = Array.from(document.querySelectorAll("[data-status-section]"));

function getPriorityStorageKey() {
  return `orders-priority:${apiBase || window.location.pathname}`;
}

function loadPriorityState() {
  try {
    const saved = JSON.parse(localStorage.getItem(getPriorityStorageKey()) || "{}");
    priorityEnabled = saved.enabled !== false;
    priorityOrderState = {
      received: Array.isArray(saved.received) ? saved.received : [],
      "in progress": Array.isArray(saved["in progress"]) ? saved["in progress"] : []
    };
  } catch {
    priorityEnabled = true;
    priorityOrderState = { received: [], "in progress": [] };
  }
}

function savePriorityState() {
  localStorage.setItem(getPriorityStorageKey(), JSON.stringify({
    enabled: priorityEnabled,
    received: priorityOrderState.received,
    "in progress": priorityOrderState["in progress"]
  }));
}

const customerFields = {
  name: document.getElementById("orderCustomerName"),
  surname: document.getElementById("orderCustomerSurname"),
  phone: document.getElementById("orderCustomerPhone"),
  email: document.getElementById("orderCustomerEmail"),
  payment: document.getElementById("orderPaymentMethod"),
  note: document.getElementById("orderNote")
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function formatCurrency(value) {
  const amount = Number(value || 0);
  return `$${amount.toFixed(2)}`;
}

function parseOrderItems(rawItems) {
  if (Array.isArray(rawItems)) return rawItems;
  try {
    return JSON.parse(rawItems || "[]");
  } catch {
    return [];
  }
}

function computeDraftTotal() {
  return draftItems.reduce((sum, item) => {
    const qty = Number(item.quantity || 1);
    const basePrice = Number(item.base_price ?? item.price ?? 0);
    const discount = allowDiscounts.checked ? Number(item.discount || 0) : 0;
    const linePrice = Math.max(basePrice - discount, 0);
    return sum + (linePrice * qty);
  }, 0);
}

function readDraftPayload() {
  return {
    items: draftItems.map((item) => ({
      id: item.id,
      item_kind: item.item_kind,
      quantity: Number(item.quantity || 1),
      rank: item.rank || null,
      discount: allowDiscounts.checked ? Number(item.discount || 0) : 0
    })),
    payment: customerFields.payment.value,
    name: customerFields.name.value.trim(),
    surname: customerFields.surname.value.trim(),
    phone: customerFields.phone.value.trim(),
    email: customerFields.email.value.trim(),
    note: customerFields.note.value.trim()
  };
}

function resetModalState() {
  currentOrderId = null;
  draftItems = [];
  orderModalTitle.textContent = "Add Order";
  orderModalCopy.textContent = "Search products or deals, build the order summary, and save it straight into the orders list.";
  allowDiscounts.checked = false;
  orderSearch.value = "";
  customerFields.name.value = "";
  customerFields.surname.value = "";
  customerFields.phone.value = "";
  customerFields.email.value = "";
  customerFields.payment.value = "cash";
  customerFields.note.value = "";
  document.getElementById("orderStatusPreview").value = "Received";
  renderSearchResults();
  renderSummary();
}

function openOrderModal() {
  resetModalState();
  orderModal.classList.add("open");
  orderModal.setAttribute("aria-hidden", "false");
  orderSearch.focus();
}

function closeOrderModal() {
  orderModal.classList.remove("open");
  orderModal.setAttribute("aria-hidden", "true");
}

function getCatalogMatches() {
  const query = orderSearch.value.trim().toLowerCase();
  const products = orderCatalog.products.map((product) => ({
    ...product,
    item_kind: "product"
  }));
  const deals = orderCatalog.deals.map((deal) => ({
    ...deal,
    item_kind: "deal"
  }));

  const catalog = [...products, ...deals];
  if (!query) return catalog.slice(0, 18);

  return catalog.map((item) => {
    const title = String(item.title || "").toLowerCase();
    const description = String(item.description || "").toLowerCase();
    const category = String(item.category || item.type || "").toLowerCase();

    let score = -1;

    if (title.startsWith(query)) score = 400;
    else if (title.includes(query)) score = 300;
    else if (description.startsWith(query)) score = 220;
    else if (description.includes(query)) score = 180;
    else if (category.startsWith(query)) score = 120;
    else if (category.includes(query)) score = 90;

    return { item, score };
  }).filter((entry) => entry.score >= 0)
    .sort((a, b) => b.score - a.score || String(a.item.title || "").localeCompare(String(b.item.title || "")))
    .map((entry) => entry.item)
    .slice(0, 18);
}

function addCatalogItem(item) {
  const existingIndex = draftItems.findIndex((entry) =>
    entry.id === item.id &&
    entry.item_kind === item.item_kind &&
    (entry.rank || "") === ""
  );

  const basePayload = {
    id: item.id,
    item_kind: item.item_kind,
    title: item.title,
    quantity: 1,
    rank: null,
    price: Number(item.price || 0),
    base_price: Number(item.price || 0),
    discount: 0
  };

  if (item.item_kind === "product" && item.has_ranking && Array.isArray(item.ranks) && item.ranks.length) {
    basePayload.rank = item.ranks[0].name;
    basePayload.price = Number(item.ranks[0].price || 0);
    basePayload.base_price = Number(item.ranks[0].price || 0);
    draftItems.push(basePayload);
  } else if (existingIndex >= 0) {
    draftItems[existingIndex].quantity = Number(draftItems[existingIndex].quantity || 1) + 1;
  } else {
    draftItems.push(basePayload);
  }

  renderSummary();
}

function updateDraftItem(index, field, value) {
  const item = draftItems[index];
  if (!item) return;

  if (field === "quantity") {
    item.quantity = Math.max(1, Number(value || 1));
  }

  if (field === "discount") {
    const nextDiscount = Math.max(0, Number(value || 0));
    item.discount = Math.min(nextDiscount, Number(item.base_price || 0));
  }

  if (field === "rank") {
    const product = orderCatalog.products.find((entry) => entry.id === item.id);
    const matchedRank = product?.ranks?.find((rank) => rank.name === value);
    if (matchedRank) {
      item.rank = matchedRank.name;
      item.base_price = Number(matchedRank.price || 0);
      item.price = Number(matchedRank.price || 0);
      item.discount = Math.min(Number(item.discount || 0), item.base_price);
    }
  }

  renderSummary();
}

function removeDraftItem(index) {
  draftItems.splice(index, 1);
  renderSummary();
}

function renderSearchResults() {
  const matches = getCatalogMatches();

  if (!matches.length) {
    orderSearchResults.innerHTML = '<div class="summary-empty">No products or deals matched that search.</div>';
    return;
  }

  orderSearchResults.innerHTML = matches.map((item) => {
    const isProduct = item.item_kind === "product";
    const bundleHtml = !isProduct && Array.isArray(item.bundle_items) && item.bundle_items.length
      ? `<div class="bundle-pills">${item.bundle_items.map((bundle) => `<span class="bundle-pill">${escapeHtml(`${bundle.quantity} x ${bundle.product_title || `Product ${bundle.product_id}`}`)}</span>`).join("")}</div>`
      : "";
    const meta = isProduct
      ? `<span class="item-meta">${escapeHtml(item.category || "Product")}</span>`
      : `<span class="item-meta">${escapeHtml((item.type || "Deal").toUpperCase())}</span>`;

    return `
      <article class="catalog-card">
        <div class="catalog-card-head">
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(item.description || (isProduct ? "Product available for ordering." : "Deal available for ordering."))}</p>
          </div>
          ${meta}
        </div>
        ${bundleHtml}
        <div class="catalog-card-footer">
          <span>${formatCurrency(item.price)}</span>
          <button class="btn btn-primary" type="button" data-add-kind="${escapeHtml(item.item_kind)}" data-add-id="${item.id}">Add to Order</button>
        </div>
      </article>
    `;
  }).join("");
}

function renderSummary() {
  if (!draftItems.length) {
    orderSummaryList.innerHTML = '<div class="summary-empty">No items added yet. Search above to build this order.</div>';
    orderSummaryTotal.textContent = formatCurrency(0);
    return;
  }

  orderSummaryList.innerHTML = draftItems.map((item, index) => {
    const product = item.item_kind === "product"
      ? orderCatalog.products.find((entry) => entry.id === item.id)
      : null;

    const rankOptions = product?.ranks?.map((rank) => `
      <option value="${escapeHtml(rank.name)}" ${rank.name === item.rank ? "selected" : ""}>
        ${escapeHtml(`${rank.name} (${formatCurrency(rank.price)})`)}
      </option>
    `).join("") || "";

    const linePrice = Math.max(Number(item.base_price || 0) - (allowDiscounts.checked ? Number(item.discount || 0) : 0), 0);
    const lineMeta = [
      item.item_kind === "deal" ? "Deal" : "Product",
      item.rank || null,
      allowDiscounts.checked && Number(item.discount || 0) > 0 ? `Discount ${formatCurrency(item.discount)}` : null
    ].filter(Boolean).join(" | ");

    return `
      <article class="summary-card">
        <div class="summary-card-head">
          <div>
            <strong>${escapeHtml(item.title)}</strong>
            <p>${escapeHtml(lineMeta || "Ready to save")}</p>
          </div>
          <strong>${formatCurrency(linePrice * Number(item.quantity || 1))}</strong>
        </div>
        <div class="summary-row-grid">
          <div class="summary-field">
            <label>Quantity
              <input type="number" min="1" value="${Number(item.quantity || 1)}" data-field="quantity" data-index="${index}">
            </label>
          </div>
          <div class="summary-field">
            ${rankOptions ? `
              <label>Variant
                <select data-field="rank" data-index="${index}">${rankOptions}</select>
              </label>
            ` : `
              <label>Base Price
                <input type="text" value="${formatCurrency(item.base_price)}" disabled>
              </label>
            `}
          </div>
          <div class="summary-field">
            <label>Discount
              <input type="number" min="0" step="0.01" value="${allowDiscounts.checked ? Number(item.discount || 0) : 0}" data-field="discount" data-index="${index}" ${allowDiscounts.checked ? "" : "disabled"}>
            </label>
          </div>
        </div>
        <div class="catalog-card-footer">
          <span>Unit Price ${formatCurrency(linePrice)}</span>
          <button class="summary-remove" type="button" data-remove-index="${index}">Remove</button>
        </div>
      </article>
    `;
  }).join("");

  orderSummaryTotal.textContent = formatCurrency(computeDraftTotal());
}

function renderEmptyTable(tableBody, label) {
  tableBody.innerHTML = `<tr class="empty-table"><td colspan="8">No ${label.toLowerCase()} right now.</td></tr>`;
}

function setViewMode(mode) {
  orderViewMode = mode;
  document.querySelectorAll("[data-view-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.viewMode === mode);
  });
  statusSections.forEach((section) => {
    section.classList.toggle("view-mode-container", mode === "container");
  });
}

function setDetailMode(mode) {
  orderDetailMode = mode;
  document.querySelectorAll("[data-detail-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.detailMode === mode);
  });
}

function setPriorityMode(mode) {
  priorityEnabled = mode === "on";
  document.querySelectorAll("[data-priority-mode]").forEach((button) => {
    button.classList.toggle("active", button.dataset.priorityMode === mode);
  });
  savePriorityState();
}

function syncPriorityLists(orders) {
  ["received", "in progress"].forEach((status) => {
    const idsForStatus = orders
      .filter((order) => order.status === status)
      .map((order) => Number(order.id));
    const preserved = priorityOrderState[status].filter((id) => idsForStatus.includes(Number(id)));
    const missing = idsForStatus.filter((id) => !preserved.includes(id));
    priorityOrderState[status] = [...preserved, ...missing];
  });
  savePriorityState();
}

function sortOrdersByPriority(orders) {
  if (!priorityEnabled) return orders;

  syncPriorityLists(orders);

  return [...orders].sort((a, b) => {
    const aStatus = a.status || "";
    const bStatus = b.status || "";

    if (aStatus === bStatus && (aStatus === "received" || aStatus === "in progress")) {
      const list = priorityOrderState[aStatus] || [];
      const aIndex = list.indexOf(Number(a.id));
      const bIndex = list.indexOf(Number(b.id));
      return aIndex - bIndex;
    }

    return 0;
  });
}

function moveOrderPriority(orderId, status, direction) {
  if (!(status === "received" || status === "in progress")) return;

  const list = [...(priorityOrderState[status] || [])];
  const index = list.indexOf(Number(orderId));
  if (index === -1) return;

  const nextIndex = direction === "up" ? index - 1 : index + 1;
  if (nextIndex < 0 || nextIndex >= list.length) return;

  [list[index], list[nextIndex]] = [list[nextIndex], list[index]];
  priorityOrderState[status] = list;
  savePriorityState();
  loadOrders();
}

function renderOrderItems(items) {
  if (!items.length) {
    return '<div class="order-item-card"><div class="order-item-title">No items</div></div>';
  }

  return items.map((item) => {
    const unitPrice = Number(item.price || 0);
    const basePrice = Number(item.base_price ?? item.price ?? 0);
    const discount = Number(item.discount || 0);
    const subtitleParts = [
      item.item_kind === "deal" ? "Deal" : "Product",
      item.rank || null,
      discount > 0 ? `-${formatCurrency(discount)}` : null
    ].filter(Boolean);

    const selections = Array.isArray(item.bundle_selections) ? item.bundle_selections : [];
    const selectionsHtml = selections.length
      ? `<div class="order-deal-selections">${selections.map((sel, i) =>
          `<div class="order-deal-selection-row"><span class="ods-num">${i + 1}.</span> ${escapeHtml(sel.slot_label || sel.product_title || "")}</div>`
        ).join("")}</div>`
      : "";

    return `
      <div class="order-item-card">
        <div class="order-item-head">
          <div>
            <div class="order-item-title">${escapeHtml(item.title || "Item")}</div>
            <div class="order-item-sub">${escapeHtml(subtitleParts.join(" | "))}</div>
          </div>
          <strong>${formatCurrency(unitPrice * Number(item.quantity || 1))}</strong>
        </div>
        <div class="order-item-sub">Qty ${Number(item.quantity || 1)} | Unit ${formatCurrency(unitPrice)}${discount > 0 ? ` from ${formatCurrency(basePrice)}` : ""}</div>
        ${selectionsHtml}
      </div>
    `;
  }).join("");
}

function deliveryStatusPill(status) {
  if (!status) return "";
  const labels = { preparing: "Preparing", on_the_way: "On the Way", delivered: "Delivered" };
  const cls = { preparing: "ds-preparing", on_the_way: "ds-on_the_way", delivered: "ds-delivered" };
  return `<span class="delivery-status-pill ${cls[status] || "ds-preparing"}">${labels[status] || status}</span>`;
}

function buildOrderRow(order) {
  const tr = document.createElement("tr");
  const isNew = !previousOrderIds.has(order.id);
  if (isNew) tr.classList.add("new-order");

  const items = parseOrderItems(order.items);
  const created = order.created_at ? new Date(order.created_at).toLocaleString() : "-";
  const started = order.in_progress_time ? new Date(order.in_progress_time).toLocaleString() : "-";
  const completed = order.completed_time ? new Date(order.completed_time).toLocaleString() : "-";

  const timingHtml = order.status === "received"
    ? `<div class="time-stack"><div><strong>Created</strong></div><small>${created}</small></div>`
    : order.status === "in progress"
      ? `<div class="time-stack"><div><strong>Created</strong></div><small>${created}</small><div><strong>Started</strong></div><small>${started}</small></div>`
      : `<div class="time-stack"><div><strong>Created</strong></div><small>${created}</small><div><strong>Started</strong></div><small>${started}</small><div><strong>Completed</strong></div><small>${completed}</small></div>`;

  const deliveryHtml = order.is_delivery
    ? `<div class="delivery-badge-pill">🚗 Delivery</div>
       <div class="delivery-addr-cell">📍 ${escapeHtml(order.delivery_address || "No address")}</div>
       <div style="margin-top:0.2rem;">${deliveryStatusPill(order.delivery_status)}</div>`
    : "";

  const noteOrReason = order.status === "rejected"
    ? (order.rejection_reason ? `Rejected: ${order.rejection_reason}` : "Rejected — no reason given")
    : (order.note || "No notes added.");

  tr.innerHTML = `
    <td>
      <div class="customer-stack">
        <div class="customer-name">#${order.order_number || order.id}</div>
        <span class="detail-chip">Order ID ${order.id}</span>
        ${deliveryHtml}
      </div>
    </td>
    <td>
      <div class="customer-stack">
        <div class="customer-name">${escapeHtml(`${order.name || ""} ${order.surname || ""}`.trim() || "Walk-in Customer")}</div>
        <div><strong>${escapeHtml(order.phone || "No phone")}</strong></div>
        <div>${escapeHtml(order.email || "No email")}</div>
      </div>
    </td>
    <td class="order-items">${renderOrderItems(items)}</td>
    <td class="order-note" style="${order.status === "rejected" ? "color:#b91c1c;" : ""}">${escapeHtml(noteOrReason)}</td>
    <td><strong>${formatCurrency(order.total)}</strong></td>
    <td>${paymentMethodCell(order)}</td>
    <td>${timingHtml}</td>
    <td><div class="action-cluster">${getOrderActionButtons(order)}</div></td>
  `;

  previousOrderIds.add(order.id);
  return tr;
}

function isInstorePending(order) {
  return (order.payment_method || "").toLowerCase() === "instore" && order.payment_status !== "paid";
}

function paymentMethodCell(order) {
  if (isInstorePending(order)) {
    return `<span style="display:inline-block;background:#fef3c7;color:#92400e;border:1px solid #fcd34d;border-radius:6px;padding:0.15rem 0.5rem;font-size:0.78rem;font-weight:600;">Pay-in-Store</span>`;
  }
  if ((order.payment_method || "").toLowerCase() === "instore" && order.payment_status === "paid") {
    return `<span style="display:inline-block;background:#d1fae5;color:#065f46;border:1px solid #6ee7b7;border-radius:6px;padding:0.15rem 0.5rem;font-size:0.78rem;font-weight:600;">Pay-in-Store ✓</span>`;
  }
  return escapeHtml(order.payment_method || "-");
}

async function confirmInstorePayment(orderId) {
  const btn = document.querySelector(`[data-confirm-payment="${orderId}"]`);
  if (btn) { btn.disabled = true; btn.textContent = "Confirming…"; }
  await fetch(api(`/confirm_instore_payment/${orderId}`), { method: "POST" });
  loadOrders();
}

function getOrderActionButtons(order) {
  if (order.status === "rejected") return "";

  const buttons = [
    `<button class="table-action-btn edit" type="button" data-edit-order="${order.id}">Edit Items</button>`
  ];

  if (order.status === "received") {
    buttons.push(`<button class="table-action-btn start" type="button" data-status-order="${order.id}" data-next-status="in progress">Start</button>`);
  }

  if (order.status === "in progress") {
    buttons.push(`<button class="table-action-btn complete" type="button" data-status-order="${order.id}" data-next-status="completed">Complete</button>`);
  }

  if (isInstorePending(order)) {
    buttons.push(`<button class="table-action-btn" style="background:#16a34a;color:#fff;" type="button" data-confirm-payment="${order.id}" onclick="confirmInstorePayment(${order.id})">Payment Confirmed</button>`);
  }

  if (order.status !== "completed") {
    buttons.push(`<button class="table-action-btn reject" type="button" data-reject-order="${order.id}">Reject</button>`);
  }

  if (priorityEnabled && (order.status === "received" || order.status === "in progress")) {
    buttons.push(`
      <div class="priority-actions">
        <button class="table-action-btn priority" type="button" data-priority-order="${order.id}" data-priority-status="${escapeHtml(order.status)}" data-priority-direction="up">&uarr;</button>
        <button class="table-action-btn priority" type="button" data-priority-order="${order.id}" data-priority-status="${escapeHtml(order.status)}" data-priority-direction="down">&darr;</button>
      </div>
    `);
  }

  return buttons.join("");
}

function buildOrderCard(order) {
  const items = parseOrderItems(order.items);
  const displayName = `${order.name || ""} ${order.surname || ""}`.trim() || "Walk-in Customer";
  const orderNumber = order.order_number || order.id;
  const statusLabel = order.status || "received";
  const created = order.created_at ? new Date(order.created_at).toLocaleString() : "-";
  const started = order.in_progress_time ? new Date(order.in_progress_time).toLocaleString() : "-";
  const completed = order.completed_time ? new Date(order.completed_time).toLocaleString() : "-";

  if (orderDetailMode === "short") {
    const itemBriefs = items.map((i) => {
      const qty = Number(i.quantity || 1);
      return `<span class="item-brief-pill">${escapeHtml(i.title || "Item")}${qty > 1 ? ` ×${qty}` : ""}</span>`;
    }).join("");

    return `
      <article class="order-card order-card-short" data-order-detail="${order.id}" style="cursor:pointer;">
        <div class="order-card-head">
          <div class="order-card-kicker">${escapeHtml(statusLabel)}</div>
          <div class="order-card-title-row">
            <div>
              <div class="order-card-title">${escapeHtml(displayName)}</div>
              <div class="order-card-subtitle">Order #${escapeHtml(String(orderNumber))}</div>
            </div>
          </div>
        </div>
        <div class="order-card-items-brief">${itemBriefs || '<span class="item-brief-pill">No items</span>'}</div>
        ${order.note ? `<div class="order-card-note-brief">📝 ${escapeHtml(order.note)}</div>` : ""}
        <div class="order-card-actions" onclick="event.stopPropagation()">${getOrderActionButtons(order)}</div>
      </article>
    `;
  }

  const details = [
    ["Customer", `${displayName}${order.phone ? ` | ${order.phone}` : ""}${order.email ? ` | ${order.email}` : ""}`],
    ["Note", order.note || "No notes added."],
    ["Payment", isInstorePending(order) ? "Pay-in-Store (awaiting payment)" : ((order.payment_method === "instore" && order.payment_status === "paid") ? "Pay-in-Store (confirmed)" : (order.payment_method || "-"))],
    ["Timeline", `Created: ${created}${order.status !== "received" ? ` | Started: ${started}` : ""}${order.status === "completed" ? ` | Completed: ${completed}` : ""}`]
  ];

  const deliveryCardHtml = order.is_delivery
    ? `<li class="order-card-detail" style="background:#f0fdf4;border-radius:10px;padding:0.6rem 0.8rem;border:1px solid #86efac;">
        <strong style="color:#15803d;">🚗 Delivery</strong>
        <span style="color:#15803d;font-weight:600;">${escapeHtml(order.delivery_address || "No address")} &nbsp; ${deliveryStatusPill(order.delivery_status)}</span>
       </li>`
    : "";

  return `
    <article class="order-card">
      <div class="order-card-head">
        <div class="order-card-kicker">${escapeHtml(statusLabel)}</div>
        <div class="order-card-title-row">
          <div>
            <div class="order-card-title">${escapeHtml(displayName)}</div>
            <div class="order-card-subtitle">Order #${escapeHtml(String(orderNumber))}${order.is_delivery ? ' &nbsp;<span class="delivery-badge-pill">🚗 Delivery</span>' : ""}</div>
          </div>
          <span class="detail-chip">${formatCurrency(order.total)}</span>
        </div>
      </div>
      <ul class="order-card-detail-list">
        ${deliveryCardHtml}
        <li class="order-card-detail items-detail">
          <strong>Items</strong>
          <div class="order-items">${renderOrderItems(items)}</div>
        </li>
        ${details.map(([label, value]) => `
          <li class="order-card-detail">
            <strong>${escapeHtml(label)}</strong>
            <span>${escapeHtml(value)}</span>
          </li>
        `).join("")}
      </ul>
      <div class="order-card-actions">${getOrderActionButtons(order)}</div>
    </article>
  `;
}

async function loadCatalog() {
  const res = await fetch(api("/order_catalog"));
  if (!res.ok) return;
  orderCatalog = await res.json();
  renderSearchResults();
}

async function updateStatus(orderId, status) {
  await fetch(api(`/update_order_status/${orderId}`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status })
  });
  loadOrders();
}

function hydrateModalFromOrder(order) {
  currentOrderId = order.id;
  orderModalTitle.textContent = `Edit Order #${order.order_number || order.id}`;
  orderModalCopy.textContent = "Adjust items, discounts, notes, and customer details. Saving will recalculate the order total.";
  customerFields.name.value = order.name || "";
  customerFields.surname.value = order.surname || "";
  customerFields.phone.value = order.phone || "";
  customerFields.email.value = order.email || "";
  customerFields.payment.value = order.payment_method || "cash";
  customerFields.note.value = order.note || "";
  document.getElementById("orderStatusPreview").value = order.status || "received";

  draftItems = parseOrderItems(order.items).map((item) => ({
    ...item,
    quantity: Number(item.quantity || 1),
    price: Number(item.price || 0),
    base_price: Number(item.base_price ?? item.price ?? 0),
    discount: Number(item.discount || 0)
  }));
  allowDiscounts.checked = draftItems.some((item) => Number(item.discount || 0) > 0);
  renderSearchResults();
  renderSummary();
  orderModal.classList.add("open");
  orderModal.setAttribute("aria-hidden", "false");
}

async function openEditOrder(orderId) {
  const res = await fetch(api("/get_orders"));
  if (!res.ok) return;
  const orders = await res.json();
  const order = orders.find((entry) => Number(entry.id) === Number(orderId));
  if (!order) return;
  hydrateModalFromOrder(order);
}

async function saveOrder() {
  if (!draftItems.length) {
    alert("Add at least one product or deal before saving.");
    return;
  }

  const payload = readDraftPayload();
  const endpoint = currentOrderId ? api(`/orders/${currentOrderId}`) : api("/add_order");
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  if (!res.ok) {
    alert("The order could not be saved.");
    return;
  }

  closeOrderModal();
  await loadOrders();
}

document.addEventListener("click", async (event) => {
  const addButton = event.target.closest("[data-add-id]");
  if (addButton) {
    const type = addButton.dataset.addKind;
    const collection = type === "deal" ? orderCatalog.deals : orderCatalog.products;
    const item = collection.find((entry) => String(entry.id) === addButton.dataset.addId);
    if (item) addCatalogItem({ ...item, item_kind: type });
    return;
  }

  const removeButton = event.target.closest("[data-remove-index]");
  if (removeButton) {
    removeDraftItem(Number(removeButton.dataset.removeIndex));
    return;
  }

  const editButton = event.target.closest("[data-edit-order]");
  if (editButton) {
    await openEditOrder(editButton.dataset.editOrder);
    return;
  }

  const statusButton = event.target.closest("[data-status-order]");
  if (statusButton) {
    await updateStatus(statusButton.dataset.statusOrder, statusButton.dataset.nextStatus);
    return;
  }

  const priorityButton = event.target.closest("[data-priority-order]");
  if (priorityButton) {
    moveOrderPriority(
      priorityButton.dataset.priorityOrder,
      priorityButton.dataset.priorityStatus,
      priorityButton.dataset.priorityDirection
    );
  }
});

document.addEventListener("input", (event) => {
  if (event.target === orderSearch) {
    renderSearchResults();
  }
});

document.addEventListener("change", (event) => {
  const field = event.target.dataset.field;
  if (!field) return;
  updateDraftItem(Number(event.target.dataset.index), field, event.target.value);
});

document.getElementById("openOrderModal")?.addEventListener("click", openOrderModal);
document.getElementById("closeOrderModal")?.addEventListener("click", closeOrderModal);
document.getElementById("cancelOrderModal")?.addEventListener("click", closeOrderModal);
allowDiscounts?.addEventListener("change", renderSummary);
saveOrderBtn?.addEventListener("click", saveOrder);
document.querySelectorAll("[data-view-mode]").forEach((button) => {
  button.addEventListener("click", () => setViewMode(button.dataset.viewMode));
});
document.querySelectorAll("[data-detail-mode]").forEach((button) => {
  button.addEventListener("click", async () => {
    setDetailMode(button.dataset.detailMode);
    await loadOrders();
  });
});
document.querySelectorAll("[data-priority-mode]").forEach((button) => {
  button.addEventListener("click", async () => {
    setPriorityMode(button.dataset.priorityMode);
    await loadOrders();
  });
});

orderModal?.addEventListener("click", (event) => {
  if (event.target === orderModal) closeOrderModal();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && orderModal?.classList.contains("open")) closeOrderModal();
});

let cachedOrders = [];

const orderDetailModal = document.getElementById("orderDetailModal");
const orderDetailClose = document.getElementById("closeOrderDetailModal");

function openOrderDetail(orderId) {
  const order = cachedOrders.find((o) => Number(o.id) === Number(orderId));
  if (!order || !orderDetailModal) return;

  const items = parseOrderItems(order.items);
  const displayName = `${order.name || ""} ${order.surname || ""}`.trim() || "Walk-in Customer";
  const orderNumber = order.order_number || order.id;
  const created = order.created_at ? new Date(order.created_at).toLocaleString() : "-";
  const started = order.in_progress_time ? new Date(order.in_progress_time).toLocaleString() : "-";
  const completed = order.completed_time ? new Date(order.completed_time).toLocaleString() : "-";

  document.getElementById("orderDetailTitle").textContent = `Order #${orderNumber}${order.is_delivery ? " 🚗" : ""}`;
  const deliveryDetailHtml = order.is_delivery ? `
    <section class="detail-section" style="margin-top:1rem;background:#f0fdf4;border:1px solid #86efac;border-radius:14px;padding:1rem;">
      <h3 class="panel-title" style="color:#15803d;">🚗 Delivery Details</h3>
      <dl class="detail-dl">
        <dt>Address</dt><dd style="font-weight:700;color:#15803d;">${escapeHtml(order.delivery_address || "—")}</dd>
        <dt>Status</dt><dd>${deliveryStatusPill(order.delivery_status)}</dd>
        <dt>Phone</dt><dd><strong>${escapeHtml(order.phone || "—")}</strong></dd>
      </dl>
    </section>` : "";

  document.getElementById("orderDetailBody").innerHTML = `
    ${deliveryDetailHtml}
    <div class="detail-modal-grid">
      <section class="detail-section">
        <h3 class="panel-title">Customer</h3>
        <dl class="detail-dl">
          <dt>Name</dt><dd>${escapeHtml(displayName)}</dd>
          <dt>Phone</dt><dd><strong>${escapeHtml(order.phone || "—")}</strong></dd>
          <dt>Email</dt><dd>${escapeHtml(order.email || "—")}</dd>
          <dt>Payment</dt><dd>${paymentMethodCell(order)}${isInstorePending(order) ? `<br><button class="table-action-btn" style="background:#16a34a;color:#fff;margin-top:0.4rem;" type="button" data-confirm-payment="${order.id}" onclick="confirmInstorePayment(${order.id})">Payment Confirmed</button>` : ""}</dd>
          <dt>Note</dt><dd>${escapeHtml(order.note || "No notes.")}</dd>
        </dl>
      </section>
      <section class="detail-section">
        <h3 class="panel-title">Timing</h3>
        <dl class="detail-dl">
          <dt>Status</dt><dd>${escapeHtml(order.status || "received")}</dd>
          <dt>Created</dt><dd>${escapeHtml(created)}</dd>
          ${order.status !== "received" ? `<dt>Started</dt><dd>${escapeHtml(started)}</dd>` : ""}
          ${order.status === "completed" ? `<dt>Completed</dt><dd>${escapeHtml(completed)}</dd>` : ""}
          <dt>Total</dt><dd><strong>${formatCurrency(order.total)}</strong></dd>
        </dl>
      </section>
    </div>
    <section class="detail-section" style="margin-top:1rem;">
      <h3 class="panel-title">Items</h3>
      <div class="order-items">${renderOrderItems(items)}</div>
    </section>
    <div class="detail-modal-actions">${getOrderActionButtons(order)}</div>
  `;

  orderDetailModal.classList.add("open");
  orderDetailModal.setAttribute("aria-hidden", "false");
}

function closeOrderDetail() {
  if (!orderDetailModal) return;
  orderDetailModal.classList.remove("open");
  orderDetailModal.setAttribute("aria-hidden", "true");
}

orderDetailClose?.addEventListener("click", closeOrderDetail);
orderDetailModal?.addEventListener("click", (e) => { if (e.target === orderDetailModal) closeOrderDetail(); });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && orderDetailModal?.classList.contains("open")) closeOrderDetail();
});

document.addEventListener("click", (e) => {
  const card = e.target.closest("[data-order-detail]");
  if (card && !e.target.closest("[data-status-order]") && !e.target.closest("[data-edit-order]") && !e.target.closest("[data-priority-order]")) {
    openOrderDetail(card.dataset.orderDetail);
  }
});

async function loadOrders() {
  const res = await fetch(api("/get_orders"));
  if (!res.ok) return;

  const orders = sortOrdersByPriority(await res.json());
  cachedOrders = orders;

  const receivedTable = document.querySelector("#received-orders tbody");
  const inProgressTable = document.querySelector("#in-progress-orders tbody");
  const completedTable = document.querySelector("#completed-orders tbody");
  const rejectedTable = document.querySelector("#rejected-orders tbody");
  const receivedCards = document.getElementById("received-order-cards");
  const inProgressCards = document.getElementById("in-progress-order-cards");
  const completedCards = document.getElementById("completed-order-cards");
  const rejectedCards = document.getElementById("rejected-order-cards");

  receivedTable.innerHTML = "";
  inProgressTable.innerHTML = "";
  completedTable.innerHTML = "";
  if (rejectedTable) rejectedTable.innerHTML = "";
  receivedCards.innerHTML = "";
  inProgressCards.innerHTML = "";
  completedCards.innerHTML = "";
  if (rejectedCards) rejectedCards.innerHTML = "";

  orders.forEach((order) => {
    const row = buildOrderRow(order);
    const cardHtml = buildOrderCard(order);

    if (order.status === "received") {
      receivedTable.appendChild(row);
      receivedCards.insertAdjacentHTML("beforeend", cardHtml);
    } else if (order.status === "in progress") {
      inProgressTable.appendChild(row);
      inProgressCards.insertAdjacentHTML("beforeend", cardHtml);
    } else if (order.status === "rejected") {
      if (rejectedTable) rejectedTable.appendChild(row);
      if (rejectedCards) rejectedCards.insertAdjacentHTML("beforeend", cardHtml);
    } else {
      completedTable.appendChild(row);
      completedCards.insertAdjacentHTML("beforeend", cardHtml);
    }
  });

  if (!receivedTable.children.length) renderEmptyTable(receivedTable, "Incoming Orders");
  if (!inProgressTable.children.length) renderEmptyTable(inProgressTable, "In Progress Orders");
  if (!completedTable.children.length) renderEmptyTable(completedTable, "Completed Orders");
  if (rejectedTable && !rejectedTable.children.length) renderEmptyTable(rejectedTable, "Rejected Orders");
  if (!receivedCards.children.length) receivedCards.innerHTML = '<div class="summary-empty">No incoming orders right now.</div>';
  if (!inProgressCards.children.length) inProgressCards.innerHTML = '<div class="summary-empty">No in progress orders right now.</div>';
  if (!completedCards.children.length) completedCards.innerHTML = '<div class="summary-empty">No completed orders right now.</div>';
  if (rejectedCards && !rejectedCards.children.length) rejectedCards.innerHTML = '<div class="summary-empty">No rejected orders.</div>';
}

// ── Reject order ────────────────────────────────────────────────────────────

let pendingRejectOrderId = null;
const rejectModal = document.getElementById("rejectModal");
const rejectReason = document.getElementById("rejectReason");

function openRejectModal(orderId) {
  pendingRejectOrderId = orderId;
  if (rejectReason) rejectReason.value = "";
  if (rejectModal) { rejectModal.classList.add("open"); rejectModal.removeAttribute("aria-hidden"); }
}

function closeRejectModal() {
  pendingRejectOrderId = null;
  if (rejectModal) { rejectModal.classList.remove("open"); rejectModal.setAttribute("aria-hidden", "true"); }
}

async function confirmReject() {
  if (!pendingRejectOrderId) return;
  const reason = rejectReason ? rejectReason.value.trim() : "";
  const btn = document.getElementById("confirmRejectBtn");
  if (btn) { btn.disabled = true; btn.textContent = "Rejecting…"; }
  try {
    await fetch(api(`/reject_order/${pendingRejectOrderId}`), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason })
    });
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Reject Order"; }
  }
  closeRejectModal();
  loadOrders();
}

document.getElementById("closeRejectModal")?.addEventListener("click", closeRejectModal);
document.getElementById("cancelRejectModal")?.addEventListener("click", closeRejectModal);
document.getElementById("confirmRejectBtn")?.addEventListener("click", confirmReject);
rejectModal?.addEventListener("click", (e) => { if (e.target === rejectModal) closeRejectModal(); });

document.addEventListener("click", (e) => {
  const rb = e.target.closest("[data-reject-order]");
  if (rb) openRejectModal(rb.dataset.rejectOrder);
});

// ── Service override controls ────────────────────────────────────────────────

let svcHoursPendingCallback = null;
const svcHoursModal = document.getElementById("svcHoursModal");

function openSvcHoursModal(title, desc, callback) {
  svcHoursPendingCallback = callback;
  const titleEl = document.getElementById("svcHoursTitle");
  const descEl = document.getElementById("svcHoursDesc");
  const inp = document.getElementById("svcHoursInput");
  if (titleEl) titleEl.textContent = title;
  if (descEl) descEl.textContent = desc;
  if (inp) inp.value = "2";
  if (svcHoursModal) { svcHoursModal.classList.add("open"); svcHoursModal.removeAttribute("aria-hidden"); }
}

function closeSvcHoursModal() {
  svcHoursPendingCallback = null;
  if (svcHoursModal) { svcHoursModal.classList.remove("open"); svcHoursModal.setAttribute("aria-hidden", "true"); }
}

document.getElementById("closeSvcHoursModal")?.addEventListener("click", closeSvcHoursModal);
document.getElementById("cancelSvcHoursModal")?.addEventListener("click", closeSvcHoursModal);
svcHoursModal?.addEventListener("click", (e) => { if (e.target === svcHoursModal) closeSvcHoursModal(); });
document.getElementById("confirmSvcHoursBtn")?.addEventListener("click", () => {
  const hours = parseFloat(document.getElementById("svcHoursInput")?.value || "2");
  if (!hours || hours <= 0) { alert("Please enter a valid number of hours."); return; }
  const cb = svcHoursPendingCallback;
  closeSvcHoursModal();
  if (cb) cb(hours);
});

async function callServiceOverride(service, action, hours) {
  await fetch(api(`/service-override`), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ service, action, hours })
  });
  loadServiceStatus();
}

function renderServiceCard(service, data) {
  const badgeEl = document.getElementById(`svc-${service}-badge`);
  const infoEl = document.getElementById(`svc-${service}-info`);
  const actionsEl = document.getElementById(`svc-${service}-actions`);
  if (!badgeEl || !actionsEl) return;

  const isDisabled = service === "ordering" ? data.ordering_disabled : data.delivery_disabled;
  const isForced   = service === "ordering" ? data.ordering_enabled : data.delivery_enabled;
  const disabledUntil = service === "ordering" ? data.ordering_disabled_until : data.delivery_disabled_until;
  const enabledUntil  = service === "ordering" ? data.ordering_enabled_until : data.delivery_enabled_until;

  const label = service === "ordering" ? "Online Ordering" : "Delivery";

  if (isDisabled) {
    badgeEl.textContent = "Disabled";
    badgeEl.className = "service-status-badge svc-disabled";
    if (infoEl) infoEl.textContent = `Temporarily disabled until ${new Date(disabledUntil).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;
    actionsEl.innerHTML = `<button class="svc-btn svc-btn-cancel" data-svc="${service}" data-action="cancel_disable">Cancel Disable</button>`;
  } else if (isForced) {
    badgeEl.textContent = "Force-Enabled";
    badgeEl.className = "service-status-badge svc-forced";
    if (infoEl) infoEl.textContent = `Force-enabled until ${new Date(enabledUntil).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})}`;
    actionsEl.innerHTML = `<button class="svc-btn svc-btn-cancel" data-svc="${service}" data-action="cancel_enable">Cancel Enable</button>`;
  } else {
    badgeEl.textContent = "Active";
    badgeEl.className = "service-status-badge svc-normal";
    if (infoEl) infoEl.textContent = `${label} is running normally.`;
    actionsEl.innerHTML = `
      <button class="svc-btn svc-btn-disable" data-svc="${service}" data-action="disable">Disable (temp)</button>
      <button class="svc-btn svc-btn-enable"  data-svc="${service}" data-action="enable">Enable (outside hours)</button>
    `;
  }
}

async function loadServiceStatus() {
  try {
    const res = await fetch(api("/service-status"));
    if (!res.ok) return;
    const data = await res.json();
    if (document.getElementById("svc-ordering-badge")) renderServiceCard("ordering", data);
    if (document.getElementById("svc-delivery-badge")) renderServiceCard("delivery", data);
  } catch (e) { console.warn("Service status load failed", e); }
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-svc][data-action]");
  if (!btn) return;
  const service = btn.dataset.svc;
  const action  = btn.dataset.action;
  if (action === "cancel_disable" || action === "cancel_enable") {
    callServiceOverride(service, action, 0);
  } else if (action === "disable") {
    openSvcHoursModal(
      `Disable ${service === "ordering" ? "Online Ordering" : "Delivery"}`,
      "For how many hours should it be disabled?",
      (hours) => callServiceOverride(service, "disable", hours)
    );
  } else if (action === "enable") {
    openSvcHoursModal(
      `Force-Enable ${service === "ordering" ? "Online Ordering" : "Delivery"}`,
      "For how many hours should it be force-enabled (overrides your set hours)?",
      (hours) => callServiceOverride(service, "enable", hours)
    );
  }
});

loadPriorityState();
loadCatalog();
setViewMode(orderViewMode);
setDetailMode(orderDetailMode);
setPriorityMode(priorityEnabled ? "on" : "off");
loadOrders();
loadServiceStatus();
setInterval(loadOrders, 3000);
setInterval(loadServiceStatus, 30000);
