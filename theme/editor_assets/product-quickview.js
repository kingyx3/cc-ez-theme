
class ProductQuickviewModal extends HTMLElement {
  constructor() {
    super();

    this.modal = this.querySelector('#product-quickview-modal');
    this.closeButton = this.querySelector('.modal__close-button');
    this.modalBody = this.querySelector('.product-quickview-modal__body');
    this.modalLoading = this.querySelector('.loading-overlay');
    this.modalBackdrop = this.querySelector('.product-quickview-modal-backdrop');
    this.bindEvents();

    this.isUpdateCart = false; 
    this.cartItem = null;
  }
  
  bindEvents() {
    this.addEventListener('focusout', this.onFocusOut.bind(this));
    this.closeButton.addEventListener('click', this.close.bind(this));
    this.modalBackdrop.addEventListener('click', this.close.bind(this));
  }

  open(el, isUpdateCart = false) {
    this.isUpdateCart = isUpdateCart;
    this.modal.setAttribute('open', true);
    trapFocus(this, this.modal);
    document.body.classList.add(`overflow-hidden`);

    if(this.isUpdateCart) {
      this.cartItem = el.closest('cart-edit-button');
      this.modal.dataset.cartItem = JSON.stringify(el.dataset);
    } else {
      this.cartItem = null;
      this.modal.removeAttribute('data-cart-item');
    }
    
    let productHandle = el.dataset.productHandle;

    if (productHandle) {
      fetch(`/products/${productHandle}/product_quickview_html`, {
        method: 'GET',
        headers: {
          'Accept': 'application/json'
        }
      })
        .then(response => {
          if (!response.ok) {
            throw new Error('Network response was not ok');
          }
          return response.json();
        })
        .then(res => {
          this.renderHTML(res.html, this.cartItem);
          this.modalLoading.classList.add('hidden');
          this.modalBody.style.display = '';

          this.initProductOptionsSelector(res.product);
          this.preselectProductOptionsSelector(el);
          this.getProductModalPromotionList(res.product.url);
        })
        .catch(() => {
          console.log("Failed to load product data");
        });
    }
  }

  close(event, elementToFocus = false) {
    if (event !== undefined) {
      document.body.classList.remove(`overflow-hidden`);
      removeTrapFocus(elementToFocus);
      this.modal.removeAttribute('open');
      this.modalBody.style.display = 'none';
      this.modalBody.innerHTML = ''; 
      this.modalLoading.style.display = '';
      this.modalLoading.classList.remove('hidden');
    }
  }

  onFocusOut(event) {
    setTimeout(() => {
      if (this.modal.hasAttribute('open') && !this.modal.contains(document.activeElement)) this.close();
    });
  }

  isOpen() {
    return this.modal.hasAttribute('open');
  }

  renderHTML(html, cartItem = null) {
    this.modalBody.innerHTML = ''; // Clear existing content
    // Create a temporary div to parse HTML
    const tempDiv = document.createElement('div');
    tempDiv.innerHTML = html;

    // Append script & html elements
    Array.from(tempDiv.childNodes).forEach(node => {
      if (node.tagName === 'SCRIPT') {
        const script = document.createElement('script');
        script.text = node.textContent;
        this.modalBody.appendChild(script);
      } else {
        this.modalBody.appendChild(node);
      }
    });

    if(this.isUpdateCart) {
      let cartItemQuantity = cartItem.querySelector('[data-quantity]').dataset.quantity || 1;
      this.modalBody.querySelector('[type="submit"]').dataset.updateCart = true;
      this.modalBody.querySelector('[name="quantity"]').value = cartItemQuantity;
      if (cartItem) this.modalBody.querySelector('[type="submit"]').dataset.cartItemId = cartItem.id;
    }
  }
  
  initProductOptionsSelector(product) {
    let variants = product.variants,
        variants_unavailable = variants.filter(value => value.available == false);

    var selectCallback = function(variant, selector) {
      console.log('variant, selector',variant, selector);
      VariantSelector.onVariantChange(variant, 'ProductModal')
      if(variants_unavailable && variants_unavailable.length > 0 && VariantSelector.updateVariantsUnavailable) VariantSelector.updateVariantsUnavailable(variants,variants_unavailable);
      if(variant.featured_image != undefined && variant.featured_image.src) document.querySelector('#productModal-MainImg').src = variant.featured_image.src;
    }

    let display_type = window.productSettings.variantOptionsDisplay || 'radio';

    EasyStore.OptionSelectorsNew.create('productModal-productSelect', display_type, {
        product: product,
        onVariantSelected: selectCallback,
        enableHistoryState: false
    })
  }

  preselectProductOptionsSelector(el) {
    let { variantId, variantName } = el.dataset;
    let select = document.getElementById('productModal-productSelect');
    if (select && variantId) {
      select.value = variantId;
      select.dispatchEvent(new Event('change', { bubbles: true }));
    }
    if (variantName) {
      variantName.split(',').map(v => v.trim()).forEach((val, idx) => {
        let fieldset = document.getElementById(`productModal-productSelect-option-${idx}`);
        if (fieldset) {
          fieldset.querySelectorAll('input[type="radio"]').forEach(radio => {
            if (radio.value.trim() === val) {
              radio.checked = true;
              radio.dispatchEvent(new Event('change', { bubbles: true }));
            }
          });
        }
      });
    }
  }
  
  getProductModalPromotionList(url) {
    fetch(`${url}/promotions`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json'
      }
    })
      .then(response => {
        if (!response.ok) {
          throw new Error('Network response was not ok');
        }
        return response.json();
      })
      .then(response => {
        const { total_promotions, promotions } = response.data || {};
        let tagLabelHtml = '', tagHtml = '';

        if (total_promotions > 0 && Array.isArray(promotions)) {
          tagLabelHtml = `<div><label>${window.promotionStrings.title}</label></div>`;

          promotions.forEach(promo => {
            const isClickable = promo.prerequisite_subtotal_range == null && promo.prerequisite_to_entitlement_quantity_ratio != null;
            const labelClass = isClickable ? "quickview_promo-label-clickable" : "quickview_promo-label-unclickable";
            const svgIcon = isClickable
              ? `<svg class="quickview_promo-svg-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" stroke-width="2.8" stroke="currentColor" fill="none" stroke-linecap="round" stroke-linejoin="round"><path stroke="none" d="M0 0h24v24H0z" fill="none"/><polyline points="9 6 15 12 9 18" /></svg>`
              : '';
            const safeTitle = promo.title
              .replace(/&/g, '&amp;')
              .replace(/>/g, '&gt;')
              .replace(/</g, '&lt;')
              .replace(/\//g, '&sol;')
              .replace(/“/g, '&quot;')
              .replace(/'/g, '&#39;');
            tagHtml += `<a href="${url}" class="quickview_promo-promo-label ${labelClass}"><b class="quickview_promo-tag-label-title">${safeTitle}</b>${svgIcon}</a>`;
          });
        }

        document.getElementById("quickview_promo-tag-label").innerHTML = tagLabelHtml;
        document.getElementById("quickview_promo-tag").innerHTML += tagHtml;
      })
      .catch(error => {
        // Handle error if needed
      });
  }

}

customElements.define('product-quickview-modal', ProductQuickviewModal);
