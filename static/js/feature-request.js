(function () {
  /* ── Inject styles ── */
  const style = document.createElement('style');
  style.textContent = `
    .fr-btn {
      position: fixed;
      bottom: 28px;
      left: 28px;
      z-index: 9000;
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 11px 18px;
      border-radius: 999px;
      border: none;
      cursor: pointer;
      font-family: inherit;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.02em;
      color: #ffffff;
      background: linear-gradient(135deg, #7c3aed, #4f46e5);
      box-shadow: 0 8px 24px rgba(124, 58, 237, 0.38), 0 2px 6px rgba(0,0,0,0.18);
      transition: transform 0.18s ease, box-shadow 0.18s ease;
    }
    .fr-btn:hover {
      transform: translateY(-2px);
      box-shadow: 0 12px 30px rgba(124, 58, 237, 0.48), 0 2px 8px rgba(0,0,0,0.18);
    }
    .fr-btn .fr-plus {
      font-size: 16px;
      font-weight: 800;
      line-height: 1;
    }

    @keyframes fr-jump {
      0%   { transform: translateY(0) rotate(0deg); }
      15%  { transform: translateY(-10px) rotate(-2deg); }
      30%  { transform: translateY(-4px) rotate(1deg); }
      42%  { transform: translateY(-8px) rotate(-1deg); }
      55%  { transform: translateY(-2px) rotate(0.5deg); }
      65%  { transform: translateY(-5px) rotate(-0.5deg) scale(1.03); }
      75%  { transform: translateY(0) rotate(0deg) scale(1); }
      82%  { transform: translateX(-2px); }
      86%  { transform: translateX(3px); }
      90%  { transform: translateX(-2px); }
      94%  { transform: translateX(2px); }
      100% { transform: translateX(0); }
    }
    .fr-btn.fr-animate {
      animation: fr-jump 0.85s cubic-bezier(0.36, 0.07, 0.19, 0.97) both;
    }

    .fr-overlay {
      display: none;
      position: fixed;
      inset: 0;
      z-index: 9100;
      background: rgba(10, 12, 17, 0.7);
      backdrop-filter: blur(4px);
      align-items: center;
      justify-content: center;
    }
    .fr-overlay.fr-open {
      display: flex;
    }
    .fr-modal {
      background: #ffffff;
      border-radius: 22px;
      padding: 36px 32px 28px;
      width: min(90vw, 460px);
      box-shadow: 0 28px 80px rgba(0,0,0,0.28);
      position: relative;
      animation: fr-modal-in 0.28s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    @keyframes fr-modal-in {
      from { opacity: 0; transform: scale(0.88) translateY(16px); }
      to   { opacity: 1; transform: scale(1) translateY(0); }
    }
    .fr-modal-close {
      position: absolute;
      top: 14px;
      right: 16px;
      background: none;
      border: none;
      cursor: pointer;
      font-size: 20px;
      color: #94a3b8;
      line-height: 1;
      padding: 4px;
      border-radius: 6px;
      transition: color 0.15s;
    }
    .fr-modal-close:hover { color: #0f172a; }
    .fr-modal h2 {
      margin: 0 0 6px;
      font-size: 1.22rem;
      font-weight: 800;
      color: #0f172a;
    }
    .fr-modal p {
      margin: 0 0 22px;
      font-size: 0.88rem;
      color: #64748b;
      line-height: 1.6;
    }
    .fr-modal label {
      display: block;
      font-size: 0.78rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      color: #475569;
      margin-bottom: 6px;
    }
    .fr-modal input,
    .fr-modal textarea {
      width: 100%;
      box-sizing: border-box;
      border: 1.5px solid #e2e8f0;
      border-radius: 10px;
      padding: 10px 13px;
      font-size: 14px;
      font-family: inherit;
      color: #0f172a;
      outline: none;
      transition: border-color 0.18s;
      margin-bottom: 16px;
      background: #f8fafc;
    }
    .fr-modal input:focus,
    .fr-modal textarea:focus {
      border-color: #7c3aed;
      background: #ffffff;
    }
    .fr-modal textarea { resize: vertical; min-height: 90px; }
    .fr-submit {
      width: 100%;
      padding: 12px;
      border: none;
      border-radius: 12px;
      background: linear-gradient(135deg, #7c3aed, #4f46e5);
      color: #ffffff;
      font-size: 15px;
      font-weight: 700;
      font-family: inherit;
      cursor: pointer;
      transition: opacity 0.18s, transform 0.18s;
    }
    .fr-submit:hover { opacity: 0.92; transform: translateY(-1px); }
    .fr-submit:disabled { opacity: 0.55; cursor: not-allowed; transform: none; }
    .fr-thankyou {
      display: none;
      text-align: center;
      padding: 12px 0 4px;
    }
    .fr-thankyou .fr-check {
      font-size: 48px;
      line-height: 1;
      margin-bottom: 14px;
    }
    .fr-thankyou h3 {
      margin: 0 0 8px;
      font-size: 1.15rem;
      font-weight: 800;
      color: #0f172a;
    }
    .fr-thankyou p {
      margin: 0;
      color: #64748b;
      font-size: 0.9rem;
    }
  `;
  document.head.appendChild(style);

  /* ── Build DOM ── */
  const btn = document.createElement('button');
  btn.className = 'fr-btn';
  btn.innerHTML = '<span class="fr-plus">+</span> Request Feature';
  document.body.appendChild(btn);

  const overlay = document.createElement('div');
  overlay.className = 'fr-overlay';
  overlay.innerHTML = `
    <div class="fr-modal" role="dialog" aria-modal="true" aria-labelledby="fr-title">
      <button class="fr-modal-close" aria-label="Close">&times;</button>
      <div class="fr-form-view">
        <h2 id="fr-title">Request a Feature</h2>
        <p>Tell us what you'd like to see. We read every submission and use them to shape what we build next.</p>
        <label for="fr-name">Feature Name</label>
        <input id="fr-name" type="text" placeholder="e.g. Export orders to CSV" maxlength="120">
        <label for="fr-desc">Description</label>
        <textarea id="fr-desc" placeholder="Describe the feature and why it would help you..." maxlength="1000"></textarea>
        <button class="fr-submit" id="fr-submit-btn">Submit Request</button>
      </div>
      <div class="fr-thankyou" id="fr-thankyou">
        <div class="fr-check">&#10003;</div>
        <h3>Thank you!</h3>
        <p>Your request has been sent. We'll review it and may reach out if we need more details.</p>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);

  const modal       = overlay.querySelector('.fr-modal');
  const formView    = overlay.querySelector('.fr-form-view');
  const thankyou    = overlay.querySelector('#fr-thankyou');
  const nameInput   = overlay.querySelector('#fr-name');
  const descInput   = overlay.querySelector('#fr-desc');
  const submitBtn   = overlay.querySelector('#fr-submit-btn');
  const closeBtn    = overlay.querySelector('.fr-modal-close');

  /* ── Animation trigger ── */
  function triggerJump() {
    btn.classList.remove('fr-animate');
    void btn.offsetWidth; // reflow
    btn.classList.add('fr-animate');
  }

  function resetAnimation() {
    btn.addEventListener('animationend', () => btn.classList.remove('fr-animate'), { once: true });
  }

  triggerJump();
  resetAnimation();
  setInterval(() => { triggerJump(); resetAnimation(); }, 20000);

  /* ── Open / close ── */
  function openModal() {
    formView.style.display = '';
    thankyou.style.display = 'none';
    nameInput.value = '';
    descInput.value = '';
    submitBtn.disabled = false;
    overlay.classList.add('fr-open');
    setTimeout(() => nameInput.focus(), 80);
  }

  function closeModal() {
    overlay.classList.remove('fr-open');
  }

  btn.addEventListener('click', openModal);
  closeBtn.addEventListener('click', closeModal);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) closeModal(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

  /* ── Submit ── */
  submitBtn.addEventListener('click', async () => {
    const feature_name = nameInput.value.trim();
    if (!feature_name) { nameInput.focus(); return; }

    submitBtn.disabled = true;
    submitBtn.textContent = 'Sending...';

    try {
      const res = await fetch('/feature_request', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          feature_name,
          description: descInput.value.trim(),
          page_context: window.location.pathname
        })
      });
      const data = await res.json();
      if (data.success) {
        formView.style.display = 'none';
        thankyou.style.display = '';
        setTimeout(closeModal, 3200);
      } else {
        submitBtn.disabled = false;
        submitBtn.textContent = 'Submit Request';
        alert(data.error || 'Something went wrong. Please try again.');
      }
    } catch {
      submitBtn.disabled = false;
      submitBtn.textContent = 'Submit Request';
      alert('Connection error. Please try again.');
    }
  });
})();
