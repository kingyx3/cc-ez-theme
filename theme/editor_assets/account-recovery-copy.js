/*
 * Replaces one sentence: the promise of a password reset email.
 *
 * This store recovers an account by confirming a one-time password sent to the
 * shopper's mobile number, and the recovery form asks for that number. Where
 * this theme renders the copy, the template says so directly. Where EasyStore
 * renders the page - /account/auth is the platform's own flow - the sentence
 * comes from the platform's translation, and no theme deploy can change it, so
 * a shopper is told to wait for an email the store never sends.
 *
 * This recovery-copy block is text only, deliberately. It reads and writes
 * textContent on leaf elements: it never touches an input, never sets a value,
 * and never dispatches an event. That is the line whose crossing broke signup
 * with "Customer already exists (phone)" - theme scripts writing into the
 * platform's verification cells - and nothing in this block goes near it.
 *
 * Setting `customer.recover_password.subtext` in the store's translations makes
 * this a no-op, and it can be deleted at that point.
 */
(() => {
  const EMAIL_PROMISE = /send\s+you\s+an\s+e-?mail\s+to\s+reset\s+your\s+password/i;
  const OTP_COPY = 'Confirm your mobile OTP to proceed';
  // Markers of a page that has a recovery step, so the rest of the storefront
  // neither scans nor observes anything.
  const RECOVERY_MARKERS = [
    'form[action="/account/recover"]',
    '#recover',
    '[href="#recover"]',
    '[href*="/account/recover"]',
  ].join(',');

  // A leaf element holds its own text, so replacing it cannot discard markup.
  const isLeaf = (element) => element.children.length === 0;

  const rewriteWithin = (root) => {
    if (!root || !root.querySelectorAll) return 0;
    let rewritten = 0;
    const candidates = Array.from(root.querySelectorAll('p, span, small, div, li'));
    if (root.matches && root.matches('p, span, small, div, li')) candidates.unshift(root);
    candidates.forEach((element) => {
      if (!isLeaf(element)) return;
      if (!EMAIL_PROMISE.test(element.textContent || '')) return;
      element.textContent = OTP_COPY;
      rewritten += 1;
    });
    return rewritten;
  };

  const hasRecoveryStep = () => Boolean(document.querySelector(RECOVERY_MARKERS))
    || EMAIL_PROMISE.test(document.body ? document.body.textContent || '' : '');

  const start = () => {
    // The marker/text probe is much cheaper than materialising every candidate
    // element on a normal storefront page. Run it first so non-account pages do
    // no broad DOM scan at all. Keep the second probe after the rewrite because
    // that was the original rule for whether a dynamically-rendered step needs
    // an observer once the matching sentence has been replaced.
    if (!hasRecoveryStep()) return;
    rewriteWithin(document.body);
    if (!hasRecoveryStep()) return;

    // The platform flow can render its recovery step after a click, so the page
    // is watched - but only on a page that has such a step at all.
    // One rescan per frame at most, and a timer where frames are unavailable.
    const soon = typeof window.requestAnimationFrame === 'function'
      ? (callback) => window.requestAnimationFrame(callback)
      : (callback) => window.setTimeout(callback, 0);
    let queued = false;
    const observer = new MutationObserver(() => {
      if (queued) return;
      queued = true;
      soon(() => {
        queued = false;
        rewriteWithin(document.body);
      });
    });
    observer.observe(document.documentElement, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();

/*
 * Account-details validation that complements EasyStore's server checks.
 *
 * EasyStore rejects some addresses that the browser accepts as type=email, such
 * as a local part beginning with punctuation (`-test@gmail.com`). Catch those
 * before the POST so a validation error does not reload the page. As a safety
 * net for server-only rules, remember non-password profile fields immediately
 * before a valid POST and restore them if EasyStore renders the form with an
 * error response.
 */
(() => {
  'use strict';

  const FORM_SELECTOR = '#details_form';
  const EMAIL_SELECTOR = '[name="details[email]"]';
  const DETAIL_FIELD_SELECTOR = 'input[name^="details["], select[name^="details["], textarea[name^="details["]';
  const DRAFT_KEY = 'cc:account-details-draft';
  const DRAFT_MAX_AGE_MS = 10 * 60 * 1000;
  const EMAIL_MESSAGE = 'Please enter a valid email address.';
  const EMAIL_PATTERN = '[A-Za-z0-9](?:[A-Za-z0-9._%+\\-]*[A-Za-z0-9])?@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+';

  const strictEmail = (value) => {
    const email = String(value || '').trim();
    const parts = email.split('@');
    if (parts.length !== 2) return false;

    const local = parts[0];
    const domain = parts[1];
    if (!/^[A-Za-z0-9](?:[A-Za-z0-9._%+\-]*[A-Za-z0-9])?$/.test(local)) return false;
    if (local.includes('..')) return false;

    const labels = domain.split('.');
    if (labels.length < 2) return false;
    return labels.every((label) => /^[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?$/.test(label));
  };

  const validateEmail = (field) => {
    if (!field) return;
    const value = String(field.value || '').trim();
    if (!value) {
      field.setCustomValidity('');
      return;
    }
    field.setCustomValidity(strictEmail(value) ? '' : EMAIL_MESSAGE);
  };

  const serializableFields = (form) => Array.from(form.querySelectorAll(DETAIL_FIELD_SELECTOR))
    .filter((field) => field.name && String(field.type || '').toLowerCase() !== 'password');

  const saveDraft = (form) => {
    const values = {};
    serializableFields(form).forEach((field) => {
      if (/^(checkbox|radio)$/i.test(String(field.type || ''))) {
        values[field.name] = { checked: Boolean(field.checked), value: field.value };
      } else {
        values[field.name] = { value: field.value };
      }
    });

    try {
      window.sessionStorage.setItem(DRAFT_KEY, JSON.stringify({
        storedAt: Date.now(),
        values,
      }));
    } catch (_error) {
      /* preserving the submission is best-effort */
    }
  };

  const clearDraft = () => {
    try {
      window.sessionStorage.removeItem(DRAFT_KEY);
    } catch (_error) {
      /* nothing to clear */
    }
  };

  const readDraft = () => {
    let raw = null;
    try {
      raw = window.sessionStorage.getItem(DRAFT_KEY);
    } catch (_error) {
      return null;
    }
    if (!raw) return null;

    try {
      const draft = JSON.parse(raw);
      const storedAt = Number(draft && draft.storedAt);
      if (!Number.isFinite(storedAt) || Date.now() - storedAt > DRAFT_MAX_AGE_MS) {
        clearDraft();
        return null;
      }
      return draft && draft.values ? draft.values : null;
    } catch (_error) {
      clearDraft();
      return null;
    }
  };

  const hasServerError = (form) => {
    if (form.querySelector('.errors, .error, [data-form-error], [role="alert"]')) return true;
    return /invalid\s+email\s+address\s+format/i.test(form.textContent || '');
  };

  const restoreDraft = (form) => {
    const values = readDraft();
    if (!values) return;

    serializableFields(form).forEach((field) => {
      const saved = values[field.name];
      if (!saved) return;
      if (/^(checkbox|radio)$/i.test(String(field.type || ''))) {
        field.checked = Boolean(saved.checked) && String(field.value) === String(saved.value);
      } else if (Object.prototype.hasOwnProperty.call(saved, 'value')) {
        field.value = saved.value;
      }
    });
    clearDraft();
  };

  const start = () => {
    const form = document.querySelector(FORM_SELECTOR);
    if (!form) return;

    const email = form.querySelector(EMAIL_SELECTOR);
    if (email) {
      email.setAttribute('type', 'email');
      email.setAttribute('pattern', EMAIL_PATTERN);
      email.setAttribute('title', EMAIL_MESSAGE);
      validateEmail(email);
      ['input', 'change', 'blur'].forEach((type) => {
        email.addEventListener(type, () => validateEmail(email));
      });
    }

    if (document.getElementById('UpdateSuccess')) {
      clearDraft();
    } else if (hasServerError(form)) {
      restoreDraft(form);
      validateEmail(email);
    }

    form.addEventListener('submit', () => {
      validateEmail(email);
      if (form.checkValidity && !form.checkValidity()) return;
      saveDraft(form);
    }, true);
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
