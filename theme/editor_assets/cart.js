document.getElementById('cart-form')?.addEventListener('submit',(event)=>{
  if(event.submitter) event.submitter.classList.add('loading');
})

document.body.addEventListener("click", function(event) {
    const trigger = event.target.closest(".product-bundle__toggle");
    if (trigger) {
        const targetId = trigger.getAttribute("data-target");
        const target = document.getElementById(targetId);
        if (target) {
            const isOpening = window.getComputedStyle(target).display === 'none';
            slideToggle(target, 300, trigger);
            trigger.setAttribute('aria-expanded', String(isOpening));
        }
    }
});

class CartRemoveButton extends HTMLElement {
  constructor() {
    super();
    this.addEventListener('click', (event) => {
      event.preventDefault();
      this.closest('.cart-item__quantity').querySelector('.quantity__input').value = 0
      this.closest('cart-items').removeCartItem(this.dataset.index);
    });
  }
}

customElements.define('cart-remove-button', CartRemoveButton);

class CartEditButton extends HTMLElement {
  constructor() {
    super();
    if(document.querySelector('product-quickview-modal')) this.classList.remove('hide');
    this.button = this.querySelector('[data-product-handle]');
    this.addEventListener('click', (event) => {
      document.querySelector('product-quickview-modal').open(this.button, true);
    });
  }

  removeCartItem() {
    this.closest('.cart-item__quantity').querySelector('.quantity__input').value = 0
    this.closest('cart-items').removeCartItem(this.dataset.index, false);
  }
}

customElements.define('cart-edit-button', CartEditButton);

class DiscountInput extends HTMLElement {
  constructor() {
    super();
    this.input = this.querySelector('input');
    this.button = this.querySelector('button');

    this.button.addEventListener('click', this.onButtonClick.bind(this))
    this.input.addEventListener('keypress', (event)=>{
      if (event.key == 'Enter' || event.keyCode == 13){
        event.preventDefault()
        this.onButtonClick(event)
      }
      this.hideErrorMsg()
    })
  }

  onButtonClick(event) {
    event.preventDefault();
    this.hideErrorMsg();

    if(this.input.value != ''){
      this.button.classList.add('loading')
      EasyStore.Action.updateVoucher("create",this.input.value,(cart)=>{
        this.button.classList.remove('loading')
        if(cart.error && cart.error.message) {
          this.renderErrorMsg(cart.error.message)
        }else{
          if(document.querySelector('vouchers-modal')) document.querySelector('vouchers-modal').close()
        }
        if(cart.cart_content) document.querySelector('#cart-template').innerHTML = cart.cart_content
      })
    }
  }

  renderErrorMsg(html){
    const formMessage = this.querySelector('.form__message');
    const errorContent = this.querySelector('.js-error-content');

    if (
      typeof html === "string" &&
      /log in/i.test(html) &&
      !/voucher-error__login/.test(html)
    ) {
      const loginUrl = "/account/login?redirect_uri=" + encodeURIComponent(window.location.pathname + window.location.search);
      html = html.replace(/log in/i, `<a href="${loginUrl}" class="voucher-error__login">$&</a>`);
    }

    formMessage.classList.remove('hidden');
    errorContent.innerHTML = html;
  }


  hideErrorMsg(){
    this.querySelector('.form__message').classList.add('hidden')
  }
}
customElements.define('discount-input', DiscountInput);

class DiscountRemoveButton extends HTMLElement {
  constructor() {
    super();
    this.button = this.querySelector('button');
    this.button.addEventListener('click', this.onButtonClick.bind(this))
  }

  onButtonClick(event) {
    event.preventDefault();
    this.enableLoading()
    EasyStore.Action.updateVoucher("remove",this.button.dataset.discount_id,(cart)=>{
      if(cart.cart_content) document.querySelector('#cart-template').innerHTML = cart.cart_content
    })
  }

  enableLoading() {
    this.closest('.totals').classList.add('cart__items--disabled');
    this.closest('.totals').querySelector('.loading-overlay').classList.remove('hidden');
    document.activeElement.blur();
  }

  disableLoading() {
    this.closest('.totals').classList.remove('cart__items--disabled');
    this.closest('.totals').querySelector('.loading-overlay').classList.add('hidden');
  }
}
customElements.define('discount-remove-button', DiscountRemoveButton);


