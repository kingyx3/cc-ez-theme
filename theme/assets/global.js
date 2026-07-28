
function getFocusableElements(container) {
  return Array.from(
    container.querySelectorAll(
      "summary, a[href], button:enabled, [tabindex]:not([tabindex^='-']), [draggable], area, input:not([type=hidden]):enabled, select:enabled, textarea:enabled, object, iframe"
    )
  );
}

const trapFocusHandlers = {};

function trapFocus(container, elementToFocus = container) {
  var elements = getFocusableElements(container);
  var first = elements[0];
  var last = elements[elements.length - 1];

  removeTrapFocus();

  trapFocusHandlers.focusin = (event) => {
    if (
      event.target !== container &&
      event.target !== last &&
      event.target !== first
    )
      return;

    document.addEventListener('keydown', trapFocusHandlers.keydown);
  };

  trapFocusHandlers.focusout = function() {
    document.removeEventListener('keydown', trapFocusHandlers.keydown);
  };

  trapFocusHandlers.keydown = function(event) {
    if (event.code.toUpperCase() !== 'TAB') return; // If not TAB key
    // On the last focusable element and tab forward, focus the first element.
    if (event.target === last && !event.shiftKey) {
      event.preventDefault();
      first.focus();
    }

    //  On the first focusable element and tab backward, focus the last element.
    if (
      (event.target === container || event.target === first) &&
      event.shiftKey
    ) {
      event.preventDefault();
      last.focus();
    }
  };

  document.addEventListener('focusout', trapFocusHandlers.focusout);
  document.addEventListener('focusin', trapFocusHandlers.focusin);

  elementToFocus.focus();
}

const serializeForm = form => {
  const obj = {};
  const formData = new FormData(form);
  for (const key of formData.keys()) {
    const regex = /(?:^(properties\[))(.*?)(?:\]$)/;
    let matches_array = key.match(/\[\]/);

    if (matches_array) {
      let new_key = key.replace(/[^a-zA-Z0-9_-]/g, "")
      
      obj[new_key] = new FormData(form).getAll(key)

    } else if (regex.test(key)) { 
      obj.properties = obj.properties || {};
      obj.properties[regex.exec(key)[2]] = formData.get(key);
    } else {
      obj[key] = formData.get(key);
    }
  }
console.log('obj',obj);
  return JSON.stringify(obj);
};

function removeTrapFocus(elementToFocus = null) {
  document.removeEventListener('focusin', trapFocusHandlers.focusin);
  document.removeEventListener('focusout', trapFocusHandlers.focusout);
  document.removeEventListener('keydown', trapFocusHandlers.keydown);

  if (elementToFocus) elementToFocus.focus();
}

function pauseAllMedia() {
  document.querySelectorAll('.js-youtube').forEach((video) => {
    video.contentWindow.postMessage('{"event":"command","func":"' + 'pauseVideo' + '","args":""}', '*');
  });
  document.querySelectorAll('.js-vimeo').forEach((video) => {
    video.contentWindow.postMessage('{"method":"pause"}', '*');
  });
  document.querySelectorAll('video').forEach((video) => video.pause());
  document.querySelectorAll('product-model').forEach((model) => {
    if (model.modelViewerUI) modelViewerUI.pause();
  });
}

function debounce(fn, wait) {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn.apply(this, args), wait);
  };
}

function slideToggle(element, duration = 300, trigger) {
  if (!element) return;

  const icon = trigger.querySelector('.chevron-icon'); 
  const isHidden = window.getComputedStyle(element).display === "none";

  if (isHidden) {
      // Show the element
      element.style.display = "block";
      const height = element.scrollHeight;
      element.style.height = "0px";
      element.style.overflow = "hidden";

      setTimeout(() => {
          element.style.transition = `height ${duration}ms ease-in-out`;
          element.style.height = height + "px";

          setTimeout(() => {
              element.style.height = "";
              element.style.transition = "";
              element.style.overflow = "";
          }, duration);

          if (icon) {
              icon.classList.add('rotate');
          }
      }, 10);
  } else {
      // Hide the element
      const height = element.scrollHeight;
      element.style.height = height + "px";
      element.style.overflow = "hidden";

      setTimeout(() => {
          element.style.transition = `height ${duration}ms ease-in-out`;
          element.style.height = "0px";

          setTimeout(() => {
              element.style.display = "none";
              element.style.height = "";
              element.style.transition = "";
              element.style.overflow = "";
          }, duration);

          if (icon) {
              icon.classList.remove('rotate');
          }
      }, 10);
  }
}

