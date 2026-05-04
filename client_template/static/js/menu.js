// ============================
// MENU.JS - FETCH FROM BACKEND
// ============================

const menuContainer = document.getElementById('menu');
const tabsContainer = document.getElementById('menu-tabs');
const dealsSection = document.getElementById('deals-section');
const hotDealsSection = document.getElementById('hot-deals-section');
const searchToggle = document.getElementById('menu-search-toggle');
const searchPanel = document.getElementById('menu-search-panel');
const searchInput = document.getElementById('menu-search-input');
const api = (path) => path;
const publicPath = (path) => path;
const orderingEnabled = Boolean(window.PROJECT_MODULES?.online_ordering_system);
const hasImagePath = (value) => Boolean(value && value !== 'null' && value !== 'None');
const DEAL_BUNDLE_MARKER = '\n[[DEAL_BUNDLE]]';

console.log(window.PROJECT_SLUG);

let menuData = [];
let allProducts = [];
let allCategories = [];
let activeCategory = 'All';
let searchQuery = '';

function formatCurrency(value) {
  return `$${Number(value || 0).toFixed(2)}`;
}

function getProductRanks(product) {
  if (!product?.has_ranking || !Array.isArray(product.ranks)) {
    return [];
  }
  return product.ranks.filter(rank => rank?.name && rank?.price !== undefined && rank?.price !== null);
}

function parseDealDescription(rawDescription) {
  const source = (rawDescription || '').toString();
  const markerIndex = source.indexOf(DEAL_BUNDLE_MARKER);

  if (markerIndex === -1) {
    return { description: source.trim(), bundleItems: [] };
  }

  const description = source.slice(0, markerIndex).trim();
  const rawBundle = source.slice(markerIndex + DEAL_BUNDLE_MARKER.length).trim();

  try {
    const bundleItems = JSON.parse(rawBundle);
    return {
      description,
      bundleItems: Array.isArray(bundleItems) ? bundleItems : []
    };
  } catch {
    return { description: source.trim(), bundleItems: [] };
  }
}

function initMobileMenu() {
  const toggle = document.querySelector('.nav-toggle');
  const mobileMenu = document.querySelector('.mobile-menu');
  const mobileMenuBackdrop = document.querySelector('.mobile-menu-backdrop');

  if (!toggle || !mobileMenu || toggle.dataset.menuBound === 'true') return;

  const closeMobileMenu = () => {
    mobileMenu.classList.remove('open');
    toggle.classList.remove('open');
    mobileMenuBackdrop?.classList.remove('open');
    document.body.classList.remove('menu-open');
  };

  const openMobileMenu = () => {
    mobileMenu.classList.add('open');
    toggle.classList.add('open');
    mobileMenuBackdrop?.classList.add('open');
    document.body.classList.add('menu-open');
  };

  toggle.addEventListener('click', (e) => {
    e.preventDefault();
    if (mobileMenu.classList.contains('open')) {
      closeMobileMenu();
    } else {
      openMobileMenu();
    }
  });

  mobileMenuBackdrop?.addEventListener('click', closeMobileMenu);

  mobileMenu.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', closeMobileMenu);
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      closeMobileMenu();
    }
  });

  toggle.dataset.menuBound = 'true';
}

async function fetchMenu() {
  if (!menuContainer || !tabsContainer) return;

  try {
    const categoriesRes = await fetch(api('/categories'));
    const productsRes = await fetch(api('/products'));

    const categories = await categoriesRes.json();
    const products = await productsRes.json();

    allProducts = products;
    allCategories = categories;

    menuData = categories.map(cat => ({
      ...cat,
      products: products.filter(p => p.category_id === cat.id)
    }));

    renderTabs();
    renderMenu();
  } catch (err) {
    console.error('Failed to fetch menu:', err);
  }
}

function renderTabs() {
  tabsContainer.innerHTML = '';
  const allTab = document.createElement('div');
  allTab.classList.add('menu-tab', 'active');
  allTab.dataset.category = 'All';
  allTab.textContent = 'All';
  tabsContainer.appendChild(allTab);

  menuData.forEach(cat => {
    const tab = document.createElement('div');
    tab.classList.add('menu-tab');
    tab.textContent = cat.name;
    tab.dataset.category = cat.name;
    tabsContainer.appendChild(tab);
  });
}

function normalizeText(value) {
  return (value || '').toString().trim().toLowerCase();
}

