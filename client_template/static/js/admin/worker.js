const apiBase = document.body.dataset.apiBase || "";
const api = (path) => `${apiBase}${path}`;

let previousOrderIds = new Set();
let orderCatalog = { products: [], deals: [] };
let draftItems = [];
let currentOrderId = null;

const orderModal = document.getElementById("orderModal");
const orderModalTitle = document.getElementById("orderModalTitle");
const orderModalCopy = document.getElementById("orderModalCopy");
const orderSearch = document.getElementById("orderSearch");
const orderSearchResults = document.getElementById("orderSearchResults");
const orderSummaryList = document.getElementById("orderSummaryList");
const orderSummaryTotal = document.getElementById("orderSummaryTotal");
const allowDiscounts = document.getElementById("allowDiscounts");
const saveOrderBtn = document.getElementById("saveOrderBtn");

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

  return catalog.filter((item) => {
    const fields = [
      item.title,
      item.description,
      item.category,
      item.type
    ].filter(Boolean).join(" ").toLowerCase();
    return fields.includes(query);
  }).slice(0, 18);
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
      </div>
    `;
  }).join("");
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

  const actionButtons = [];
  actionButtons.push(`<button class="table-action-btn edit" type="button" data-edit-order="${order.id}">Edit Items</button>`);
  if (order.status === "received") {
    actionButtons.push(`<button class="table-action-btn start" type="button" data-status-order="${order.id}" data-next-status="in progress">Start</button>`);
  }
  if (order.status === "in progress") {
    actionButtons.push(`<button class="table-action-btn complete" type="button" data-status-order="${order.id}" data-next-status="completed">Complete</button>`);
  }

  tr.innerHTML = `
    <td>
      <div class="customer-stack">
        <div class="customer-name">#${order.order_number || order.id}</div>
        <span class="detail-chip">Order ID ${order.id}</span>
      </div>
    </td>
    <td>
      <div class="customer-stack">
        <div class="customer-name">${escapeHtml(`${order.name || ""} ${order.surname || ""}`.trim() || "Walk-in Customer")}</div>
        <div>${escapeHtml(order.phone || "No phone")}</div>
        <div>${escapeHtml(order.email || "No email")}</div>
      </div>
    </td>
    <td class="order-items">${renderOrderItems(items)}</td>
    <td class="order-note">${escapeHtml(order.note || "No notes added.")}</td>
    <td><strong>${formatCurrency(order.total)}</strong></td>
    <td>${escapeHtml(order.payment_method || "-")}</td>
    <td>${timingHtml}</td>
    <td><div class="action-cluster">${actionButtons.join("")}</div></td>
  `;

  previousOrderIds.add(order.id);
  return tr;
}

async function loadOrders() {
  const res = await fetch(api("/get_orders"));
  if (!res.ok) return;

  const orders = await res.json();
  const receivedTable = document.querySelector("#received-orders tbody");
  const inProgressTable = document.querySelector("#in-progress-orders tbody");
  const completedTable = document.querySelector("#completed-orders tbody");

  receivedTable.innerHTML = "";
  inProgressTable.innerHTML = "";
  completedTable.innerHTML = "";

  orders.forEach((order) => {
    const row = buildOrderRow(order);
    if (order.status === "received") receivedTable.appendChild(row);
    else if (order.status === "in progress") inProgressTable.appendChild(row);
    else completedTable.appendChild(row);
  });

  if (!receivedTable.children.length) renderEmptyTable(receivedTable, "Incoming Orders");
  if (!inProgressTable.children.length) renderEmptyTable(inProgressTable, "In Progress Orders");
  if (!completedTable.children.length) renderEmptyTable(completedTable, "Completed Orders");
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
  }
});

document.addEventListener("input", (event) => {
  if (event.target === orderSearch) {
    renderSearchResults();
    return;
  }

  const field = event.target.dataset.field;
  if (!field) return;
  updateDraftItem(Number(event.target.dataset.index), field, event.target.value);
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

orderModal?.addEventListener("click", (event) => {
  if (event.target === orderModal) closeOrderModal();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && orderModal?.classList.contains("open")) closeOrderModal();
});

loadCatalog();
loadOrders();
setInterval(loadOrders, 3000);
