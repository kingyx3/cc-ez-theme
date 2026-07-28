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
      document.getElementById('cart-notification-product').innerHTML = this.getSectionInnerHTML(cart);
      document.querySelectorAll('.js-content-cart-count').forEach((el)=>{ el.innerHTML = cart.item_count; })
      if(cart.item_count > 0) document.querySelector('.cart-count-bubble').classList.remove('hidden')
      if(cart.item_count == 0) document.querySelector('.cart-count-bubble').classList.add('hidden')
      
      if (this.header) this.header.reveal();
      this.open();
  }

  updateCartCount(cart) {
      document.querySelectorAll('.js-content-cart-count').forEach((el)=>{ el.innerHTML = cart.item_count; })
      if(cart.item_count > 0) document.querySelector('.cart-count-bubble').classList.remove('hidden')
      if(cart.item_count == 0) document.querySelector('.cart-count-bubble').classList.add('hidden')
  }

  getSectionInnerHTML(cart) {
    console.log(cart);
    let added_item = cart.latest_items[0]
    return `
      <img class="cart-notification-product__image" src="${added_item.img_url ? added_item.img_url : '/assets/images/products/no_image.png'}" alt="Bo Ivy" width="70" height="70" loading="lazy">
      <div class="cart-notification-product__info">
        <h3 class="cart-notification-product__name h4">${added_item.product_name}</h3>
        <div class="cart-notification-product__option h4">
          ${added_item.variant_name ? added_item.variant_name : ''}
        </div>
      </div>`
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
