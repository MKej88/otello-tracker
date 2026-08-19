-- Reconcile the FY2025 cash FX anchor to the currencies disclosed by Otello.
-- USD and BRL bank-account exposure are reported directly. The Annual Report also
-- states that Group cash deposits are held in NOK, USD and BRL, so audited total
-- cash less USD/BRL is a source-backed derived NOK residual rather than UNALLOCATED.
-- This changes provenance/coverage, not the NOK value previously assigned to the
-- fixed residual in the economic NAV overlay.

UPDATE source_documents
SET metadata_json = json_set(
    metadata_json,
    '$.economic_nav_input_version', 'economic-nav-inputs-2026-08-19.3',
    '$.exposures[2].currency', 'NOK',
    '$.exposures[2].quality', 'RECONCILED_RESIDUAL_NOK',
    '$.exposures[2].notes', 'Derived by reconciliation: audited total cash less explicitly reported USD and BRL bank-account exposure. The Annual Report states Group cash deposits are held in NOK, USD and BRL, so the remaining cash exposure is classified as NOK. This is a derived source-backed residual, not a directly reported NOK line item.',
    '$.source_locator', 'Annual Report 2025 currency-risk disclosure and foreign-currency exposure table; Group states cash deposits are held in NOK, USD and BRL; bank accounts disclose USD 1.217m and BRL USD-equivalent 12.169m; audited cash is USD 15.881m',
    '$.notes', 'Full source-backed currency allocation for the 2025 cash anchor: USD and BRL are reported directly; NOK is the reconciled residual supported by the disclosed set of cash currencies.',
    '$.allocation_quality', 'FULL_SOURCE_BACKED',
    '$.policy', 'REVALUE_SOURCE_BACKED_USD_BRL_KEEP_NOK_FIXED_KEEP_UNALLOCATED_FIXED'
)
WHERE external_id = 'economic-nav-cash-fx:2025-12-31'
  AND document_type = 'ECONOMIC_NAV_CASH_FX_ANCHOR';
