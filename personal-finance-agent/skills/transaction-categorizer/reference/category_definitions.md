# Category Definitions

Precise definitions for all 12 values of the `Category` enum.  Use these when
writing pattern rules, when prompting the LLM, and when resolving ambiguous
transactions with the user.

The golden rule: when a transaction fits multiple categories, choose the **most
specific** one.  If you're still unsure, prefer `OTHER` over `UNCATEGORIZED`
(`UNCATEGORIZED` means "not yet classified"; `OTHER` means "classified as
miscellaneous").

---

## HOUSING

**Includes:**
- Mortgage payments (principal + interest combined)
- Rent payments (e-transfer or PAD to a landlord)
- Property tax instalments
- Home insurance premiums
- Condo/strata fees
- Home warranty or maintenance contracts paid monthly
- Storage unit rentals (attached to a home)

**Excludes:**
- Home Depot or IKEA purchases → `SHOPPING`
- Home improvement services paid as one-off charges → `OTHER`
- Furniture purchases → `SHOPPING`
- Airbnb/hotel stays (temporary accommodation) → `TRAVEL`

**Edge cases:**
- `TORONTO PROPERTY TAX` — `HOUSING`, not `UTILITIES`
- A rent payment sent via Interac e-transfer to a person's name — the
  description will look like a regular e-transfer.  If the user has confirmed
  a contact is their landlord, use `HOUSING`; otherwise default to `TRANSFER`
  and ask.
- `CMHC INSURANCE` — `HOUSING` (mortgage insurance, not home contents insurance).

---

## GROCERIES

**Includes:**
- Dedicated supermarkets and grocery chains (Loblaws, Sobeys, Metro, Costco,
  T&T, No Frills, Freshco, Whole Foods, Farm Boy, Fortinos, Zehrs, Longos)
- Ethnic grocery stores (Highland Farms, Nations Fresh Foods, Sunny Supermarket)
- Bulk food stores (Bulk Barn)
- Online grocery delivery platforms billed under a grocery store name

**Excludes:**
- Convenience stores (7-Eleven, Mac's, Hasty Market) → `SHOPPING`
- Gas station food purchases → `TRANSPORTATION` (or `DINING` if clearly a hot meal)
- Shoppers Drug Mart food items → `SHOPPING` (the store is primarily a pharmacy)
- Amazon Fresh or Instacart if billed under Amazon → `SHOPPING`

**Edge cases:**
- **Costco** — always `GROCERIES`, even though Costco sells electronics,
  clothing, and gas.  The primary purchase occasion is grocery restocking.
- **Walmart Supercenter** (description contains "WALMART SUPER") — `GROCERIES`.
  Regular Walmart without "SUPER" → `SHOPPING`.
- **LOBLAWS PC MASTERCARD** — this is a Loblaws credit card payment, not a
  grocery purchase. If seen on a chequing account it may be a payment → `TRANSFER`.
  If seen on a Visa statement with a positive amount, it may be a grocery charge
  on a PC Mastercard → context-dependent; default to `GROCERIES` and flag LOW.
- **Rabba Fine Foods** — convenience + grocery hybrid; classify as `GROCERIES`.

---

## DINING

**Includes:**
- Full-service restaurants, fast food, coffee shops
- Food delivery platforms (Uber Eats, Skip the Dishes, DoorDash)
- Cafeterias and food courts
- Meal kit services (HelloFresh, GoodFood) billed per box
- Bar tabs where food is the primary purchase
- Bakeries, ice cream parlours, juice bars

**Excludes:**
- Grocery stores → `GROCERIES` (even if buying prepared foods)
- Alcohol-only purchases at an LCBO or beer store → `SHOPPING`

**Edge cases:**
- **Tim Hortons** — always `DINING` (coffee + food, even drive-through).
- **Starbucks** — `DINING` not `SUBSCRIPTIONS`, even if paying via a stored
  Starbucks card auto-reload.
- A restaurant charge that appears to be a workplace expense (e.g.,
  "MONTREAL RESTAURANTS EXPENSE") — classify `DINING` first; the user can
  reclassify as a reimbursable business expense if needed.
- **LCBO / Beer Store** — `SHOPPING` by default.  If clearly a restaurant
  bar tab (description includes "BAR" or "GRILL"), use `DINING`.

---

## TRANSPORTATION

**Includes:**
- Gasoline purchases at any gas station (Esso, Petro-Canada, Shell, Pioneer,
  Sunoco, Ultramar)
- Transit passes and top-ups (Presto, TTC, OC Transpo, Go Transit, STM, Translink)
- Rideshare fares (Uber Trips/Rides, Lyft)
- Parking (Green P, Impark, Indigo, SP+)
- Car wash
- Vehicle maintenance and repairs (Jiffy Lube, Midas, Speedy Auto, dealership
  service centres)
- Ferry or bus tickets for commuting
- Via Rail and Amtrak tickets purchased for regular travel (not vacations)

**Excludes:**
- Flights → `TRAVEL`
- Long-distance intercity bus or train tickets for a trip → `TRAVEL`
- Car rental → `TRAVEL`
- Vehicle insurance → classified under `UTILITIES` if a monthly PAD

**Edge cases:**
- **Canadian Tire auto service** — if description includes "AUTO" or the
  transaction is at the service desk, use `TRANSPORTATION`.  A general Canadian
  Tire retail purchase → `SHOPPING`.
- **Uber Eats** vs **Uber Trips** — both appear under "UBER" in the description.
  Use the full description: "UBER EATS" → `DINING`; "UBER TRIP" or "UBER RIDES" →
  `TRANSPORTATION`.
- **Presto autoload** — `TRANSPORTATION` (transit card top-up).

---

## UTILITIES

**Includes:**
- Electricity (Toronto Hydro, Hydro One, Hydro Ottawa, BC Hydro)
- Natural gas (Enbridge Gas, Union Gas, FortisBC)
- Water and sewer (Toronto Water, municipal utilities)
- Internet service (Rogers Internet, Bell Internet, Cogeco, Shaw, Videotron)
- Home phone and wireless (Rogers Wireless, Bell Mobility, Telus, Freedom,
  Koodo, Fido, Public Mobile)
- Cable TV (Rogers Cable, Bell Fibe, Cogeco TV)
- Garbage and waste removal (Waste Management, GFL)

**Excludes:**
- Streaming services → `SUBSCRIPTIONS`
- Cell phone purchases/upgrades → `SHOPPING`
- Rogers or Bell retail store purchases → `SHOPPING`

**Edge cases:**
- A **Rogers** transaction could be wireless (UTILITIES), internet (UTILITIES),
  or a device purchase (SHOPPING). Use UTILITIES as the default for recurring
  Rogers charges; flag anomalously large Rogers charges as LOW confidence.
- **Vehicle insurance** paid as a monthly pre-authorized debit — classify as
  `UTILITIES` (recurring essential bill) even though it is insurance.

---

## SUBSCRIPTIONS

**Includes:**
- Streaming video and audio (Netflix, Crave, Disney+, Paramount+, Spotify,
  Apple Music, YouTube Premium, DAZN)
- Cloud storage (Google One, iCloud, Dropbox, OneDrive)
- Productivity software (Microsoft 365, Adobe Creative Cloud)
- Password managers, security software (1Password, LastPass, Malwarebytes)
- Gym memberships (Goodlife, Equinox, Planet Fitness, Anytime Fitness) billed
  monthly — recurring and membership-based
- News and media subscriptions (Globe and Mail, New York Times, Audible)
- App store subscriptions (Apple.com/Bill, Google Play recurring charges)

**Excludes:**
- One-time software purchases → `SHOPPING`
- Single gym day passes → `SHOPPING`
- Annual insurance premiums → `UTILITIES` or `OTHER`

**Edge cases:**
- **Apple.com/Bill** and **ITUNES** — `SUBSCRIPTIONS`. These are always
  recurring App Store or media charges.
- **Amazon** — distinguish between Amazon.ca purchases (`SHOPPING`),
  Amazon Prime (`SUBSCRIPTIONS`), and Prime Video (`SUBSCRIPTIONS`).
  The description usually differentiates: "AMAZON.CA" → SHOPPING;
  "AMAZON PRIME" or "PRIMEVIDEO.COM" → SUBSCRIPTIONS.
- A gym that also sells one-time personal training sessions billed monthly —
  if it appears to be the same amount each month, use `SUBSCRIPTIONS`; if the
  amount varies, use `SHOPPING`.

---

## SHOPPING

**Includes:**
- General retail (Amazon.ca, Best Buy, Canadian Tire, IKEA, Home Depot, Walmart)
- Clothing (H&M, Zara, Gap, Anthropologie, Roots, Hudson's Bay, Simons)
- Home goods and decor (HomeSense, Marshalls, Winners)
- Books, media (Indigo, Chapters)
- Pharmacies and drug stores (Shoppers Drug Mart, Rexall, London Drugs)
- Alcohol retail (LCBO, The Beer Store, SAQ) when not a bar tab
- Dollar stores (Dollarama, Dollar Tree)
- Sporting goods (Sport Chek, Decathlon)
- Electronics (Best Buy, Apple Store, Canada Computers)
- Entertainment purchases: cinema tickets (Cineplex, Landmark), event tickets
  (Ticketmaster, Eventbrite)
- Convenience stores (7-Eleven, Mac's) — even if groceries are bought there

**Excludes:**
- Costco and large grocery chains → `GROCERIES`
- Online subscriptions from Amazon (Prime, Kindle Unlimited) → `SUBSCRIPTIONS`

**Edge cases:**
- **Shoppers Drug Mart** — default to `SHOPPING`. If the user indicates it
  was a prescription pickup, reclassify as `OTHER` (healthcare) or define a
  future HEALTH category.
- **Home Depot / IKEA** — `SHOPPING` even for home renovation materials.
  Not `HOUSING` (HOUSING is for recurring housing costs, not one-off purchases).

---

## TRAVEL

**Includes:**
- Flights (Air Canada, WestJet, Porter, Flair, Sunwing, and any airline)
- Hotels and accommodation (Marriott, Hilton, Fairmont, Best Western, Airbnb,
  VRBO, Hotels.com, Booking.com)
- Car rentals (Enterprise, Hertz, Budget, Avis, National, Alamo)
- Online travel agencies (Expedia, Kayak, Priceline)
- Intercity/long-distance train and bus tickets used for trips (not commuting)
- Travel insurance
- Airport parking
- NEXUS / Global Entry application fees
- Currency exchange transactions

**Excludes:**
- Local transit (TTC, Presto, Uber) → `TRANSPORTATION`
- Via Rail commuter passes → `TRANSPORTATION`
- Restaurant meals while travelling → `DINING`

**Edge cases:**
- **Airbnb** — always `TRAVEL`, even for a local staycation.
- A large Uber charge in an unfamiliar city — likely `TRANSPORTATION`; flag
  MEDIUM confidence and note it may be travel-related.
- **Via Rail** tickets: short-distance commuter → `TRANSPORTATION`;
  cross-country or vacation → `TRAVEL`.  When ambiguous, default to `TRAVEL`
  since the amount is usually larger.

---

## INCOME

**Includes:**
- Salary and payroll deposits (any "PAYROLL DEPOSIT" or employer name)
- Freelance or contractor payments
- Government transfers: EI, CPP, OAS, CRB, CERB, GST/HST credit
- Tax refunds (Canada Revenue Agency)
- Dividends and investment income distributions
- E-transfers received that are clearly income or reimbursement

**Excludes:**
- E-transfers received from friends for shared expenses → `TRANSFER`
- Refunds from a retailer → negate the original expense category
  (e.g., a Loblaws refund → `GROCERIES` with positive amount), not `INCOME`

**Edge cases:**
- A positive-amount Visa statement item is a **credit or refund**, not income.
  Classify it the same category as the original purchase if knowable; otherwise
  use `OTHER`.
- **E-TRANSFER RECEIVED** — default to `INCOME` for large amounts (over $500)
  that appear on a regular schedule; default to `TRANSFER` for small or
  irregular amounts.

---

## TRANSFER

**Includes:**
- Credit card bill payments (VISA PAYMENT, MASTERCARD PAYMENT)
- Interac e-transfers sent to friends/family (expense sharing, not income)
- Savings account transfers (TFSA, RRSP, FHSA, LIRA contributions)
- Between own accounts (TRANSFER TO / FROM, RBC transfers)
- Canada Revenue Agency tax instalments (not a tax payment at return time —
  those go to `OTHER`)
- Investment account contributions

**Excludes:**
- E-transfers received → could be `INCOME` or `TRANSFER` (see INCOME above)
- Mortgage payments → `HOUSING`
- Rent payments → `HOUSING`

**Edge cases:**
- **VISA PAYMENT RBC AVION** appearing on the chequing account — this is
  paying off the credit card balance. Classify as `TRANSFER`, not a repeat
  of the expenses already captured on the Visa statement. Be careful not to
  double-count: when both chequing and Visa statements are loaded, the credit
  card payment on chequing is `TRANSFER` and the individual Visa charges are
  their respective categories.

---

## OTHER

**Use when:**
- The transaction is clearly identified but does not fit any category above.
- Examples: charitable donations, tax payments (lump sum at filing), legal
  fees, medical/dental bills, vet bills, childcare, tuition, moving costs.

**Do not use OTHER as a lazy default.** Only assign it when you have positively
identified the transaction type and confirmed it has no better bucket.

---

## UNCATEGORIZED

**Meaning:** Not yet processed.  This is the **parser default** — every
transaction starts here unless the parser can pre-assign a category (Visa CSV
category column, mortgage HOUSING, payroll INCOME).

**This value must not remain after the categorizer skill runs.**  If the
two-pass process exhausts all options, assign `OTHER` rather than leaving
`UNCATEGORIZED`.
