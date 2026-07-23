/* ==========================================================================
   theme.js - theme toggle
   --------------------------------------------------------------------------
   Same approach as bottledpepsi.github.io: the toggle only flips the
   data-theme attribute on <html> and saves the choice to localStorage.
   The actual colour fade is done entirely by CSS transitions already
   sitting on every element in style.css, so the toggle button itself never
   touches opacity or timing. That's what makes the cross-fade run every
   time instead of only sometimes.

   Two extra bits on top of the homepage version, since this is a docs
   site rather than a single page:
   - the little knight icon in the sidebar/topbar swaps between the black
     and white piece PNG depending on theme
   - the favicon swaps the same way, using the same two files
   ========================================================================== */

(function () {
  'use strict';

  var KNIGHT_DARK = 'assets/imgs/w_knight.png';  // dark background -> light piece
  var KNIGHT_LIGHT = 'assets/imgs/b_knight.png'; // light background -> dark piece

  function currentTheme() {
    return document.documentElement.getAttribute('data-theme') || 'dark';
  }

  function syncLabel() {
    var toggle = document.getElementById('theme-toggle');
    if (!toggle) return;
    var theme = currentTheme();
    toggle.setAttribute(
      'aria-label',
      theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'
    );
  }

  function syncKnights() {
    var theme = currentTheme();
    var src = theme === 'dark' ? KNIGHT_DARK : KNIGHT_LIGHT;
    document.querySelectorAll('img.knight-icon').forEach(function (img) {
      img.src = src;
    });
    var fav = document.getElementById('favicon');
    if (fav) fav.href = src;
  }

  function setTheme(next) {
    document.documentElement.setAttribute('data-theme', next);
    try { localStorage.setItem('theme', next); } catch (e) { /* private mode */ }
    syncLabel();
    syncKnights();
  }

  function init() {
    syncLabel();
    syncKnights();

    var toggles = document.querySelectorAll('.theme-toggle');
    toggles.forEach(function (toggle) {
      toggle.addEventListener('click', function () {
        var next = currentTheme() === 'dark' ? 'light' : 'dark';
        setTheme(next);
      });
    });
  }

  window.BP_THEME = { init: init, setTheme: setTheme, currentTheme: currentTheme };
})();

// ---------------------------------------------------------------------------
// Mobile sidebar toggle + active nav link
// ---------------------------------------------------------------------------
document.addEventListener('DOMContentLoaded', function () {
  window.BP_THEME.init();

  var navToggle = document.querySelector('.nav-toggle');
  var sidebar = document.querySelector('.sidebar');

  // Overlay behind the mobile drawer: created here rather than hardcoded
  // in every page's HTML, so it can't be forgotten on a new page.
  var overlay = document.querySelector('.sidebar-overlay');
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.className = 'sidebar-overlay';
    document.body.appendChild(overlay);
  }

  function closeSidebar() {
    if (!sidebar) return;
    sidebar.classList.remove('open');
    overlay.classList.remove('open');
    if (navToggle) navToggle.setAttribute('aria-expanded', 'false');
  }

  function openSidebar() {
    if (!sidebar) return;
    sidebar.classList.add('open');
    overlay.classList.add('open');
    if (navToggle) navToggle.setAttribute('aria-expanded', 'true');
  }

  if (navToggle && sidebar) {
    navToggle.addEventListener('click', function () {
      var expanded = sidebar.classList.contains('open');
      if (expanded) closeSidebar(); else openSidebar();
    });

    sidebar.querySelectorAll('a').forEach(function (link) {
      link.addEventListener('click', closeSidebar);
    });

    overlay.addEventListener('click', closeSidebar);

    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeSidebar();
    });
  }

  var here = window.location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('.nav-group a').forEach(function (link) {
    var href = link.getAttribute('href');
    if (href === here || (here === '' && href === 'index.html')) {
      link.classList.add('active');
      link.setAttribute('aria-current', 'page');
    }
  });
});
