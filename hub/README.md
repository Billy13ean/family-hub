# Family hub: text Claude to run the household

Nick and his wife text a **Family Hub** contact in iMessage:

> Add soccer Saturday 2 to 3 at Field 4
> Put milk and eggs on the grocery list
> What's going on this weekend?
> Electric bill is paid

A Claude Code session on the Mac mini reads each text through the official
[iMessage channel plugin](https://github.com/anthropics/claude-plugins-official/tree/main/external_plugins/imessage).
It updates Apple Calendar and Reminders through `./hm`, then replies in the
same thread. Every morning the hub also texts a digest of the day: conflicts,
events, bills due soon and anything due today.

## How it fits together

```
iPhones ──iMessage──▶ Family Hub's Apple Account, signed in on a Mac of its own
                      (a macOS VM on your desktop, or a separate macOS user)
                            │
                            ▼
                      Terminal: start-hub.command
                        ├─ Claude Code + iMessage plugin   (may only run ./hm)
                        └─ ./hm digest-loop                (7:00 digest)
                            │  EventKit
                            ▼
                      iCloud: Household calendar  ◀── shared with you both
                              Grocery / To-Do / Bills Reminders lists
```

**Why the hub gets its own Apple Account.** The iMessage plugin reads every
text that reaches the Mac it runs on. If it used your Apple Account, every text
your wife sends *you* would reach Claude. With its own account, only texts sent
to Family Hub arrive, and only the allowlisted numbers are acted on.

**What it can and can't do.** `hub-settings.json`, which `start-hub.command` passes to Claude Code, runs the session in
`dontAsk` mode. It may only run `./hm ...`, reply by iMessage, and read photo
attachments. Everything else is denied without a prompt, which matters because
no one is at the terminal to approve prompts. `./hm` only changes the
Household calendar and the Reminders lists shared with the hub. Personal
calendars shared with it are read-only.

## Setup

Allow about an hour. Steps 1–3 depend on where the hub runs. Everything after
that happens **inside the hub's Mac** (the VM, or the Family Hub user).

### 1. Pick where the hub runs

Either way, it keeps running while you use your own account.

**Option A: a macOS virtual machine (recommended).** A separate Mac in a
window on your desktop. It can't see your files, keychain or Messages, and you
can stop it any time to free its memory. Apple supports Messages and iCloud in
VMs when the host runs macOS Sequoia or later.

1. Install [VirtualBuddy](https://github.com/insidegui/VirtualBuddy) (free);
   UTM also works.
2. Create a macOS VM with **macOS 26.2 or later**. 26.1 had a bug that
   blocked Apple sign-in in VMs. Name it "Family Hub" and give it 4 CPU cores,
   6 GB of memory and a 64 GB disk.
3. In the VM's Setup Assistant, create a local user named `familyhub`. You can
   skip the Apple Account screen for now. Skip FileVault in the VM; your Mac's
   own encryption covers the VM's disk.
4. Inside the VM:
   - System Settings → Users & Groups → **Automatically log in as** `familyhub`.
   - System Settings → Energy → turn on **Prevent automatic sleeping**.
   - Don't set up shared folders with your Mac.
5. When you need the memory back, shut the VM down. After the Mac mini
   restarts, open VirtualBuddy and start the VM. The hub comes back by itself
   and answers anything sent while it was off.

**Option B: a separate macOS user.** Lighter, since it shares your running
macOS, but less isolated.

1. System Settings → Users & Groups → **Add User**. Make it **Standard**, full
   name "Family Hub", account name `familyhub`.
2. System Settings → Control Center → **Fast User Switching** → Show in Menu Bar.
3. Switch to Family Hub from the menu bar to set it up, then switch back. It
   keeps running in the background.
4. After a restart, log into Family Hub first, then your account. Automatic
   login doesn't work with FileVault on.

### 2. Create the hub's Apple Account (on real Mac hardware, not in the VM)

Apple doesn't allow creating an Apple Account inside a VM, and it's quick to
block new accounts that show up in several places at once (website, App Store,
VM). What worked: one attempt, from a temporary macOS user on the Mac mini.

1. On the Mac mini: System Settings → Users & Groups → **Add User** (Standard,
   for example "Hub Setup"). Log into it.
2. System Settings → **Sign in** → **Don't have an account?** Name it
   "Family Hub", use your own birthday, choose **Get a free iCloud email
   address**, and use a family mobile number for the verification code.
3. Don't retry if it refuses: wait a day. Repeated attempts extend Apple's block.
4. In the VM: System Settings → **Sign in** with the new account.
5. Once the VM works, sign the temporary user out of iMessage (Messages →
   Settings → iMessage → Sign Out), so hub texts only land in the VM. You can
   keep the user as a backup or delete it.

On your phone and your wife's, save the address as a contact named
**Family Hub**.

### 3. Turn on what the hub uses (inside the hub's Mac)

1. System Settings → your Family Hub name → **iCloud**. Turn on **Calendars**
   and **Reminders**. Turn off Photos and iCloud Drive; the hub doesn't need them.
2. Open **Messages**, check it's signed in to the hub's account, and text the
   Family Hub contact from your phone to make sure messages arrive. If iMessage
   won't activate on a brand-new account, wait a day and try again.

### 4. Share the calendar and lists from your iPhone

Keep them in **your** iCloud account and share them, so the family's data
doesn't depend on the hub account.

- **Household calendar:** in the Calendar app, tap Calendars → **Add
  Calendar** → name it "Household" (under iCloud). Tap ⓘ next to it → **Add
  Person**. Add your wife and the Family Hub address, with **Allow Editing** on.
- **Reminders lists:** create **Grocery** (list type Groceries), **To-Do** and
  **Bills**. On each, tap ⋯ → **Share List** and invite your wife and Family Hub.
- **Personal calendars (optional):** share yours with Family Hub with Allow
  Editing **off**, and have your wife do the same. The hub can then warn about
  clashes. It never changes them.
- In the hub's Mac, accept each invitation. They appear in Calendar and
  Reminders there, or in the hub's iCloud email.

The names Household and Bills are the defaults. If you use others, set them in
the config file (step 7).

### 5. Install the tools (inside the hub's Mac)

In Terminal:

```sh
xcode-select --install                             # git
curl -LsSf https://astral.sh/uv/install.sh | sh    # uv (Python)
curl -fsSL https://bun.sh/install | bash           # Bun, for the iMessage plugin
curl -fsSL https://claude.ai/install.sh | bash     # Claude Code
```

Close and reopen Terminal, then clone the repo. It's private, so paste a GitHub
personal access token when git asks for a password (github.com → Settings →
Developer settings → Fine-grained tokens, read-only access to `family-hub`).
Once the repo is public, no token is needed:

```sh
git clone https://github.com/Billy13ean/family-hub.git ~/family-hub
```

### 6. Give Terminal its permissions (inside the hub's Mac)

1. System Settings → Privacy & Security → **Full Disk Access** → turn on
   **Terminal**. The iMessage plugin needs it to read the Messages database.
2. Then, in Terminal:

   ```sh
   cd ~/family-hub/hub
   ./hm setup
   ```

   Click **Allow** on the Calendars and Reminders prompts. `setup` then lists
   every calendar and list the hub can see, and says if anything is missing,
   such as an invitation not accepted yet.

### 7. Config and family details (inside the hub's Mac)

```sh
mkdir -p ~/.config/home-manager && chmod 700 ~/.config/home-manager
cp ~/family-hub/config.example.toml ~/.config/home-manager/config.toml
open -e ~/.config/home-manager/config.toml     # digest phone numbers, calendar names

cd ~/family-hub/hub
cp CLAUDE.local.example.md CLAUDE.local.md
open -e CLAUDE.local.md                        # names, numbers, kids, usual places
```

Test the digest now. You should get a text from Family Hub. The first time,
macOS asks whether Terminal may control Messages: click **OK**.

```sh
./hm summary            # prints it
./hm summary --send     # texts it
```

### 8. Install the iMessage plugin and set the allowlist (inside the hub's Mac)

```sh
cd ~/family-hub/hub
claude            # log in with your claude.ai account and trust this folder
```

In Claude Code, run `/plugin install imessage@claude-plugins-official`, pick
**user** scope, then `/exit`.

Now write the allowlist. Use your and your wife's handles exactly as Messages
shows them: `+1` and the digits, or an Apple Account email.

```sh
mkdir -p ~/.claude/channels/imessage && chmod 700 ~/.claude/channels/imessage
cat > ~/.claude/channels/imessage/access.json <<'JSON'
{
  "dmPolicy": "allowlist",
  "allowFrom": ["+15551234567", "+15557654321"],
  "groups": {},
  "pending": {},
  "chunkMode": "newline"
}
JSON
chmod 600 ~/.claude/channels/imessage/access.json
```

The allowlist is edited by hand here, not with `/imessage:access`. The hub's
locked-down settings block that skill on purpose, so a text message can never
talk the session into adding someone.

### 9. Start it (inside the hub's Mac)

Double-click `start-hub.command` in Finder (in `~/family-hub/hub`)
and leave the Terminal window open. To start it at login, add it in System
Settings → General → **Login Items** → **+**.

Text Family Hub "what's on today?" from your phone. The answer should arrive
within a few seconds.

## Day-to-day

| Situation | What to do |
|---|---|
| Free up memory for a big job | Shut down the VM. When it's back, the hub answers anything sent while it was off (last 12 hours) |
| Add or remove who can text it | Edit `allowFrom` in `~/.claude/channels/imessage/access.json`, then restart the hub (Ctrl-C twice in its Terminal and double-click `start-hub.command`) |
| Change the digest time or recipients | Edit `[digest]` in `~/.config/home-manager/config.toml`. It applies from the next digest |
| It stopped answering | Look at the hub's Terminal window. Check Messages is signed in, and that the VM or user is running |
| Digest didn't arrive | `~/Library/Logs/family-hub-digest.log` in the hub's Mac |
| Update the code | `cd ~/family-hub && git pull`, then restart the hub |
| See what it did | The hub's Terminal window shows every command it ran |

## Limits worth knowing

- Channels are a Claude Code **research preview**. The flag or plugin may
  change. It runs on your Claude subscription and counts toward its usage.
- Claude restarts every night at 3 AM (`RESTART_HOUR` in `start-hub.command`) so the
  conversation starts fresh and each text uses less of your plan's limits.
- Texts are only caught up for the last 12 hours after the hub restarts.
- AppleScript can't do tapbacks or threaded replies. You get plain replies.
- Reminders' own "assign to" feature isn't available to the hub, so it writes
  the person's name into the title instead.
