/*
 * The referral invitation a shopper arrives with.
 *
 * A referred visitor lands carrying `customer_referral_code`, either as the
 * cookie EasyStore sets from the invitation link or, for a signed-in customer,
 * as their own code. The campaign behind it names the credit the store is
 * offering, so the amount is fetched once and remembered; the invitation is
 * then shown as a popover beside the desktop account icon or as a modal on
 * mobile, until the shopper dismisses it or the three-day window lapses.
 *
 * This was inline in `sections/header.liquid`, re-sent inside the HTML of every
 * page and cacheable by nothing. The three values it needs from Liquid arrive
 * as `window.referralNotificationConfig`; everything else is here.
 *
 * `dismissReferralNotification`, `goToSignupPage`, `closeMobileReferralModal`
 * and `goToSignupPageFromMobile` stay on `window` because `global.js` resolves
 * `data-theme-action` attributes through it. Nothing else is exported.
 */
(() => {
  'use strict';

  const STORAGE_KEY = 'referral_notification_data';
  const COOKIE_NAME = 'customer_referral_code';
  const EXPIRATION_DAYS = 3;
  const MOBILE_MAX_WIDTH = 749;

  const config = window.referralNotificationConfig || {};
  const referralMessageTemplate = config.messageTemplate || '';
  const shopCurrency = config.currency || '';
  const customerReferralCode = config.customerReferralCode || null;

  function updateReferralData(data) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(data));
      return true;
    } catch (error) {
      return false;
    }
  }

  function removeReferralData() {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch (error) {
      // Storage can be unavailable under strict browser privacy policies.
    }
  }

  function readReferralData() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
    } catch (error) {
      removeReferralData();
      return {};
    }
  }

  function getCookie(name) {
    const value = `; ${document.cookie}`;
    const parts = value.split(`; ${name}=`);
    if (parts.length === 2) return parts.pop().split(';').shift();
    return null;
  }

  function removeCookie(name) {
    document.cookie = `${name}=; expires=Thu, 01 Jan 1970 00:00:00 UTC; path=/;`;
  }

  // The window is remembered alongside the credit so a dismissal, and an
  // unanswered invitation, both lapse rather than following the shopper for good.
  function rememberDismissalWindow(referralData) {
    referralData.timestamp = referralData.timestamp || Date.now();
    referralData.expirationDays = referralData.expirationDays || EXPIRATION_DAYS;
  }

  function creditMessage(creditAmount) {
    return referralMessageTemplate
      .replace('__CREDIT_AMOUNT__', creditAmount)
      .replace('__CURRENCY_CODE__', shopCurrency);
  }

  function showReferralNotification() {
    const activeReferralCode = getCookie(COOKIE_NAME) || customerReferralCode;
    const referralData = readReferralData();

    if (referralData.timestamp && referralData.expirationDays) {
      const expirationTime = referralData.timestamp
        + (referralData.expirationDays * 24 * 60 * 60 * 1000);
      if (Date.now() > expirationTime) {
        removeReferralData();
        return;
      }
    }

    if (referralData.dismissed) return;
    if (!activeReferralCode) return;

    if (referralData.creditAmount) {
      displayReferralNotification(referralData.creditAmount);
    } else {
      fetchReferralCampaignData(activeReferralCode);
    }
  }

  function fetchReferralCampaignData(referralCode) {
    fetch(`/customer/referral_program/campaigns/${encodeURIComponent(referralCode)}`)
      .then(response => {
        if (!response.ok) {
          throw new Error('Network response was not ok');
        }
        return response.json();
      })
      .then(data => {
        let refereeCreditAmount = null;
        const campaign = data && data.data && data.data.campaign;
        if (campaign && Array.isArray(campaign.referral_rules)) {
          const refereeRule = campaign.referral_rules.find(rule =>
            rule.target_type === 'referee'
            && rule.event_name === 'customer/create'
            && rule.entitlement
            && rule.entitlement.type === 'credit'
          );

          if (refereeRule) {
            refereeCreditAmount = refereeRule.entitlement.amount;
          }
        }

        const referralData = readReferralData();
        referralData.creditAmount = refereeCreditAmount;
        referralData.dismissed = referralData.dismissed || false;
        referralData.timestamp = Date.now();
        referralData.expirationDays = EXPIRATION_DAYS;
        updateReferralData(referralData);

        displayReferralNotification(refereeCreditAmount);
      })
      .catch(error => {
        removeCookie(COOKIE_NAME);
      });
  }

  function displayReferralNotification(creditAmount = null) {
    if (innerWidth <= MOBILE_MAX_WIDTH) {
      const mobileModal = document.querySelector('#referralMobileModal details');
      const mobileMessageElement = document.getElementById('referralSignupMessageMobile');
      if (!mobileModal || !mobileMessageElement) return;

      if (creditAmount) mobileMessageElement.textContent = creditMessage(creditAmount);
      mobileModal.setAttribute('open', '');
      return;
    }

    const notification = document.getElementById('referralNotification');
    if (!notification) return;

    if (creditAmount) {
      const messageElement = document.getElementById('referralSignupMessage');
      if (messageElement) messageElement.textContent = creditMessage(creditAmount);
    }

    notification.style.display = 'block';
  }

  function dismissReferralNotification() {
    const referralData = readReferralData();
    referralData.dismissed = true;
    rememberDismissalWindow(referralData);
    updateReferralData(referralData);

    const notification = document.getElementById('referralNotification');
    if (notification) notification.style.display = 'none';
  }

  function closeMobileReferralModal() {
    const mobileModal = document.querySelector('#referralMobileModal details');
    if (mobileModal) mobileModal.removeAttribute('open');

    const referralData = readReferralData();
    referralData.dismissed = true;
    rememberDismissalWindow(referralData);
    updateReferralData(referralData);
  }

  window.dismissReferralNotification = dismissReferralNotification;
  window.closeMobileReferralModal = closeMobileReferralModal;

  window.goToSignupPage = () => {
    location.href = '/account/register';
    dismissReferralNotification();
  };

  window.goToSignupPageFromMobile = () => {
    location.href = '/account/register';
    closeMobileReferralModal();
  };

  showReferralNotification();

  // The remembered credit belongs to this visit: the campaign is read again on
  // the next page so a changed offer is never shown from storage.
  addEventListener('beforeunload', () => {
    const referralData = readReferralData();

    if (referralData.creditAmount !== undefined) {
      referralData.creditAmount = null;
      updateReferralData(referralData);
    }
  });
})();
