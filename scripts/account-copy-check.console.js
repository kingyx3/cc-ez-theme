/*
 * Paste into the browser console on a live store page to find out why a copy or
 * label change is not showing.
 *
 * Two questions it answers, because both have cost real time:
 *   1. Is this page rendered by this theme at all? /account/auth is EasyStore's
 *      own flow, and no theme deploy can change copy on a page the theme does
 *      not render. Theme-only markers settle it.
 *   2. Is the published build current? It reads the deployed stylesheet and
 *      reports which CSS rules are in it, so "I deployed main" can be checked
 *      rather than assumed.
 *
 * Run it on /account/auth, /account/login, /account/details, or a checkout page.
 */
(async () => {
  const out = (label, value) => console.log(String(label).padEnd(30), value);
  const text = (element) => ((element && element.textContent) || '').replace(/\s+/g, ' ').trim();
  const html = document.documentElement.outerHTML;

  console.log('--- page ---');
  out('path', location.pathname + location.hash);
  out('title', document.title);

  // Markers this theme emits and EasyStore's own auth flow does not.
  const themeMarkers = {
    'recover form': 'form[action="/account/recover"]',
    'RecoverEmail input': '#RecoverEmail',
    'login form': '#form-login',
    'customer login wrapper': '.customer.login',
    'account details email': '#DetailEmail',
    'theme layout header': '.header-wrapper, .section-header',
  };
  console.log('--- is this page the theme\'s ---');
  const found = [];
  Object.keys(themeMarkers).forEach((name) => {
    const hit = Boolean(document.querySelector(themeMarkers[name]));
    if (hit) found.push(name);
    out(name, hit);
  });
  const authTemplateIsTheme = Boolean(
    document.querySelector('form[action="/account/recover"]')
    || document.querySelector('#RecoverEmail')
    || document.querySelector('#form-login')
  );

  console.log('--- deployed stylesheet ---');
  const sheets = Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
    .map((link) => link.href)
    .filter((href) => /base\.css/.test(href));
  out('base.css links', sheets.length ? sheets.join(' ') : '(none found)');
  const cssMarkers = {
    'no-float-label rule': '.field__input.no-float-label::placeholder',
    'label-less field rule': ':not(:has(~ label))::placeholder',
  };
  let css = '';
  for (const href of sheets) {
    try {
      css += await (await fetch(href, { credentials: 'same-origin' })).text();
    } catch (error) {
      out('stylesheet fetch failed', href + ' — ' + error.message);
    }
  }
  Object.keys(cssMarkers).forEach((name) => out(name, css ? css.includes(cssMarkers[name]) : 'could not read'));

  if (/\/account\/(auth|login)/.test(location.pathname) || document.querySelector('#RecoverEmail')) {
    console.log('--- password recovery copy ---');
    const headings = Array.from(document.querySelectorAll('h1, h2, h3'));
    const heading = headings.find((node) => node.id === 'recover')
      || headings.find((node) => /reset your password|recover/i.test(text(node)));
    let paragraph = null;
    for (let node = heading; node && !paragraph; node = node.parentElement) {
      paragraph = node.querySelector ? node.querySelector('p') : null;
      if (!paragraph && node.nextElementSibling) {
        paragraph = node.nextElementSibling.querySelector
          ? node.nextElementSibling.querySelector('p')
          : null;
      }
    }
    out('heading', heading ? text(heading) : '(not found)');
    out('paragraph', paragraph ? text(paragraph) : '(not found)');
    out('mentions email', /email/i.test(text(paragraph)));
    out('mentions OTP', /otp|one-time password/i.test(text(paragraph)));
    out('theme copy in the HTML', /Confirm your mobile/i.test(html));

    console.log('--- verdict ---');
    if (!authTemplateIsTheme) {
      console.log(
        'PLATFORM PAGE: none of the theme\'s recovery markup is here, so EasyStore '
        + 'renders this page and no theme deploy can change its copy. Set '
        + 'customer.recover_password.subtext in the store\'s translations instead.'
      );
    } else if (/Confirm your mobile/i.test(html)) {
      console.log('THEME PAGE, CURRENT BUILD: the OTP copy is published.');
    } else {
      console.log(
        'THEME PAGE, OLD BUILD: this is the theme\'s template but without the OTP '
        + 'copy, so the published theme predates it. Re-upload the artifact from '
        + 'the latest main run and publish it.'
      );
    }
  }

  if (document.querySelector('#DetailEmail')) {
    console.log('--- account email field ---');
    const input = document.querySelector('#DetailEmail');
    const label = document.querySelector('label[for="DetailEmail"]');
    out('label text', JSON.stringify(text(label)));
    out('placeholder', JSON.stringify(input.getAttribute('placeholder') || ''));
    out('value present', Boolean(input.value));

    console.log('--- verdict ---');
    if (!label) console.log('NO LABEL: the field has no label element at all.');
    else if (text(label)) console.log('TITLED: the field names itself as "' + text(label) + '".');
    else console.log(
      'UNTITLED: the label is empty, so this store returns nothing for '
      + 'customer.login.email and the published build has no fallback yet.'
    );
  }

  const labelless = Array.from(document.querySelectorAll('.field__input'))
    .filter((input) => !input.parentElement || !input.parentElement.querySelector('label'));
  if (labelless.length) {
    console.log('--- fields with no label (platform-rendered) ---');
    labelless.forEach((input) => out(
      input.getAttribute('name') || input.id || '(unnamed)',
      'placeholder ' + JSON.stringify(input.getAttribute('placeholder') || '')
    ));
    console.log(
      'A blank placeholder here cannot be fixed from the theme: the text belongs '
      + 'to the platform, so set it in the store\'s translations.'
    );
  }
})();
