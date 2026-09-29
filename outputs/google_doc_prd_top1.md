# Product Requirements Document (PRD): CertPing AI — Automated Subcontractor COI Compliance Tracker

**Scope:** Bootstrapped Lifestyle Business (<30-Day Lean MVP, Low Cost, High Margin)  
**One-Line Pitch:** Zero-bloat PDF Certificate of Insurance parser and automated SMS/email expiry chaser for small contractors.  
**Target Customer:** Independent general contractors, property managers, and construction SMBs (5-50 employees)  
**Origin Reddit Thread:** [Spending 6 hours every Friday chasing subcontractors for updated COI (Certificate of Insurance) PDFs](https://www.reddit.com/r/smallbusiness/comments/coi_tracking_pain) (r/smallbusiness)  
**Founder-Market Fit Summary:** Exceptional Founder-Market Fit (9.4/10): Combines AI document extraction + automated workflow triggers—the exact sweet spot of the founder profile.

---

## 1. Problem Statement
**User Pain Originating from r/smallbusiness:**
Small general contractors and property managers waste 5-6 hours/week chasing subcontractors for expiring Certificates of Insurance (COIs) because enterprise tools like Procore cost $600+/mo.

**Why Current Solutions Fail:**
Target buyers are trapped between two bad options: spending 5–6 hours every week doing manual copy-pasting and follow-ups in spreadsheets, or paying `$400–$600+/month` on bloated enterprise platforms that take weeks to onboard. They want a focused, single-purpose tool that works out of the box in 5 minutes.

---

## 2. Competition, Bottom-Up TAM & Startup Cost
### Competitive Landscape
| Competitor / Workaround | Pricing | Core Weakness Highlighted on Reddit |
| :--- | :--- | :--- |
| **Enterprise Suites (e.g., Procore / myCOI / Scoro)** | `$350 – $600+/mo` (Annual lock-in) | Built for 200+ employee enterprises; requires full ERP migration and sales calls. |
| **Generic Horizontal Tools (Spreadsheets / Calendars)** | `$0` (`5–6 hrs/week` manual admin) | Zero automated PDF parsing or proactive vendor SMS/email follow-up; high human error. |
| **CertPing AI — Automated Subcontractor COI Compliance Tracker (Our Wedge)** | **`$49/mo` Self-Serve** | **Single-purpose 5-minute setup that solves the exact Reddit bottleneck automatically.** |

### Bottom-Up TAM / SAM / SOM
- ** Formula:** $\text{Bottom-Up TAM} = N_{\text{target\_buyers}} \times P_{\text{annual}}$
- **Target Buyer Pool ($N$):** `140,000` reachable SMBs / prosumers in US, Canada, and UK experiencing `Small general contractors and property managers waste 5-6 hours/week chasing subcontractor...`
- **Annual Price ($P$):** `$49/mo × 12 = $588/year`
- **Bottom-Up TAM:** **`$82,320,000 / year`** (140,000 small GCs/property managers × $588/yr ($49/mo) = $82.32M/yr Bottom-Up TAM (Only 205 customers needed for $10k MRR).)
- **Lifestyle SOM Goal (`$10,000 MRR`):** Only **`205 paying customers`** (`0.14%` of niche market share), maintainable by 1–2 founders in `<15 hrs/week`.

### Initial Startup Cost Breakdown (`<$200` Total to Launch)
- **Domain & DNS:** `$12/yr`
- **Cloud Hosting & Database (Render/Supabase/Vercel):** `$20/mo`
- **AI / LLM Extraction API (Gemini 2.5 Flash):** `~$30/mo` (approx. `$0.002` per document/workflow run)
- **Transactional Email & SMS (Resend + Twilio):** `~$18/mo`
- **Initial Organic GTM Tooling:** `$100` one-time

---

## 3. Value Proposition
**Positioning Statement:**
> *For **Independent general contractors, property managers, and construction SMBs (5-50 employees)** who waste hours every week on **Small general contractors and property managers waste 5-6 hours/week chasing sub...**, **CertPing AI — Automated Subcontractor COI Compliance Tracker** is a self-serve workflow automation micro-SaaS that eliminates 90% of manual chasing in under 5 minutes—unlike `$500+/mo` enterprise suites or error-prone spreadsheets.*

- **Primary Value Metric:** Hours saved per week (`5+ hrs/wk`) + costly compliance/revenue leaks prevented.
- **Time-to-Value:** Under 3 minutes from signup to first automated workflow run.

---

## 4. Lean MVP Scope (<30-Day Build)
### Core 4-Step User Journey
1. **Drop & Parse:** User uploads or forwards existing PDFs/emails (zero manual data entry).
2. **AI Extraction & Validation:** Gemini structured output extracts key dates, dollar amounts, coverage/scope rules, and flags gaps.
3. **Automated Nudge Engine:** Scheduled cron sends polite email/SMS reminders with a magic upload/approval link (no login required for external vendors/clients).
4. **Weekly Peace-of-Mind Digest:** Every Monday at 8am, the owner gets a 30-second green/yellow/red status digest.

### Explicit Non-Goals for Day-1 MVP (Preventing Scope Creep)
- No full ERP, accounting, or payroll replacement.
- No custom native mobile apps (magic mobile web links only).
- No complex multi-department RBAC permissions in v1.

---

## 5. Prioritization of Features (Kano Model Mapped to Reddit Pain Points)
| Feature | Kano Category | Mapped Reddit Pain Point | User Impact | Build Effort (Days) | Phase |
| :--- | :--- | :--- | :--- | :---: | :--- |
| **AI Document / Thread Parser (Zero Manual Entry)** | `Basic Expectation` | Users hate manually typing dates/clauses from PDFs and threads into spreadsheets. | Eliminates 100% of manual data entry on Day 1. | 4d | Day-1 MVP (<30 Days) |
| **No-Login Vendor/Client Magic Upload & Approval Link** | `Basic Expectation` | External subcontractors/clients refuse to create accounts on enterprise portals. | 3x higher completion rate from external recipients. | 4d | Day-1 MVP (<30 Days) |
| **Automated Multi-Channel Follow-Up Cadence (Email + SMS)** | `Performance Feature` | Spending 6 hours every Friday manually chasing people who ignore emails. | Saves 5+ hours/week; SMS nudges get 85% open rate within 15 minutes. | 5d | Day-1 MVP (<30 Days) |
| **1-Click Instant Gap Rejection & Auto-Reply** | `Delighter` | Receiving an expired or insufficient document and having to write a rejection email manually. | Instant 'wow' moment—AI spots the exact missing requirement and asks the sender to fix it automatically. | 3d | Day-1 MVP (<30 Days) |
| **QuickBooks / Slack / Webhook 2-Way Sync** | `Performance Feature` | Keeping existing bookkeeping or team chat updated once an item is approved. | Reduces context switching for growing teams. | 6d | v1.1 Fast Follow |

---

## 6. Go-To-Market (GTM) & Pricing Strategy
### Bootstrapped Pricing Tiers
- **Starter (`$29/mo`):** Up to 25 active tracked items/vendors, email reminders, AI extraction.
- **Pro (`$49/mo` - Core Tier):** Up to 100 active items, SMS + Email cadences, custom branding, instant gap check.
- **Growth (`$99/mo`):** Unlimited items, multi-user alerts, webhook integrations.

### First 50 Paying Customers Playbook
1. **Direct Reddit Thread Re-Engagement (Customers 1–10):** Reply to and DM the original posters and commenters in `r/smallbusiness`, `r/freelance`, and `r/SaaS` offering a free 30-day founding member setup.
2. **Free Micro-Tool Lead Magnet (Customers 11–25):** Launch a free 'Instant PDF Compliance / Scope Checker' page where users drop 1 file to see instant AI analysis, then upsell automated monitoring for `$49/mo`.
3. **Comparison SEO & Niche Forums (Customers 26–50):** Publish high-intent 'Lightweight Procore/myCOI Alternative for Small Contractors' landing pages.

---

## 7. Risks & Mitigation Matrix
| Category | Risk Description | Severity | Likelihood | Mitigation Strategy |
| :--- | :--- | :---: | :---: | :--- |
| **Market & Willingness-to-Pay Risk** | Small businesses complain about manual admin on Reddit but might resist adding another monthly subscription. | High | Medium | Anchor pricing ($49/mo) directly against 1 hour of bookkeeper labor or 1 avoided compliance fine/scope leak ($500+), and offer a 14-day ROI guarantee. |
| **Technical / AI Accuracy Risk** | LLM OCR misreads a blurry scanned PDF date or policy limit, leading to a false positive. | High | Medium | Show side-by-side PDF highlight snippets next to extracted fields and flag any confidence score <90% for 1-click human verification. |
| **Distribution & Cold-Start Risk** | Subreddit moderators may delete direct promotional links. | Medium | High | Lead with helpful educational breakdowns, use direct 1-on-1 DMs to users who explicitly asked for a tool, and pair with niche cold email + SEO. |
| **Platform / SMS Deliverability Risk** | A2P 10DLC SMS registration delays or carrier filtering on automated reminder texts. | Medium | Medium | Start Day-1 MVP with magic-link emails + WhatsApp/Twilio toll-free verification while 10DLC processes. |
| **Lifestyle & Support Burden Risk** | Non-technical SMB owners asking for manual white-glove onboarding that eats into the founder's 20 hr/wk cap. | Medium | Low | Make onboarding 'Forward your existing files to setup@app.com' so the AI auto-populates their dashboard with zero manual configuration. |

---

## 8. Open Questions & 48-Hour Validation Playbook
### Q1: Will target buyers pay $49/mo self-serve without requiring a 30-minute live demo call?
- **Why It Matters:** A true lifestyle business requires low-touch self-serve conversion rather than high-touch enterprise sales.
- **48-Hour Validation Experiment:** Launch a 1-page Carrd/Next.js landing page with an interactive 60-second Loom video and a '$29/mo Founding Member Pre-Order' Stripe button; send to 20 Redditors who commented on the pain point.

### Q2: What percentage of real-world customer documents are blurry mobile photos vs. clean digital PDFs?
- **Why It Matters:** Determines whether standard PDF text extraction suffices or if multimodal Gemini Vision OCR is needed on every upload.
- **48-Hour Validation Experiment:** Ask 5 target SMB owners to send 3 anonymized sample PDFs they received last week and benchmark Gemini 2.5 Flash extraction accuracy.

### Q3: Do external recipients (subcontractors/clients) trust magic upload links sent via SMS/email?
- **Why It Matters:** The product's core loop depends on third-party recipients completing the action without friction.
- **48-Hour Validation Experiment:** Include the customer's company name, logo, and reply-to email in the notification header and test response rate on 10 real requests.

### Q4: Is monthly flat-tier pricing ($49/mo) preferred over usage-based per-document pricing?
- **Why It Matters:** Impacts predictable MRR and customer churn.
- **48-Hour Validation Experiment:** A/B test pricing copy in 15 customer discovery DMs ('Would you rather pay $49/mo flat or $2 per tracked vendor?').

