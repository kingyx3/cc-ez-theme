/*
 * Spreads an autofilled one-time code across the platform's six cells.
 *
 * The widget at /account/auth/send is EasyStore's, not this theme's. It renders
 * six `input type="number"` cells in `#otp-form`, and `maxlength="1"` does
 * nothing on a number input, so when Android's SMS suggestion is tapped the
 * whole code lands in the focused cell and the other five stay empty. The
 * widget already spreads a real clipboard paste correctly; it just never sees a
 * paste event from autofill, which arrives as a plain input.
 *
 * Why this is written so carefully. Theme code has broken signup here before:
 * PR #65 and PR #66 wrote into these cells and fired input and change on every
 * one of them, two scripts ended up competing for the same fields, the widget's
 * own submit ran more than once, and the second POST came back "Customer
 * already exists (phone)". b228492 reverted all of it, and the missing piece
 * was named at the time - the widget's real markup. It has since been read, and
 * this is what its own handler does on each cell:
 *
 *     if (input.value.length >= 1) {
 *       if (index < otp_inputs.length - 1) otp_inputs[index + 1].focus();
 *       if (index === 5) submitOTP();
 *     }
 *
 * `submitOTP()` has exactly one trigger: an input event on the last cell. So a
 * fix is safe precisely when it emits that event once and no other. This module
 * fills the cells by assignment, which the widget reads because it keeps no
 * state of its own, and emits a single input event on the last cell - the same
 * one event a customer's sixth keystroke produces. Nothing is dispatched on any
 * other cell, `change` is never dispatched at all, and the completion event is
 * only sent when all six cells are actually filled, so a short code cannot post
 * a partial verification.
 */
(() => {
  const CELLS = '#otp-form .otp-input';

  // Set while this module is writing, so the one event it emits cannot re-enter
  // the handler below and start a second spread.
  let writing = false;
  // Set once a completed code has been handed to the widget. Autofill can fire
  // input more than once for a single suggestion, and without this latch the
  // second one would post the verification again - the original outage.
  let handedOver = false;

  const cellsNow = () => Array.from(document.querySelectorAll(CELLS));

  const onInput = (event) => {
    if (writing) return;

    const target = event.target;
    if (!target || !target.matches || !target.matches(CELLS)) return;

    const cells = cellsNow();
    if (cells.length < 2) return;

    // A cell going empty means the customer is editing again, so a later
    // completion is a new code rather than a repeat of the one already sent.
    if (cells.some((cell) => cell.value === '')) handedOver = false;

    const digits = String(target.value || '').replace(/\D/g, '');
    // One digit is ordinary typing, and the widget handles that itself.
    if (digits.length < 2) return;

    // A full-length code belongs at the start whichever cell received it; a
    // shorter run starts where it landed, which is what the widget's own paste
    // handler does.
    const start = digits.length >= cells.length ? 0 : cells.indexOf(target);
    if (start < 0) return;

    writing = true;
    cells.forEach((cell, index) => {
      if (index < start) return;
      const digit = digits[index - start];
      // Assignment only. The widget reads value at submit time, so no event is
      // needed to make this visible, and every event not sent is a submit not
      // triggered.
      cell.value = digit === undefined ? cell.value : digit;
    });
    writing = false;

    const complete = cells.every((cell) => cell.value !== '');
    if (!complete || handedOver) return;

    const last = cells[cells.length - 1];
    handedOver = true;

    // Deferred so the browser's own input event finishes propagating to the
    // widget's handler for the cell that was autofilled before the completion
    // event arrives. That keeps the order identical to typing: earlier cells
    // settle, then the last one completes the code.
    window.requestAnimationFrame(() => {
      writing = true;
      last.dispatchEvent(new Event('input', { bubbles: true }));
      writing = false;
    });
  };

  // Capture, so the cells hold their final single digits before the widget's
  // own handler for this event runs and reads them.
  document.addEventListener('input', onInput, true);
})();
