/* ==========================================================================
   footer.js
   --------------------------------------------------------------------------
   The site footer, in one place. Edit the FOOTER_HTML string below to
   change the footer across every page - every doc page just needs:

     <div id="site-footer-slot"></div>
     <script src="assets/footer.js"></script>

   No fetch, no separate footer.html - this file IS the footer, so it works
   the same whether the site is opened over http(s) or straight from disk.
   ========================================================================== */

(function () {
  'use strict';

  var FOOTER_HTML =
    '<footer class="site-footer">' +
      '<div class="site-footer-inner">' +

        '<a class="footer-brand-link" href="index.html">' +
          '<img class="knight-icon" src="assets/imgs/w_knight.png" alt="">' +
          '<span>Python Chess</span>' +
        '</a>' +
        '<p class="footer-tagline">A free, open source desktop chess game.</p>' +

        '<nav class="footer-links" aria-label="Footer">' +
          '<a href="https://bottledpepsi.github.io">Homepage &#8599;</a>' +
          '<span class="footer-dot" aria-hidden="true">&middot;</span>' +
          '<a href="https://github.com/bottledpepsi/Python-Chess">GitHub &#8599;</a>' +
          '<span class="footer-dot" aria-hidden="true">&middot;</span>' +
          '<a href="https://github.com/bottledpepsi/Python-Chess/blob/main/LICENSE">GPL-3.0 license &#8599;</a>' +
          '<span class="footer-dot" aria-hidden="true">&middot;</span>' +
          '<a href="https://github.com/bottledpepsi/Python-Chess/issues">Report an issue &#8599;</a>' +
        '</nav>' +

      '</div>' +

      '<div class="site-footer-bottom">' +
        '<p>&copy; <span id="footer-year">2026</span> Python Chess &middot; Free software under the GPL-3.0 license.</p>' +
        '<p>Created by <a href="https://github.com/bottledpepsi">bottledpepsi</a> &middot; Built with <a href="https://www.pygame.org/docs">pygame</a>.</p>' +
      '</div>' +

    '</footer>';

  function init() {
    var slot = document.getElementById('site-footer-slot');
    if (!slot) return;

    slot.innerHTML = FOOTER_HTML;

    var yearEl = slot.querySelector('#footer-year');
    if (yearEl) yearEl.textContent = new Date().getFullYear();

    // The knight icon needs to match the current theme immediately (theme.js
    // normally does this, but it only runs on page load, and this footer is
    // injected slightly after that on the very first paint).
    if (window.BP_THEME && typeof window.BP_THEME.currentTheme === 'function') {
      var img = slot.querySelector('img.knight-icon');
      if (img) {
        img.src = window.BP_THEME.currentTheme() === 'dark'
          ? 'assets/imgs/w_knight.png'
          : 'assets/imgs/b_knight.png';
      }
    }

    document.dispatchEvent(new CustomEvent('footer:loaded'));
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
