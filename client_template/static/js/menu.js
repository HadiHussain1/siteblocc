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
const api = (path) => `${path}?project=${window.PROJECT_SLUG}`;
const publicPath = (path) => `${path}?project=${window.PROJECT_SLUG}`;
const orderingEnabled = Boolean(window.PROJECT_MODULES?.online_ordering_system);
const hasImagePath = (value) => Boolean(value && value !== 'null' && value !== 'None');
const DEAL_BUNDLE_MARKER = '\n[[DEAL_BUNDLE]]';

console.log(window.PROJECT_SLUG);

let menuData = [];
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

    const group = document.createElement('div');
    group.classList.add('category-group');
    group.dataset.category = cat.name;

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
      group.appendChild(card);
    });

    menuContainer.appendChild(group);
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
      addToCart({
        ...deal,
        item_kind: 'deal',
        price: Number(deal.price)
      });
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
    headers: {'Content-Type':'application/json'},
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
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({
      total: order.total,
      project_slug: window.PROJECT_SLUG
    })
  });

  const data = await res.json();

  console.log('creating stripe session, server returned', data);
  if (!data || !data.id) {
    console.error('no session id from backend');
    return;
  }

  const key = window.STRIPE_PUBLISHABLE_KEY || "pk_test_51Symo3HD7St6XedJ4cGXg0seXCON9afV38AUmlp3LZxIt3BL1KxmH7mDjSzg608WMOG5LfGBLFgRfevdQyltYaGg001pKowflm";
  const stripe = Stripe(key);

  stripe.redirectToCheckout({ sessionId: data.id });
}

function goToInstoreCheckout() {
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

initMobileMenu();
initMenuInteractions();
fetchMenu();
fetchDeals();
