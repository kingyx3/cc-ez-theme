/*
 * Removes one affordance: the "continue with email instead" escape hatch shown
 * while a shopper waits for the mobile OTP.
 *
 * Signing up here verifies a mobile number - the code goes to the phone, and
 * the shopper is mid-verification when the link appears. Following it out of a
 * step that is already waiting on a code is how a half-made account and a
 * second signup attempt happen, so the store does not offer it. Where EasyStore
 * renders the step - /account/auth is the platform's own flow - the link comes
 * from the platform's translation, and no theme deploy can take it out of that
 * template.
 *
 * Text in, visibility out, and nothing else. It reads textContent and hides the
 * element that holds it: it never touches an input, never sets a value, never
 * dispatches an event, and never removes a node the platform's widget may still
 * hold. That is the line whose crossing broke signup with "Customer already
 * exists (phone)" - theme scripts writing into the platform's verification
 * cells - and nothing here goes near it.
 *
 * Setting the store's translation for that link to an empty string makes this a
 * no-op, and it can be deleted at that point.
 */
(() => {
  // "Continue with email instead", "Sign up using your email address instead",
  // and the like. Both halves are required, so an ordinary sentence about email
  // is left alone.
  const EMAIL_FALLBACK = /\b(?:continue|proceed|sign\s*up|sign\s*in|signup|signin|log\s*in|login|register|verify|switch|use)\b[^.!?]{0,32}\be-?mail\b[^.!?]{0,32}\binstead\b/i;
  // Wording the platform shows only once a code is outstanding. Without it on
  // the page nothing is hidden, so a link offered before any code was sent -
  // the choice between signing up by email or by phone - still stands.
  const OTP_STEP = /verification\s+code|one-time\s+password|\botp\b|verify\s+your\s+(?:mobile|phone)|code\s+(?:we\s+)?(?:just\s+)?sent|resend\s+(?:the\s+)?code/i;
  // Markers of a page that has an account step at all, so the rest of the
  // storefront neither scans nor observes anything.
  const AUTH_MARKERS = [
    'form[action*="/account/register"]',
    'form[action*="/account/login"]',
    'form[action*="/account/auth"]',
    'form[action*="/account/recover"]',
  ].join(',');
  // A link this long is a paragraph, not the escape hatch; hiding a paragraph
  // would take instructions with it.
  const LINK_LENGTH = 80;
  const CONTROLS = 'a, button, [role="button"], [role="link"]';

  const own = (element) => ((element && element.textContent) || '').replace(/\s+/g, ' ').trim();
  const pageText = () => (document.body ? document.body.textContent || '' : '');

  // A leaf element holds its own text, so reading it cannot pick up a whole
  // step's worth of copy from a wrapper.
  const isLeaf = (element) => element.children.length === 0;

  // The text sits in the link, in a span inside it, or in a wrapper that holds
  // nothing else. Climb only while the text is still all there is, so the
  // element hidden is the control itself and never its container.
  const controlFor = (element) => {
    let target = element;
    let parent = target.parentElement;
    let hops = 0;
    while (
      parent
      && hops < 3
      && parent !== document.body
      && !parent.matches('form, main')
      && !target.matches(CONTROLS)
      && own(parent) === own(target)
    ) {
      target = parent;
      parent = target.parentElement;
      hops += 1;
    }
    return target;
  };

  // Hidden, not deleted and not blanked: the node stays where the platform put
  // it, and no empty control is left behind to click.
  const hide = (element) => {
    if (element.hidden) return 0;
    element.hidden = true;
    element.style.display = 'none';
    return 1;
  };

  const hideWithin = (root) => {
    if (!root || !root.querySelectorAll) return 0;
    if (!OTP_STEP.test(pageText())) return 0;
    let hidden = 0;
    const candidates = Array.from(root.querySelectorAll('a, button, p, span, small, div, li'));
    if (root.matches && root.matches('a, button, p, span, small, div, li')) candidates.unshift(root);
    candidates.forEach((element) => {
      if (!isLeaf(element)) return;
      const text = own(element);
      if (!text || text.length > LINK_LENGTH) return;
      if (!EMAIL_FALLBACK.test(text)) return;
      hidden += hide(controlFor(element));
    });
    return hidden;
  };

  const hasAccountStep = () => Boolean(document.querySelector(AUTH_MARKERS))
    || OTP_STEP.test(pageText())
    || EMAIL_FALLBACK.test(pageText());

  const start = () => {
    hideWithin(document.body);
    // The platform flow renders its verification step after a submit, so the
    // page is watched - but only on a page that has an account step at all.
    if (!hasAccountStep()) return;

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
        hideWithin(document.body);
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
