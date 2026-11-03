# #374 (RF-009 create_user) connected-browser results — 3 November 2026

Checker: Claude, using the Claude in Chrome extension in the user's real Chrome on macOS.
Target: http://localhost:18810 (isolated stack, head 1dac61e4), test inbox http://localhost:18815 (Mailpit).
Times are Asia/Seoul, with UTC in brackets.

**Result: PASS on every step that was run.**

| Time | Step | Observed |
| --- | --- | --- |
| 18:09 | Logged in as rf009-admin@example.com, opened Admin → Users | The create form loaded with factory Milana preselected. No Active checkbox in the form, so the account was created with the default (active). |
| 18:10:06 (09:10:06Z) | Created "RF009 Browser Review", rf009-browser-20261103@example.com, role Sales, factory Milana, no password | Green message: **"User created. A password setup link was queued for their email."** `pr374_1_created_message.jpg` |
| 18:10 | Test inbox | Message "Set up your Milana ERP password" to the new address, 6:10 pm. The body greets "Hi RF009 Browser Review", has a localhost:18810/reset-password link, and says it "expires in 60 minutes". |
| 18:11 (09:11Z) | Followed the link, set the test password | "Your password has been reset. You can sign in now." `pr374_2_password_set.jpg` |
| 18:11:43 (09:11:43Z) | Logged in as the new user, opened Profile | Name **RF009 Browser Review**, email **rf009-browser-20261103@example.com**, role **Sales**, department "-". The header shows the user and "Sales". /api/auth/me agrees, with factory MIL. `pr374_3_profile_new_user.jpg` |
| 18:12:18 (09:12:18Z) | Logged back in as admin, refreshed Admin → Users | Row: **RF009 Browser Review · rf009-browser-20261103@example.com · Sales · - · MIL · Active Yes · Online recently, last login Nov 03 06:11 PM.** `pr374_4_admin_users_row.jpg` |
| 18:12:39 (09:12:39Z) | Extra: opened the same setup link again and tried a different password | Refused: **"Invalid or expired reset link"**. The link works only once. `pr374_5_used_link_refused.jpg` |

## Notes (not RF-009 regressions)
- The setup email says "Set up your password", but the page it opens is titled "Reset password", and its success text says "has been reset". That's a small wording mismatch for first-time setup.
- The test stack also lists earlier Codex fixtures ("RF009 Pilot", "RF009 bounded test"). These are expected test data.

## Not covered
- Phone layout and RU/UZ.
- Database readback is Codex's comparison.
- Nothing is marked verified or accepted. No production access.
