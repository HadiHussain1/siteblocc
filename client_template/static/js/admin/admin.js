document.addEventListener('DOMContentLoaded', () => {
  const categoriesTableBody = document.querySelector('#categories-table tbody');
  const productsGrid = document.querySelector('#products-grid');
  const productsEmpty = document.querySelector('#products-empty');
  const dealsGrid = document.querySelector('#deals-grid');
  const dealsEmpty = document.querySelector('#deals-empty');
  const productCategorySelect = document.querySelector('#product-category');
  const addCategoryForm = document.querySelector('#add-category-form');
  const addProductForm = document.querySelector('#add-product-form');
  const bulkProductsPanel = document.querySelector('#bulk-products-panel');
  const bulkProductsForm = document.querySelector('#bulk-products-form');
  const bulkProductsFile = document.querySelector('#bulk-products-file');
  const bulkProductsFileName = document.querySelector('#bulk-products-file-name');
  const bulkProductsSubmit = document.querySelector('#bulk-products-submit');
  const bulkProductsAttempts = document.querySelector('#bulk-products-attempts');
  const bulkProductsProgress = document.querySelector('#bulk-products-progress');
  const bulkProductsProgressBar = document.querySelector('#bulk-products-progress-bar');
  const bulkProductsStatus = document.querySelector('#bulk-products-status');
  const dealForm = document.querySelector('#deal-form');
  const bundleList = document.querySelector('#deal-bundle-list');
  const bundleSummary = document.querySelector('#deal-bundle-summary');
  const addDealProductRowButton = document.querySelector('#add-deal-product-row');
  const productRankingToggle = document.querySelector('#product-has-ranking');
  const rankingFields = document.querySelector('#ranking-fields');
  const productPriceInput = document.querySelector('#product-price');
  const categoriesSearchInput = document.querySelector('#categories-search');
  const productsSearchInput = document.querySelector('#products-search');
  const dealsSearchInput = document.querySelector('#deals-search');
  const managementInfoButton = document.querySelector('#management-info-button');
  const managementHelpOverlay = document.querySelector('#management-help-overlay');
  const managementHelpClose = document.querySelector('#management-help-close');
  const adminSlugMatch = window.location.pathname.match(/^\/admin\/([^/]+)/);
  const adminBasePath = adminSlugMatch ? `/admin/${adminSlugMatch[1]}` : '';
  const apiUrl = (path) => `${adminBasePath}${path}`;

  let categories = [];
  let sections = [];
  let products = [];
  const pendingDealSaves = new Map();
  let bulkProgressTimer = null;


  function escapeHtml(value) {
    return String(value ?? '')
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function getProductRanks(product) {
    if (!product?.has_ranking || !Array.isArray(product.ranks)) {
      return [];
    }
    return product.ranks.filter(rank => rank?.name && rank?.price !== undefined && rank?.price !== null);
  }

  function getProductById(productId) {
    return products.find(product => String(product.id) === String(productId));
  }

  function getCategoryById(categoryId) {
    return categories.find(category => String(category.id) === String(categoryId));
  }

  function getSectionById(sectionId) {
    return sections.find(section => String(section.id) === String(sectionId));
  }

  function getUniqueRankNames(productList) {
    const names = new Set();
    productList.forEach(p => {
      if (p.has_ranking && Array.isArray(p.ranks)) {
        p.ranks.forEach(r => { if (r.name) names.add(r.name); });
      }
    });
    return Array.from(names);
  }

  function parseDealBundleItems(deal) {
    return Array.isArray(deal.bundle_items) ? deal.bundle_items : [];
  }

  function buildDealProductsColumn(bundleItems) {
    const parts = [];

    bundleItems.forEach((item) => {
      const quantity = Number(item.quantity || 0);
      if (!item.product_id || quantity <= 0) return;

      for (let index = 0; index < quantity; index += 1) {
        parts.push(String(item.product_id));
      }
    });

    return parts.join('^^^&');
  }

  function toggleRankingFields() {
    const enabled = Boolean(productRankingToggle?.checked);
    if (rankingFields) {
      rankingFields.hidden = !enabled;
    }
    if (productPriceInput) {
      productPriceInput.disabled = enabled;
      productPriceInput.placeholder = enabled ? 'Rank 1 price will be used' : 'Price';
    }
  }

  function bindUploadLabel(inputSelector, labelSelector, defaultText) {
    const input = document.querySelector(inputSelector);
    const label = document.querySelector(labelSelector);
    if (!input || !label) return;

    input.addEventListener('change', () => {
      label.textContent = input.files?.[0]?.name || defaultText;
    });
  }

  function setBulkProgress(value) {
    if (!bulkProductsProgress || !bulkProductsProgressBar) return;
    bulkProductsProgress.classList.add('active');
    bulkProductsProgressBar.style.width = `${Math.max(0, Math.min(value, 100))}%`;
  }

  function startBulkProgress() {
    let progress = 8;
    setBulkProgress(progress);
    window.clearInterval(bulkProgressTimer);
    bulkProgressTimer = window.setInterval(() => {
      progress += progress < 55 ? 7 : progress < 82 ? 3 : 1;
      setBulkProgress(Math.min(progress, 94));
    }, 900);
  }

  function stopBulkProgress(finalValue = 100) {
    window.clearInterval(bulkProgressTimer);
    bulkProgressTimer = null;
    if (bulkProductsProgressBar) {
      bulkProductsProgressBar.style.transition = 'none';
      setBulkProgress(finalValue);
      // restore transition after the instant snap
      requestAnimationFrame(() => {
        bulkProductsProgressBar.style.transition = '';
      });
    } else {
      setBulkProgress(finalValue);
    }
  }

  function setBulkStatus(message, type = '') {
    if (!bulkProductsStatus) return;
    bulkProductsStatus.textContent = message;
    bulkProductsStatus.classList.remove('success', 'error');
    if (type) {
      bulkProductsStatus.classList.add(type);
    }
  }

  function updateBulkAttemptUi(payload = {}) {
    const limit = Number(bulkProductsPanel?.dataset.attemptLimit || 3);
    const used = Number(payload.attempts_used ?? bulkProductsPanel?.dataset.attemptsUsed ?? 0);
    const disabled = Boolean(payload.disabled || used >= limit);

    if (bulkProductsPanel) {
      bulkProductsPanel.dataset.attemptsUsed = String(used);
    }
    if (bulkProductsAttempts) {
      bulkProductsAttempts.textContent = `${used}/${limit} used`;
    }
    if (bulkProductsSubmit) {
      bulkProductsSubmit.disabled = disabled;
    }
    if (bulkProductsFile) {
      bulkProductsFile.disabled = disabled;
    }
  }

  function openManagementHelp() {
    if (!managementHelpOverlay) return;
    managementHelpOverlay.classList.add('open');
    managementHelpOverlay.setAttribute('aria-hidden', 'false');
  }

  function closeManagementHelp() {
    if (!managementHelpOverlay) return;
    managementHelpOverlay.classList.remove('open');
    managementHelpOverlay.setAttribute('aria-hidden', 'true');
  }

  function populateCategoryDropdown() {
    if (!productCategorySelect) return;
    const grouped = {};
    categories.forEach(cat => {
      const key = cat.section_name || '';
      if (!grouped[key]) grouped[key] = [];
      grouped[key].push(cat);
    });
    let html = '';
    if (grouped['']) {
      html += grouped[''].map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('');
    }
    Object.keys(grouped).filter(k => k).forEach(sectionName => {
      html += `<optgroup label="${escapeHtml(sectionName)}">${grouped[sectionName].map(c => `<option value="${c.id}">${escapeHtml(c.name)}</option>`).join('')}</optgroup>`;
    });
    productCategorySelect.innerHTML = html;
  }

  function applyCategoryFilter() {
    const query = (categoriesSearchInput?.value || '').trim().toLowerCase();
    Array.from(categoriesTableBody?.querySelectorAll('tr') || []).forEach((row) => {
      const text = row.textContent.toLowerCase();
      row.hidden = Boolean(query) && !text.includes(query);
    });
  }

  function applyProductFilter() {
    const query = (productsSearchInput?.value || '').trim().toLowerCase();
    Array.from(productsGrid?.querySelectorAll('.product-card') || []).forEach((card) => {
      const text = card.textContent.toLowerCase();
      card.hidden = Boolean(query) && !text.includes(query);
    });
  }

  function applyDealFilter() {
    const query = (dealsSearchInput?.value || '').trim().toLowerCase();
    Array.from(dealsGrid?.querySelectorAll('.deal-card') || []).forEach((card) => {
      const text = card.textContent.toLowerCase();
      card.hidden = Boolean(query) && !text.includes(query);
    });
  }

  function renderSections() {
    const sectionsTableBody = document.querySelector('#sections-table tbody');
    if (!sectionsTableBody) return;
    sectionsTableBody.innerHTML = '';

    sections.forEach((section) => {
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${section.id}</td>
        <td contenteditable="true" class="editable-section" data-id="${section.id}">${escapeHtml(section.name)}</td>
        <td><span class="remove-btn" data-section-id="${section.id}">×</span></td>
      `;
      sectionsTableBody.appendChild(row);
    });

    document.querySelectorAll('.editable-section').forEach((cell) => {
      cell.addEventListener('blur', async () => {
        const id = cell.dataset.id;
        const name = cell.textContent.trim();
        if (!name) { alert('Section name cannot be empty'); return; }
        try {
          const res = await fetch(apiUrl(`/menu-sections/${id}`), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name })
          });
          if (!res.ok) throw new Error();
        } catch { alert('Failed to update section'); }
      });
    });

    document.querySelectorAll('#sections-table .remove-btn').forEach((button) => {
      button.addEventListener('click', async () => {
        if (!confirm('Delete this section? Categories under it will become ungrouped.')) return;
        try {
          const res = await fetch(apiUrl(`/menu-sections/${button.dataset.sectionId}`), { method: 'DELETE' });
          if (!res.ok) throw new Error();
          await fetchData();
        } catch { alert('Failed to delete section'); }
      });
    });

    const newCatSectionSelect = document.querySelector('#new-category-section');
    if (newCatSectionSelect) {
      newCatSectionSelect.innerHTML = '<option value="">— No Section —</option>' +
        sections.map(s => `<option value="${s.id}">${escapeHtml(s.name)}</option>`).join('');
    }
  }

  function renderCategories() {
    if (!categoriesTableBody) return;
    categoriesTableBody.innerHTML = '';

    categories.forEach((category) => {
      const sectionOptions = `<option value="">— No Section —</option>` +
        sections.map(s => `<option value="${s.id}" ${String(s.id) === String(category.section_id) ? 'selected' : ''}>${escapeHtml(s.name)}</option>`).join('');
      const row = document.createElement('tr');
      row.innerHTML = `
        <td>${category.id}</td>
        <td contenteditable="true" class="editable-cat" data-id="${category.id}">${escapeHtml(category.name)}</td>
        <td>
          <select class="cat-section-select" data-id="${category.id}" style="font-size:0.82rem;padding:0.3rem 0.5rem;border-radius:8px;border:1px solid rgba(148,163,184,0.3);">
            ${sectionOptions}
          </select>
        </td>
        <td><span class="remove-btn" data-id="${category.id}">×</span></td>
      `;
      categoriesTableBody.appendChild(row);
    });

    document.querySelectorAll('.editable-cat').forEach((cell) => {
      cell.addEventListener('blur', async () => {
        const id = cell.dataset.id;
        const name = cell.textContent.trim();
        if (!name) { alert('Category name cannot be empty'); return; }
        const row = cell.closest('tr');
        const sectionSelect = row?.querySelector('.cat-section-select');
        const section_id = sectionSelect ? (sectionSelect.value || null) : undefined;
        const body = { name };
        if (section_id !== undefined) body.section_id = section_id;
        try {
          const response = await fetch(apiUrl(`/categories/${id}`), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
          });
          if (!response.ok) throw new Error();
        } catch { alert('Failed to update category'); }
      });
    });

    document.querySelectorAll('.cat-section-select').forEach((select) => {
      select.addEventListener('change', async () => {
        const id = select.dataset.id;
        const row = select.closest('tr');
        const nameCell = row?.querySelector('.editable-cat');
        const name = nameCell ? nameCell.textContent.trim() : '';
        if (!name) return;
        try {
          const response = await fetch(apiUrl(`/categories/${id}`), {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name, section_id: select.value || null })
          });
          if (!response.ok) throw new Error();
          await fetchData();
        } catch { alert('Failed to update category section'); }
      });
    });

    document.querySelectorAll('#categories-table .remove-btn').forEach((button) => {
      button.addEventListener('click', async () => {
        if (!confirm('Delete this category?')) return;
        try {
          const response = await fetch(apiUrl(`/categories/${button.dataset.id}`), { method: 'DELETE' });
          if (!response.ok) throw new Error();
          await fetchData();
        } catch { alert('Failed to delete category'); }
      });
    });

    applyCategoryFilter();
    renderSections();
  }

  function renderRankingEditor(product) {
    const ranks = getProductRanks(product);
    if (!ranks.length) {
      return `
        <div class="field-group">
          <label class="field-label">Price</label>
          <input class="product-price-input" type="number" step="0.01" value="${Number(product.price || 0).toFixed(2)}">
        </div>
      `;
    }

    return `
      <div class="field-group full-width">
        <label class="field-label">Ranking</label>
        <div class="ranking-grid product-ranking-grid">
          ${ranks.map((rankItem, index) => {
      const rank = rankItem || {};
      return `
              <div class="rank-row">
                <input class="product-rank-name" data-rank-index="${index + 1}" type="text" placeholder="Rank ${index + 1} name" value="${escapeHtml(rank.name || '')}">
                <input class="product-rank-price" data-rank-index="${index + 1}" type="number" step="0.01" placeholder="Price" value="${rank.price != null ? escapeHtml(Number(rank.price).toFixed(2)) : ''}">
              </div>
            `;
    }).join('')}
        </div>
      </div>
    `;
  }

  function renderProducts() {
    if (!productsGrid) return;

    productsGrid.innerHTML = '';
    productsEmpty.hidden = products.length !== 0;

    products.forEach((product) => {
      const card = document.createElement('div');
      card.className = 'product-card';
      card.innerHTML = `
        <div class="product-id">#${product.id}</div>
        <div class="card-image-shell">
          ${product.image_path ? `<img src="${escapeHtml(product.image_path)}" class="product-image" alt="${escapeHtml(product.title)}">` : `<div class="product-image"></div>`}
          <input class="image-edit-input product-image-update-input" data-id="${product.id}" type="file" accept="image/*">
          <button class="image-edit-trigger product-image-edit-trigger" type="button" aria-label="Change product image">+</button>
        </div>
        <div class="product-body">
          <div class="field-group">
            <label class="field-label">Title</label>
            <input class="product-title-input" data-id="${product.id}" type="text" value="${escapeHtml(product.title)}">
          </div>
          <div class="field-group">
            <label class="field-label">Description</label>
            <textarea class="product-desc-input" data-id="${product.id}">${escapeHtml(product.description)}</textarea>
          </div>
          ${renderRankingEditor(product)}
          <select class="product-category editable-prod-cat" data-id="${product.id}">
            ${categories.map(category => `
              <option value="${category.id}" ${category.id === product.category_id ? 'selected' : ''}>${escapeHtml(category.name)}</option>
            `).join('')}
          </select>
          <div class="product-actions">
            <div></div>
            <button class="delete-btn" data-id="${product.id}">×</button>
          </div>
        </div>
      `;
      productsGrid.appendChild(card);
    });

    productsGrid.querySelectorAll('.product-title-input, .product-desc-input, .product-price-input, .product-rank-name, .product-rank-price').forEach((element) => {
      element.addEventListener('blur', async () => {
        const card = element.closest('.product-card');
        const id = card?.querySelector('.product-title-input')?.dataset.id;
        try {
          await updateProduct(card, id);
          await fetchData();
        } catch {
          alert('Failed to update product');
        }
      });
    });

    productsGrid.querySelectorAll('.editable-prod-cat').forEach((select) => {
      select.addEventListener('change', async () => {
        const card = select.closest('.product-card');
        const id = select.dataset.id;
        try {
          await updateProduct(card, id);
          await fetchData();
        } catch {
          alert('Failed to update product');
        }
      });
    });

    productsGrid.querySelectorAll('.delete-btn').forEach((button) => {
      button.addEventListener('click', async () => {
        if (!confirm('Delete this product?')) return;

        try {
          const response = await fetch(apiUrl(`/products/${button.dataset.id}`), {
            method: 'DELETE'
          });

          if (!response.ok) throw new Error();
          await fetchData();
        } catch {
          alert('Failed to delete product');
        }
      });
    });

    productsGrid.querySelectorAll('.product-image-edit-trigger').forEach((button) => {
      button.addEventListener('click', () => {
        button.closest('.card-image-shell')?.querySelector('.product-image-update-input')?.click();
      });
    });

    productsGrid.querySelectorAll('.product-image-update-input').forEach((input) => {
      input.addEventListener('change', async () => {
        const file = input.files?.[0];
        if (!file) return;
        const card = input.closest('.product-card');
        const id = input.dataset.id;
        try {
          await updateProduct(card, id, file);
          await fetchData();
        } catch {
          alert('Failed to update product image');
        } finally {
          input.value = '';
        }
      });
    });

    applyProductFilter();
  }

  async function updateProduct(card, id, imageFile = null) {
    const product = getProductById(id);
    if (!product) throw new Error('Product not found');

    const formData = new FormData();
    formData.append('title', card.querySelector('.product-title-input').value.trim());
    formData.append('description', card.querySelector('.product-desc-input').value.trim());
    formData.append('category_id', card.querySelector('.editable-prod-cat').value);

    const rankNameInputs = Array.from(card.querySelectorAll('.product-rank-name'));
    const rankPriceInputs = Array.from(card.querySelectorAll('.product-rank-price'));
    const hasRanking = rankNameInputs.length > 0;

    if (hasRanking) {
      formData.append('has_ranking', '1');
      rankNameInputs.forEach((input, index) => {
        formData.append(`rank${index + 1}_name`, input.value.trim());
      });
      rankPriceInputs.forEach((input, index) => {
        formData.append(`rank${index + 1}_price`, input.value.trim());
      });
      formData.append('price', card.querySelector('.product-rank-price')?.value.trim() || String(product.price ?? 0));
    } else {
      formData.append('price', card.querySelector('.product-price-input').value.trim());
    }

    if (imageFile) {
      formData.append('image', imageFile);
    }

    const response = await fetch(apiUrl(`/products/${id}`), {
      method: 'PUT',
      body: formData
    });

    if (!response.ok) throw new Error();
  }

  function applyRankOptionsToSelect(rankSelect, selectedValue, selectedRankName) {
    if (!rankSelect) return;

    if (selectedValue.startsWith('section:')) {
      const sectionId = selectedValue.split(':')[1];
      const sectionCatIds = categories
        .filter(c => String(c.section_id) === String(sectionId))
        .map(c => c.id);
      const sectionProducts = products.filter(p => sectionCatIds.includes(p.category_id));
      const rankNames = getUniqueRankNames(sectionProducts);
      if (rankNames.length) {
        rankSelect.disabled = false;
        rankSelect.innerHTML = '<option value="">Any rank</option>' +
          rankNames.map(name => `<option value="${escapeHtml(name)}" ${name === selectedRankName ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('');
      } else {
        rankSelect.innerHTML = '<option value="">No variants</option>';
        rankSelect.disabled = true;
      }
      return;
    }

    if (selectedValue.startsWith('category:')) {
      const categoryId = selectedValue.split(':')[1];
      const categoryProducts = products.filter(p => String(p.category_id) === String(categoryId));
      const rankNames = getUniqueRankNames(categoryProducts);
      if (rankNames.length) {
        rankSelect.disabled = false;
        rankSelect.innerHTML = '<option value="">Any rank</option>' +
          rankNames.map(name => `<option value="${escapeHtml(name)}" ${name === selectedRankName ? 'selected' : ''}>${escapeHtml(name)}</option>`).join('');
      } else {
        rankSelect.innerHTML = '<option value="">No variants</option>';
        rankSelect.disabled = true;
      }
      return;
    }

    const product = getProductById(selectedValue);
    const ranks = getProductRanks(product);
    if (!product || !ranks.length) {
      rankSelect.innerHTML = '<option value="">Standard price</option>';
      rankSelect.disabled = true;
      return;
    }
    rankSelect.disabled = false;
    rankSelect.innerHTML = ranks.map(rank => `
      <option value="${escapeHtml(rank.name)}" ${rank.name === selectedRankName ? 'selected' : ''}>
        ${escapeHtml(rank.name)} ($${Number(rank.price).toFixed(2)})
      </option>
    `).join('');
  }

  function updateBundleRowRankOptions(row, selectedRankName = '') {
    const productSelect = row.querySelector('.bundle-product');
    const rankSelect = row.querySelector('.bundle-rank');
    if (!productSelect || !rankSelect) return;
    applyRankOptionsToSelect(rankSelect, productSelect.value || '', selectedRankName);
  }

  function validateBundleOrOptions(bundleItems) {
    for (const item of bundleItems) {
      if (!Array.isArray(item.or_options) || item.or_options.length === 0) continue;
      const allOptions = [item, ...item.or_options];
      const ranks = allOptions.map(o => (o.rank_name || '').trim().toLowerCase());
      const allSame = ranks.every(r => r === ranks[0]);
      if (!allSame) {
        return `All OR alternatives in a bundle row must use the same variant. Found mismatched variants: ${allOptions.map(o => `"${o.product_title}${o.rank_name ? ` (${o.rank_name})` : ' (no variant)'}`).join(' OR ')}`;
      }
    }
    return null;
  }

  function buildOrOptionsFromRow(bundleRow) {
    return Array.from(bundleRow.querySelectorAll('.bundle-or-row')).map(orRow => {
      const productSel = orRow.querySelector('.bundle-or-product');
      const rankSel = orRow.querySelector('.bundle-or-rank');
      const selectedValue = productSel?.value || '';

      if (selectedValue.startsWith('section:')) {
        const sectionId = selectedValue.split(':')[1];
        const section = getSectionById(sectionId);
        if (!section) return null;
        const rankName = rankSel?.disabled ? null : (rankSel?.value || null);
        return { product_id: null, category_id: null, section_id: section.id, product_title: `Any ${section.name}`, rank_name: rankName || null, rank_price: null };
      }

      const categoryMatch = selectedValue.startsWith('category:') ? selectedValue.split(':')[1] : null;
      const category = categoryMatch ? getCategoryById(categoryMatch) : null;
      if (category) {
        const rankName = rankSel?.disabled ? null : (rankSel?.value || null);
        return { product_id: null, category_id: category.id, product_title: `Any ${category.name}`, rank_name: rankName || null, rank_price: null };
      }

      const product = getProductById(selectedValue);
      if (!product) return null;
      const selectedRankName = rankSel?.disabled ? null : (rankSel?.value || null);
      const selectedRank = selectedRankName
        ? getProductRanks(product).find(r => r.name === selectedRankName) || null
        : null;
      return { product_id: product.id, product_title: product.title, rank_name: selectedRank?.name || null, rank_price: selectedRank?.price ?? null };
    }).filter(Boolean);
  }

  function addOrRow(parentBundleRow, orOption = {}, summaryScope) {
    const orRowsContainer = parentBundleRow.querySelector('.bundle-or-rows');
    if (!orRowsContainer) return;

    let orSelectedValue = '';
    if (orOption.section_id) orSelectedValue = `section:${orOption.section_id}`;
    else if (orOption.product_id) orSelectedValue = String(orOption.product_id);
    else if (orOption.category_id) orSelectedValue = `category:${orOption.category_id}`;

    const sectionOptgroup = sections.length
      ? `<optgroup label="Any from Section">${sections.map(s => `<option value="section:${s.id}" ${`section:${s.id}` === orSelectedValue ? 'selected' : ''}>Any ${escapeHtml(s.name)}</option>`).join('')}</optgroup>`
      : '';
    const categoryOptgroup = categories.length
      ? `<optgroup label="Any from Category">${categories.map(c => `<option value="category:${c.id}" ${`category:${c.id}` === orSelectedValue ? 'selected' : ''}>Any ${escapeHtml(c.name)}</option>`).join('')}</optgroup>`
      : '';
    const productOptgroup = products.length
      ? `<optgroup label="Specific Product">${products.map(p => `<option value="${p.id}" ${String(p.id) === orSelectedValue ? 'selected' : ''}>${escapeHtml(p.title)}</option>`).join('')}</optgroup>`
      : '';

    const orRow = document.createElement('div');
    orRow.className = 'bundle-or-row';
    orRow.innerHTML = `
      <span class="bundle-or-badge">OR</span>
      <select class="bundle-or-product">
        <option value="">Select product</option>
        ${sectionOptgroup}
        ${categoryOptgroup}
        ${productOptgroup}
      </select>
      <select class="bundle-or-rank"></select>
      <button class="bundle-remove bundle-or-remove" type="button" aria-label="Remove OR option">×</button>
    `;

    const refreshSummary = () => renderBundleSummary(summaryScope);
    const maybeQueueSave = () => {
      if (summaryScope && summaryScope !== dealForm && summaryScope.dataset?.id) {
        queueDealSave(summaryScope);
      }
    };

    orRow.querySelector('.bundle-or-product')?.addEventListener('change', () => {
      applyRankOptionsToSelect(orRow.querySelector('.bundle-or-rank'), orRow.querySelector('.bundle-or-product').value || '', '');
      refreshSummary();
      maybeQueueSave();
    });

    orRow.querySelector('.bundle-or-rank')?.addEventListener('change', () => {
      refreshSummary();
      maybeQueueSave();
    });

    orRow.querySelector('.bundle-or-remove')?.addEventListener('click', () => {
      orRow.remove();
      refreshSummary();
      maybeQueueSave();
    });

    applyRankOptionsToSelect(orRow.querySelector('.bundle-or-rank'), orSelectedValue, orOption.rank_name || '');
    orRowsContainer.appendChild(orRow);
  }

  function buildBundleItemsFromScope(scope) {
    return Array.from(scope.querySelectorAll('.bundle-row'))
      .map((row) => {
        const productSelect = row.querySelector('.bundle-product');
        const rankSelect = row.querySelector('.bundle-rank');
        const quantityInput = row.querySelector('.bundle-qty');
        const selectedValue = productSelect?.value || '';
        const quantity = Number(quantityInput?.value || 0);

        if (selectedValue.startsWith('section:')) {
          const sectionId = selectedValue.split(':')[1];
          const section = getSectionById(sectionId);
          if (!section || quantity <= 0) return null;
          const sectionRankName = rankSelect?.disabled ? null : (rankSelect?.value || null);
          return {
            product_id: null,
            category_id: null,
            section_id: section.id,
            product_title: `Any ${section.name}`,
            quantity,
            rank_name: sectionRankName || null,
            rank_price: null,
            or_options: buildOrOptionsFromRow(row)
          };
        }

        const categoryMatch = selectedValue.startsWith('category:') ? selectedValue.split(':')[1] : null;
        const category = categoryMatch ? getCategoryById(categoryMatch) : null;
        const product = getProductById(selectedValue);

        if ((!product && !category) || quantity <= 0) return null;

        if (category) {
          const categoryRankName = rankSelect?.disabled ? null : (rankSelect?.value || null);
          return {
            product_id: null,
            category_id: category.id,
            product_title: `Any ${category.name}`,
            quantity,
            rank_name: categoryRankName || null,
            rank_price: null,
            or_options: buildOrOptionsFromRow(row)
          };
        }

        const selectedRankName = rankSelect?.disabled ? null : (rankSelect.value || null);
        const selectedRank = selectedRankName
          ? getProductRanks(product).find(rank => rank.name === selectedRankName) || null
          : null;

        return {
          product_id: product.id,
          product_title: product.title,
          quantity,
          rank_name: selectedRank?.name || null,
          rank_price: selectedRank?.price ?? null,
          or_options: buildOrOptionsFromRow(row)
        };
      })
      .filter(Boolean);
  }

  function renderBundleSummary(scope = dealForm || document) {
    const target = scope.querySelector('.bundle-summary') || bundleSummary;
    if (!target) return;

    const items = buildBundleItemsFromScope(scope);
    target.innerHTML = '';

    if (!items.length) {
      target.innerHTML = '<span class="bundle-pill">No products selected yet</span>';
      return;
    }

    items.forEach((item) => {
      const pill = document.createElement('span');
      pill.className = 'bundle-pill';
      const rankText = item.rank_name ? ` (${item.rank_name})` : '';
      let pillText = `${item.quantity} x ${item.product_title}${rankText}`;
      if (Array.isArray(item.or_options) && item.or_options.length) {
        const orTexts = item.or_options.map(o => `${o.product_title}${o.rank_name ? ` (${o.rank_name})` : ''}`);
        pillText += ' OR ' + orTexts.join(' OR ');
      }
      pill.textContent = pillText;
      target.appendChild(pill);
    });
  }

  function createBundleRow(item = {}, summaryScope = dealForm || document) {
    const row = document.createElement('div');
    row.className = 'bundle-row';

    const quantity = Number(item.quantity || 1);
    let selectedProductId = '';
    if (item.section_id) {
      selectedProductId = `section:${item.section_id}`;
    } else if (item.product_id) {
      selectedProductId = String(item.product_id);
    } else if (item.category_id) {
      selectedProductId = `category:${item.category_id}`;
    }

    const sectionOptgroup = sections.length
      ? `<optgroup label="Any from Section">${sections.map(s => `<option value="section:${s.id}" ${`section:${s.id}` === selectedProductId ? 'selected' : ''}>Any ${escapeHtml(s.name)}</option>`).join('')}</optgroup>`
      : '';
    const categoryOptgroup = categories.length
      ? `<optgroup label="Any from Category">${categories.map(c => `<option value="category:${c.id}" ${`category:${c.id}` === selectedProductId ? 'selected' : ''}>Any ${escapeHtml(c.name)}</option>`).join('')}</optgroup>`
      : '';
    const productOptgroup = products.length
      ? `<optgroup label="Specific Product">${products.map(p => `<option value="${p.id}" ${String(p.id) === selectedProductId ? 'selected' : ''}>${escapeHtml(p.title)}</option>`).join('')}</optgroup>`
      : '';

    row.innerHTML = `
      <div class="bundle-row-main">
        <input class="bundle-qty" type="number" min="1" step="1" value="${quantity}">
        <select class="bundle-product">
          <option value="">Select product</option>
          ${sectionOptgroup}
          ${categoryOptgroup}
          ${productOptgroup}
        </select>
        <select class="bundle-rank"></select>
        <button class="bundle-remove" type="button" aria-label="Remove product line">×</button>
      </div>
      <div class="bundle-or-section">
        <div class="bundle-or-rows"></div>
        <button class="bundle-add-or-btn" type="button">+ Add alternative</button>
      </div>
    `;

    const refreshSummary = () => renderBundleSummary(summaryScope);
    const maybeQueueSave = () => {
      if (summaryScope && summaryScope !== dealForm && summaryScope.dataset?.id) {
        queueDealSave(summaryScope);
      }
    };

    row.querySelector('.bundle-product')?.addEventListener('change', (event) => {
      updateBundleRowRankOptions(row);
      const product = getProductById(event.target.value);
      if (!product?.has_ranking) {
        row.querySelector('.bundle-rank').value = '';
      }
      refreshSummary();
      maybeQueueSave();
    });

    row.querySelector('.bundle-rank')?.addEventListener('change', () => {
      refreshSummary();
      maybeQueueSave();
    });
    row.querySelector('.bundle-qty')?.addEventListener('input', () => {
      refreshSummary();
      maybeQueueSave();
    });

    row.querySelector('.bundle-remove')?.addEventListener('click', () => {
      const list = row.parentElement;
      row.remove();

      if (!list?.children.length) {
        list?.appendChild(createBundleRow({}, summaryScope));
      }

      refreshSummary();
      maybeQueueSave();
    });

    row.querySelector('.bundle-add-or-btn')?.addEventListener('click', () => {
      addOrRow(row, {}, summaryScope);
      refreshSummary();
      maybeQueueSave();
    });

    (item.or_options || []).forEach(orOpt => addOrRow(row, orOpt, summaryScope));

    updateBundleRowRankOptions(row, item.rank_name || '');
    return row;
  }

  function initBundleBuilder(initialItems = []) {
    if (!bundleList) return;
    bundleList.innerHTML = '';

    const items = initialItems.length ? initialItems : [{}];
    items.forEach(item => bundleList.appendChild(createBundleRow(item, dealForm || document)));
    renderBundleSummary(dealForm || document);
  }

  async function loadDeals() {
    const response = await fetch(apiUrl('/deals'));
    const deals = await response.json();

    dealsGrid.innerHTML = '';
    dealsEmpty.hidden = deals.length !== 0;

    deals.forEach((deal) => {
      const bundleItems = parseDealBundleItems(deal);
      const card = document.createElement('div');
      card.className = 'deal-card';
      card.dataset.id = deal.id;
      card.innerHTML = `
        <div class="deal-card-head">
          <span class="deal-type-badge">${deal.type === 'hot' ? 'Hot Deal' : 'Deal'}</span>
          <button class="delete-btn deal-delete" data-id="${deal.id}">×</button>
        </div>
        <div class="card-image-shell">
          ${deal.image_path ? `<img src="${escapeHtml(deal.image_path)}" class="deal-card-image" alt="${escapeHtml(deal.title)}">` : '<div class="deal-card-image"></div>'}
          <input class="image-edit-input deal-image-update-input" data-id="${deal.id}" type="file" accept="image/*">
          <button class="image-edit-trigger deal-image-edit-trigger" type="button" aria-label="Change deal image">+</button>
        </div>
        <div class="field-group">
          <label class="field-label">Title</label>
          <input class="deal-title-input" type="text" value="${escapeHtml(deal.title)}">
        </div>
        <div class="field-group">
          <label class="field-label">Description</label>
          <textarea class="deal-description-input">${escapeHtml(deal.description || '')}</textarea>
        </div>
        <div class="field-group">
          <label class="field-label">Price</label>
          <input class="deal-card-price deal-price-input" type="number" step="0.01" value="${escapeHtml(deal.price)}">
        </div>
        <div class="field-group">
          <label class="field-label">Deal Type</label>
          <select class="deal-type-input">
            <option value="deal" ${deal.type === 'deal' ? 'selected' : ''}>Deal</option>
            <option value="hot" ${deal.type === 'hot' ? 'selected' : ''}>Hot Deal</option>
          </select>
        </div>
        <div class="field-group">
          <label class="field-label">Products in deal</label>
          <div class="bundle-list deal-edit-bundle-list"></div>
        </div>
        <button class="btn ghost-btn deal-add-product-row" type="button">Add Product Form</button>
        <div class="field-group">
          <label class="field-label">Bundle Preview</label>
          <div class="bundle-summary"></div>
        </div>
        <button class="btn btn-primary deal-save" type="button">Save Deal</button>
      `;

      dealsGrid.appendChild(card);

      const list = card.querySelector('.deal-edit-bundle-list');
      const items = bundleItems.length ? bundleItems : [{}];
      items.forEach(item => list.appendChild(createBundleRow(item, card)));
      renderBundleSummary(card);
    });

    dealsGrid.querySelectorAll('.deal-add-product-row').forEach((button) => {
      button.addEventListener('click', () => {
        const card = button.closest('.deal-card');
        card.querySelector('.deal-edit-bundle-list')?.appendChild(createBundleRow({}, card));
        renderBundleSummary(card);
        queueDealSave(card);
      });
    });

    dealsGrid.querySelectorAll('.deal-save').forEach((button) => {
      button.addEventListener('click', async () => {
        const card = button.closest('.deal-card');
        await saveDealCard(card);
      });
    });

    dealsGrid.querySelectorAll('.deal-title-input, .deal-description-input, .deal-price-input').forEach((input) => {
      input.addEventListener('blur', async () => {
        const card = input.closest('.deal-card');
        await saveDealCard(card);
      });
    });

    dealsGrid.querySelectorAll('.deal-type-input').forEach((select) => {
      select.addEventListener('change', async () => {
        const card = select.closest('.deal-card');
        await saveDealCard(card);
      });
    });

    dealsGrid.querySelectorAll('.deal-delete').forEach((button) => {
      button.addEventListener('click', async () => {
        if (!confirm('Are you sure you want to delete this deal?')) return;

        try {
          const response = await fetch(apiUrl(`/delete_deal/${button.dataset.id}`), { method: 'POST' });
          if (!response.ok) throw new Error();
          await loadDeals();
        } catch (error) {
          console.error(error);
          alert('Failed to delete deal');
        }
      });
    });

    dealsGrid.querySelectorAll('.deal-image-edit-trigger').forEach((button) => {
      button.addEventListener('click', () => {
        button.closest('.card-image-shell')?.querySelector('.deal-image-update-input')?.click();
      });
    });

    dealsGrid.querySelectorAll('.deal-image-update-input').forEach((input) => {
      input.addEventListener('change', async () => {
        const file = input.files?.[0];
        if (!file) return;
        const card = input.closest('.deal-card');
        try {
          await saveDealCard(card, file);
          await loadDeals();
        } catch {
          alert('Failed to update deal image');
        } finally {
          input.value = '';
        }
      });
    });

    applyDealFilter();
  }

  function queueDealSave(card) {
    const cardId = card?.dataset.id;
    if (!cardId) return;

    clearTimeout(pendingDealSaves.get(cardId));
    const timeoutId = setTimeout(() => {
      saveDealCard(card).catch((error) => {
        console.error(error);
        alert('Failed to update deal');
      });
    }, 250);

    pendingDealSaves.set(cardId, timeoutId);
  }

  async function saveDealCard(card, imageFile = null) {
    const id = card?.dataset.id;
    if (!id) return;

    const bundleItems = buildBundleItemsFromScope(card);
    const validationError = validateBundleOrOptions(bundleItems);
    if (validationError) { alert(validationError); return; }

    let response;

    if (imageFile) {
      const formData = new FormData();
      formData.append('title', card.querySelector('.deal-title-input').value.trim());
      formData.append('description', card.querySelector('.deal-description-input').value.trim());
      formData.append('price', card.querySelector('.deal-price-input').value.trim());
      formData.append('type', card.querySelector('.deal-type-input').value);
      formData.append('bundle_items', JSON.stringify(bundleItems));
      formData.append('products', buildDealProductsColumn(bundleItems));
      formData.append('image', imageFile);

      response = await fetch(apiUrl(`/update_deal/${id}`), {
        method: 'POST',
        body: formData
      });
    } else {
      response = await fetch(apiUrl(`/update_deal/${id}`), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: card.querySelector('.deal-title-input').value.trim(),
          description: card.querySelector('.deal-description-input').value.trim(),
          price: card.querySelector('.deal-price-input').value.trim(),
          type: card.querySelector('.deal-type-input').value,
          bundle_items: bundleItems,
          products: buildDealProductsColumn(bundleItems)
        })
      });
    }

    if (!response.ok) {
      throw new Error('Failed to update deal');
    }
  }

  document.querySelector('#add-section-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const name = document.querySelector('#new-section-name')?.value.trim();
    if (!name) return;
    try {
      const res = await fetch(apiUrl('/menu-sections'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name })
      });
      if (!res.ok) throw new Error();
      event.target.reset();
      await fetchData();
    } catch { alert('Failed to add section'); }
  });

  addCategoryForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const name = document.querySelector('#new-category-name')?.value.trim();
    const sectionId = document.querySelector('#new-category-section')?.value || null;
    if (!name) return;

    try {
      const response = await fetch(apiUrl('/categories'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, section_id: sectionId })
      });

      if (!response.ok) throw new Error();
      event.target.reset();
      await fetchData();
    } catch {
      alert('Failed to add category');
    }
  });

  addProductForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const formData = new FormData(event.target);

    if (productRankingToggle?.checked) {
      const rank1Price = formData.get('rank1_price');
      formData.set('price', rank1Price || '0');
    }

    try {
      const response = await fetch(apiUrl('/products'), {
        method: 'POST',
        body: formData
      });

      if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.error || 'Failed to add product');
      }

      event.target.reset();
      toggleRankingFields();
      document.querySelector('#product-image-name').textContent = 'Upload product image';
      await fetchData();
    } catch (error) {
      alert(error.message || 'Failed to add product');
    }
  });

  bulkProductsForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const file = bulkProductsFile?.files?.[0];
    if (!file) {
      setBulkStatus('Choose a catalogue file first.', 'error');
      return;
    }

    const maxFileSize = Number(bulkProductsPanel?.dataset.maxFileSizeBytes || 12 * 1024 * 1024);
    if (file.size > maxFileSize) {
      const maxMb = Math.max(1, Math.round(maxFileSize / (1024 * 1024)));
      setBulkStatus(`That file is too large. Please choose an image under ${maxMb}MB.`, 'error');
      return;
    }

    const formData = new FormData();
    formData.append('catalogue', file);

    bulkProductsSubmit.disabled = true;
    bulkProductsFile.disabled = true;
    setBulkStatus('Reading catalogue and extracting products...');
    startBulkProgress();

    let jobId = null;

    try {
      const response = await fetch(apiUrl('/bulk-products-upload'), {
        method: 'POST',
        body: formData
      });
      const payload = await response.json().catch(() => ({}));

      if (!response.ok) {
        updateBulkAttemptUi(payload);
        const friendlyMessage = payload.error || (response.status === 413
          ? `That file is too large. Please choose an image under ${Math.max(1, Math.round(maxFileSize / (1024 * 1024)))}MB.`
          : 'Bulk product upload failed');
        throw new Error(friendlyMessage);
      }

      if (payload.status === 'processing' && payload.job_id) {
        jobId = payload.job_id;
        await pollBulkUpload(jobId);
      } else if (payload.success) {
        // synchronous success (fallback)
        onBulkSuccess(payload);
      } else {
        updateBulkAttemptUi(payload);
        throw new Error(payload.error || 'Bulk product upload failed');
      }
    } catch (error) {
      stopBulkProgress(0);
      setBulkStatus(error.message || 'Bulk product upload failed', 'error');
      updateBulkAttemptUi();
      const limit = Number(bulkProductsPanel?.dataset.attemptLimit || 3);
      const used = Number(bulkProductsPanel?.dataset.attemptsUsed || 0);
      if (used < limit) {
        bulkProductsSubmit.disabled = false;
        bulkProductsFile.disabled = false;
      }
    }
  });

  async function pollBulkUpload(jobId) {
    const maxWait = 240000;
    const interval = 3000;
    let elapsed = 0;

    while (elapsed < maxWait) {
      await new Promise((resolve) => setTimeout(resolve, interval));
      elapsed += interval;

      try {
        const res = await fetch(apiUrl(`/bulk-products-status/${jobId}`));
        const data = await res.json().catch(() => ({}));

        if (data.status === 'done' && data.success) {
          onBulkSuccess(data);
          return;
        }

        if (data.status === 'error') {
          updateBulkAttemptUi(data);
          throw new Error(data.error || 'Bulk product upload failed');
        }
        // still processing — loop continues
      } catch (err) {
        stopBulkProgress(0);
        setBulkStatus(err.message || 'Bulk product upload failed', 'error');
        updateBulkAttemptUi();
        const limit = Number(bulkProductsPanel?.dataset.attemptLimit || 3);
        const used = Number(bulkProductsPanel?.dataset.attemptsUsed || 0);
        if (used < limit) {
          bulkProductsSubmit.disabled = false;
          bulkProductsFile.disabled = false;
        }
        return;
      }
    }

    // timed out on the client side
    stopBulkProgress(0);
    setBulkStatus('Import is taking longer than expected. Refresh the page to check if products were imported.', 'error');
    bulkProductsSubmit.disabled = false;
    bulkProductsFile.disabled = false;
  }

  function onBulkSuccess(payload) {
    stopBulkProgress(100);
    updateBulkAttemptUi(payload);
    setBulkStatus(
      `Imported ${payload.inserted_products} products across ${payload.touched_categories} categories. ${payload.attempts_remaining} attempt${payload.attempts_remaining === 1 ? '' : 's'} remaining.`,
      'success'
    );
    if (bulkProductsForm) bulkProductsForm.reset();
    if (bulkProductsFileName) bulkProductsFileName.textContent = 'Upload catalogue or menu';
    const limit = Number(bulkProductsPanel?.dataset.attemptLimit || 3);
    const used = Number(bulkProductsPanel?.dataset.attemptsUsed || 0);
    if (used < limit) {
      bulkProductsSubmit.disabled = false;
      bulkProductsFile.disabled = false;
    }
    fetchData().catch(() => { });
  }


  dealForm?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const formData = new FormData(event.target);
    const bundleItems = buildBundleItemsFromScope(bundleList || dealForm || document);
    const validationError = validateBundleOrOptions(bundleItems);
    if (validationError) { alert(validationError); return; }
    formData.set('bundle_items', JSON.stringify(bundleItems));
    formData.set('products', buildDealProductsColumn(bundleItems));

    try {
      const response = await fetch(apiUrl('/add_deal'), {
        method: 'POST',
        body: formData
      });

      if (!response.ok) throw new Error();
      event.target.reset();
      document.querySelector('#deal-image-name').textContent = 'Upload deal image';
      initBundleBuilder();
      await loadDeals();
    } catch (error) {
      console.error(error);
      alert('Failed to add deal');
    }
  });

  addDealProductRowButton?.addEventListener('click', () => {
    bundleList?.appendChild(createBundleRow({}, dealForm || document));
    renderBundleSummary(dealForm || document);
  });

  productRankingToggle?.addEventListener('change', toggleRankingFields);
  categoriesSearchInput?.addEventListener('input', applyCategoryFilter);
  productsSearchInput?.addEventListener('input', applyProductFilter);
  dealsSearchInput?.addEventListener('input', applyDealFilter);
  managementInfoButton?.addEventListener('click', openManagementHelp);
  managementHelpClose?.addEventListener('click', closeManagementHelp);
  managementHelpOverlay?.addEventListener('click', (event) => {
    if (event.target === managementHelpOverlay) {
      closeManagementHelp();
    }
  });
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape' && managementHelpOverlay?.classList.contains('open')) {
      closeManagementHelp();
    }
  });

  async function fetchData() {
    try {
      const [categoriesResponse, productsResponse, sectionsResponse] = await Promise.all([
        fetch(apiUrl('/categories')),
        fetch(apiUrl('/products')),
        fetch(apiUrl('/menu-sections'))
      ]);

      categories = await categoriesResponse.json();
      products = await productsResponse.json();
      sections = await sectionsResponse.json();

      renderCategories();
      populateCategoryDropdown();
      renderProducts();
      initBundleBuilder(buildBundleItemsFromScope(bundleList || dealForm || document));
      await loadDeals();
    } catch (error) {
      console.error(error);
      alert('Failed to fetch management data');
    }
  }

  bindUploadLabel('#product-image', '#product-image-name', 'Upload product image');
  bindUploadLabel('#deal-image', '#deal-image-name', 'Upload deal image');
  bindUploadLabel('#bulk-products-file', '#bulk-products-file-name', 'Upload catalogue or menu');
  toggleRankingFields();
  updateBulkAttemptUi();
  fetchData();
});