class CartItems extends HTMLElement {
  constructor() {
    super();
    
	  this.cartNotification = document.querySelector('cart-notification');

    this.currentItemCount = Array.from(this.querySelectorAll('[name="updates[]"]'))
      .reduce((total, quantityInput) => total + parseInt(quantityInput.value), 0);

    this.debouncedOnChange = debounce((event) => {
      this.onChange(event);
    }, 300);

    this.addEventListener('change', this.debouncedOnChange.bind(this));
  }

  onChange(event) {
    this.updateQuantity(event.target.dataset.index, event.target.value, document.activeElement?.getAttribute('name'));
  }

  
  updateQuantity(line, quantity, name) {
    this.enableLoading(line);
    this.hideErrorMsg();

    let body = JSON.parse(serializeForm(document.getElementById('cart-form')));

    EasyStore.Action.updateCart(body,(cart)=>{

        this.classList.toggle('is-empty', cart.item_count === 0);
        let cartFooter = document.getElementById('main-cart-footer');
        if (cartFooter) cartFooter.classList.toggle('is-empty', cart.item_count === 0);

       
        this.disableLoading();
        if(cart.error && cart.error.message) { 
          this.renderErrorMsg(cart.error.message)
          this.disableLoading(line);
        }
        if(cart.cart_content) document.querySelector('#cart-template').innerHTML = cart.cart_content
      
        if(this.cartNotification != undefined && this.cartNotification.updateCartCount != undefined) this.cartNotification.updateCartCount(cart);
        if(window.EasyStore != undefined && window.EasyStore.Promotion != undefined && window.EasyStore.Promotion.updateCartPromotion != undefined) window.EasyStore.Promotion.updateCartPromotion()

        if (window.checkProductProperties !== undefined){
      		window.checkProductProperties();
        }
    })
    
  }

  removeCartItem(line, isCheckProductProperties = true) {
    let cartItem = this.querySelector(`#CartItem-${line}`);
    if (!cartItem) return;
    let cartItemDeleteBtn = cartItem.querySelector(`cart-remove-button [data-item-id]`);
    if (!cartItemDeleteBtn) return;

    this.enableLoading(line);
    this.hideErrorMsg();
    let body = {
      variant_id: cartItemDeleteBtn.dataset.variantId,
      item_id: cartItemDeleteBtn.dataset.itemId,
    };

    EasyStore.Action.removeCartItem(body,(cart)=>{

        this.classList.toggle('is-empty', cart.item_count === 0);
        let cartFooter = document.getElementById('main-cart-footer');
        if (cartFooter) cartFooter.classList.toggle('is-empty', cart.item_count === 0);

        this.disableLoading();
        if(cart.error && cart.error.message) { 
          this.renderErrorMsg(cart.error.message)
          this.disableLoading(line);
        }
        if(cart.cart_content) document.querySelector('#cart-template').innerHTML = cart.cart_content
      
        if(this.cartNotification != undefined && this.cartNotification.updateCartCount != undefined) this.cartNotification.updateCartCount(cart);
        if(window.EasyStore != undefined && window.EasyStore.Promotion != undefined && window.EasyStore.Promotion.updateCartPromotion != undefined) window.EasyStore.Promotion.updateCartPromotion();

        if (window.checkProductProperties !== undefined && isCheckProductProperties){
      		window.checkProductProperties();
        };
        if(document.querySelector('product-quickview-modal') && document.querySelector('product-quickview-modal').isOpen()) document.querySelector('product-quickview-modal').close(true)

    })

  }


  renderErrorMsg(html){
    this.querySelector('.cart_form__error').classList.remove('hidden')
    this.querySelector('.cart_form__error .js-error-content').innerHTML = html
    window.scrollTo(0, 0)
  }

  hideErrorMsg(){
    this.querySelector('.cart_form__error').classList.add('hidden')
  }


  enableLoading(line) {
    document.getElementById('main-cart-items').classList.add('cart__items--disabled');
    this.querySelectorAll(`#CartItem-${line} .loading-overlay`).forEach((overlay) => overlay.classList.remove('hidden'));
    document.activeElement.blur();
  }

  disableLoading() {
    document.getElementById('main-cart-items').classList.remove('cart__items--disabled');
    this.querySelectorAll('.loading-overlay').forEach((overlay) => overlay.classList.add('hidden'));
  }
}

customElements.define('cart-items', CartItems);
