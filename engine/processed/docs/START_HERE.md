# Same Person or Not? The development set, for browsing

This workbook is a read-only view of the development set in the data room. Your system should read the JSON Lines files in the dev/ folder: they are the source of truth, and the unseen set comes in the same format. Long texts are cut at 32,000 characters here.

Development set: the data you get, without answers. Practice labels: 50 hits from the development set that come with their answers (the Practice labels tab). Unseen set: a separate set you never see, which we run your system on to score you.

## Tabs

- Alerts (440): one row per screening alert: the customer as screened, the link to the customer if the alert has one, and the hit IDs.
- Hits (819): one row per watchlist profile that matched. Decide each of these.
- Customers (72265): the bank's system of record.
- Accounts (86659) and Onboarding (72265): links from account numbers and logins to customers, and from accounts to KYC applicants.
- KYC checks (54488): identity checks by the KYC provider, keyed by applicant ID.
- Notes (31895): support and onboarding notes, filed by the customer's email.
- Search results (16882): web search results by name; most are about namesakes.
- Practice labels (50): answered hits with the path through the files that leads to the answer.
- Policy: the SOP (POLICY.md) and the name variants (name_variants.json).

## How the tabs link

- `Alerts.hit_ids → Hits.hit_id`
- `Alerts.account_ref → Accounts.account_id → Accounts.customer_id → Customers.record_id`
- `Alerts.login_handle → Accounts.login_handle → Customers.record_id`
- `Alerts.email → Customers.email`
- `Accounts.account_id + customer_id → Onboarding.account_id + customer_id → Onboarding.kyc_applicant_id → KYC checks.applicant_id`
- `Customers.email → Notes.requester_email`
- `Hit name → Search results.query (the name's lowercase words in alphabetical order)`

An alert with no link carries only the screened name and attributes: find the customer records that fit.

## Try it

Pick a row in Practice labels, find its hit in Hits and its alert in Alerts, then follow its path column through the other tabs.