function getFilteredProducts(products) {
  const query = normalizeText(searchQuery);
  if (!query) return products;

  return products.filter(product => {
    const title = normalizeText(product.title);
    const description = normalizeText(product.description);
    return title.includes(query) || description.includes(query);
  });
}

function renderMenu() {
  menuContainer.innerHTML = '';

  document.querySelectorAll('.menu-tab').forEach(tab => {
    tab.classList.toggle('active', tab.dataset.category === activeCategory);
  });

  menuData.forEach(cat => {
    if (activeCategory !== 'All' && cat.name !== activeCategory) {
      return;
    }

    const filteredProducts = getFilteredProducts(cat.products);
    if (!filteredProducts.length) {
      return;
    }

    const group = document.createElement('section');
    group.classList.add('category-group');
    group.dataset.category = cat.name;

    const categoryHeader = document.createElement('div');
    categoryHeader.className = 'category-header';

    const categoryLabel = document.createElement('span');
    categoryLabel.className = 'category-label';
    categoryLabel.textContent = 'Category';
    categoryHeader.appendChild(categoryLabel);

    const categoryTitle = document.createElement('h2');
    categoryTitle.className = 'category-title';
    categoryTitle.textContent = cat.name;
    categoryHeader.appendChild(categoryTitle);

    const categoryLine = document.createElement('div');
    categoryLine.className = 'category-line';
    categoryHeader.appendChild(categoryLine);

    const categoryProducts = document.createElement('div');
    categoryProducts.className = 'category-products';

    group.appendChild(categoryHeader);
    group.appendChild(categoryProducts);

    const descExpandPairs = [];

    filteredProducts.forEach(product => {
      const card = document.createElement('div');
      card.classList.add('menu-card');

      if (hasImagePath(product.image_path)) {
        const img = document.createElement('img');
        img.classList.add('menu-card-img');
        img.src = product.image_path;
        card.appendChild(img);
      }

      const body = document.createElement('div');
      body.classList.add('menu-card-body');

      const title = document.createElement('h3');
      title.classList.add('menu-card-title');
      title.textContent = product.title;
      body.appendChild(title);

      const desc = document.createElement('p');
      desc.classList.add('menu-card-description');
      desc.textContent = product.description;
      body.appendChild(desc);

      const moreLink = document.createElement('span');
      moreLink.className = 'desc-more-link';
      moreLink.textContent = '...more';
      moreLink.hidden = true;
      body.appendChild(moreLink);
      descExpandPairs.push({ desc, moreLink });

      moreLink.addEventListener('click', () => {
        const expanded = desc.classList.toggle('expanded');
        moreLink.textContent = expanded ? 'less' : '...more';
      });

      let selectedRank = null;
      const ranks = getProductRanks(product);

      if (ranks.length) {
        selectedRank = ranks[0];

        const rankSelect = document.createElement('select');
        rankSelect.className = 'menu-rank-select';

        ranks.forEach(rank => {
          const option = document.createElement('option');
          option.value = rank.name;
          option.textContent = rank.name;
          rankSelect.appendChild(option);
        });

        body.appendChild(rankSelect);

        rankSelect.addEventListener('change', () => {
          selectedRank = ranks.find(rank => rank.name === rankSelect.value) || ranks[0];
          price.textContent = formatCurrency(selectedRank.price);
        });
      }

      const footer = document.createElement('div');
      footer.classList.add('menu-card-footer');

      const price = document.createElement('span');
      price.classList.add('menu-price');
      price.textContent = formatCurrency(selectedRank ? selectedRank.price : product.price);
      footer.appendChild(price);

      if (orderingEnabled) {
        const addBtn = document.createElement('button');
        addBtn.className = 'add-btn';
        addBtn.textContent = 'Add';
        addBtn.addEventListener('click', () => addToCart({
          ...product,
          item_kind: 'product',
          price: selectedRank ? Number(selectedRank.price) : Number(product.price),
          rank: selectedRank ? selectedRank.name : null
        }));
        footer.appendChild(addBtn);
      }

      body.appendChild(footer);
      card.appendChild(body);
      categoryProducts.appendChild(card);
    });

    menuContainer.appendChild(group);

    requestAnimationFrame(() => {
      descExpandPairs.forEach(({ desc, moreLink }) => {
        // Check if text is actually truncated by comparing full height to clamped height
        const clone = desc.cloneNode(true);
        clone.style.webkitLineClamp = 'unset';
        clone.style.display = 'block';
        clone.style.visibility = 'hidden';
        clone.style.position = 'absolute';
        clone.style.height = 'auto';
        desc.parentNode.appendChild(clone);

        const fullHeight = clone.scrollHeight;
        const clampedHeight = desc.clientHeight;

        clone.remove();

        if (fullHeight > clampedHeight + 2) {
          moreLink.hidden = false;
        }
      });
    });
  });

  if (!menuContainer.children.length) {
    const emptyState = document.createElement('div');
    emptyState.className = 'menu-empty-state';
    emptyState.innerHTML = `
      <h3>No matches found</h3>
      <p>Try a different keyword or browse another category.</p>
    `;
    menuContainer.appendChild(emptyState);
  }
}

