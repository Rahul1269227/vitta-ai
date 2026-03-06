# Sentinel-Fi Leakage Audit Report

**Client:** {{client_name}}  
**Report Period:** {{report_period}}  
**Generated On:** {{generated_on}}  
**Prepared By:** Sentinel-Fi Audit Engine

---

## 1. Executive Summary

**Total Transactions Scanned:** {{tx_count}}  
**Estimated Annual Leakage:** **INR {{annual_leakage}}**  
**Immediate Recoverable Amount (30 days):** **INR {{recoverable_30d}}**  
**Compliance Risk Score (0-100):** **{{compliance_score}}**

### Top Leak Drivers
- {{driver_1}}
- {{driver_2}}
- {{driver_3}}

---

## 2. Leakage Breakdown (Ghost Money)

| Leak Type | Impact (INR) | Confidence | Priority | Notes |
| --- | ---: | --- | --- | --- |
| Duplicate SaaS | {{dup_saas_amt}} | High | P1 | {{dup_saas_note}} |
| Zombie Subscriptions | {{zombie_amt}} | Medium | P1 | {{zombie_note}} |
| Price Hike Without Usage Growth | {{price_hike_amt}} | Medium | P2 | {{price_hike_note}} |
| Forgotten Free Trials | {{free_trial_amt}} | High | P1 | {{free_trial_note}} |
| Personal-Business Mixing | {{mixing_amt}} | Medium | P2 | {{mixing_note}} |

---

## 3. Tax and GST Anomaly Check (India)

### GST Findings
- **Missing GST invoices:** {{missing_gst_invoices}}
- **Potential missed ITC:** **INR {{missed_itc}}**
- **Likely miscategorized ledger entries:** {{miscategorized_entries}}

### Compliance Risk Flags
- {{tax_flag_1}}
- {{tax_flag_2}}
- {{tax_flag_3}}

---

## 4. Recommended Cleanup Actions

| Action | Mode | Estimated Value (INR) | Effort | Owner |
| --- | --- | ---: | --- | --- |
| Reclassify ledger rows for tax accuracy | Cleanup Agent | {{reclass_value}} | Medium | Finance Ops |
| Cancel duplicate SaaS plans | Cleanup Agent | {{cancel_value}} | Low | Admin |
| Recover receipts from email/WhatsApp | Cleanup Agent | {{receipt_value}} | High | Ops + CA |
| GST reconciliation sheet for CA | Cleanup Agent | {{gst_recon_value}} | Medium | Accounts |

---

## 5. ROI Snapshot

- **One-time Backlog Cleanup fee:** INR {{cleanup_fee}}
- **Projected annual savings unlocked:** INR {{projected_savings}}
- **Payback period:** {{payback_period}}
- **Recommended plan:** {{plan_recommendation}}

---

## 6. Appendix: High-Risk Transactions (Sample)

| Date | Merchant | Amount | Current Category | Suggested Category | Risk |
| --- | --- | ---: | --- | --- | --- |
| {{tx_1_date}} | {{tx_1_merchant}} | {{tx_1_amount}} | {{tx_1_current}} | {{tx_1_suggested}} | {{tx_1_risk}} |
| {{tx_2_date}} | {{tx_2_merchant}} | {{tx_2_amount}} | {{tx_2_current}} | {{tx_2_suggested}} | {{tx_2_risk}} |
| {{tx_3_date}} | {{tx_3_merchant}} | {{tx_3_amount}} | {{tx_3_current}} | {{tx_3_suggested}} | {{tx_3_risk}} |

---

## 7. Notes and Assumptions

- This report is generated from transaction-level pattern analysis and metadata available at the time of scan.
- Final tax treatment should be confirmed by a qualified CA.
- Cleanup actions are executed only after explicit client approval.
