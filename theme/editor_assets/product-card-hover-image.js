(() => {
  // The hover image is only shown by a desktop pointer (component-card.css), so
  // product-card.liquid ships it as a placeholder and this loads it on first hover.
  const hoverQuery = window.matchMedia('(min-width: 990px)');

  function loadHoverImage(event) {
    if (!hoverQuery.matches || !event.target.closest) return;

    const card = event.target.closest('.card-wrapper');
    const image = card && card.querySelector('img[data-hover-src]');
    if (!image) return;

    const srcset = image.getAttribute('data-hover-srcset');
    const src = image.getAttribute('data-hover-src');
    image.removeAttribute('data-hover-srcset');
    image.removeAttribute('data-hover-src');
    if (srcset) image.srcset = srcset;
    if (src) image.src = src;
  }

  document.addEventListener('pointerover', loadHoverImage, { passive: true });
})();