document.querySelectorAll('.rte table').forEach((table) => {
  table.outerHTML = '<div class="table-wrapper">'+ table.outerHTML +'</div>'
})

class QuantityInput extends HTMLElement {
  constructor() {
    super();
    this.input = this.querySelector('input');
    this.changeEvent = new Event('change', { bubbles: true })

    this.querySelectorAll('button').forEach(
      (button) => button.addEventListener('click', this.onButtonClick.bind(this))
    );
  }

  onButtonClick(event) {
    event.preventDefault();
    const previousValue = this.input.value;

    event.target.name === 'plus' ? this.input.stepUp() : this.input.stepDown();
    if (previousValue !== this.input.value) this.input.dispatchEvent(this.changeEvent);
  }
}

customElements.define('quantity-input', QuantityInput);

class VariantSelects {

  onVariantChange(selected_variant, id) {
    this.currentVariant = selected_variant
    this.productForm = document.getElementById('AddToCartForm-'+id);
    this.productInfo = document.getElementById('ProductInfo-'+id);

    this.toggleAddButton(true, '', false);
    this.updateProductPrice(id);
    this.updateLabelValue();

    if (!this.currentVariant || (!this.currentVariant.available && this.currentVariant.inventory_quantity != 0)) {
      this.toggleAddButton(true, '', true);
      this.setUnavailable();
    } else {

      const price = document.getElementById('price-'+id);
      if (price) price.classList.remove('visibility-hidden');
      this.toggleAddButton(!this.currentVariant.available, window.variantStrings.soldOut);
    }
  }
  
  updateLabelValue(){
  	let fieldsets = this.productForm.querySelectorAll('[data-selector-type="radio-img"]');
    fieldsets.forEach((fieldset)=>{
      if(this.productForm.querySelector(`label[for="${fieldset.id}"] .label__value`)){
        this.productForm.querySelector(`label[for="${fieldset.id}"] .label__value`)
        .innerHTML = `: ${this.currentVariant[fieldset.dataset.option]}`
      }
    })
  }

  updateVariantsUnavailable(all_variants,variants_unavailable){
    let match_disabled_variant = {};
    variants_unavailable.forEach((variant_unavailable)=>{
      let matched_variant = this.matchVariantUnavailable(this.currentVariant.options,variant_unavailable.options)
      if(matched_variant){
        Object.keys(matched_variant).forEach(key => {
          let option_index = `option${Number(key) + 1}`;
          match_disabled_variant[option_index] = match_disabled_variant[option_index] ?? [];
          if(key == '0' && this.currentVariant.options.length > 1) {
            match_disabled_variant[option_index].push(...this.matchOptionUnavailable(key, matched_variant[key], variants_unavailable, all_variants));
          }else{
            match_disabled_variant[option_index].push(...matched_variant[key]);
          }
        });
      }
    })
      
    this.productForm.querySelectorAll(`.disabled`).forEach((el)=>{
      el.classList.remove('disabled'),el.removeAttribute("disabled");
    })

    Object.entries(match_disabled_variant).forEach(([key, values]) => {
      values.forEach(value => {
          let el = this.productForm.querySelector(`[data-option='${key}'] [value='${CSS.escape(value)}']`);
          if(el) el.classList.add('disabled');
          // el.disabled = true;
      });
    });
  }
  
  matchVariantUnavailable(selected_variant,variant_unavailable){
    const trimmed_unavailable = variant_unavailable.map(v => v.trim());
    const trimmed_selected = selected_variant.map(v => v.trim());

    let matches = trimmed_selected.filter((value, index) => trimmed_unavailable[index] == value);

    if (matches.length == trimmed_selected.length - 1) {
      let option_unavailable = trimmed_unavailable.filter((value, index) => trimmed_selected[index] != value),
          option_index = trimmed_unavailable.findIndex(value => option_unavailable.includes(value));
	  
      return { [option_index]: option_unavailable };
    }
    return false;
  }

  matchOptionUnavailable(index,options,variants_unavailable,all_variants){
    let total_unavailable_option = [];
    options.forEach(option => {
      let matches_available = all_variants.filter((value) => value.options[index] == option),
          matches_unavailable = variants_unavailable.filter((value) => value.options[index] == option);
          
      if (matches_available.length == matches_unavailable.length) total_unavailable_option.push(option)
    })
    return total_unavailable_option;
  }

