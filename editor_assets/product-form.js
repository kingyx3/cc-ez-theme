if (!customElements.get('product-form')) {
  customElements.define('product-form', class ProductForm extends HTMLElement {
    constructor() {
      super();

      this.form = this.querySelector('form');
      this.form.addEventListener('submit', this.onSubmitHandler.bind(this));
      this.cartNotification = document.querySelector('cart-notification');
    }

    onSubmitHandler(evt) {
      evt.preventDefault();
      this.cartNotification.setActiveElement(document.activeElement);

      const submitButton = this.querySelector('[type="submit"]');

      submitButton.setAttribute('disabled', true);
      submitButton.classList.add('loading');

      let updateCartItem = false;
      if(submitButton.dataset.updateCart && submitButton.dataset.cartItemId) {
        updateCartItem = true;
      }

      const body = JSON.parse(serializeForm(this.form));

      EasyStore.Action.addToCart(body,(cart)=>{
        this.hideErrorMsg()

        if(!updateCartItem && cart.item_count != undefined && cart.latest_items != undefined) this.cartNotification.renderContents(cart);
        if(cart.description != undefined) this.renderErrorMsg(cart.description);

        let cartItem = document.querySelector(`#${submitButton.dataset.cartItemId}`);
        if(updateCartItem && cartItem) {
          cartItem.removeCartItem();
        } else {
          submitButton.classList.remove('loading');
          submitButton.removeAttribute('disabled');
        }

      })

    }

    renderErrorMsg(html){
      this.form.querySelector('.form__message').classList.remove('hidden')
      this.form.querySelector('.js-error-content').innerHTML = html
    }

    hideErrorMsg(){
      this.form.querySelector('.form__message').classList.add('hidden')
    }

  });
}
