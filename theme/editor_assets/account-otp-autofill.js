/*
 * Emergency kill switch for theme-side OTP autofill.
 *
 * EasyStore owns the `/account/auth` OTP widget and its fetch/JSON response
 * contract. The live signup flow is currently surfacing `Unexpected token '<'`
 * after OTP, which means a caller expected JSON but received HTML. This theme
 * cannot safely repair that platform response from the browser, and this module
 * is the only shipped theme code that writes into EasyStore's verification
 * cells and dispatches a synthetic completion event.
 *
 * Keep the asset in place so the layout does not need a risky hotfix and the
 * implementation can be restored deliberately after the live platform contract
 * is captured again. For now, EasyStore has exclusive ownership of the OTP
 * inputs: no value writes, no synthetic events, no submit-path interference.
 */
(() => {
  'use strict';
})();