  toggleAddButton(disable = true, text, modifyClass = true) {
    if (!this.productForm) return;

    const addButton = this.productForm.querySelector('[name="add"]');
    if (!addButton) return;

    if (disable) {
      addButton.setAttribute('disabled', true);
      if (text) addButton.innerHTML = text;
    } else {
      addButton.removeAttribute('disabled');
      addButton.innerHTML = window.variantStrings.addToCart;
      if(addButton.dataset.updateCart)  addButton.innerHTML = window.variantStrings.updateCart;
    }

    if (!modifyClass) return;
  }


  updateProductPrice(id){
    [...this.productInfo.querySelectorAll('.price-item .money')].map((el)=>{
      if(this.currentVariant && this.currentVariant.price){
        el.innerHTML = EasyStore.Currencies.formatMoney(this.currentVariant.price)
        this.productInfo.querySelector('.price').classList.remove('hide');
      } else {
        this.productInfo.querySelector('.price').classList.add('hide');
      }
    });
    [...this.productInfo.querySelectorAll('.price__compare .money')].map((el)=>{
      if(this.currentVariant && this.currentVariant.compare_at_price){
        el.innerHTML = EasyStore.Currencies.formatMoney(this.currentVariant.compare_at_price)
        el.classList.remove('hide');
      } else {
        el.classList.add('hide');
      }
    });

    this.productInfo.querySelector('.price').classList.remove('price--sold-out','price--on-sale')
    this.productInfo.querySelector('.product-form__quantity').style.display = ''
    this.productInfo.querySelector('.product-form__submit').style.display = ''

    if(this.currentVariant.compare_at_price > this.currentVariant.price) this.productInfo.querySelector('.price').classList.add('price--on-sale')
    if(!this.currentVariant.available && this.currentVariant.inventory_quantity <= 0) {
      this.productInfo.querySelector('.price').classList.add('price--sold-out')
      this.productInfo.querySelector('.product-form__quantity').style.display = 'none'
    }

    if(this.currentVariant.price <= 0){
      this.productInfo.querySelector('.product-form__quantity').style.display = 'none'
      this.productInfo.querySelector('.product-form__submit').style.display = 'none'
    }
  }

  setUnavailable() {
    const button = document.getElementById('AddToCartForm-'+id);
    const addButton = button.querySelector('[name="add"]');
    const price = document.getElementById('price-'+id);
    if (!addButton) return;
    addButton.innerHTML = window.variantStrings.unavailable;
    if (price) price.classList.add('visibility-hidden');
  }

}
const VariantSelector = new VariantSelects;


class MenuDrawer extends HTMLElement {
  constructor() {
    super();

    this.mainDetailsToggle = this.querySelector('details');
    const summaryElements = this.querySelectorAll('summary');
    this.addAccessibilityAttributes(summaryElements);

    if (navigator.platform === 'iPhone') document.documentElement.style.setProperty('--viewport-height', `${window.innerHeight}px`);

    this.addEventListener('keyup', this.onKeyUp.bind(this));
    this.addEventListener('focusout', this.onFocusOut.bind(this));
    this.bindEvents();
  }

  bindEvents() {
    this.querySelectorAll('summary').forEach(summary => summary.addEventListener('click', this.onSummaryClick.bind(this)));
    this.querySelectorAll('button').forEach(button => button.addEventListener('click', this.onCloseButtonClick.bind(this)));
  }

  addAccessibilityAttributes(summaryElements) {
    summaryElements.forEach(element => {
      element.setAttribute('role', 'button');
      element.setAttribute('aria-expanded', false);
      element.setAttribute('aria-controls', element.nextElementSibling.id);
    });
  }

  onKeyUp(event) {
    if(event.code.toUpperCase() !== 'ESCAPE') return;

    const openDetailsElement = event.target.closest('details[open]');
    if(!openDetailsElement) return;

    openDetailsElement === this.mainDetailsToggle ? this.closeMenuDrawer(this.mainDetailsToggle.querySelector('summary')) : this.closeSubmenu(openDetailsElement);
  }

  onSummaryClick(event) {
    const summaryElement = event.currentTarget;
    const detailsElement = summaryElement.parentNode;
    const isOpen = detailsElement.hasAttribute('open');

    if (detailsElement === this.mainDetailsToggle) {
      if(isOpen) event.preventDefault();
      isOpen ? this.closeMenuDrawer(summaryElement) : this.openMenuDrawer(summaryElement);
    } else {
      trapFocus(summaryElement.nextElementSibling, detailsElement.querySelector('button'));

      setTimeout(() => {
        detailsElement.classList.add('menu-opening');
      });
    }
  }

