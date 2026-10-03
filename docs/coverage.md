# Policy coverage audit

This executable inventory maps every policy bullet/table row in §§1–6 to its responsible issues. #32 output contracts and #35 comparator remain pending teammate integration. M1–M7 solver rules remain planned. Delivered P1 rows cover monetary representation and ledger validation only; supplier-master override behavior remains planned. Golden data is audit/evaluation evidence only.

Reproduce: `PYTHONPATH=src python3 -m unittest discover -s tests -p test_coverage.py`. Archive SHA-256: `c813449eab9ddc7fc28b04eff85518957035e895b5500fd19e26c0d8ef7f0109`.

Counts mean unique task-qualified source rows matching the exact enum/category selector in JSON. They are not nested occurrence counts, complete behavior tests, or assertions that unkeyed behavior is absent. Bank cases identify account rows rather than individual movements; IC/close use immutable source line IDs because canonical keys can repeat.

| Rule | Policy evidence | Responsible issues | Unique July rows | Status |
|---|---|---|---|---|
| P1-01 | POLITICAS_CONTABLES.md:7 | #31 | 0; requires_evidence_or_synthetic_test | m0_delivered |
| P1-02 | POLITICAS_CONTABLES.md:8 | #33, #34 | 0; requires_evidence_or_synthetic_test | m0_delivered |
| P1-03 | POLITICAS_CONTABLES.md:9 | #33, #34 | 0; requires_evidence_or_synthetic_test | m0_delivered |
| P1-04 | POLITICAS_CONTABLES.md:10 | #33, #34 | 0; requires_evidence_or_synthetic_test | m0_delivered |
| P1-05 | POLITICAS_CONTABLES.md:11 | #33, #34 | 0; requires_evidence_or_synthetic_test | m0_delivered |
| P1-06 | POLITICAS_CONTABLES.md:12 | #34 | 0; requires_evidence_or_synthetic_test | m0_delivered |
| P1-07 | POLITICAS_CONTABLES.md:13 | #29, #34 | 0; requires_evidence_or_synthetic_test | m0_delivered |
| P1-08 | POLITICAS_CONTABLES.md:14 | #42, #45 | 0; requires_evidence_or_synthetic_test | planned |
| P2-01 | POLITICAS_CONTABLES.md:22 | #39, #40 | 283; observed_code_presence | planned |
| P2-02 | POLITICAS_CONTABLES.md:23 | #40, #54 | 9; observed_code_presence | planned |
| P2-03 | POLITICAS_CONTABLES.md:24 | #40, #54 | 1; observed_code_presence | planned |
| P2-04 | POLITICAS_CONTABLES.md:25 | #40, #50 | 3; observed_code_presence | planned |
| P2-05 | POLITICAS_CONTABLES.md:26 | #40, #50 | 3; observed_code_presence | planned |
| P2-06 | POLITICAS_CONTABLES.md:27 | #40, #46, #50 | 1; observed_code_presence | planned |
| P2-07 | POLITICAS_CONTABLES.md:28 | #40, #46, #50 | 0; requires_evidence_or_synthetic_test | planned |
| P2-08 | POLITICAS_CONTABLES.md:29 | #40, #46, #50 | 1; observed_code_presence | planned |
| P2-09 | POLITICAS_CONTABLES.md:30 | #40, #46, #50 | 4; observed_code_presence | planned |
| P2-10 | POLITICAS_CONTABLES.md:36 | #47 | 14; observed_code_presence | planned |
| P2-11 | POLITICAS_CONTABLES.md:37 | #48 | 18; observed_code_presence | planned |
| P2-12 | POLITICAS_CONTABLES.md:46 | #49 | 19; observed_code_presence | planned |
| P2-13 | POLITICAS_CONTABLES.md:51 | #46, #50 | 0; requires_evidence_or_synthetic_test | planned |
| P2-14 | POLITICAS_CONTABLES.md:52 | #49, #51 | 242; observed_code_presence | planned |
| P2-15 | POLITICAS_CONTABLES.md:56 | #46, #50 | 1; observed_code_presence | planned |
| P2-16 | POLITICAS_CONTABLES.md:57 | #46, #50 | 0; requires_evidence_or_synthetic_test | planned |
| P2-17 | POLITICAS_CONTABLES.md:58 | #50 | 0; requires_evidence_or_synthetic_test | planned |
| P2-18 | POLITICAS_CONTABLES.md:62 | #44, #51 | 0; requires_evidence_or_synthetic_test | planned |
| P2-19 | POLITICAS_CONTABLES.md:63 | #44, #51 | 0; requires_evidence_or_synthetic_test | planned |
| P2-20 | POLITICAS_CONTABLES.md:64 | #51 | 0; requires_evidence_or_synthetic_test | planned |
| P2-21 | POLITICAS_CONTABLES.md:65 | #45 | 0; requires_evidence_or_synthetic_test | planned |
| P2-22 | POLITICAS_CONTABLES.md:66 | #52 | 0; requires_evidence_or_synthetic_test | planned |
| P2-23 | POLITICAS_CONTABLES.md:67 | #52 | 0; requires_evidence_or_synthetic_test | planned |
| P2-24 | POLITICAS_CONTABLES.md:68 | #52 | 0; requires_evidence_or_synthetic_test | planned |
| P2-25 | POLITICAS_CONTABLES.md:69 | #52 | 0; requires_evidence_or_synthetic_test | planned |
| P2-26 | POLITICAS_CONTABLES.md:70 | #52 | 0; requires_evidence_or_synthetic_test | planned |
| P2-27 | POLITICAS_CONTABLES.md:71 | #53 | 0; requires_evidence_or_synthetic_test | planned |
| P2-28 | POLITICAS_CONTABLES.md:72 | #53 | 0; requires_evidence_or_synthetic_test | planned |
| P2-29 | POLITICAS_CONTABLES.md:73 | #53 | 0; requires_evidence_or_synthetic_test | planned |
| P2-30 | POLITICAS_CONTABLES.md:74 | #51, #53, #54 | 0; requires_evidence_or_synthetic_test | planned |
| P2-31 | POLITICAS_CONTABLES.md:75 | #31, #54 | 0; requires_evidence_or_synthetic_test | planned |
| P3-01 | POLITICAS_CONTABLES.md:81 | #58, #59 | 0; requires_evidence_or_synthetic_test | planned |
| P3-02 | POLITICAS_CONTABLES.md:82 | #59 | 0; requires_evidence_or_synthetic_test | planned |
| P3-03 | POLITICAS_CONTABLES.md:83 | #64 | 0; requires_evidence_or_synthetic_test | planned |
| P3-04 | POLITICAS_CONTABLES.md:84 | #58, #65, #99 | 1; observed_code_presence | planned |
| P3-05 | POLITICAS_CONTABLES.md:85 | #63 | 0; requires_evidence_or_synthetic_test | planned |
| P3-06 | POLITICAS_CONTABLES.md:86 | #63 | 0; requires_evidence_or_synthetic_test | planned |
| P3-07 | POLITICAS_CONTABLES.md:87 | #63 | 0; requires_evidence_or_synthetic_test | planned |
| P3-08 | POLITICAS_CONTABLES.md:88 | #63 | 0; requires_evidence_or_synthetic_test | planned |
| P3-09 | POLITICAS_CONTABLES.md:89 | #63 | 0; requires_evidence_or_synthetic_test | planned |
| P3-10 | POLITICAS_CONTABLES.md:90 | #63 | 0; requires_evidence_or_synthetic_test | planned |
| P3-11 | POLITICAS_CONTABLES.md:91 | #63 | 0; requires_evidence_or_synthetic_test | planned |
| P3-12 | POLITICAS_CONTABLES.md:92 | #63 | 0; requires_evidence_or_synthetic_test | planned |
| P3-13 | POLITICAS_CONTABLES.md:95 | #57, #64 | 0; requires_evidence_or_synthetic_test | planned |
| P3-14 | POLITICAS_CONTABLES.md:96 | #60 | 0; requires_evidence_or_synthetic_test | planned |
| P3-15 | POLITICAS_CONTABLES.md:97 | #61 | 0; requires_evidence_or_synthetic_test | planned |
| P3-16 | POLITICAS_CONTABLES.md:98 | #31, #62 | 0; requires_evidence_or_synthetic_test | planned |
| P3-17 | POLITICAS_CONTABLES.md:99 | #62 | 0; requires_evidence_or_synthetic_test | planned |
| P3-18 | POLITICAS_CONTABLES.md:100 | #64 | 0; requires_evidence_or_synthetic_test | planned |
| P3-19 | POLITICAS_CONTABLES.md:101 | #64 | 0; requires_evidence_or_synthetic_test | planned |
| P3-20 | POLITICAS_CONTABLES.md:102 | #63, #64 | 0; requires_evidence_or_synthetic_test | planned |
| P3-21 | POLITICAS_CONTABLES.md:103 | #57, #64 | 0; requires_evidence_or_synthetic_test | planned |
| P3-22 | POLITICAS_CONTABLES.md:104 | #63, #64 | 0; requires_evidence_or_synthetic_test | planned |
| P3-23 | POLITICAS_CONTABLES.md:110 | #79, #80, #81 | 0; requires_evidence_or_synthetic_test | planned |
| P3-24 | POLITICAS_CONTABLES.md:111 | #82, #83, #84 | 0; requires_evidence_or_synthetic_test | planned |
| P3-25 | POLITICAS_CONTABLES.md:112 | #82 | 1; observed_code_presence | planned |
| P3-26 | POLITICAS_CONTABLES.md:113 | #82 | 1; observed_code_presence | planned |
| P3-27 | POLITICAS_CONTABLES.md:114 | #83 | 1; observed_code_presence | planned |
| P3-28 | POLITICAS_CONTABLES.md:115 | #83 | 2; observed_code_presence | planned |
| P3-29 | POLITICAS_CONTABLES.md:116 | #84 | 2; observed_code_presence | planned |
| P3-30 | POLITICAS_CONTABLES.md:117 | #85 | 0; requires_evidence_or_synthetic_test | planned |
| P4-01 | POLITICAS_CONTABLES.md:123 | #67, #68, #69 | 0; requires_evidence_or_synthetic_test | planned |
| P4-02 | POLITICAS_CONTABLES.md:124 | #71, #72, #73, #74 | 0; requires_evidence_or_synthetic_test | planned |
| P4-03 | POLITICAS_CONTABLES.md:128 | #71 | 12; observed_code_presence | planned |
| P4-04 | POLITICAS_CONTABLES.md:129 | #71 | 2; observed_code_presence | planned |
| P4-05 | POLITICAS_CONTABLES.md:130 | #70, #71 | 1; observed_code_presence | planned |
| P4-06 | POLITICAS_CONTABLES.md:131 | #71 | 1; observed_code_presence | planned |
| P4-07 | POLITICAS_CONTABLES.md:132 | #72 | 3; observed_code_presence | planned |
| P4-08 | POLITICAS_CONTABLES.md:133 | #72 | 1; observed_code_presence | planned |
| P4-09 | POLITICAS_CONTABLES.md:134 | #70 | 2; observed_code_presence | planned |
| P4-10 | POLITICAS_CONTABLES.md:135 | #70, #72 | 1; observed_code_presence | planned |
| P4-11 | POLITICAS_CONTABLES.md:136 | #73 | 1; observed_code_presence | planned |
| P4-12 | POLITICAS_CONTABLES.md:137 | #71, #85 | 1; observed_code_presence | planned |
| P4-13 | POLITICAS_CONTABLES.md:138 | #73 | 0; requires_evidence_or_synthetic_test | planned |
| P4-14 | POLITICAS_CONTABLES.md:139 | #73 | 2; observed_code_presence | planned |
| P4-15 | POLITICAS_CONTABLES.md:140 | #73 | 1; observed_code_presence | planned |
| P4-16 | POLITICAS_CONTABLES.md:141 | #74 | 1; observed_code_presence | planned |
| P4-17 | POLITICAS_CONTABLES.md:142 | #74 | 1; observed_code_presence | planned |
| P4-18 | POLITICAS_CONTABLES.md:143 | #74 | 1; observed_code_presence | planned |
| P4-19 | POLITICAS_CONTABLES.md:144 | #74 | 3; observed_code_presence | planned |
| P4-20 | POLITICAS_CONTABLES.md:145 | #74 | 1; observed_code_presence | planned |
| P5-01 | POLITICAS_CONTABLES.md:149 | #95, #96, #97 | 57; observed_code_presence | planned |
| P5-02 | POLITICAS_CONTABLES.md:150 | #95 | 0; requires_evidence_or_synthetic_test | planned |
| P5-03 | POLITICAS_CONTABLES.md:151 | #96 | 0; requires_evidence_or_synthetic_test | planned |
| P5-04 | POLITICAS_CONTABLES.md:152 | #97, #103 | 0; requires_evidence_or_synthetic_test | planned |
| P5-05 | POLITICAS_CONTABLES.md:153 | #95 | 0; requires_evidence_or_synthetic_test | planned |
| P5-06 | POLITICAS_CONTABLES.md:154 | #98 | 9; observed_code_presence | planned |
| P5-07 | POLITICAS_CONTABLES.md:155 | #98 | 0; requires_evidence_or_synthetic_test | planned |
| P5-08 | POLITICAS_CONTABLES.md:156 | #98 | 0; requires_evidence_or_synthetic_test | planned |
| P5-09 | POLITICAS_CONTABLES.md:157 | #98 | 0; requires_evidence_or_synthetic_test | planned |
| P5-10 | POLITICAS_CONTABLES.md:158 | #99 | 1; observed_code_presence | planned |
| P5-11 | POLITICAS_CONTABLES.md:159 | #99, #103 | 0; requires_evidence_or_synthetic_test | planned |
| P5-12 | POLITICAS_CONTABLES.md:160 | #100 | 8; observed_code_presence | planned |
| P5-13 | POLITICAS_CONTABLES.md:161 | #100 | 0; requires_evidence_or_synthetic_test | planned |
| P5-14 | POLITICAS_CONTABLES.md:162 | #100 | 0; requires_evidence_or_synthetic_test | planned |
| P5-15 | POLITICAS_CONTABLES.md:163 | #100, #103 | 0; requires_evidence_or_synthetic_test | planned |
| P5-16 | POLITICAS_CONTABLES.md:164 | #101 | 1; observed_code_presence | planned |
| P5-17 | POLITICAS_CONTABLES.md:165 | #101 | 0; requires_evidence_or_synthetic_test | planned |
| P5-18 | POLITICAS_CONTABLES.md:166 | #101 | 0; requires_evidence_or_synthetic_test | planned |
| P5-19 | POLITICAS_CONTABLES.md:167 | #101 | 0; requires_evidence_or_synthetic_test | planned |
| P5-20 | POLITICAS_CONTABLES.md:168 | #102 | 0; requires_evidence_or_synthetic_test | planned |
| P5-21 | POLITICAS_CONTABLES.md:169 | #102 | 0; requires_evidence_or_synthetic_test | planned |
| P6-01 | POLITICAS_CONTABLES.md:173 | #88, #89 | 0; requires_evidence_or_synthetic_test | planned |
| P6-02 | POLITICAS_CONTABLES.md:174 | #90 | 0; requires_evidence_or_synthetic_test | planned |
| P6-03 | POLITICAS_CONTABLES.md:175 | #91 | 0; requires_evidence_or_synthetic_test | planned |
| P6-04 | POLITICAS_CONTABLES.md:176 | #90, #91, #92, #93 | 0; requires_evidence_or_synthetic_test | planned |
| P6-05 | POLITICAS_CONTABLES.md:180 | #90 | 1; observed_code_presence | planned |
| P6-06 | POLITICAS_CONTABLES.md:181 | #91 | 1; observed_code_presence | planned |
| P6-07 | POLITICAS_CONTABLES.md:182 | #92 | 1; observed_code_presence | planned |
| P6-08 | POLITICAS_CONTABLES.md:183 | #92 | 1; observed_code_presence | planned |
| P6-09 | POLITICAS_CONTABLES.md:184 | #73, #93 | 1; observed_code_presence | planned |
| VAR-POST_PAYMENT_BLOCK | roadmap-auditado.md §5 | #46, #50, #109 | 0; unobserved_required_variant | planned |
| VAR-TAX_GARNISHMENT_ORDER | roadmap-auditado.md §5 | #40, #46, #50, #109 | 0; unobserved_required_variant | planned |
| VAR-REGISTER_EMBARGO | roadmap-auditado.md §5 | #40, #46, #50, #109 | 0; unobserved_required_variant | planned |
| VAR-AEAT_EMBARGO | roadmap-auditado.md §5 | #46, #50, #109 | 0; unobserved_required_variant | planned |
| VAR-BOOK_AMOUNT_ERROR | roadmap-auditado.md §5 | #73, #77, #109 | 0; unobserved_required_variant | planned |
| VAR-DOUBTFUL_RECLASS | roadmap-auditado.md §5 | #101, #102, #109 | 0; unobserved_required_variant | planned |
| VAR-UNOBSERVED_TAX_CODES | roadmap-auditado.md §5 | #52, #53, #63, #109 | 0; unobserved_required_variant | planned |
| VAR-NON_CUSTOMER_INSURANCE | roadmap-auditado.md §5 | #84 | 0; unobserved_required_variant | planned |
| VAR-PREPAID_INITIAL_DEFERRAL | roadmap-auditado.md §5 | #98 | 0; unobserved_required_variant | planned |
| VAR-BAD_DEBT_REVERSAL | roadmap-auditado.md §5 | #101 | 0; unobserved_required_variant | planned |
| VAR-GBP_COMBINATIONS | roadmap-auditado.md §5 | #31, #54, #100 | 0; unobserved_required_variant | planned |
| P-DETAIL-12 | POLITICAS_CONTABLES.md:12 | #34 | 0; requires_evidence_or_synthetic_test | m0_delivered |
| P-DETAIL-22 | POLITICAS_CONTABLES.md:22 | #39, #40 | 0; requires_evidence_or_synthetic_test | planned |
| P-DETAIL-28 | POLITICAS_CONTABLES.md:28 | #40, #46, #50 | 0; requires_evidence_or_synthetic_test | planned |
| P-DETAIL-38 | POLITICAS_CONTABLES.md:38 | #48 | 2; observed_code_presence | planned |
| P-DETAIL-39 | POLITICAS_CONTABLES.md:39 | #42, #48 | 3; observed_code_presence | planned |
| P-DETAIL-40 | POLITICAS_CONTABLES.md:40 | #48, #52 | 3; observed_code_presence | planned |
| P-DETAIL-41 | POLITICAS_CONTABLES.md:41 | #48, #52 | 3; observed_code_presence | planned |
| P-DETAIL-42 | POLITICAS_CONTABLES.md:42 | #48, #53 | 2; observed_code_presence | planned |
| P-DETAIL-43 | POLITICAS_CONTABLES.md:43 | #48 | 2; observed_code_presence | planned |
| P-DETAIL-44 | POLITICAS_CONTABLES.md:44 | #48, #59 | 2; observed_code_presence | planned |
| P-DETAIL-45 | POLITICAS_CONTABLES.md:45 | #39, #48 | 1; observed_code_presence | planned |
| P-DETAIL-47 | POLITICAS_CONTABLES.md:47 | #42, #49 | 2; observed_code_presence | planned |
| P-DETAIL-48 | POLITICAS_CONTABLES.md:48 | #46, #49, #50 | 2; observed_code_presence | planned |
| P-DETAIL-49 | POLITICAS_CONTABLES.md:49 | #44, #49 | 9; observed_code_presence | planned |
| P-DETAIL-50 | POLITICAS_CONTABLES.md:50 | #49, #51 | 6; observed_code_presence | planned |
| P-DETAIL-51 | POLITICAS_CONTABLES.md:51 | #46, #50 | 0; requires_evidence_or_synthetic_test | planned |
| P-DETAIL-68 | POLITICAS_CONTABLES.md:68 | #52 | 0; requires_evidence_or_synthetic_test | planned |
| P-DETAIL-70 | POLITICAS_CONTABLES.md:70 | #52 | 0; requires_evidence_or_synthetic_test | planned |
| P-DETAIL-72 | POLITICAS_CONTABLES.md:72 | #53 | 0; requires_evidence_or_synthetic_test | planned |
| P-DETAIL-87 | POLITICAS_CONTABLES.md:87 | #63 | 0; requires_evidence_or_synthetic_test | planned |
| P-DETAIL-89 | POLITICAS_CONTABLES.md:89 | #63 | 0; requires_evidence_or_synthetic_test | planned |
| P-DETAIL-93 | POLITICAS_CONTABLES.md:93 | #63 | 0; requires_evidence_or_synthetic_test | planned |
| P-DETAIL-94 | POLITICAS_CONTABLES.md:94 | #63 | 0; requires_evidence_or_synthetic_test | planned |

All rows, including P-DETAIL reason and tax rows, are included above. Required synthetic variants include certificate expiry, embargo, BOOK_AMOUNT_ERROR, new insolvency/reclassification, unused master tax codes, insurance receipts, initial deferral, impairment reversals and GBP combinations. Synthetic tests must implement the stated behavior from policy evidence and must never invent additional July delivery rows. Full requirements, issue titles, selectors, case IDs and acceptance criteria are in coverage.json.