async function fetchDeals() {
  const dealsContainer = document.getElementById('deals-container');
  const hotContainer = document.getElementById('hot-deals-container');
  if (!dealsContainer || !hotContainer) return;

  const res = await fetch(api('/deals'));
  const deals = await res.json();

  dealsContainer.innerHTML = '';
  hotContainer.innerHTML = '';
  let dealCount = 0;
  let hotDealCount = 0;

  deals.forEach(deal => {
    const card = createDealCard(deal);

    if (deal.type === 'deal') {
      dealsContainer.appendChild(card);
      dealCount += 1;
    } else {
      hotContainer.appendChild(card);
      hotDealCount += 1;
    }
  });

  if (dealsSection) {
    dealsSection.hidden = dealCount === 0;
  }

  if (hotDealsSection) {
    hotDealsSection.hidden = hotDealCount === 0;
  }
}

function createDealCard(deal) {
  const parsedDeal = {
    description: deal.description || parseDealDescription(deal.description).description,
    bundleItems: Array.isArray(deal.bundle_items) ? deal.bundle_items : parseDealDescription(deal.description).bundleItems
  };
  const card = document.createElement('div');
  card.classList.add('deal-card');

  const imgWrapper = document.createElement('div');
  imgWrapper.classList.add('deal-card-img-wrapper');

  if (hasImagePath(deal.image_path)) {
    const img = document.createElement('img');
    img.classList.add('deal-card-img');
    img.src = deal.image_path;
    img.alt = deal.title;
    imgWrapper.appendChild(img);
  }

  const body = document.createElement('div');
  body.classList.add('deal-card-body');

  const title = document.createElement('h3');
  title.classList.add('deal-card-title');
  title.textContent = deal.title;

  const desc = document.createElement('p');
  desc.classList.add('deal-card-description');
  desc.textContent = parsedDeal.description;

  const footer = document.createElement('div');
  footer.classList.add('deal-card-footer');

  const price = document.createElement('span');
  price.classList.add('menu-price');
  price.textContent = formatCurrency(deal.price);
  footer.appendChild(price);

  if (orderingEnabled) {
    const btn = document.createElement('button');
    btn.className = 'add-btn';
    btn.textContent = 'Add';
    btn.addEventListener('click', () => {
      const hasChoices = Array.isArray(deal.bundle_items) && deal.bundle_items.some(
        item => (item.category_id || item.section_id) && !item.product_id ||
                (item.product_id && Array.isArray(item.or_options) && item.or_options.length > 0)
      );
      if (hasChoices) {
        openDealModal(deal);
      } else {
        addToCart({
          ...deal,
          item_kind: 'deal',
          price: Number(deal.price),
          bundle_selections: buildFixedSelections(deal.bundle_items || [])
        });
      }
    });
    footer.appendChild(btn);
  }

  body.appendChild(title);
  body.appendChild(desc);

  if (parsedDeal.bundleItems.length) {
    const bundlePreview = document.createElement('div');
    bundlePreview.className = 'bundle-summary';

    parsedDeal.bundleItems.forEach(item => {
      const pill = document.createElement('span');
      pill.className = 'bundle-pill';
      pill.textContent = `${item.quantity} x ${item.product_title || `Product #${item.product_id}`}`;
      bundlePreview.appendChild(pill);
    });

    body.appendChild(bundlePreview);
  }

  body.appendChild(footer);

  if (imgWrapper.childElementCount > 0) {
    card.appendChild(imgWrapper);
  }
  card.appendChild(body);

  return card;
}

function checkout() {
  if (typeof window.isOrderingOpenNow === 'function' && !window.isOrderingOpenNow()) {
    alert('Online ordering is currently closed. Please come back during ordering hours.');
    return;
  }

  if (cart.length === 0) {
    alert("Your cart is empty!");
    return;
  }

  const orderDraft = {
    items: cart,
    total: cart.reduce((sum, i) => sum + (i.price * (i.quantity || 1)), 0)
  };

  localStorage.setItem("checkout_order", JSON.stringify(orderDraft));
  window.location.href = publicPath('/checkout');
}