  openMenuDrawer(summaryElement) {
    setTimeout(() => {
      this.mainDetailsToggle.classList.add('menu-opening');
    });
    summaryElement.setAttribute('aria-expanded', true);
    trapFocus(this.mainDetailsToggle, summaryElement);
    document.body.classList.add(`overflow-hidden-${this.dataset.breakpoint}`);
  }

  closeMenuDrawer(event, elementToFocus = false) {
    if (event !== undefined) {
      this.mainDetailsToggle.classList.remove('menu-opening');
      this.mainDetailsToggle.querySelectorAll('details').forEach(details =>  {
        details.removeAttribute('open');
        details.classList.remove('menu-opening');
      });
      this.mainDetailsToggle.querySelector('summary').setAttribute('aria-expanded', false);
      document.body.classList.remove(`overflow-hidden-${this.dataset.breakpoint}`);
      removeTrapFocus(elementToFocus);
      this.closeAnimation(this.mainDetailsToggle);
    }
  }

  onFocusOut(event) {
    setTimeout(() => {
      if (this.mainDetailsToggle.hasAttribute('open') && !this.mainDetailsToggle.contains(document.activeElement)) this.closeMenuDrawer();
    });
  }

  onCloseButtonClick(event) {
    const detailsElement = event.currentTarget.closest('details');
    this.closeSubmenu(detailsElement);
  }

  closeSubmenu(detailsElement) {
    detailsElement.classList.remove('menu-opening');
    removeTrapFocus();
    this.closeAnimation(detailsElement);
  }

  closeAnimation(detailsElement) {
    let animationStart;

    const handleAnimation = (time) => {
      if (animationStart === undefined) {
        animationStart = time;
      }

      const elapsedTime = time - animationStart;

      if (elapsedTime < 400) {
        window.requestAnimationFrame(handleAnimation);
      } else {
        detailsElement.removeAttribute('open');
        if (detailsElement.closest('details[open]')) {
          trapFocus(detailsElement.closest('details[open]'), detailsElement.querySelector('summary'));
        }
      }
    }

    window.requestAnimationFrame(handleAnimation);
  }
}

customElements.define('menu-drawer', MenuDrawer);

class HeaderDrawer extends MenuDrawer {
  constructor() {
    super();
  }

  openMenuDrawer(summaryElement) {
    this.header = this.header || document.querySelector('#easystore-section-header header');
    this.borderOffset = this.borderOffset || this.closest('.header-wrapper').classList.contains('header-wrapper--border-bottom') ? 1 : 0;
    document.documentElement.style.setProperty('--header-bottom-position', `${parseInt(this.header.getBoundingClientRect().bottom - this.borderOffset)}px`);

    setTimeout(() => {
      this.mainDetailsToggle.classList.add('menu-opening');
    });

    summaryElement.setAttribute('aria-expanded', true);
    trapFocus(this.mainDetailsToggle, summaryElement);
    document.body.classList.add(`overflow-hidden-${this.dataset.breakpoint}`);
  }
}

customElements.define('header-drawer', HeaderDrawer);

class DeferredMedia extends HTMLElement {
  constructor() {
    super();
    const poster = this.querySelector('[id^="Deferred-Poster-"]');
    if (!poster) return;
    poster.addEventListener('click', this.loadContent.bind(this));

    let youtube_id = this.querySelector('iframe').getAttribute('data-video-id'),
        VID_REGEX = /(?:youtube(?:-nocookie)?\.com\/(?:[^\/\n\s]+\/\S+\/|(?:v|e(?:mbed)?)\/|\S*?[?&]v=)|youtu\.be\/)([a-zA-Z0-9_-]{11})/;
    if(youtube_id.match(VID_REGEX) != null) youtube_id = youtube_id.match(VID_REGEX)[1];
    this.querySelector('iframe').src = `https://www.youtube.com/embed/${ youtube_id }?enablejsapi=1&rel=0`
  }
  
  loadContent() {
    window.pauseAllMedia();
    if (!this.getAttribute('loaded')) {

      this.setAttribute('loaded', true);
      this.querySelector('video, model-viewer, iframe').focus();

      this.querySelectorAll('.js-youtube').forEach((video) => {
        video.contentWindow.postMessage('{"event":"command","func":"' + 'playVideo' + '","args":""}', '*');
      });

    }
  }
}

customElements.define('deferred-media', DeferredMedia);

