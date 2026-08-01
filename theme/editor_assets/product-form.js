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
      const submitButton = evt.submitter || this.querySelector('[type="submit"]');
      const submitButtons = this.querySelectorAll('.product-form__submit');
      const buyNow = submitButton && submitButton.name === 'buy_now';

      if (!buyNow && this.cartNotification) {
        this.cartNotification.setActiveElement(document.activeElement);
      }

      submitButtons.forEach((button) => button.setAttribute('disabled', true));
      submitButton.classList.add('loading');

      let updateCartItem = false;
      if(submitButton.dataset.updateCart && submitButton.dataset.cartItemId) {
        updateCartItem = true;
      }

      const body = JSON.parse(serializeForm(this.form));

      EasyStore.Action.addToCart(body,(cart)=>{
        this.hideErrorMsg()

        if(cart.description != undefined) {
          this.renderErrorMsg(cart.description);
          submitButton.classList.remove('loading');
          submitButtons.forEach((button) => button.removeAttribute('disabled'));
          return;
        }

        if(buyNow) {
          window.location.assign('/checkout');
          return;
        }

        if(!updateCartItem && cart.item_count != undefined && cart.latest_items != undefined && this.cartNotification) {
          this.cartNotification.renderContents(cart);
        }

        let cartItem = document.querySelector(`#${submitButton.dataset.cartItemId}`);
        if(updateCartItem && cartItem) {
          cartItem.removeCartItem();
        } else {
          submitButton.classList.remove('loading');
          submitButtons.forEach((button) => button.removeAttribute('disabled'));
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
