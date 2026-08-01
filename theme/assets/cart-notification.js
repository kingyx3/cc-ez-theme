class CartNotification extends HTMLElement {
  constructor() {
    super();

    this.notification = document.getElementById('cart-notification');
    this.header = document.querySelector('sticky-header');
    this.onBodyClick = this.handleBodyClick.bind(this);
    
    this.notification.addEventListener('keyup', (evt) => evt.code === 'Escape' && this.close());
    this.querySelectorAll('button[type="button"]').forEach((closeButton) =>
      closeButton.addEventListener('click', this.close.bind(this))
    );
  }

  open() {
    this.notification.classList.add('animate', 'active');

    this.notification.addEventListener('transitionend', () => {
      this.notification.focus();
      trapFocus(this.notification);
    }, { once: true });

    document.body.addEventListener('click', this.onBodyClick);

    if(document.querySelector('product-quickview-modal') && document.querySelector('product-quickview-modal').isOpen()) {
      document.querySelector('product-quickview-modal').close(true)
    }
  }

  close() {
    this.notification.classList.remove('active');

    document.body.removeEventListener('click', this.onBodyClick);

    removeTrapFocus(this.activeElement);
  }

  renderContents(cart) {
      this.renderProduct(cart);
      document.querySelectorAll('.js-content-cart-count').forEach((el)=>{ el.textContent = cart.item_count; })
      const cartBubble = document.querySelector('.cart-count-bubble');
      if (cartBubble) cartBubble.classList.toggle('hidden', cart.item_count === 0);
      
      if (this.header) this.header.reveal();
      this.open();
  }

  updateCartCount(cart) {
      document.querySelectorAll('.js-content-cart-count').forEach((el)=>{ el.textContent = cart.item_count; })
      const cartBubble = document.querySelector('.cart-count-bubble');
      if (cartBubble) cartBubble.classList.toggle('hidden', cart.item_count === 0);
  }

  renderProduct(cart) {
    const container = document.getElementById('cart-notification-product');
    const addedItem = cart.latest_items && cart.latest_items[0];
    if (!container || !addedItem) return;

    const image = document.createElement('img');
    image.className = 'cart-notification-product__image';
    image.src = addedItem.img_url || '/assets/images/products/no_image.png';
    image.alt = addedItem.product_name || '';
    image.width = 70;
    image.height = 70;

    const info = document.createElement('div');
    info.className = 'cart-notification-product__info';
    const name = document.createElement('h3');
    name.className = 'cart-notification-product__name h4';
    name.textContent = addedItem.product_name || '';
    const variant = document.createElement('div');
    variant.className = 'cart-notification-product__option h4';
    variant.textContent = addedItem.variant_name || '';
    info.append(name, variant);
    container.replaceChildren(image, info);
  }

  handleBodyClick(evt) {
    const target = evt.target;
    if (target !== this.notification && !target.closest('cart-notification')) {
      const disclosure = target.closest('details-disclosure');
      this.activeElement = disclosure ? disclosure.querySelector('summary') : null;
      this.close();
    }
  }

  setActiveElement(element) {
    this.activeElement = element;
  }
}

customElements.define('cart-notification', CartNotification);