async function submitFinalOrder(event) {
  event.preventDefault();
  const order = JSON.parse(localStorage.getItem("checkout_order"));
  if (!order) return;

  if (!event.target.checkValidity()) {
    event.target.reportValidity();
    return;
  }

  const name = document.getElementById("name").value;
  const surname = document.getElementById("surname").value;
  const phone = document.getElementById("phone").value;

  const res = await fetch(publicPath('/add_order'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      items: order.items,
      total: order.total,
      payment: order.payment,
      name: name,
      surname: surname,
      phone: phone
    })
  });

  const data = await res.json();

  if (data.success) {
    document.body.innerHTML = `
      <div style="
        display:flex;
        flex-direction:column;
        align-items:center;
        justify-content:center;
        height:80vh;
        font-size:28px;
        font-weight:600;
        text-align:center;
        color:#f5f5f5;
      ">
        <div>
          Your Order Number is ${data.order_number}<br><br>
          See you soon!
        </div>

        <button id="back-home" style="
          margin-top:30px;
          padding:16px 36px;
          border-radius:999px;
          border:2px solid #d4a373;
          background:#000;
          color:#d4a373;
          font-size:16px;
          font-weight:600;
          cursor:pointer;
          transition:all 0.25s ease;
        ">
          Back to Home
        </button>
      </div>
    `;

    document.getElementById("back-home").addEventListener("click", () => {
      localStorage.clear();
      sessionStorage.clear();
      window.location.href = publicPath("/");
    });
  }
}

async function payOnline(event) {
  event.preventDefault();

  const order = JSON.parse(localStorage.getItem("checkout_order"));
  if (!order) return;

  localStorage.setItem("name", document.getElementById("name").value);
  localStorage.setItem("surname", document.getElementById("surname").value);
  localStorage.setItem("phone", document.getElementById("phone").value);

  const res = await fetch('/create-checkout-session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      items: order.items,
      total: order.total,
      payment: 'instore',
      name: document.getElementById("name")?.value || '',
      surname: document.getElementById("surname")?.value || '',
      phone: document.getElementById("phone")?.value || '',
      email: document.getElementById("email")?.value || '',
      note: document.getElementById("note")?.value || ''
    })
  });

  const data = await res.json();

  // LEGACY: Stripe payment system (disabled for trial phase)
  // console.log('creating stripe session, server returned', data);
  // if (!data || !data.id) {
  //   console.error('no session id from backend');
  //   return;
  // }
  // const key = window.STRIPE_PUBLISHABLE_KEY || "pk_test_51Symo3HD7St6XedJ4cGXg0seXCON9afV38AUmlp3LZxIt3BL1KxmH7mDjSzg608WMOG5LfGBLFgRfevdQyltYaGg001pKowflm";
  // const stripe = Stripe(key);
  // stripe.redirectToCheckout({ sessionId: data.id });

  if (!data || !data.success || !data.order_number) {
    console.error('offline order creation failed', data);
    return;
  }

  sessionStorage.setItem("latest_order_confirmation", JSON.stringify({
    order_number: data.order_number,
    payment_method: data.payment_method || "instore",
    payment_status: data.payment_status || "pending"
  }));
  localStorage.removeItem("checkout_order");
  window.location.href = data.redirect_url || publicPath('/payment-success');
}

function goToInstoreCheckout() {
  if (typeof window.isOrderingOpenNow === 'function' && !window.isOrderingOpenNow()) {
    alert('Online ordering is currently closed. Please come back during ordering hours.');
    return;
  }

  if (cart.length === 0) {
    alert("Your cart is empty!");
    return;
  }

  const order = {
    items: cart,
    total: cart.reduce((sum, i) => sum + (i.price * (i.quantity || 1)), 0)
  };

  localStorage.setItem("checkout_order", JSON.stringify(order));
  window.location.href = publicPath('/checkout-instore');
}

function buildFixedSelections(bundleItems) {
  const selections = [];
  (bundleItems || []).forEach(item => {
    const qty = Number(item.quantity || 1);
    const hasOrOptions = Array.isArray(item.or_options) && item.or_options.length > 0;
    for (let i = 0; i < qty; i++) {
      if (item.product_id && !hasOrOptions) {
        const title = item.product_title || `Product #${item.product_id}`;
        selections.push({
          product_id: item.product_id,
          product_title: title,
          rank_name: item.rank_name || null,
          slot_label: item.rank_name ? `${item.rank_name} ${title}` : title
        });
      }
    }
  });
  return selections;
}

