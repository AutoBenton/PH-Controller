/*
 * numpad.js -- shared on-screen numeric keypad for <input type="number">.
 *
 * The kiosk is a capacitive touchscreen with no physical keyboard, and Chromium
 * does not raise a native on-screen keyboard, so number inputs are untypable by
 * finger without this. Wraps the already-vendored simple-keyboard library --
 * no new dependency.
 *
 * Usage:
 *     attachNumpad('input[type="number"]');
 *     attachNumpad('#target-val', { onCommit: function(el) { ... } });
 *
 * The keypad instance and its DOM are created lazily on first use, so this file
 * can be loaded in <head> regardless of where simple-keyboard.js sits.
 *
 * ponytail: one shared keypad instance for the whole page, decimal only. If a
 * field ever needs negative values, add a {sign} key to the layout below.
 */

(function () {
  "use strict";

  var keyboard = null;      // simple-keyboard instance (lazily built)
  var wrapEl   = null;      // #numpad-wrap
  var labelEl  = null;      // caption showing which field is being edited
  var valueEl  = null;      // live readout of the value being typed
  var activeEl = null;      // the <input> currently bound
  var activeOpts = null;    // opts for the active input
  var prevValue  = "";      // value on open, restored if entry is unusable
  var prevBodyPad = "";     // body padding-bottom to restore when the pad closes

  function buildDom() {
    wrapEl = document.getElementById("numpad-wrap");
    if (!wrapEl) {
      wrapEl = document.createElement("div");
      wrapEl.id = "numpad-wrap";
      wrapEl.innerHTML =
        '<div class="numpad-inner">' +
        '<div class="numpad-label"></div>' +
        '<div class="numpad-value"></div>' +
        '<div class="numpad-keyboard"></div>' +
        "</div>";
      document.body.appendChild(wrapEl);
    }
    labelEl = wrapEl.querySelector(".numpad-label");
    valueEl = wrapEl.querySelector(".numpad-value");
  }

  function buildKeyboard() {
    var KB = (typeof SimpleKeyboard === "function") ? SimpleKeyboard : SimpleKeyboard.default;
    keyboard = new KB(".numpad-keyboard", {
      onChange: function (val) {
        // While the numpad is open the field is type="text" (see openNumpad),
        // so partial entries like "7." render instead of being coerced to "".
        if (activeEl) activeEl.value = val;
        // Mirror it on the pad too -- the field itself can end up hidden behind
        // the pad on a short screen, so this is the reliable readout.
        if (valueEl) valueEl.textContent = val || "—";
      },
      onKeyPress: function (btn) {
        if (btn === "{done}") commit();
      },
      layout: {
        default: ["1 2 3", "4 5 6", "7 8 9", ". 0 {bksp}", "{done}"]
      },
      display: { "{bksp}": "⌫", "{done}": "Done" },
      theme: "hg-theme-default",
      // Keeps focus on the input when a key is tapped, so blur-to-commit does
      // not fire on every keypress.
      preventMouseDownDefault: true
    });
  }

  function labelFor(el) {
    var lab = el.closest ? el.closest(".field") : null;
    var txt = lab ? lab.querySelector("label") : null;
    if (txt) return txt.textContent.trim();
    return el.getAttribute("aria-label") || el.id || "Value";
  }

  function openNumpad(el, opts) {
    if (activeEl === el) return;
    if (activeEl) commit();          // switching fields commits the previous one

    if (!wrapEl) buildDom();
    if (!keyboard) {
      try { buildKeyboard(); }
      catch (e) { console.error("[numpad] init failed:", e); return; }
    }

    activeEl   = el;
    activeOpts = opts || {};
    prevValue  = el.value;

    // ponytail: type is swapped to text while the pad is open purely so partial
    // decimals ("7.") display -- assigning those to a type="number" input
    // silently blanks it. Native type/min/max/step are restored in commit().
    try { el.type = "text"; } catch (e) { /* older engines: leave as number */ }

    keyboard.setInput(el.value || "");
    labelEl.textContent = labelFor(el);
    valueEl.textContent = el.value || "—";
    wrapEl.classList.add("show");

    // The pad is fixed to the bottom and is tall enough to cover page content
    // behind it (on /config, the Save button sits right underneath). Reserve
    // that much space so everything stays scrollable, and bring the field being
    // edited into view. Harmless on the dashboard, which does not scroll.
    prevBodyPad = document.body.style.paddingBottom;
    document.body.style.paddingBottom = (wrapEl.offsetHeight + 24) + "px";

    // Scroll to the TOP of the viewport, not the centre: on a short kiosk
    // screen the centre can sit inside the pad's own area, hiding the very
    // field being edited. Scroll the whole .field so its label comes too.
    var scrollTo = (el.closest && el.closest(".field")) || el;
    if (scrollTo.scrollIntoView) {
      scrollTo.scrollIntoView({ block: "start" });
      window.scrollBy(0, -12);          // a little breathing room from the edge
    }
  }

  function commit() {
    if (!activeEl) return;
    var el   = activeEl;
    var opts = activeOpts || {};
    var raw  = el.value;

    try {
      el.type = "number";          // restore native validation + spinners
    } finally {
      activeEl   = null;
      activeOpts = null;
      if (wrapEl) wrapEl.classList.remove("show");
      document.body.style.paddingBottom = prevBodyPad;
    }

    var num = parseFloat(raw);
    if (raw === "" || isNaN(num)) {
      el.value = prevValue;        // unusable entry -- put back what was there
    } else {
      var min = parseFloat(el.getAttribute("min"));
      var max = parseFloat(el.getAttribute("max"));
      if (!isNaN(min) && num < min) num = min;
      if (!isNaN(max) && num > max) num = max;
      el.value = String(num);
    }

    el.dispatchEvent(new Event("change", { bubbles: true }));
    if (typeof opts.onCommit === "function") {
      try { opts.onCommit(el); } catch (e) { console.error("[numpad] onCommit:", e); }
    }
  }

  /* Tapping anywhere that is not the pad or the active field commits and closes.
     Deliberately on "click", not "mousedown": closing on mousedown hides the pad
     midway through the tap, so the later click lands on whatever is revealed
     underneath instead of the button actually pressed. */
  document.addEventListener("click", function (ev) {
    if (!activeEl) return;
    if (wrapEl && wrapEl.contains(ev.target)) return;
    if (ev.target === activeEl) return;
    commit();
  });

  document.addEventListener("keydown", function (ev) {
    if (!activeEl) return;
    if (ev.key === "Enter")  { ev.preventDefault(); commit(); }
    if (ev.key === "Escape") { activeEl.value = prevValue; commit(); }
  });

  /**
   * Wire every input matching `selector` to the keypad.
   * opts.onCommit(el) -- called after the value is clamped and written back.
   */
  window.attachNumpad = function (selector, opts) {
    var els = document.querySelectorAll(selector);
    Array.prototype.forEach.call(els, function (el) {
      if (el.dataset.numpadBound) return;
      el.dataset.numpadBound = "1";
      el.addEventListener("focus", function () { openNumpad(el, opts); });
    });
  };

  /* Exposed so callers can force a commit (e.g. before submitting a form). */
  window.commitNumpad = commit;
})();
