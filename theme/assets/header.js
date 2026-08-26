/*
 * Header behaviour: the sticky bar and the hover/focus disclosure menus.
 *
 * Both used to be inline in `sections/header.liquid`, which meant every page of
 * the store re-sent them inside its HTML and no browser could cache either. The
 * code takes no Liquid values at all, so it lives here and loads deferred like
 * the header's other modules.
 */
class StickyHeader extends HTMLElement {
  connectedCallback() {
    this.header = document.getElementById('easystore-section-header');
    this.headerBounds = {};
    this.currentScrollTop = 0;
    this.preventReveal = false;

    this.onScrollHandler = this.onScroll.bind(this);
    this.hideHeaderOnScrollUp = () => this.preventReveal = true;

    this.addEventListener('preventHeaderReveal', this.hideHeaderOnScrollUp);
    window.addEventListener('scroll', this.onScrollHandler, false);

    this.createObserver();
  }

  disconnectedCallback() {
    this.removeEventListener('preventHeaderReveal', this.hideHeaderOnScrollUp);
    window.removeEventListener('scroll', this.onScrollHandler);
  }

  createObserver() {
    const observer = new IntersectionObserver((entries, instance) => {
      this.headerBounds = entries[0].intersectionRect;
      instance.disconnect();
    });

    observer.observe(this.header);
  }

  onScroll() {
    const scrollTop = window.pageYOffset || document.documentElement.scrollTop;

    if (scrollTop > this.currentScrollTop && scrollTop > this.headerBounds.bottom) {
      requestAnimationFrame(this.sticky.bind(this));
    } else if (scrollTop < this.currentScrollTop && scrollTop > this.headerBounds.bottom) {
      if (!this.preventReveal) {
        requestAnimationFrame(this.reveal.bind(this));
      } else {
        window.clearTimeout(this.isScrolling);

        this.isScrolling = setTimeout(() => {
          this.preventReveal = false;
        }, 66);

        requestAnimationFrame(this.sticky.bind(this));
      }
    } else if (scrollTop <= this.headerBounds.top) {
      requestAnimationFrame(this.reset.bind(this));
    }

    this.currentScrollTop = scrollTop;
  }

  sticky() {
    this.header.classList.add('easystore-section-header-sticky');
    this.closeMenuDisclosure();
    this.closeSearchModal();
  }

  reveal() {
    this.header.classList.add('easystore-section-header-sticky');
  }

  reset() {
    this.header.classList.remove('easystore-section-header-sticky', 'animate');
  }

  closeMenuDisclosure() {
    this.disclosures = this.disclosures || this.header.querySelectorAll('details-disclosure');
    this.disclosures.forEach(disclosure => disclosure.close());
  }

  closeSearchModal() {
    this.searchModals = this.searchModals || this.header.querySelectorAll('details-modal.header__search');
    this.searchModals.forEach((searchModal) => searchModal.close(false));
  }
}

if (!customElements.get('sticky-header')) customElements.define('sticky-header', StickyHeader);

class DetailsDisclosure extends HTMLElement {
  constructor() {
    super();
    this.mainDetailsToggle = this.querySelector('details');
    this.mainDetailsToggle.addEventListener('focusout', this.onFocusOut.bind(this));
    this.mainDetailsToggle.addEventListener('mouseover', this.open.bind(this));
    this.mainDetailsToggle.addEventListener('mouseleave', this.close.bind(this));
    this.mainDetailsToggle.addEventListener('toggle', this.updateExpandedState.bind(this));
  }

  onFocusOut() {
    setTimeout(() => {
      if (!this.contains(document.activeElement)) this.close();
    });
  }

  open() {
    this.mainDetailsToggle.setAttribute('open', '');
  }

  close() {
    this.mainDetailsToggle.removeAttribute('open');
  }

  updateExpandedState() {
    const summary = this.mainDetailsToggle.querySelector('summary');
    if (summary) summary.setAttribute('aria-expanded', String(this.mainDetailsToggle.open));
  }
}

if (!customElements.get('details-disclosure')) customElements.define('details-disclosure', DetailsDisclosure);