function getCandidatesForOption(opt) {
  if (!opt) return [];
  let filtered;

  if (opt.section_id) {
    const catIds = allCategories
      .filter(c => String(c.section_id) === String(opt.section_id))
      .map(c => c.id);
    filtered = allProducts.filter(p => catIds.includes(p.category_id));
  } else if (opt.category_id) {
    filtered = allProducts.filter(p => String(p.category_id) === String(opt.category_id));
  } else if (opt.product_id) {
    filtered = allProducts.filter(p => String(p.id) === String(opt.product_id));
  } else {
    return [];
  }

  if (opt.rank_name) {
    filtered = filtered.filter(p =>
      p.has_ranking && Array.isArray(p.ranks) &&
      p.ranks.some(r => r.name === opt.rank_name)
    );
  }

  return filtered;
}

function getProductsForSlot(bundleItem) {
  const primary = getCandidatesForOption(bundleItem);
  const orCandidates = (bundleItem.or_options || []).flatMap(opt => getCandidatesForOption(opt));

  const seen = new Set();
  const combined = [];
  for (const p of [...primary, ...orCandidates]) {
    if (!seen.has(p.id)) {
      seen.add(p.id);
      combined.push(p);
    }
  }
  return combined;
}

function openDealModal(deal) {
  const overlay = document.getElementById('deal-modal-overlay');
  const titleEl = document.getElementById('deal-modal-title');
  const subtitleEl = document.getElementById('deal-modal-subtitle');
  const slotsContainer = document.getElementById('deal-modal-slots');

  if (!overlay || !slotsContainer) return;

  titleEl.textContent = deal.title || 'Customise Your Deal';
  subtitleEl.textContent = `$${Number(deal.price).toFixed(2)} — select your choices below`;
  slotsContainer.innerHTML = '';

  const slots = [];
  (deal.bundle_items || []).forEach(item => {
    const qty = Number(item.quantity || 1);
    for (let i = 0; i < qty; i++) {
      slots.push({ ...item });
    }
  });

  let hasUnavailable = false;

  slots.forEach((slot, index) => {
    const slotEl = document.createElement('div');
    slotEl.className = 'deal-modal-slot';

    const labelEl = document.createElement('span');
    labelEl.className = 'deal-modal-slot-label';
    const primaryRank = slot.rank_name ? `${slot.rank_name} ` : '';
    let slotLabelText = `${primaryRank}${slot.product_title || 'Item'}`;
    if (Array.isArray(slot.or_options) && slot.or_options.length) {
      const orParts = slot.or_options.map(o => `${o.rank_name ? `${o.rank_name} ` : ''}${o.product_title || 'Item'}`);
      slotLabelText += ' OR ' + orParts.join(' OR ');
    }
    labelEl.textContent = `Item ${index + 1}: ${slotLabelText}`;
    slotEl.appendChild(labelEl);

    const hasOrOptions = Array.isArray(slot.or_options) && slot.or_options.length > 0;

    if (slot.product_id && !hasOrOptions) {
      const fixedEl = document.createElement('div');
      fixedEl.className = 'deal-modal-slot-fixed';
      fixedEl.textContent = slot.product_title || `Product #${slot.product_id}`;
      slotEl.appendChild(fixedEl);
    } else {
      const candidates = getProductsForSlot(slot);

      if (!candidates.length) {
        const unavailEl = document.createElement('div');
        unavailEl.className = 'deal-modal-slot-unavailable';
        unavailEl.textContent = 'Not currently available';
        slotEl.appendChild(unavailEl);
        hasUnavailable = true;
      } else {
        const selectEl = document.createElement('select');
        selectEl.className = 'deal-modal-slot-select';
        selectEl.dataset.slotIndex = index;
        selectEl.dataset.rankName = slot.rank_name || '';

        candidates.forEach(product => {
          const opt = document.createElement('option');
          opt.value = product.id;
          opt.textContent = product.title;
          selectEl.appendChild(opt);
        });

        slotEl.appendChild(selectEl);
      }
    }

    slotsContainer.appendChild(slotEl);
  });

  const confirmBtn = document.getElementById('deal-modal-confirm');
  if (confirmBtn) confirmBtn.disabled = hasUnavailable;

  overlay._pendingDeal = deal;
  overlay._pendingSlots = slots;

  overlay.removeAttribute('hidden');
  overlay.setAttribute('aria-hidden', 'false');

  const onConfirm = () => confirmDealModal(deal, slots);
  const onCancel = closeDealModal;
  const onClose = closeDealModal;
  const onKey = (e) => { if (e.key === 'Escape') closeDealModal(); };

  document.getElementById('deal-modal-confirm')._dealHandler = onConfirm;
  document.getElementById('deal-modal-cancel')._dealHandler = onCancel;
  document.getElementById('deal-modal-close')._dealHandler = onClose;

  document.getElementById('deal-modal-confirm').onclick = onConfirm;
  document.getElementById('deal-modal-cancel').onclick = onCancel;
  document.getElementById('deal-modal-close').onclick = onClose;
  overlay.onclick = (e) => { if (e.target === overlay) closeDealModal(); };
  document._dealKeyHandler = onKey;
  document.addEventListener('keydown', onKey);
}

