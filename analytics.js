// analytics.js — Tuenjai Panichkroup Dashboard Suite
// Include AFTER the gtag.js initialization snippet on every dashboard page.
// All functions are safe to call before window.onload.

(function(window) {
  'use strict';

  // ── Configuration ──────────────────────────────────────────────────────────
  // Set DASHBOARD_NAME on each HTML page before including this script:
  //   <script>window.DASHBOARD_NAME = 'sales';</script>
  //   Valid values: 'index' | 'sales' | 'fraud' | 'product'
  var DASHBOARD = window.DASHBOARD_NAME || 'unknown';

  // ── Guard: only fire if gtag is available ──────────────────────────────────
  function track(eventName, params) {
    if (typeof window.gtag !== 'function') return;
    window.gtag('event', eventName, params || {});
  }

  // ── Helpers ────────────────────────────────────────────────────────────────

  // Derives the broadest active filter scope from current filter state.
  // Call this from each dashboard's filter variables.
  // Pass the current values of fStore, fDM, fRM (strings, empty = not set).
  function filterScope(fStore, fDM, fRM) {
    if (fStore) return 'store';
    if (fDM)    return 'dm';
    if (fRM)    return 'rm';
    return 'company';
  }


  // ── Events ─────────────────────────────────────────────────────────────────

  // dashboard.viewed — fire once after data loads successfully
  // Call from inside .then(d=>{D=d; init(); Analytics.dashboardViewed(D);})
  // or equivalent init function after D is populated.
  function dashboardViewed(D) {
    var params = {
      dashboard_name: DASHBOARD,
      data_month:     (D && D.month26)      || '',
      days_elapsed:   (D && D.days_elapsed) || 0
    };
    if (DASHBOARD === 'product' && D && D.products) {
      params.sku_count = D.products.length;
    }
    track('dashboard_viewed', params);
  }

  // filter.applied — fire from onFilter() after fRM/fDM/fStore/fType are updated
  // Pass the updated filter values directly.
  function filterApplied(filterType, fRM, fDM, fStore) {
    track('filter_applied', {
      dashboard_name: DASHBOARD,
      filter_type:    filterType,   // 'rm' | 'dm' | 'store' | 'type' | 'search'
      filter_scope:   filterScope(fStore, fDM, fRM),
      filter_rm:      fRM    || '',
      filter_dm:      fDM    || '',
      filter_store:   fStore || ''
    });
  }

  // filter.reset — fire from resetFilter()
  function filterReset() {
    track('filter_reset', { dashboard_name: DASHBOARD });
  }

  // view.changed — fire from goHome(), goRM(), goDM(), goStore(), goExec(), tab clicks
  // viewName examples: 'home' | 'rm' | 'dm' | 'store' | 'exec' | 'report'
  //                    'overview' | 'store_risk' | 'cashiers' | 'bills' | 'time'
  function viewChanged(viewName, previousView) {
    track('view_changed', {
      dashboard_name: DASHBOARD,
      view_name:      viewName,
      previous_view:  previousView || ''
    });
  }

  // dashboard.navigated — fire from hub links in index.html
  // destination: 'sales' | 'fraud' | 'product'
  function dashboardNavigated(destination) {
    track('dashboard_navigated', { destination: destination });
  }

  // search.performed — fire from product dashboard search (debounce 500ms)
  // Do NOT pass the query string — only its length and result count.
  function searchPerformed(queryLength, resultsCount) {
    track('search_performed', {
      dashboard_name: DASHBOARD,
      query_length:   queryLength,
      results_count:  resultsCount
    });
  }

  // linetype_modal.viewed — fire from showLinetypeModal()
  function linetypeModalViewed(fRM, fDM, fStore) {
    track('linetype_modal_viewed', {
      dashboard_name: DASHBOARD,
      filter_scope:   filterScope(fStore, fDM, fRM)
    });
  }

  // sort.changed — fire from sortProd()
  // sortColumn: 's26' | 'q26' | 'gp_pct' | 's_yoy' | etc.
  // direction: 'asc' | 'desc'
  function sortChanged(sortColumn, direction) {
    track('sort_changed', {
      dashboard_name: DASHBOARD,
      sort_column:    sortColumn,
      sort_direction: direction
    });
  }

  // data_load.failed — fire from .catch() handlers
  // errorType: 'fetch_failed' | 'json_parse_error' | 'init_error'
  function dataLoadFailed(errorType) {
    track('data_load_failed', {
      dashboard_name: DASHBOARD,
      error_type:     errorType
    });
  }

  // dashboard.error — attach to window.onerror for unhandled JS errors
  function dashboardError(errorMessage) {
    track('dashboard_error', {
      dashboard_name: DASHBOARD,
      error_message:  (errorMessage || '').substring(0, 100)
    });
  }


  // ── Global error handler ───────────────────────────────────────────────────
  // Attach once — catches unhandled errors on any dashboard
  var _origOnError = window.onerror;
  window.onerror = function(msg, src, line, col, err) {
    dashboardError(msg);
    if (typeof _origOnError === 'function') _origOnError(msg, src, line, col, err);
    return false; // don't suppress error
  };


  // ── Search debounce helper ─────────────────────────────────────────────────
  // Use in product dashboard search input handler:
  //   input.addEventListener('input', Analytics.onSearchInput);
  var _searchTimer = null;
  function onSearchInput(getQueryLength, getResultsCount) {
    // Returns an event handler suitable for addEventListener('input', ...)
    return function() {
      clearTimeout(_searchTimer);
      _searchTimer = setTimeout(function() {
        searchPerformed(getQueryLength(), getResultsCount());
      }, 500);
    };
  }


  // ── Public API ─────────────────────────────────────────────────────────────
  window.Analytics = {
    dashboardViewed:     dashboardViewed,
    filterApplied:       filterApplied,
    filterReset:         filterReset,
    viewChanged:         viewChanged,
    dashboardNavigated:  dashboardNavigated,
    searchPerformed:     searchPerformed,
    linetypeModalViewed: linetypeModalViewed,
    sortChanged:         sortChanged,
    dataLoadFailed:      dataLoadFailed,
    dashboardError:      dashboardError,
    onSearchInput:       onSearchInput,
    filterScope:         filterScope  // exposed for debugging
  };

})(window);
