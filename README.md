# TeamPulse v2.2 — Full README

## What's new in this version

- **"Delete all" button on Recordings.** Respects the current employee
  filter — if you've filtered to one employee, it deletes only theirs
  (with a confirmation prompt showing their name); with no filter, it
  wipes everything for the account. Removes both the database rows and
  the actual screenshot files on disk.
- **"Last online" time per employee**, shown on the Employees page — even
  for employees who currently show as offline on the live dashboard, you
  can see exactly when they were last active.
- **Recordings page now auto-refreshes every 5 seconds** while you're on
  it — no more clicking away to Dashboard and back to see new captures.

## Verified with a real multi-company test (not just written — run)

I tested this with two separate company accounts (3 employees + 2
employees), varied activity levels, and confirmed:
- Each company only ever sees their own recordings and employees
- Filtered bulk-delete on Company A's data never touched Company B's data
- Full bulk-delete correctly removed both database rows and the actual
  screenshot files from disk
- Last-seen times correctly track per-employee, showing null/"Never" for
  an employee who hasn't captured anything yet

This is on top of everything from v2.1 (seat requests, start/stop popups,
expiry warnings, shake-to-correct wrong passwords) and v2.0 (three roles,
IST timestamps, configurable capture interval and retention).

- **No activity percentages shown to the boss.** The system still tracks
  active/idle/offline status internally, but the raw activity number is
  never displayed — only status.
- **Employee-seat requests.** A boss who's hit their employee limit can
  request an increase from the Employees page. You (the admin) see it on
  a "Pending seat requests" table, and can Approve or Deny with one click.
  Approving instantly raises their limit — tested end to end.
- **Live start/stop popups.** When an employee starts or stops sharing
  their screen, the boss's dashboard shows a toast notification within a
  few seconds — no page refresh needed.
- **Expiry countdown warnings.** When a boss logs in with 7, 5, 3, or 1
  day(s) left on their validity date, they get a popup: "Your plan expires
  on [date]. Please renew your plan." Shown once per day, not spammed on
  every page load.
- **Wrong password now visibly highlights the field** — it shakes and
  turns red, on top of the existing error message, so it's obvious what
  to fix.

## The three roles (unchanged core behavior)

1. **Boss** signs up, adds employees (up to their limit), can request more
   seats, sees the dashboard/recordings/settings.
2. **Employee** only logs in (never signs up) with a username/password the
   boss set, lands only on the screen-share page.
3. **Admin (you)** — log in with `admin` / `admin` on the same login form
   as the boss. See every customer, approve/deny seat requests, edit
   validity dates.

## Tested before delivery (not just written — actually run)

- Employee limit enforcement and rejection message
- Seat-increase request → pending → admin approval → limit actually
  updates → boss can then add the new employees
- Start/stop capture events recorded and retrievable by the boss
- Wrong password error messages for boss, employee, distinct from
  "account not found" / "username not found"
- Validity expiration blocking both boss and employee logins

## Setup

```
pip install -r requirements.txt
python app.py
```

## Deploying to Render

Same as before — Language: Python 3, Build: `pip install -r requirements.txt`,
Start: `gunicorn app:app --bind 0.0.0.0:$PORT`.

## Known limitations (worth knowing, not hidden)

- `admin`/`admin` is hardcoded in the source code — fine for a school
  project demo, not something you'd do in a real production app.
- Expiry-warning "shown once per day" tracking uses the browser's
  `sessionStorage`, so it resets if the boss closes and reopens their
  browser tab same day — a minor, low-stakes limitation.
- Free hosting tiers (Render free, etc.) use temporary storage — accounts
  and screenshots can be wiped on a cold restart. Fine for demoing.

