document.addEventListener("DOMContentLoaded", function () {
    const steps = document.querySelectorAll(".step");
    const nextBtns = document.querySelectorAll(".next");
    const backBtns = document.querySelectorAll(".back");
    const form = document.querySelector("form");
    const loadingScreen = document.getElementById("builderLoadingScreen");
    const uploadBox = document.getElementById("uploadBox");
    const logoInput = document.getElementById("logoInput");
    const preview = document.getElementById("logoPreview");
    const menuUploadBox = document.getElementById("menuUploadBox");
    const menuFileInput = document.getElementById("menuFileInput");
    const menuPreview = document.getElementById("menuPreview");
    const progressFill = document.querySelector(".progress-fill");
    const progressTriangle = document.querySelector(".progress-triangle");
    const previewBtn = document.getElementById("themePreviewBtn");
    const previewLayer = document.getElementById("themePreviewLayer");
    const loadingTitle = document.getElementById("builderLoadingTitle");
    const loadingText = document.getElementById("builderLoadingText") || loadingScreen?.querySelector("p");
    const loaderAnimation = document.getElementById("builderLoaderAnimation");
    const successIcon = document.getElementById("builderSuccessIcon");
    const errorIcon = document.getElementById("builderErrorIcon");
    const builderProgressBar = document.getElementById("builderProgressBar");
    const builderProgressText = document.getElementById("builderProgressText");
    const postBuildActions = document.getElementById("postBuildActions");
    const restartWebsiteBtn = document.getElementById("restartWebsiteBtn");
    const confirmWebsiteBtn = document.getElementById("confirmWebsiteBtn");
    const nameInput = document.getElementById("project_name");
    const addressSearchInput = document.getElementById("addressSearch");
    const addressHiddenInput = document.getElementById("address");
    const addressResults = document.getElementById("addressResults");
    const priceReceiptLines = document.getElementById("priceReceiptLines");
    const totalCostInput = document.getElementById("totalCostInput");

    const totalSteps = steps.length;
    const basePrice = 65;
    const onlineOrderingCard = document.querySelector('.module-card input[value="online_ordering_system"]')?.closest(".module-card");
    const dependentModuleCards = document.querySelectorAll(".module-dependent");

    let currentStep = 0;
    let total = basePrice;
    let currentSlug = null;
    let previewPort = null;
    let previewOpen = false;
    let nameAvailable = true;
    let nameCheckTimeout = null;
    let addressSearchTimeout = null;
    let buildProgressValue = 0;
    let buildProgressTimer = null;
    let menuFileName = null;
    let draftSaveTimeout = null;

    function setBuildProgress(value) {
        buildProgressValue = Math.max(0, Math.min(100, Math.round(value)));
        if (builderProgressBar) builderProgressBar.style.width = `${buildProgressValue}%`;
        if (builderProgressText) builderProgressText.textContent = `${buildProgressValue}%`;
    }

    function stopBuildProgress() {
        if (buildProgressTimer) {
            clearInterval(buildProgressTimer);
            buildProgressTimer = null;
        }
    }

    function animateBuildProgress(target, step, intervalMs) {
        stopBuildProgress();
        buildProgressTimer = setInterval(() => {
            if (buildProgressValue >= target) {
                stopBuildProgress();
                return;
            }
            setBuildProgress(Math.min(target, buildProgressValue + step));
        }, intervalMs);
    }

    function setBuilderScreen({
        title,
        text,
        status = "loading",
        showActions = false,
        confirmLabel = "Confirm",
        confirmMode = "dashboard",
        showRestart = true
    }) {
        if (loadingTitle && title) loadingTitle.textContent = title;
        if (loadingText && text) loadingText.textContent = text;
        if (loaderAnimation) loaderAnimation.style.display = status === "loading" ? "flex" : "none";
        if (successIcon) successIcon.style.display = status === "success" ? "grid" : "none";
        if (errorIcon) errorIcon.style.display = status === "error" ? "grid" : "none";
        if (status === "success") {
            stopBuildProgress();
            setBuildProgress(100);
        }
        if (status === "error") {
            stopBuildProgress();
        }
        if (postBuildActions) postBuildActions.style.display = showActions ? "flex" : "none";
        if (restartWebsiteBtn) restartWebsiteBtn.style.display = showRestart ? "" : "none";
        if (confirmWebsiteBtn) {
            confirmWebsiteBtn.textContent = confirmLabel;
            confirmWebsiteBtn.dataset.mode = confirmMode;
        }
    }

    async function finalizeCurrentProject() {
        if (!currentSlug) {
            throw new Error("Project not ready yet.");
        }

        setBuilderScreen({
            title: "Creating Your Website",
            text: "Generating visuals and content...",
            status: "loading",
            showActions: false
        });
        setBuildProgress(Math.max(buildProgressValue, 42));
        animateBuildProgress(94, 1, 850);

        const res = await fetch("/finalize-project", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ slug: currentSlug })
        });

        const data = await res.json();

        if (!data.success) {
            throw new Error(data.error || "Failed to finalize website");
        }

        const updates = [];
        if (data.generated_featured) updates.push("featured content");
        if (data.generated_hero) updates.push("hero image");

        setBuilderScreen({
            title: "Site Complete",
            text: updates.length
                ? `Saved ${updates.join(" and ")} to your project.`
                : "Your website is complete and everything is already ready.",
            status: "success",
            showActions: true,
            confirmLabel: "Confirm",
            confirmMode: "dashboard",
            showRestart: true
        });
    }

    function escapeHtml(text) {
        return String(text)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#39;");
    }

    function clearErrors() {
        document.querySelectorAll(".error-text").forEach(e => e.classList.remove("show"));
        document.querySelectorAll(".input-error").forEach(i => i.classList.remove("input-error"));
    }

    function validateStep() {
        const step = steps[currentStep];
        clearErrors();

        if (currentStep === 0) {
            const selected = step.querySelector(".option-card.selected");
            if (!selected) {
                document.getElementById("typeError")?.classList.add("show");
                return false;
            }
        }

        if (currentStep === 1) {
            if (!nameInput.value.trim()) {
                document.getElementById("nameError")?.classList.add("show");
                nameInput.classList.add("input-error");
                return false;
            }

            if (!nameAvailable) {
                document.getElementById("nameTakenError")?.classList.add("show");
                nameInput.classList.add("input-error");
                return false;
            }
        }

        if (currentStep === 2) {
            const slogan = document.getElementById("slogan");
            if (!slogan.value.trim()) {
                slogan.classList.add("input-error");
                document.getElementById("sloganError")?.classList.add("show");
                return false;
            }
        }

        if (currentStep === 3) {
            const description = document.getElementById("description");
            if (!description.value.trim()) {
                description.classList.add("input-error");
                document.getElementById("descriptionError")?.classList.add("show");
                return false;
            }
        }

        if (currentStep === 4) {
            const story = document.getElementById("story");
            if (!story.value.trim()) {
                story.classList.add("input-error");
                document.getElementById("storyError")?.classList.add("show");
                return false;
            }
        }

        if (currentStep === 5) {
            const bg = document.getElementById("bg_color").value;
            const primary = document.getElementById("primary_color").value;
            const secondary = document.getElementById("secondary_color").value;

            if (!bg || !primary || !secondary) {
                document.getElementById("colorError")?.classList.add("show");
                return false;
            }
        }


        if (currentStep === 7) {
            const enteredAddress = addressSearchInput?.value.trim() || "";
            const selectedAddress = addressHiddenInput?.value.trim() || "";

            if (enteredAddress && !selectedAddress) {
                document.getElementById("contactError")?.classList.add("show");
                addressSearchInput?.classList.add("input-error");
                return false;
            }
        }

        return true;
    }

    function buildSummary() {
        const name = document.getElementById("project_name").value || "Not provided";
        const slogan = document.getElementById("slogan").value || "—";
        const bg = document.getElementById("bg_color").value;
        const primary = document.getElementById("primary_color").value;
        const secondary = document.getElementById("secondary_color").value;
        const logoImg = document.querySelector("#logoPreview img")?.src || null;
        const projectType = document.querySelector(".option-card.selected")?.innerText || "Not selected";
        const address = addressHiddenInput?.value || addressSearchInput?.value || "—";
        const phone = document.querySelector('input[placeholder="Phone"]')?.value || "—";
        const email = document.querySelector('input[placeholder="Email (optional)"]')?.value || "—";
        const operatingHours = document.getElementById("operating_hours")?.value || "—";

        let modules = [];
        let modulesTotal = 0;

        document.querySelectorAll(".module-card.selected").forEach(card => {
            modules.push({
                name: card.querySelector(".module-title")?.innerText.trim() || card.innerText.trim(),

            });
            modulesTotal += parseInt(card.dataset.price) || 0;
        });


        const modulesHTML = modules.length
            ? modules.map(m => `<li>${escapeHtml(m.name)}</li>`).join("")
            : "<li>No extra modules selected</li>";

        document.getElementById("summary").innerHTML = `
        <div class="summary-report">
            <h2>Project Setup Summary</h2>
            ${logoImg ? `<img src="${logoImg}" style="height:60px;margin-bottom:15px;">` : ""}

            <div class="summary-section">
                <h3>Business Identity</h3>
                <p><strong>Type:</strong> ${escapeHtml(projectType)}</p>
                <p><strong>Name:</strong> ${escapeHtml(name)}</p>
                <p><strong>Slogan:</strong> ${escapeHtml(slogan)}</p>
            </div>

            <div class="summary-section">
                <h3>Brand Colours</h3>
                <div class="summary-color-strip">
                    <div class="summary-color-tab" style="background:${bg}" title="Background"></div>
                    <div class="summary-color-tab" style="background:${primary}" title="Primary"></div>
                    <div class="summary-color-tab" style="background:${secondary}" title="Secondary"></div>
                </div>
            </div>

            <div class="summary-section">
                <h3>Selected Features</h3>
                <ul class="invoice-list">
                    <li>Website Base</li>
                    ${modulesHTML}
                </ul>
            </div>

            <div class="summary-section">
                <h3>Contact Details</h3>
                <p><strong>Address:</strong> ${escapeHtml(address)}</p>
                <p><strong>Phone:</strong> ${escapeHtml(phone)}</p>
                <p><strong>Email:</strong> ${escapeHtml(email)}</p>
            </div>

            <div class="summary-section">
                <h3>Operating Hours</h3>
                <p class="summary-preline">${escapeHtml(operatingHours)}</p>
            </div>

            <div class="summary-section">
                <h3>Menu Upload</h3>
                <p>${menuFileName ? `<strong>${escapeHtml(menuFileName)}</strong> — will be imported automatically on deployment.` : 'No menu file uploaded.'}</p>
            </div>

            <div class="invoice-total">
                Free for 3 months, then charged only if you choose to continue
            </div>
        </div>
    `;
    }

    function syncDependentModules() {
        const onlineOrderingEnabled = !!onlineOrderingCard?.classList.contains("selected");

        dependentModuleCards.forEach(card => {
            card.classList.toggle("module-dependent-visible", onlineOrderingEnabled);

            if (!onlineOrderingEnabled && card.tagName === "LABEL") {
                card.classList.remove("selected");
                const checkbox = card.querySelector('input[type="checkbox"]');
                if (checkbox) checkbox.checked = false;
            }
        });

        recalculatePrice();
    }

    function recalculatePrice() {
        total = basePrice;
        const selectedModules = [];

        document.querySelectorAll('.module-card.selected').forEach(card => {
            const price = parseInt(card.dataset.price) || 0;
            total += price;
        });

        if (totalCostInput) totalCostInput.value = String(total);

        
    }

    function updateProgress(stepIndex) {
        const percent = (stepIndex / (totalSteps - 1)) * 100;
        progressFill.style.width = `${percent}%`;

        const barWidth = document.querySelector(".progress-bar").offsetWidth;
        const trianglePos = (percent / 100) * barWidth;
        progressTriangle.style.left = `${trianglePos - 10}px`;
    }

    function showStep(index) {
        steps.forEach((step, i) => {
            step.classList.toggle("active", i === index);
        });
        updateProgress(index);
    }

    function formatPhotonAddress(props) {
        const parts = [];
        const streetPart = [props.housenumber, props.street].filter(Boolean).join(" ");
        if (streetPart) parts.push(streetPart);
        else if (props.name && props.name !== (props.city || props.town || props.village)) parts.push(props.name);
        const city = props.city || props.town || props.village || props.hamlet;
        if (city) parts.push(city);
        if (props.postcode) parts.push(props.postcode);
        return parts.join(", ");
    }

    function showAddressResults(features) {
        if (!addressResults) return;

        if (!features.length) {
            addressResults.innerHTML = `<div class="address-search-empty">No addresses found</div>`;
            addressResults.classList.add("show");
            return;
        }

        addressResults.innerHTML = features.map(feat => {
            const label = formatPhotonAddress(feat.properties || {});
            return `<button type="button" class="address-result-item" data-address="${escapeHtml(label)}">
                📍 ${escapeHtml(label)}
            </button>`;
        }).join("");

        addressResults.classList.add("show");

        addressResults.querySelectorAll(".address-result-item").forEach(button => {
            button.addEventListener("click", () => {
                const address = button.dataset.address;
                addressSearchInput.value = address;
                addressHiddenInput.value = address;
                addressSearchInput.classList.remove("input-error");
                document.getElementById("contactError")?.classList.remove("show");
                addressResults.classList.remove("show");
            });
        });
    }

    async function fetchAddressSuggestions(query) {
        try {
            const response = await fetch(
                `https://photon.komoot.io/api/?q=${encodeURIComponent(query)}&limit=6&lang=en&lat=-25.2744&lon=133.7751`
            );
            const data = await response.json();
            const features = (data.features || []).filter(f => {
                const p = f.properties || {};
                return p.street || p.name;
            });
            showAddressResults(features);
        } catch (error) {
            console.error("Address search failed", error);
            addressResults.innerHTML = `<div class="address-search-empty">Address search is unavailable right now</div>`;
            addressResults.classList.add("show");
        }
    }

    function handleFile(event) {
        const file = event.target.files[0];
        if (!file) return;

        if (!file.type.startsWith("image/")) {
            alert("Only image files allowed");
            return;
        }

        const reader = new FileReader();
        reader.onload = function (loadEvent) {
            preview.innerHTML = `<img src="${loadEvent.target.result}">`;
        };
        reader.readAsDataURL(file);
    }

    function handleMenuFile(event) {
        const file = event.target.files[0];
        if (!file) return;
        menuFileName = file.name;
        const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
        if (isPdf) {
            menuPreview.innerHTML = `<div style="padding:0.75rem 1rem;background:#eff6ff;border-radius:12px;color:#1d4ed8;font-weight:600;">&#128196; ${escapeHtml(file.name)}</div>`;
        } else {
            const reader = new FileReader();
            reader.onload = function (e) {
                menuPreview.innerHTML = `<img src="${e.target.result}" style="max-height:120px;border-radius:10px;"><p style="margin:0.4rem 0 0;font-size:0.85rem;color:#64748b;">${escapeHtml(file.name)}</p>`;
            };
            reader.readAsDataURL(file);
        }
    }

    // Draft save/restore
    function collectDraftState() {
        const state = {
            currentStep,
            project_name: nameInput?.value || "",
            slogan: document.getElementById("slogan")?.value || "",
            description: document.getElementById("description")?.value || "",
            story: document.getElementById("story")?.value || "",
            bg_color: document.getElementById("bg_color")?.value || "",
            primary_color: document.getElementById("primary_color")?.value || "",
            secondary_color: document.getElementById("secondary_color")?.value || "",
            niche: document.getElementById("nicheInput")?.value || "",
            address: addressHiddenInput?.value || "",
            address_display: addressSearchInput?.value || "",
            phone: document.querySelector('input[placeholder="Phone"]')?.value || "",
            email: document.querySelector('input[placeholder="Email (optional)"]')?.value || "",
            operating_hours: document.getElementById("operating_hours")?.value || "",
            modules: Array.from(document.querySelectorAll(".module-card.selected input[type=checkbox]")).map(cb => cb.value),
            menu_file_name: menuFileName || null
        };
        return JSON.stringify(state);
    }

    function scheduleDraftSave() {
        clearTimeout(draftSaveTimeout);
        draftSaveTimeout = setTimeout(() => {
            const draft = collectDraftState();
            localStorage.setItem("wizard_draft", draft);
            fetch("/wizard/draft", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ draft })
            }).catch(() => {});
        }, 800);
    }

    function applyDraftState(state) {
        try {
            if (state.project_name && nameInput) nameInput.value = state.project_name;
            if (state.slogan) { const el = document.getElementById("slogan"); if (el) el.value = state.slogan; }
            if (state.description) { const el = document.getElementById("description"); if (el) el.value = state.description; }
            if (state.story) { const el = document.getElementById("story"); if (el) el.value = state.story; }
            if (state.bg_color) { const el = document.getElementById("bg_color"); if (el) el.value = state.bg_color; }
            if (state.primary_color) { const el = document.getElementById("primary_color"); if (el) el.value = state.primary_color; }
            if (state.secondary_color) { const el = document.getElementById("secondary_color"); if (el) el.value = state.secondary_color; }
            if (state.niche) { document.getElementById("nicheInput").value = state.niche; document.querySelectorAll(".option-card[data-value]").forEach(c => { c.classList.toggle("selected", c.dataset.value === state.niche); }); }
            if (state.address && addressHiddenInput) addressHiddenInput.value = state.address;
            if (state.address_display && addressSearchInput) addressSearchInput.value = state.address_display;
            if (state.phone) { const el = document.querySelector('input[placeholder="Phone"]'); if (el) el.value = state.phone; }
            if (state.email) { const el = document.querySelector('input[placeholder="Email (optional)"]'); if (el) el.value = state.email; }
            if (state.operating_hours) { const el = document.getElementById("operating_hours"); if (el) el.value = state.operating_hours; }
            if (Array.isArray(state.modules)) {
                document.querySelectorAll(".module-card").forEach(card => {
                    const cb = card.querySelector('input[type="checkbox"]');
                    if (!cb) return;
                    const active = state.modules.includes(cb.value);
                    card.classList.toggle("selected", active);
                    cb.checked = active;
                });
            }
            if (state.menu_file_name) {
                menuFileName = state.menu_file_name;
                if (menuPreview) menuPreview.innerHTML = `<p style="margin:0.4rem 0;font-size:0.85rem;color:#64748b;">Previously selected: ${escapeHtml(state.menu_file_name)} (re-upload to include)</p>`;
            }
        } catch (e) { console.warn("Draft restore error", e); }
    }

    async function loadDraft() {
        try {
            const res = await fetch("/wizard/draft");
            const data = await res.json();
            if (data.draft) {
                const state = JSON.parse(data.draft);
                const step = Math.max(0, parseInt(state.currentStep || 0, 10));
                if (step > 0) {
                    const banner = document.createElement("div");
                    banner.id = "draftBanner";
                    banner.style.cssText = "position:fixed;bottom:1.2rem;right:1.2rem;background:#fff;border-radius:18px;padding:1rem 1.25rem;box-shadow:0 12px 32px rgba(0,0,0,0.12);z-index:200;display:grid;gap:0.5rem;max-width:320px;border:1px solid #e2e8f0;";
                    banner.innerHTML = `<strong style="font-size:0.95rem;">Continue your draft?</strong><p style="margin:0;font-size:0.85rem;color:#64748b;">${escapeHtml(state.project_name || "Untitled")} — step ${step + 1}</p><div style="display:flex;gap:0.5rem;"><button id="draftContinueBtn" style="flex:1;padding:0.5rem 0.75rem;background:#2563eb;color:#fff;border:none;border-radius:10px;font-weight:700;cursor:pointer;">Continue</button><button id="draftDiscardBtn" style="flex:1;padding:0.5rem 0.75rem;background:#f1f5f9;color:#334155;border:none;border-radius:10px;font-weight:700;cursor:pointer;">Start Fresh</button></div>`;
                    document.body.appendChild(banner);
                    document.getElementById("draftContinueBtn").addEventListener("click", () => {
                        applyDraftState(state);
                        syncDependentModules();
                        currentStep = step;
                        showStep(currentStep);
                        banner.remove();
                    });
                    document.getElementById("draftDiscardBtn").addEventListener("click", () => {
                        fetch("/wizard/draft", { method: "DELETE" }).catch(() => {});
                        localStorage.removeItem("wizard_draft");
                        banner.remove();
                    });
                }
            }
        } catch (e) { console.warn("Draft load failed", e); }
    }

    function deleteDraft() {
        fetch("/wizard/draft", { method: "DELETE" }).catch(() => {});
        localStorage.removeItem("wizard_draft");
    }

    nextBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            if (!validateStep()) return;

            if (currentStep < steps.length - 1) {
                currentStep++;
                showStep(currentStep);
                window.scrollTo(0, 0);
                scheduleDraftSave();

                if (currentStep === steps.length - 1) {
                    buildSummary();
                }
            }
        });
    });

    backBtns.forEach(btn => {
        btn.addEventListener("click", () => {
            if (currentStep > 0) {
                currentStep--;
                showStep(currentStep);
            }
        });
    });

    document.querySelectorAll(".option-card[data-value]").forEach(card => {
        card.addEventListener("click", () => {
            document.querySelectorAll(".option-card[data-value]").forEach(c => c.classList.remove("selected"));
            card.classList.add("selected");
            document.getElementById("nicheInput").value = card.dataset.value;
            document.getElementById("typeError")?.classList.remove("show");
        });
    });

    document.querySelectorAll(".theme-card").forEach(card => {
        card.addEventListener("click", () => {
            document.querySelectorAll(".theme-card").forEach(c => c.classList.remove("selected"));
            card.classList.add("selected");
        });
    });

    document.querySelectorAll(".module-card").forEach(card => {
        const cb = card.querySelector('input[type="checkbox"]');
        if (cb && cb.checked) {
            card.classList.add("selected");
        }
    });

    document.querySelectorAll(".module-card").forEach(card => {
        card.addEventListener("click", (e) => {
            if (card.classList.contains("module-card-disabled")) {
                e.preventDefault();
                return;
            }

            if (card.classList.contains("module-dependent") && !card.classList.contains("module-dependent-visible")) {
                e.preventDefault();
                return;
            }

            e.preventDefault();

            card.classList.toggle("selected");
            const cb = card.querySelector('input[type="checkbox"]');
            if (cb) cb.checked = card.classList.contains("selected");

            syncDependentModules();
        });
    });

    document.querySelectorAll("input, textarea").forEach(input => {
        input.addEventListener("input", () => {
            input.classList.remove("input-error");
        });
    });

    document.querySelectorAll('input[type="color"]').forEach(color => {
        color.addEventListener("input", () => {
            document.getElementById("colorError")?.classList.remove("show");
        });
    });

    if (addressSearchInput && addressHiddenInput && addressResults) {
        addressSearchInput.addEventListener("input", () => {
            const query = addressSearchInput.value.trim();

            addressHiddenInput.value = "";
            addressSearchInput.classList.remove("input-error");
            document.getElementById("contactError")?.classList.remove("show");
            clearTimeout(addressSearchTimeout);

            if (query.length < 3) {
                addressResults.innerHTML = "";
                addressResults.classList.remove("show");
                return;
            }

            addressSearchTimeout = setTimeout(() => {
                fetchAddressSuggestions(query);
            }, 280);
        });

        document.addEventListener("click", (event) => {
            if (!addressResults.contains(event.target) && event.target !== addressSearchInput) {
                addressResults.classList.remove("show");
            }
        });
    }

    uploadBox.addEventListener("click", () => logoInput.click());
    logoInput.addEventListener("change", handleFile);

    uploadBox.addEventListener("dragover", e => {
        e.preventDefault();
        uploadBox.classList.add("dragover");
    });

    uploadBox.addEventListener("dragleave", () => {
        uploadBox.classList.remove("dragover");
    });

    uploadBox.addEventListener("drop", e => {
        e.preventDefault();
        uploadBox.classList.remove("dragover");
        const file = e.dataTransfer.files[0];
        handleFile({ target: { files: [file] } });
    });

    if (menuUploadBox) {
        menuUploadBox.addEventListener("click", () => menuFileInput?.click());
        menuFileInput?.addEventListener("change", handleMenuFile);
        menuUploadBox.addEventListener("dragover", e => { e.preventDefault(); menuUploadBox.classList.add("dragover"); });
        menuUploadBox.addEventListener("dragleave", () => menuUploadBox.classList.remove("dragover"));
        menuUploadBox.addEventListener("drop", e => {
            e.preventDefault();
            menuUploadBox.classList.remove("dragover");
            handleMenuFile({ target: { files: [e.dataTransfer.files[0]] } });
        });
    }

    function openPreview() {
        const bg = document.getElementById("bg_color").value;
        const primary = document.getElementById("primary_color").value;
        const secondary = document.getElementById("secondary_color").value;

        if (!bg || !primary || !secondary) {
            document.getElementById("colorError").classList.add("show");
            return;
        }

        previewOpen = true;
        previewLayer.classList.add("active");
        previewBtn.innerText = "✖ Close Preview";

        previewLayer.style.background = bg;
        document.querySelector(".preview-navbar").style.background = primary;
        document.querySelector(".preview-navbar").style.color = "#fff";
        document.querySelectorAll(".preview-navbar a").forEach(a => a.style.color = "#fff");
        document.querySelector(".preview-navbar .nav-left").style.color = "#fff";
        document.querySelector(".nav-cta").style.background = secondary;
        document.querySelector(".nav-cta").style.color = "#fff";
        document.querySelector(".hero-btn").style.background = primary;
        document.querySelector(".hero-btn").style.color = "#fff";

        // prevent body scroll while preview is open
        document.body.style.overflow = "hidden";
    }

    function closePreview() {
        previewOpen = false;
        previewLayer.classList.remove("active");
        previewBtn.innerText = "🔍 Preview Theme";
        document.body.style.overflow = "";
    }

    previewBtn.addEventListener("click", () => {
        if (previewOpen) closePreview(); else openPreview();
    });

    const previewCloseBtn = document.getElementById("previewCloseBtn");
    if (previewCloseBtn) {
        previewCloseBtn.addEventListener("click", closePreview);
    }

    form.addEventListener("submit", async function (e) {
        e.preventDefault();
        loadingScreen.classList.add("active");
        setBuildProgress(6);
        animateBuildProgress(38, 2, 320);
        setBuilderScreen({
            title: "Creating Your Website",
            text: "Applying design, modules, and configuration...",
            status: "loading",
            showActions: false
        });

        const formData = new FormData(form);

        try {
            const res = await fetch("/create_project", {
                method: "POST",
                body: formData
            });

            const data = await res.json();

            if (data.success) {
                currentSlug = data.slug;
                deleteDraft();
                stopBuildProgress();
                setBuildProgress(100);
                setBuilderScreen({
                    title: "Project Created",
                    text: "Your website setup is saved. Deploy it from Config when you are ready to generate visuals and publish.",
                    status: "success",
                    showActions: true,
                    confirmLabel: "Confirm",
                    confirmMode: "dashboard",
                    showRestart: false
                });
            } else {
                setBuilderScreen({
                    title: "Site Error",
                    text: data.error || "Failed to create project.",
                    status: "error",
                    showActions: true,
                    confirmLabel: "Confirm",
                    confirmMode: "dashboard",
                    showRestart: false
                });
            }
        } catch (err) {
            setBuilderScreen({
                title: "Site Error",
                text: err.message,
                status: "error",
                showActions: true,
                confirmLabel: "Confirm",
                confirmMode: "dashboard",
                showRestart: Boolean(currentSlug)
            });
        }
    });

    async function startPreview(slug) {
        currentSlug = slug;
        const res = await fetch(`/start_project_preview/${slug}`, { method: "POST" });
        const data = await res.json();

        if (data.success) {
            previewPort = data.port;
            window.open(`http://127.0.0.1:${previewPort}`, "_blank");
        }
    }

    document.getElementById("previewWebsiteBtn")?.addEventListener("click", () => {
        if (currentSlug) startPreview(currentSlug);
    });

    restartWebsiteBtn?.addEventListener("click", async () => {
        if (!currentSlug) return;

        if (errorIcon && errorIcon.style.display !== "none") {
            window.location.href = "/dashboard";
            return;
        }

        window.location.href = "/dashboard";
    });

    confirmWebsiteBtn?.addEventListener("click", async () => {
        if (confirmWebsiteBtn.dataset.mode === "dashboard") {
            window.location.href = "/dashboard";
            return;
        }

        if (!currentSlug) {
            setBuilderScreen({
                title: "Site Error",
                text: "Project not ready yet.",
                status: "error",
                showActions: false
            });
            return;
        }

        window.location.href = "/dashboard";
    });

    form.addEventListener("keydown", function (e) {
        if (e.key === "Enter") {
            if (e.target.tagName.toLowerCase() === "textarea") return;

            e.preventDefault();

            if (currentStep < steps.length - 1) {
                if (!validateStep()) return;

                currentStep++;
                showStep(currentStep);
                window.scrollTo(0, 0);

                if (currentStep === steps.length - 1) {
                    buildSummary();
                }
            } else {
                form.requestSubmit();
            }
        }
    });

    document.getElementById("exitBuilderBtn").addEventListener("click", () => {
        window.location.href = "/dashboard";
    });

    nameInput.addEventListener("input", () => {
        const name = nameInput.value.trim();
        document.getElementById("nameTakenError")?.classList.remove("show");

        if (name.length < 2) return;

        clearTimeout(nameCheckTimeout);

        nameCheckTimeout = setTimeout(async () => {
            try {
                const res = await fetch(`/check_project_name?name=${encodeURIComponent(name)}`);
                const data = await res.json();

                if (!data.available) {
                    nameAvailable = false;
                    nameInput.classList.add("input-error");
                    document.getElementById("nameTakenError")?.classList.add("show");
                } else {
                    nameAvailable = true;
                    nameInput.classList.remove("input-error");
                    document.getElementById("nameTakenError")?.classList.remove("show");
                }
            } catch (err) {
                console.error("Name check failed", err);
            }
        }, 400);
    });

    syncDependentModules();
    updateProgress(currentStep);
    showStep(currentStep);
    loadDraft();
});