class SliderComponent extends HTMLElement {
  constructor() {
    super();
    this.slider = this.querySelector('ul');
    this.sliderItems = this.querySelectorAll('li');
    this.pageCount = this.querySelector('.slider-counter--current');
    this.pageTotal = this.querySelector('.slider-counter--total');
    this.prevButton = this.querySelector('button[name="previous"]');
    this.nextButton = this.querySelector('button[name="next"]');

    if (!this.slider || !this.nextButton) return;

    const resizeObserver = new ResizeObserver(entries => this.initPages());
    resizeObserver.observe(this.slider);

    this.slider.addEventListener('scroll', this.update.bind(this));
    this.prevButton.addEventListener('click', this.onButtonClick.bind(this));
    this.nextButton.addEventListener('click', this.onButtonClick.bind(this));
  }

  initPages() {
    const sliderItemsToShow = Array.from(this.sliderItems).filter(element => element.clientWidth > 0);
    this.sliderLastItem = sliderItemsToShow[sliderItemsToShow.length - 1];
    if (sliderItemsToShow.length === 0) return;
    this.slidesPerPage = Math.floor(this.slider.clientWidth / sliderItemsToShow[0].clientWidth);
    this.totalPages = sliderItemsToShow.length - this.slidesPerPage + 1;
    this.update();
  }

  update() {
    if (!this.pageCount || !this.pageTotal) return;
    this.currentPage = Math.round(this.slider.scrollLeft / this.sliderLastItem.clientWidth) + 1;

    if (this.currentPage === 1) {
      this.prevButton.setAttribute('disabled', true);
    } else {
      this.prevButton.removeAttribute('disabled');
    }

    if (this.currentPage === this.totalPages) {
      this.nextButton.setAttribute('disabled', true);
    } else {
      this.nextButton.removeAttribute('disabled');
    }

    this.pageCount.textContent = this.currentPage;
    this.pageTotal.textContent = this.totalPages;
  }

  onButtonClick(event) {
    console.log('onButtonClick');
    event.preventDefault();
    const slideScrollPosition = event.currentTarget.name === 'next' ? this.slider.scrollLeft + this.sliderLastItem.clientWidth : this.slider.scrollLeft - this.sliderLastItem.clientWidth;
    this.slider.scrollTo({
      left: slideScrollPosition
    });
  }
}

customElements.define('slider-component', SliderComponent);

class AddToCartButton extends HTMLElement {
  constructor() {
    super();

    this.loading = this.querySelector('.loading-overlay');
    this.button = this.querySelector('.addToClassList');
    this.quickviewModal = document.querySelector('product-quickview-modal');
    this.button.addEventListener('click', this.onSubmitHandler.bind(this), { passive: false });
    this.cartNotification = document.querySelector('cart-notification');
  }

  async onSubmitHandler(evt) {
    evt.preventDefault();
    this.setLoading(true);
    const { productId } = this.button.dataset;

    if (window.getProductProperties && productId && this.quickviewModal) {
      const hasProps = await new Promise(resolve => {
        window.getProductProperties(true, productId, null, res => resolve(!!res.propertyStatus));
      });
      if (hasProps) {
        this.quickviewModal.open(this.button);
        this.setLoading(false);
        return;
      } 
    } 
    this.addToCartHandler();
  }

  addToCartHandler() {
    const { variantId, productHandle, productPriceMax, productAvailable } = this.button.dataset;

    // If product is unavailable or price is zero, redirect to product page
    if (productPriceMax <= 0 || !productAvailable) {
      window.location.href = `/products/${productHandle}`;
      return;
    }

    // If sole variant is selected, add to cart
    if (variantId) {
      this.addToCart();
      return;
    }

    // If quickview modal exists, open it; otherwise, redirect
    if (productHandle && this.quickviewModal) {
      this.quickviewModal.open(this.button);
      this.setLoading(false);
      return;
    }
    window.location.href = `/products/${productHandle}`;
  }

  addToCart(){
    this.cartNotification.setActiveElement(document.activeElement);

    this.button.classList.add('transparent');

    const body = {
      _token : this.button.dataset.token,
      id : this.button.dataset.variantId,
      quantity : this.button.dataset.quantity
    }

    EasyStore.Action.addToCart(body,(cart)=>{

      if(window.location.pathname == '/cart'){
        location.reload()
      }else if(cart.item_count != undefined && cart.latest_items != undefined){
        this.cartNotification.renderContents(cart)
      } 
      
      console.log('addToCart',cart);
      this.setLoading(false);
    })
  }

  setLoading(isLoading = true){
    if (isLoading) {
      this.button.classList.add('transparent');
      this.loading.classList.remove('hidden');
    } else {
      this.button.classList.remove('transparent');
      this.loading.classList.add('hidden');
    }
  }

}

customElements.define('add-to-cart-button', AddToCartButton);
