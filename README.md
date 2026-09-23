# home-manager

Household helper. **Version 1** reads two Google Calendars (mine, plus my wife's calendar shared with me) and emails a morning summary of both our days, with any conflicts at the top.

Planned later phases: bills, diet, exercise.

## What the summary contains

- **Conflicts:** busy, timed events that overlap. Either one person is double-booked, or both of us are busy at the same time. All-day events, events marked "Free", and events you've declined are ignored.
- **One section per person**, then **Together** for events on both calendars. Events count as the same when they share a Google event ID and start time, so they're listed once and don't show up as conflicts.
- **Warnings** if a calendar couldn't be read. The email still goes out with whatever did load.

## Where secrets live

Nothing secret is stored in the repo. Everything lives in `~/.config/home-manager/`, or in the folder named by `HOME_MANAGER_CONFIG_DIR` if you set it:

| File | What it is | Created by |
|---|---|---|
| `client_secret.json` | OAuth client from Google Cloud | You (step 5) |
| `token.json` | Your sign-in token, saved with 600 permissions | `auth` command |
| `config.toml` | Calendar IDs and email recipients | You, copied from `config.example.toml` |

The root `.gitignore` also blocks `client_secret*.json`, `token*.json` and `credentials*.json` anywhere in the repo, in case one is ever saved here by accident.

## Google Cloud setup (one time)

Do this signed in as **your** Google account, the one that will read the calendars and send the email. No billing account is needed. Google renames console menus from time to time, so labels may differ slightly.

1. **Create a project.** Go to <https://console.cloud.google.com>, open the project picker at the top, choose **New project**, name it `home-manager`, and create it. Make sure it's selected afterwards.
2. **Turn on the two APIs.** Go to **APIs & Services → Library**, then search for and **Enable** both **Google Calendar API** and **Gmail API**.
3. **Set up the sign-in screen.** Go to **Google Auth Platform** (called *OAuth consent screen* in older consoles) and click **Get started**:
   - App name: `home-manager`. User support email: your address.
   - Audience: **External** (the only option for a personal @gmail.com account).
   - Contact email: your address. Agree to the policy and click **Create**.
4. **Publish the app.** Under **Audience**, click **Publish app** so the status reads **In production**.
   While an External app is in *Testing*, Google expires its sign-in tokens after 7 days, which would break the morning email every week. Publishing doesn't make anything public. The app isn't verified, so at sign-in Google shows "Google hasn't verified this app". That's expected for a personal tool: click **Advanced → Go to home-manager**.
   You don't need to add scopes under **Data Access**. The app asks for them when you sign in.
5. **Create the OAuth client.** Under **Clients**, click **Create client**, pick **Desktop app** as the type, name it `home-manager-cli`, and create it. **Download the JSON right away**, because Google may not show the secret again. Then move it out of Downloads:
   ```sh
   mkdir -p ~/.config/home-manager && chmod 700 ~/.config/home-manager
   mv ~/Downloads/client_secret_*.json ~/.config/home-manager/client_secret.json
   chmod 600 ~/.config/home-manager/client_secret.json
   ```
6. **Have your wife share her calendar with you.** She does this in her own account at <https://calendar.google.com>: **Settings → (her calendar under "Settings for my calendars") → Share with specific people or groups → Add people**. She enters your address and picks **See all event details**. If she picks *See only free/busy*, her events show up as "(busy)" with no titles. You'll get an email; open the link in it to add her calendar to your account. The ID of her main calendar is her email address.
7. **Write the config.**
   ```sh
   cp config.example.toml ~/.config/home-manager/config.toml
   ```
   Edit it: set `timezone`, change the labels to your names, set her calendar `id`, and set `[email] to`.
8. **Sign in.** This opens a browser. Accept the unverified-app warning from step 4 and allow both permissions: *view your calendars* (read-only) and *send email on your behalf*.
   ```sh
   uv run python -m home_manager auth
   ```
9. **Check that both calendars are visible, then preview the summary:**
   ```sh
   uv run python -m home_manager calendars   # her calendar should be listed
   uv run python -m home_manager summary     # prints without sending
   uv run python -m home_manager summary --send
   ```

If you ever need to revoke access, go to <https://myaccount.google.com/permissions>, remove `home-manager`, and delete `~/.config/home-manager/token.json`.

## Commands

Run from this folder. `uv` installs Python 3.12+ and the dependencies on first use.

```sh
uv run python -m home_manager auth                      # sign in (browser)
uv run python -m home_manager calendars                 # list readable calendar IDs
uv run python -m home_manager summary [--date YYYY-MM-DD] [--send]
uv run pytest                                           # tests; no Google access needed
uv run pytest tests/test_summary.py::test_format_summary   # one test
```

## Morning schedule (macOS)

`launchd/com.ai-lab.home-manager.plist` runs `summary --send` every day at 7:00. If the Mac is asleep at 7:00, the job runs when it wakes. If the Mac is shut down, that day's email is skipped. Output goes to `~/Library/Logs/home-manager.log`.

```sh
cp launchd/com.ai-lab.home-manager.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ai-lab.home-manager.plist
launchctl kickstart gui/$(id -u)/com.ai-lab.home-manager    # run once now to test
# to remove: launchctl bootout gui/$(id -u)/com.ai-lab.home-manager
```

The plist contains absolute paths to this folder and to `uv`. Update them if either moves.

## Code layout

- `home_manager/config.py`: config loading and secret file locations
- `home_manager/google_auth.py`: OAuth. Only `auth` opens a browser, so the scheduled job fails with a clear message instead of hanging.
- `home_manager/events.py`: reads events from the Calendar API (read-only)
- `home_manager/summary.py`: merges shared events, finds conflicts, formats the text. No network access, so it's all covered by tests.
- `home_manager/delivery.py`: sends the email through the Gmail API
