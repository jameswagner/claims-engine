# Healthcare Claims & Remittance 101

---

## The Cast of Characters

**Provider** — The entity delivering care. A therapist, physician, hospital, lab. In behavioral health: LCSWs, LMFTs, LPCs, psychologists (PhD/PsyD), psychiatrists (MD).

**Patient** — Receives care. Has insurance (or doesn't).

**Payer** — The insurance company. Commercial: Aetna, Cigna, UnitedHealthcare, BCBS, Humana. Government: Medicare (federal, run by CMS), Medicaid (state-run, jointly funded), TRICARE (military).

**Clearinghouse** — The middleman between provider and payer. Validates claim format, translates between formats, routes to the right payer. Major ones: Change Healthcare (now Optum, handles ~15B claims/year — also the one that got ransomwared in 2024), Availity, Waystar. Providers submit one standard format to the clearinghouse; the clearinghouse handles payer-specific quirks.

**Practice Management System (PMS)** — The administrative software a provider office uses. Scheduling, billing, claim submission. Examples: Kareo, AdvancedMD, athenahealth. Distinct from the EHR.

**EHR (Electronic Health Record)** — Clinical software. Progress notes, treatment plans, e-prescribing. Examples: Epic, Cerner, SimplePractice (behavioral health focused). Often integrates with a PMS or IS the PMS.

---

## Key Code Systems

**CPT Codes** (Current Procedural Terminology) — What was *done*. Published by the AMA. Five digits.

Common behavioral health CPTs:
| Code | Description |
|------|-------------|
| 90791 | Psychiatric diagnostic evaluation |
| 90837 | Individual psychotherapy, 60 min |
| 90834 | Individual psychotherapy, 45 min |
| 90832 | Individual psychotherapy, 30 min |
| 90847 | Family therapy with patient present |
| 96130 | Psychological testing, first hour |

**ICD-10 Codes** — The *diagnosis*. Published by WHO, adapted by CMS. Format: letter + 2 digits + decimal + more digits. F32.1 = major depressive disorder, single episode, moderate.

**Modifier Codes** — Two-character appended to CPT to change its meaning.

Common behavioral health modifiers:
| Modifier | Meaning |
|----------|---------|
| HO | Mental health program (master's level) |
| HN | Bachelor's level |
| GT | Telehealth via interactive audio/video |
| 95 | Synchronous telehealth (newer) |
| 59 | Distinct procedural service (unbundling defense) |

**NPI** (National Provider Identifier) — 10-digit unique ID for every provider in the US. Required on every claim.

**Place of Service (POS)** — Two-digit code. 11 = office, 02 = telehealth (patient not at home), 10 = telehealth (patient at home).

---

## The Claim Lifecycle (Real World)

**1. Prior Authorization (PA)**
Before some services can be rendered, the provider must get the payer to pre-approve. Nightmare in practice. Submitted via EDI 278 or a payer portal. Not required for most outpatient therapy but sometimes required for intensive services or specific diagnoses.

**2. Claim Creation**
After the session, the provider (or billing staff) creates a claim. Professional claims use the CMS-1500 form (physical) or 837P transaction (electronic). Contains: provider NPI, patient demographics, payer ID, date of service, CPT code, ICD-10 code, billed amount, place of service.

**3. Scrubbing**
Clearinghouse runs the claim through edits before sending to the payer. Catches format errors, missing fields, invalid code combinations. Returns a 999 (functional acknowledgment) — accepted or rejected. This is *not* adjudication, just format validation. A scrubbed claim can still be denied by the payer.

**4. Submission to Payer**
Clearinghouse routes the 837P to the payer. Payer returns a 277CA (claim acknowledgment) — accepted into their system for processing.

**5. Adjudication**
The payer decides what to pay. Checks: is the patient covered on the date of service? Is this CPT covered under their plan? Is the provider in-network? Has the deductible been met? What's the fee schedule amount? This can take days to weeks. The output is a determination.

**6. Remittance Advice (835 / EOB)**
The payer sends back an 835 EDI transaction (electronic) or an Explanation of Benefits (EOB) (paper or portal, goes to patient). Contains the adjudication detail: what was billed, what was allowed, what adjustments were made and why (via reason codes), what the patient owes, what the payer paid.

**7. Payment**
Electronic funds transfer (EFT) to the provider's bank account, or check. Usually comes with or shortly after the 835.

**8. Posting**
The practice posts the payment against the claim in the PMS. Reconciles what was expected vs. received. Identifies patient balance to collect.

**9. Denial Management**
Denied claims go to a work queue. Billing staff reviews the reason code, determines if it's correctable (wrong modifier → fix and resubmit) or requires appeal (clinical documentation dispute → write appeal letter).

---

## Financial Terms

**Billed Amount** — What the provider charges. Usually based on a "chargemaster" rate, often significantly higher than what anyone actually pays. This is intentional — it's the starting negotiation point.

**Fee Schedule / Allowed Amount** — What the payer has contractually agreed to pay for a given CPT code from an in-network provider. The real number. Set by negotiation (commercial) or by CMS (Medicare).

**Contractual Adjustment** — The difference between billed and allowed. The provider is contractually obligated to write this off. Not billable to the patient.

**Deductible** — Patient pays 100% of allowed amount until they've spent X in a plan year. Resets January 1.

**Coinsurance** — After deductible, patient pays a percentage (e.g. 20%) of the allowed amount.

**Copay** — Fixed dollar amount patient pays per visit, regardless of allowed amount.

**Patient Responsibility** — Deductible + coinsurance + copay. What actually gets billed to the patient.

**Paid Amount** — What the payer sends to the provider. `allowed_amount - patient_responsibility`.

**Out-of-Network** — Provider has no contract with the payer. Payer may still pay something (at a lower rate) or nothing. Patient usually owes much more. Balance billing (provider bills patient for the difference) is the source of "surprise bill" legislation.

---

## Remittance Reason Codes

Format: `Category-Number`. The category tells you who's responsible.

| Prefix | Category | Meaning |
|--------|----------|---------|
| CO | Contractual Obligation | Provider must write it off — contract says so |
| PR | Patient Responsibility | Patient owes this |
| OA | Other Adjustment | Neither provider nor patient — payer-initiated |
| PI | Payor Initiated | Payer discretionary adjustment |

Common codes:
| Code | Meaning | Action |
|------|---------|--------|
| CO-45 | Charge exceeds fee schedule | Write off the difference |
| CO-97 | Service bundled with another procedure | Review coding, resubmit unbundled or write off |
| CO-4 | Service not covered by plan | Write off or bill patient if plan allows |
| PR-1 | Deductible | Bill patient |
| PR-2 | Coinsurance | Bill patient |
| CO-16 | Claim lacks information | Resubmit with missing info |
| CO-22 | Duplicate claim | Do not resubmit |
| CO-50 | Not medically necessary | Appeal with clinical notes or write off |

---

## EDI Transaction Sets (the plumbing)

The X12 standard governs electronic healthcare transactions. You don't need to read raw EDI but knowing the numbers helps.

| Transaction | Purpose |
|-------------|---------|
| 837P | Professional claim submission |
| 837I | Institutional claim (hospital) |
| 835 | Remittance advice (payment + EOB detail) |
| 270/271 | Eligibility inquiry / response |
| 276/277 | Claim status inquiry / response |
| 278 | Prior authorization request |
| 999 | Functional acknowledgment (clearinghouse accepted/rejected) |
| 277CA | Claim acknowledgment (payer received it) |

---

## Behavioral Health Specifics (relevant to Grow Therapy)

- Most sessions billed as 90837 (60 min) or 90834 (45 min)
- Telehealth modifier (GT or 95) required for remote sessions
- **MHPAEA** (Mental Health Parity and Addiction Equity Act) requires insurers to cover mental health at same level as medical/surgical — but enforcement is inconsistent and a major policy battleground
- **Credentialing**: providers must be credentialed with each payer individually before billing. Takes weeks to months. Major bottleneck for new practices. CAQH is the universal credentialing database most payers pull from
- Grow Therapy's core value prop is handling credentialing and billing so therapists don't have to

---

## How This Project Maps to the Real World

| This project | Real world equivalent |
|---|---|
| UI button "Submit to Clearinghouse" | Automated 837P batch sent via clearinghouse API |
| UI button "Record Adjudication" | 277CA + 835 received from payer, parsed and posted |
| UI button "Record Payment" | EFT confirmed, posted to PMS |
| Rules engine (PayorRule table) | Clearinghouse scrubbing edits + payer-specific policy rules |
| Remit endpoint | 835 ingestion and posting |
| Event timeline | Claim audit trail in PMS |
| Denial + Resubmit flow | Human billing staff working a denial queue |

The UI approximates what a billing team's exception management dashboard looks like. The automated happy path (submit → adjudicate → pay) would in production be driven by queue consumers processing EDI files, not button clicks. The state machine, rules engine, audit trail, and idempotency underneath are the same either way.

---

## Resources

**Foundational**
- [CMS.gov](https://www.cms.gov) — authoritative on Medicare/Medicaid rules, fee schedules, everything official
- [CMS Physician Fee Schedule Lookup](https://www.cms.gov/medicare/payment/fee-schedules/physician) — what Medicare pays for any CPT code
- [NUCC](https://www.nucc.org) — maintains the CMS-1500 form and standard code sets

**Code Lookups**
- [Find-A-Code](https://www.findacode.com) — free CPT/ICD-10 lookup with plain-English explanations
- [X12 Claim Adjustment Reason Codes](https://x12.org/codes/claim-adjustment-reason-codes) — full CO/PR/OA list

**EDI / Clearinghouse**
- [X12.org](https://x12.org) — the standards body for EDI transactions
- Availity has decent free educational content aimed at providers

**Behavioral Health**
- [SAMHSA](https://www.samhsa.gov) — federal behavioral health agency, good policy background
- [CAQH](https://www.caqh.org) — the universal credentialing database
- [Open Minds](https://openminds.com) — behavioral health business intelligence, some free content

**For the interview**
- Read Grow Therapy's blog — they write publicly about the insurance/billing problem they're solving and it'll tell you exactly how they frame the domain