function closeDealModal() {
  const overlay = document.getElementById('deal-modal-overlay');
  if (!overlay) return;
  overlay.setAttribute('hidden', '');
  overlay.setAttribute('aria-hidden', 'true');
  if (document._dealKeyHandler) {
    document.removeEventListener('keydown', document._dealKeyHandler);
    document._dealKeyHandler = null;
  }
}

function confirmDealModal(deal, slots) {
  const slotsContainer = document.getElementById('deal-modal-slots');
  if (!slotsContainer) return;

  const selections = [];
  const slotEls = slotsContainer.querySelectorAll('.deal-modal-slot');

  slotEls.forEach((slotEl, index) => {
    const slot = slots[index];
    if (!slot) return;

    const hasOrOptions = Array.isArray(slot.or_options) && slot.or_options.length > 0;
    if (slot.product_id && !hasOrOptions) {
      const title = slot.product_title || `Product #${slot.product_id}`;
      selections.push({
        product_id: slot.product_id,
        product_title: title,
        rank_name: slot.rank_name || null,
        slot_label: slot.rank_name ? `${slot.rank_name} ${title}` : title
      });
    } else {
      const selectEl = slotEl.querySelector('.deal-modal-slot-select');
      if (selectEl && selectEl.value) {
        const product = allProducts.find(p => String(p.id) === String(selectEl.value));
        const rankName = selectEl.dataset.rankName || null;
        const title = product ? product.title : `Product #${selectEl.value}`;
        selections.push({
          product_id: Number(selectEl.value),
          product_title: title,
          rank_name: rankName || null,
          slot_label: rankName ? `${rankName} ${title}` : title
        });
      }
    }
  });

  addToCart({
    ...deal,
    item_kind: 'deal',
    price: Number(deal.price),
    bundle_selections: selections,
    _deal_instance_id: Date.now() + Math.random()
  });

  closeDealModal();
}

function initMenuInteractions() {
  tabsContainer?.addEventListener('click', e => {
    const target = e.target.closest('.menu-tab');
    if (!target) return;

    activeCategory = target.dataset.category || 'All';
    renderMenu();
  });

  searchToggle?.addEventListener('click', () => {
    const isOpen = searchPanel?.classList.toggle('open');
    searchToggle.setAttribute('aria-expanded', String(Boolean(isOpen)));

    if (isOpen) {
      searchInput?.focus();
    } else if (searchInput) {
      searchInput.value = '';
      searchQuery = '';
      renderMenu();
    }
  });

  searchInput?.addEventListener('input', e => {
    searchQuery = e.target.value || '';
    renderMenu();
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape' && searchPanel?.classList.contains('open')) {
      searchPanel.classList.remove('open');
      searchToggle?.setAttribute('aria-expanded', 'false');
      if (searchInput) {
        searchInput.value = '';
      }
      searchQuery = '';
      renderMenu();
    }
  });
}

function applyMenuOrderingGate() {
  if (typeof window.isOrderingOpenNow !== 'function') return;

  const open = window.isOrderingOpenNow();
  document.querySelectorAll('.order-btn').forEach((btn) => {
    btn.disabled = !open;
    btn.style.opacity = open ? '' : '0.45';
    btn.style.cursor = open ? '' : 'not-allowed';
    btn.setAttribute('aria-disabled', open ? 'false' : 'true');
    if (open) {
      btn.removeAttribute('title');
    } else {
      btn.setAttribute('title', 'Online ordering is currently closed. Please come back during ordering hours.');
    }
  });
}

initMobileMenu();
initMenuInteractions();
applyMenuOrderingGate();
setInterval(applyMenuOrderingGate, 60000);
fetchMenu();
fetchDeals();
