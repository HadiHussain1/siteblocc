function getGlobalLoader() {
  return document.getElementById('global-loader');
}

function showLoader() {
  const loader = getGlobalLoader();
  if (loader) {
    loader.classList.add('active');
  }
}

function hideLoader() {
  const loader = getGlobalLoader();
  if (loader) {
    loader.classList.remove('active');
  }
}

function initScrollReveal() {
  const items = document.querySelectorAll('.reveal, .reveal-scale, .reveal-left, .reveal-right');
  if (!items.length) {
    return;
  }

  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduceMotion || !('IntersectionObserver' in window)) {
    items.forEach((item) => item.classList.add('is-visible'));
    return;
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.15, rootMargin: '0px 0px -60px 0px' });

  items.forEach((item) => observer.observe(item));
}

document.addEventListener('DOMContentLoaded', () => {
  hideLoader();
  initScrollReveal();

  document.querySelectorAll('form').forEach((form) => {
    form.addEventListener('submit', (event) => {
      if (event.defaultPrevented) {
        hideLoader();
        return;
      }

      if (typeof form.checkValidity === 'function' && !form.checkValidity()) {
        hideLoader();
        return;
      }

      showLoader();
    });
  });

  document.querySelectorAll('[data-show-loader="true"]').forEach((element) => {
    element.addEventListener('click', () => {
      showLoader();
    });
  });
});

window.addEventListener('pageshow', hideLoader);
